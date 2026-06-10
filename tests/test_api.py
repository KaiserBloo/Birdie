from __future__ import annotations

from io import BytesIO
from pathlib import Path

from fastapi.testclient import TestClient
from PIL import Image

from birdie.classifier import ClassifierUnavailableError
from birdie.classifier import Prediction
from birdie.config import Settings
from birdie.main import create_app
from birdie.telegram import NotificationResult


class RecordingNotifier:
    def __init__(self) -> None:
        self.sent_sighting_ids: list[str] = []
        self.updated_sighting_ids: list[str] = []

    async def send_sighting(
        self,
        sighting: dict,
        image_path: Path | None,
    ) -> NotificationResult:
        self.sent_sighting_ids.append(sighting["id"])
        return NotificationResult(sent=True, message_id=42)

    async def update_sighting(
        self,
        sighting: dict,
        image_path: Path | None,
        *,
        message_id: int,
    ) -> bool:
        assert message_id == 42
        self.updated_sighting_ids.append(sighting["id"])
        return True


class FailingClassifier:
    model_name = "failing"

    def classify(self, image_path: Path) -> list:
        raise ClassifierUnavailableError("classifier unavailable")


class VisitSequenceClassifier:
    model_name = "visit-sequence"

    def __init__(self) -> None:
        self.calls = 0

    def classify(self, image_path: Path) -> list[Prediction]:
        self.calls += 1
        if self.calls <= 2:
            return [
                Prediction("Unknown", 0.55, 1, self.model_name),
                Prediction("Eurasian blue tit", 0.08, 2, self.model_name),
            ]
        return [
            Prediction("Eurasian blue tit", 0.74, 1, self.model_name),
            Prediction("Azure tit", 0.02, 2, self.model_name),
        ]


class CropOriginalClassifier:
    model_name = "crop-original"

    def __init__(self) -> None:
        self.paths: list[str] = []

    def classify(self, image_path: Path) -> list[Prediction]:
        self.paths.append(image_path.name)
        if image_path.name == "crop.jpg":
            return [Prediction("Unknown", 0.82, 1, self.model_name)]
        return [Prediction("Eurasian blue tit", 0.62, 1, self.model_name)]


def test_health_and_config(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    health = client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok", "app": "Birdie"}

    config = client.get("/config")
    assert config.status_code == 200
    assert config.json()["endpoints"]["upload"] == "/events/upload"
    assert config.json()["classifier_backend"] == "dummy"
    assert config.json()["classifier_model"] == "dummy-garden-prior-v0"
    assert "Blue Tit" in config.json()["common_species"]


def test_device_status_upsert(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.post(
        "/device/status",
        json={
            "device_id": "phone-window",
            "name": "Window phone",
            "phone_model": "Motorola G35",
            "battery_level": 74,
            "temperature_c": 31.4,
            "network_state": "wifi",
            "app_version": "0.1.0",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "phone-window"
    assert payload["phone_model"] == "Motorola G35"
    assert payload["battery_level"] == 74
    assert payload["network_state"] == "wifi"


def test_upload_image_creates_sighting_and_media(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "motion_score": "0.82",
            "phone_model": "Motorola G35",
            "battery_level": "68",
            "network_state": "wifi",
            "roi_x": "0.25",
            "roi_y": "0.25",
            "roi_width": "0.5",
            "roi_height": "0.5",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["device_id"] == "phone-window"
    assert payload["species_guess"] is not None
    assert len(payload["top_predictions"]) == 5
    assert payload["classification_status"] in {"confident", "likely", "uncertain"}
    assert payload["display_label"]
    assert payload["decision_reason"]
    assert payload["metadata"]["phone_model"] == "Motorola G35"
    assert payload["roi"] == {"x": 0.25, "y": 0.25, "width": 0.5, "height": 0.5}
    assert payload["alert_sent_at"] is None
    assert payload["media_urls"]["image"].startswith("/media/")
    assert payload["media_urls"]["crop"].startswith("/media/")

    sightings = client.get("/sightings")
    assert sightings.status_code == 200
    assert len(sightings.json()) == 1

    media = client.get(payload["media_urls"]["image"])
    assert media.status_code == 200
    assert media.content == _jpeg_bytes()

    crop = client.get(payload["media_urls"]["crop"])
    assert crop.status_code == 200
    assert crop.headers["content-type"] == "image/jpeg"


def test_upload_uses_original_when_crop_classifies_worse(tmp_path: Path) -> None:
    classifier = CropOriginalClassifier()
    client = TestClient(create_app(_settings(tmp_path), classifier=classifier))

    response = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "roi_x": "0.25",
            "roi_y": "0.25",
            "roi_width": "0.5",
            "roi_height": "0.5",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert classifier.paths == ["crop.jpg", "original.jpg"]
    assert payload["display_label"] == "likely Blue Tit"
    assert payload["classification_status"] == "likely"
    assert payload["metadata"]["classification_source"] == "original"


def test_visit_candidates_update_one_sighting_to_best_classification(tmp_path: Path) -> None:
    notifier = RecordingNotifier()
    settings = _settings(tmp_path)
    settings = Settings(
        app_name=settings.app_name,
        data_dir=settings.data_dir,
        database_path=settings.database_path,
        media_dir=settings.media_dir,
        device_token=settings.device_token,
        telegram_bot_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        alert_cooldown_seconds=0,
        default_roi=settings.default_roi,
    )
    client = TestClient(
        create_app(settings, classifier=VisitSequenceClassifier(), notifier=notifier)
    )

    first = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "visit_id": "visit-1",
            "candidate_index": "0",
            "captured_at": "2026-06-07T08:00:00+00:00",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    second = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "visit_id": "visit-1",
            "candidate_index": "1",
            "captured_at": "2026-06-07T08:00:03+00:00",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["id"] == second.json()["id"]
    assert first.json()["classification_status"] == "uncertain"
    assert second.json()["display_label"] == "Blue Tit"
    assert second.json()["classification_status"] == "confident"
    assert second.json()["candidate_count"] == 2
    assert second.json()["best_candidate_index"] == 1
    assert second.json()["visit_id"] == "visit-1"
    assert second.json()["video_path"] is None
    assert "video" not in second.json()["media_urls"]
    assert notifier.sent_sighting_ids == [first.json()["id"]]
    assert notifier.updated_sighting_ids == [first.json()["id"]]

    sightings = client.get("/sightings")
    assert sightings.status_code == 200
    assert len(sightings.json()) == 1


def test_visit_video_upload_attaches_clip_without_changing_candidates(tmp_path: Path) -> None:
    notifier = RecordingNotifier()
    settings = _settings(tmp_path)
    settings = Settings(
        app_name=settings.app_name,
        data_dir=settings.data_dir,
        database_path=settings.database_path,
        media_dir=settings.media_dir,
        device_token=settings.device_token,
        telegram_bot_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        alert_cooldown_seconds=0,
        default_roi=settings.default_roi,
    )
    client = TestClient(
        create_app(settings, classifier=VisitSequenceClassifier(), notifier=notifier)
    )

    candidate = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "visit_id": "visit-clip",
            "candidate_index": "0",
            "captured_at": "2026-06-07T08:00:00+00:00",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    clip = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "visit_id": "visit-clip",
            "captured_at": "2026-06-07T08:00:09+00:00",
            "motion_score": "0.72",
        },
        files={"video": ("visit.mp4", b"fake mp4 bytes", "video/mp4")},
    )

    assert candidate.status_code == 200
    assert clip.status_code == 200
    assert clip.json()["id"] == candidate.json()["id"]
    assert clip.json()["candidate_count"] == 1
    assert clip.json()["best_candidate_index"] == 0
    assert clip.json()["video_path"].endswith("/clip.mp4")
    assert clip.json()["media_urls"]["video"].endswith("/video")
    assert notifier.sent_sighting_ids == [candidate.json()["id"]]
    assert notifier.updated_sighting_ids == [candidate.json()["id"]]

    video = client.get(clip.json()["media_urls"]["video"])
    assert video.status_code == 200
    assert video.content == b"fake mp4 bytes"


def test_upload_requires_media(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))

    response = client.post(
        "/events/upload",
        data={"device_id": "phone-window", "motion_score": "0.82"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "image or video upload is required"


def test_upload_returns_503_when_classifier_unavailable(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path), classifier=FailingClassifier()))

    response = client.post(
        "/events/upload",
        data={"device_id": "phone-window"},
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "classifier unavailable"


def test_device_token_when_configured(tmp_path: Path) -> None:
    settings = _settings(tmp_path, device_token="secret")
    client = TestClient(create_app(settings))

    denied = client.post(
        "/events/motion",
        json={"device_id": "phone-window", "motion_score": 0.4},
    )
    assert denied.status_code == 401

    accepted = client.post(
        "/events/motion",
        headers={"X-Birdie-Token": "secret"},
        json={"device_id": "phone-window", "motion_score": 0.4},
    )
    assert accepted.status_code == 200
    assert accepted.json()["status"] == "accepted"


def test_reclassify_existing_sighting(tmp_path: Path) -> None:
    client = TestClient(create_app(_settings(tmp_path)))
    uploaded = client.post(
        "/events/upload",
        data={"device_id": "phone-window"},
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    ).json()

    response = client.post(f"/sightings/{uploaded['id']}/reclassify")

    assert response.status_code == 200
    assert response.json()["id"] == uploaded["id"]
    assert len(response.json()["top_predictions"]) == 5
    assert response.json()["classification_status"] in {"confident", "likely", "uncertain"}


def test_upload_alert_cooldown_skips_second_notification(tmp_path: Path) -> None:
    notifier = RecordingNotifier()
    settings = _settings(tmp_path)
    settings = Settings(
        app_name=settings.app_name,
        data_dir=settings.data_dir,
        database_path=settings.database_path,
        media_dir=settings.media_dir,
        device_token=settings.device_token,
        telegram_bot_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        alert_cooldown_seconds=900,
        default_roi=settings.default_roi,
    )
    client = TestClient(create_app(settings, notifier=notifier))

    first = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "captured_at": "2026-06-07T08:00:00+00:00",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )
    second = client.post(
        "/events/upload",
        data={
            "device_id": "phone-window",
            "captured_at": "2026-06-07T08:05:00+00:00",
        },
        files={"image": ("bird.jpg", _jpeg_bytes(), "image/jpeg")},
    )

    assert first.status_code == 200
    assert second.status_code == 200
    assert len(notifier.sent_sighting_ids) == 1
    assert notifier.updated_sighting_ids == []
    assert first.json()["alert_sent_at"] is not None
    assert second.json()["alert_sent_at"] is None


def _settings(tmp_path: Path, device_token: str | None = None) -> Settings:
    return Settings(
        app_name="Birdie",
        data_dir=tmp_path,
        database_path=tmp_path / "birdie.db",
        media_dir=tmp_path / "media",
        device_token=device_token,
        telegram_bot_token=None,
        telegram_chat_id=None,
        alert_cooldown_seconds=900,
        default_roi={"x": 0.25, "y": 0.25, "width": 0.50, "height": 0.50},
    )


def _jpeg_bytes() -> bytes:
    image = Image.new("RGB", (80, 60), color=(210, 220, 190))
    for x in range(20, 60):
        for y in range(15, 45):
            image.putpixel((x, y), (80, 50, 35))
    buffer = BytesIO()
    image.save(buffer, format="JPEG")
    return buffer.getvalue()
