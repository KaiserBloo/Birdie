from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class HealthOut(BaseModel):
    status: str
    app: str


class ConfigOut(BaseModel):
    device_token_required: bool
    default_roi: dict[str, float]
    alert_cooldown_seconds: int
    classifier_backend: str
    classifier_model: str
    classifier_top_k: int
    common_species: tuple[str, ...]
    endpoints: dict[str, str]


class DeviceStatusIn(BaseModel):
    device_id: str = Field(min_length=1)
    name: str = Field(default="Android camera node", min_length=1)
    phone_model: str | None = None
    battery_level: float | None = Field(default=None, ge=0, le=100)
    battery_status: str | None = None
    is_charging: bool | None = None
    power_source: str | None = None
    temperature_c: float | None = None
    network_state: str | None = None
    app_version: str | None = None
    seen_at: datetime | None = None


class DeviceOut(BaseModel):
    id: str
    name: str
    phone_model: str | None
    battery_level: float | None
    battery_status: str | None
    is_charging: bool | None
    power_source: str | None
    temperature_c: float | None
    network_state: str | None
    last_seen: datetime
    app_version: str | None
    created_at: datetime


class MotionEventIn(BaseModel):
    device_id: str = Field(min_length=1)
    motion_score: float = Field(ge=0, le=1)
    detected_at: datetime | None = None


class MotionEventOut(BaseModel):
    status: str
    event_id: str
    upload_endpoint: str


class PredictionOut(BaseModel):
    species: str
    confidence: float
    rank: int
    model_name: str


class SightingOut(BaseModel):
    id: str
    device_id: str | None
    timestamp: datetime
    species_guess: str | None
    confidence: float | None
    classification_status: str
    display_label: str
    display_confidence: float | None
    decision_reason: str
    top_predictions: list[PredictionOut]
    roi: dict[str, float]
    metadata: dict[str, Any]
    media_path: str | None
    cropped_image_path: str | None
    video_path: str | None
    motion_score: float | None
    classifier_model: str | None
    visit_id: str | None
    candidate_count: int
    best_candidate_index: int | None
    best_candidate_score: float | None
    last_candidate_at: datetime | None
    alert_sent_at: datetime | None
    created_at: datetime
    media_urls: dict[str, str]


class UploadErrorOut(BaseModel):
    detail: str


class RemoteCommandOut(BaseModel):
    id: str
    command: str
    payload: dict[str, Any]


class RemoteCommandCompleteIn(BaseModel):
    status: str = Field(pattern="^(completed|failed)$")
    error_message: str | None = None
    result: dict[str, Any] = Field(default_factory=dict)


def sighting_response(payload: dict[str, Any]) -> SightingOut:
    media_urls: dict[str, str] = {}
    if payload.get("media_path"):
        media_urls["image"] = f"/media/{payload['id']}/image"
    if payload.get("cropped_image_path"):
        media_urls["crop"] = f"/media/{payload['id']}/crop"
    if payload.get("video_path"):
        media_urls["video"] = f"/media/{payload['id']}/video"

    return SightingOut(
        id=payload["id"],
        device_id=payload["device_id"],
        timestamp=payload["timestamp"],
        species_guess=payload["species_guess"],
        confidence=payload["confidence"],
        classification_status=payload["classification_status"],
        display_label=payload["display_label"],
        display_confidence=payload["display_confidence"],
        decision_reason=payload["decision_reason"],
        top_predictions=payload["top_predictions"],
        roi=payload["roi"],
        metadata=payload["metadata"],
        media_path=payload["media_path"],
        cropped_image_path=payload["cropped_image_path"],
        video_path=payload["video_path"],
        motion_score=payload["motion_score"],
        classifier_model=payload["classifier_model"],
        visit_id=payload.get("visit_id"),
        candidate_count=payload.get("candidate_count") or 1,
        best_candidate_index=payload.get("best_candidate_index"),
        best_candidate_score=payload.get("best_candidate_score"),
        last_candidate_at=payload.get("last_candidate_at"),
        alert_sent_at=payload["alert_sent_at"],
        created_at=payload["created_at"],
        media_urls=media_urls,
    )
