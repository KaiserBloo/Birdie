from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from html import escape
from pathlib import Path
from typing import Annotated, Iterator
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, RedirectResponse

from ..classifier import ClassifierUnavailableError, ImageClassifier
from ..config import Settings
from ..database import connect
from ..image_processing import build_roi, crop_image_to_roi
from ..repository import (
    create_sighting,
    ensure_device,
    claim_next_remote_command,
    complete_remote_command,
    fail_remote_command,
    get_device,
    get_remote_command,
    get_sighting_by_visit,
    get_sighting,
    list_sightings,
    mark_alert_sent,
    record_visit_candidate,
    replace_predictions,
    score_candidate,
    should_send_alert,
    set_sighting_video_path,
    upsert_visit_candidate,
    upsert_device,
)
from ..schemas import (
    ConfigOut,
    DeviceOut,
    DeviceStatusIn,
    HealthOut,
    MotionEventIn,
    MotionEventOut,
    RemoteCommandCompleteIn,
    RemoteCommandOut,
    SightingOut,
    sighting_response,
)
from ..storage import (
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
    event_directory,
    relative_media_path,
    resolve_media_path,
    save_upload,
)
from ..telegram import NotificationResult, Notifier

router = APIRouter()


@router.get("/", include_in_schema=False)
def root() -> RedirectResponse:
    return RedirectResponse("/docs")


@router.get("/health", response_model=HealthOut)
def health(settings: Annotated[Settings, Depends(_settings)]) -> HealthOut:
    return HealthOut(status="ok", app=settings.app_name)


@router.get("/config", response_model=ConfigOut)
def config(
    request: Request,
    settings: Annotated[Settings, Depends(_settings)],
) -> ConfigOut:
    return ConfigOut(
        device_token_required=settings.device_token is not None,
        default_roi=settings.default_roi,
        alert_cooldown_seconds=settings.alert_cooldown_seconds,
        classifier_backend=settings.classifier_backend,
        classifier_model=(
            settings.birder_model_name
            if settings.classifier_backend == "birder"
            else request.app.state.classifier.model_name
        ),
        classifier_top_k=settings.classifier_top_k,
        common_species=settings.common_species,
        endpoints={
            "status": "/device/status",
            "motion": "/events/motion",
            "upload": "/events/upload",
        },
    )


@router.post("/device/status", response_model=DeviceOut)
async def device_status(
    payload: DeviceStatusIn,
    database: Annotated[sqlite3.Connection, Depends(_database)],
    settings: Annotated[Settings, Depends(_settings)],
    notifier: Annotated[Notifier, Depends(_notifier)],
    _: Annotated[None, Depends(_authorise_device)],
) -> DeviceOut:
    try:
        previous = get_device(database, payload.device_id)
    except LookupError:
        previous = None
    device = upsert_device(
        database,
        device_id=payload.device_id,
        name=payload.name,
        phone_model=payload.phone_model,
        battery_level=payload.battery_level,
        battery_status=payload.battery_status,
        is_charging=payload.is_charging,
        power_source=payload.power_source,
        temperature_c=payload.temperature_c,
        network_state=payload.network_state,
        app_version=payload.app_version,
        seen_at=payload.seen_at,
    )
    await _send_device_alerts(
        notifier,
        previous=previous,
        current=device,
        settings=settings,
    )
    return DeviceOut(**device)


@router.get("/device/commands/next", response_model=RemoteCommandOut | None)
def next_device_command(
    device_id: str,
    database: Annotated[sqlite3.Connection, Depends(_database)],
    _: Annotated[None, Depends(_authorise_device)],
) -> RemoteCommandOut | None:
    ensure_device(database, device_id=device_id)
    command = claim_next_remote_command(database, device_id=device_id)
    if command is None:
        return None
    return RemoteCommandOut(
        id=command["id"],
        command=command["command"],
        payload=command["payload"],
    )


@router.post("/device/commands/{command_id}/complete")
async def complete_device_command(
    command_id: str,
    payload: RemoteCommandCompleteIn,
    database: Annotated[sqlite3.Connection, Depends(_database)],
    notifier: Annotated[Notifier, Depends(_notifier)],
    _: Annotated[None, Depends(_authorise_device)],
) -> dict[str, str]:
    try:
        command = get_remote_command(database, command_id)
        if payload.status == "failed":
            failed_command = fail_remote_command(
                database,
                command_id=command_id,
                error_message=payload.error_message or "command failed",
            )
            if command.get("telegram_chat_id"):
                await notifier.send_text(
                    "<b>Birdie command failed</b>\n"
                    f"{escape(failed_command.get('error_message') or 'command failed')}",
                    chat_id=command["telegram_chat_id"],
                    reply_to_message_id=command.get("telegram_message_id"),
                )
        else:
            complete_remote_command(
                database,
                command_id=command_id,
                result=payload.result,
            )
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="command not found") from exc
    return {"status": "accepted"}


@router.post("/events/motion", response_model=MotionEventOut)
def motion_event(
    payload: MotionEventIn,
    _: Annotated[None, Depends(_authorise_device)],
) -> MotionEventOut:
    return MotionEventOut(
        status="accepted",
        event_id=str(uuid4()),
        upload_endpoint="/events/upload",
    )


@router.post("/events/upload", response_model=SightingOut)
async def upload_event(
    request: Request,
    database: Annotated[sqlite3.Connection, Depends(_database)],
    classifier: Annotated[ImageClassifier, Depends(_classifier)],
    notifier: Annotated[Notifier, Depends(_notifier)],
    _: Annotated[None, Depends(_authorise_device)],
    device_id: Annotated[str, Form(min_length=1)],
    motion_score: Annotated[float | None, Form(ge=0, le=1)] = None,
    captured_at: Annotated[datetime | None, Form()] = None,
    device_name: Annotated[str | None, Form()] = None,
    phone_model: Annotated[str | None, Form()] = None,
    battery_level: Annotated[float | None, Form(ge=0, le=100)] = None,
    temperature_c: Annotated[float | None, Form()] = None,
    network_state: Annotated[str | None, Form()] = None,
    app_version: Annotated[str | None, Form()] = None,
    visit_id: Annotated[str | None, Form(min_length=1)] = None,
    candidate_index: Annotated[int | None, Form(ge=0)] = None,
    command_id: Annotated[str | None, Form(min_length=1)] = None,
    upload_kind: Annotated[str | None, Form()] = None,
    roi_x: Annotated[float | None, Form()] = None,
    roi_y: Annotated[float | None, Form()] = None,
    roi_width: Annotated[float | None, Form()] = None,
    roi_height: Annotated[float | None, Form()] = None,
    image: Annotated[UploadFile | None, File()] = None,
    video: Annotated[UploadFile | None, File()] = None,
) -> SightingOut:
    settings = request.app.state.settings
    if image is None and video is None:
        raise HTTPException(status_code=400, detail="image or video upload is required")

    timestamp = captured_at or datetime.now(timezone.utc)
    event_id = str(uuid4())
    target_dir = event_directory(settings.media_dir, event_id, timestamp)

    try:
        image_path = (
            await save_upload(
                image,
                target_dir=target_dir,
                stem="original",
                allowed_extensions=IMAGE_EXTENSIONS,
                default_extension=".jpg",
            )
            if image
            else None
        )
        video_path = (
            await save_upload(
                video,
                target_dir=target_dir,
                stem="clip",
                allowed_extensions=VIDEO_EXTENSIONS,
                default_extension=".mp4",
            )
            if video
            else None
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    roi = build_roi(
        settings.default_roi,
        x=roi_x,
        y=roi_y,
        width=roi_width,
        height=roi_height,
    )
    cropped_image_path = (
        crop_image_to_roi(image_path, target_dir / "crop.jpg", roi) if image_path else None
    )
    classification_image_path = cropped_image_path or image_path
    try:
        predictions = (
            classifier.classify(classification_image_path) if classification_image_path else []
        )
    except ClassifierUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if any([device_name, phone_model, battery_level, temperature_c, network_state, app_version]):
        upsert_device(
            database,
            device_id=device_id,
            name=device_name or device_id,
            phone_model=phone_model,
            battery_level=battery_level,
            temperature_c=temperature_c,
            network_state=network_state,
            app_version=app_version,
        )
    else:
        ensure_device(database, device_id=device_id)

    metadata = {
        key: value
        for key, value in {
            "phone_model": phone_model,
            "battery_level": battery_level,
            "temperature_c": temperature_c,
            "network_state": network_state,
            "app_version": app_version,
            "upload_kind": upload_kind,
            "command_id": command_id,
        }.items()
        if value is not None
    }
    media_path = relative_media_path(settings.media_dir, image_path)
    crop_path = relative_media_path(settings.media_dir, cropped_image_path)
    clip_path = relative_media_path(settings.media_dir, video_path)
    is_new_sighting = True
    best_candidate_changed = False
    video_clip_changed = False
    if visit_id and video_path is not None and image_path is None:
        existing = get_sighting_by_visit(database, device_id=device_id, visit_id=visit_id)
        if existing is None:
            sighting = create_sighting(
                database,
                sighting_id=event_id,
                device_id=device_id,
                timestamp=timestamp,
                predictions=[],
                roi=roi,
                metadata=metadata,
                media_path=None,
                cropped_image_path=None,
                video_path=clip_path,
                motion_score=motion_score,
                visit_id=visit_id,
                candidate_index=None,
                candidate_score=0.0,
                last_candidate_at=timestamp,
                candidate_count=0,
            )
        else:
            sighting = set_sighting_video_path(
                database,
                sighting_id=existing["id"],
                video_path=clip_path,
            )
            is_new_sighting = False
            video_clip_changed = True
    elif visit_id:
        sighting, is_new_sighting, best_candidate_changed = upsert_visit_candidate(
            database,
            sighting_id=event_id,
            device_id=device_id,
            visit_id=visit_id,
            candidate_index=candidate_index,
            timestamp=timestamp,
            predictions=predictions,
            roi=roi,
            metadata=metadata,
            media_path=media_path,
            cropped_image_path=crop_path,
            video_path=clip_path,
            motion_score=motion_score,
        )
        record_visit_candidate(
            database,
            sighting_id=sighting["id"],
            visit_id=visit_id,
            candidate_index=candidate_index,
            captured_at=timestamp,
            media_path=media_path,
            cropped_image_path=crop_path,
            video_path=clip_path,
            motion_score=motion_score,
            candidate_score=score_candidate(predictions),
        )
    else:
        sighting = create_sighting(
            database,
            sighting_id=event_id,
            device_id=device_id,
            timestamp=timestamp,
            predictions=predictions,
            roi=roi,
            metadata=metadata,
            media_path=media_path,
            cropped_image_path=crop_path,
            video_path=clip_path,
            motion_score=motion_score,
        )

    notification_media_path = _notification_media_path(
        settings,
        sighting,
        fallback=cropped_image_path or image_path,
    )
    if command_id:
        await _complete_command_upload(
            database,
            notifier,
            command_id=command_id,
            sighting=sighting,
            media_path=notification_media_path,
        )
    elif is_new_sighting and should_send_alert(
        database,
        device_id=device_id,
        event_time=timestamp,
        cooldown_seconds=settings.alert_cooldown_seconds,
    ):
        alert_was_sent = await notifier.send_sighting(sighting, notification_media_path)
        if alert_was_sent.sent:
            sighting = mark_alert_sent(
                database,
                sighting_id=sighting["id"],
                telegram_message_id=alert_was_sent.message_id,
            )
    elif (
        (best_candidate_changed or video_clip_changed)
        and sighting.get("telegram_message_id") is not None
        and not is_new_sighting
    ):
        await notifier.update_sighting(
            sighting,
            notification_media_path,
            message_id=int(sighting["telegram_message_id"]),
        )
    return sighting_response(sighting)


@router.get("/sightings", response_model=list[SightingOut])
def sightings(
    database: Annotated[sqlite3.Connection, Depends(_database)],
    limit: int = 50,
) -> list[SightingOut]:
    limit = min(max(limit, 1), 200)
    return [sighting_response(sighting) for sighting in list_sightings(database, limit=limit)]


@router.get("/sightings/{sighting_id}", response_model=SightingOut)
def sighting_detail(
    sighting_id: str,
    database: Annotated[sqlite3.Connection, Depends(_database)],
) -> SightingOut:
    try:
        return sighting_response(get_sighting(database, sighting_id))
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="sighting not found") from exc


@router.post("/sightings/{sighting_id}/reclassify", response_model=SightingOut)
def reclassify_sighting(
    sighting_id: str,
    request: Request,
    database: Annotated[sqlite3.Connection, Depends(_database)],
    classifier: Annotated[ImageClassifier, Depends(_classifier)],
) -> SightingOut:
    settings = request.app.state.settings
    try:
        sighting = get_sighting(database, sighting_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="sighting not found") from exc

    classification_path = sighting.get("cropped_image_path") or sighting.get("media_path")
    if not classification_path:
        raise HTTPException(status_code=400, detail="sighting has no image to classify")

    image_path = resolve_media_path(settings.media_dir, classification_path)
    try:
        predictions = classifier.classify(image_path)
    except ClassifierUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return sighting_response(
        replace_predictions(database, sighting_id=sighting_id, predictions=predictions)
    )


@router.get("/media/{sighting_id}/{kind}")
def media(
    sighting_id: str,
    kind: str,
    request: Request,
    database: Annotated[sqlite3.Connection, Depends(_database)],
) -> FileResponse:
    settings = request.app.state.settings
    try:
        sighting = get_sighting(database, sighting_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail="sighting not found") from exc

    column_by_kind = {
        "image": "media_path",
        "crop": "cropped_image_path",
        "video": "video_path",
    }
    if kind not in column_by_kind:
        raise HTTPException(status_code=404, detail="media kind not found")

    relative_path = sighting[column_by_kind[kind]]
    if not relative_path:
        raise HTTPException(status_code=404, detail="media not found")

    try:
        path = resolve_media_path(settings.media_dir, relative_path)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail="media not found") from exc

    if not path.exists():
        raise HTTPException(status_code=404, detail="media file missing")
    return FileResponse(path)


def _settings(request: Request) -> Settings:
    return request.app.state.settings


def _classifier(request: Request) -> ImageClassifier:
    return request.app.state.classifier


def _notifier(request: Request) -> Notifier:
    return request.app.state.notifier


def _database(request: Request) -> Iterator[sqlite3.Connection]:
    connection = connect(request.app.state.settings.database_path)
    try:
        yield connection
    finally:
        connection.close()


async def _send_device_alerts(
    notifier: Notifier,
    *,
    previous: dict | None,
    current: dict,
    settings: Settings,
) -> None:
    alerts: list[str] = []
    current_level = _float_or_none(current.get("battery_level"))
    previous_level = _float_or_none(previous.get("battery_level")) if previous else None

    if current_level is not None:
        if _crossed_down(
            previous_level,
            current_level,
            threshold=settings.critical_battery_percent,
        ):
            alerts.append(f"Battery critical: {current_level:.0f}%")
        elif _crossed_down(
            previous_level,
            current_level,
            threshold=settings.low_battery_percent,
        ):
            alerts.append(f"Battery low: {current_level:.0f}%")

    current_charging = current.get("is_charging")
    previous_charging = previous.get("is_charging") if previous else None
    if previous_charging is not None and current_charging is not None:
        if bool(current_charging) and not bool(previous_charging):
            alerts.append("Charging started")
        elif bool(previous_charging) and not bool(current_charging):
            alerts.append("Charging stopped")

    current_temp = _float_or_none(current.get("temperature_c"))
    previous_temp = _float_or_none(previous.get("temperature_c")) if previous else None
    if current_temp is not None and _crossed_up(
        previous_temp,
        current_temp,
        threshold=settings.high_temperature_c,
    ):
        alerts.append(f"Phone temperature high: {current_temp:.1f}C")

    if previous and current.get("network_state") != previous.get("network_state"):
        alerts.append(
            f"Network changed: {previous.get('network_state') or 'unknown'}"
            f" -> {current.get('network_state') or 'unknown'}"
        )

    if not alerts:
        return

    lines = ["<b>Birdie device alert</b>", *[escape(alert) for alert in alerts]]
    if current_level is not None:
        lines.append(f"<b>Battery</b>: {current_level:.0f}%")
    if current.get("battery_status"):
        lines.append(f"<b>Status</b>: {escape(str(current['battery_status']))}")
    if current.get("power_source"):
        lines.append(f"<b>Power</b>: {escape(str(current['power_source']))}")
    lines.append(f"<b>Device</b>: {escape(str(current['id']))}")
    await notifier.send_text("\n".join(lines))


async def _complete_command_upload(
    database: sqlite3.Connection,
    notifier: Notifier,
    *,
    command_id: str,
    sighting: dict,
    media_path: Path | None,
) -> None:
    try:
        command = get_remote_command(database, command_id)
    except LookupError:
        return

    caption = _snapshot_caption(sighting)
    chat_id = command.get("telegram_chat_id")
    reply_to_message_id = command.get("telegram_message_id")
    notification = NotificationResult(sent=False)
    if media_path and media_path.exists():
        notification = await notifier.send_media(
            media_path,
            caption,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )
    else:
        notification = await notifier.send_text(
            caption,
            chat_id=chat_id,
            reply_to_message_id=reply_to_message_id,
        )

    complete_remote_command(
        database,
        command_id=command_id,
        result={
            "sighting_id": sighting["id"],
            "notification_sent": notification.sent,
            "telegram_message_id": notification.message_id,
        },
    )


def _snapshot_caption(sighting: dict) -> str:
    lines = ["<b>Birdie camera snapshot</b>"]
    label = sighting.get("display_label") or "species uncertain"
    status = sighting.get("classification_status") or "uncertain"
    confidence = sighting.get("display_confidence")
    if status == "uncertain" or confidence is None:
        lines.append("<b>Result</b>: species uncertain")
    else:
        lines.append(
            f"<b>Result</b>: {escape(str(label))} "
            f"({float(confidence):.0%} raw confidence)"
        )
    if sighting.get("timestamp"):
        lines.append(f"<b>Captured</b>: {escape(str(sighting['timestamp']))}")
    return "\n".join(lines)


def _notification_media_path(
    settings: Settings,
    sighting: dict,
    *,
    fallback: Path | None,
) -> Path | None:
    relative_path = sighting.get("video_path") or sighting.get("cropped_image_path")
    if relative_path:
        try:
            resolved = resolve_media_path(settings.media_dir, relative_path)
        except ValueError:
            return fallback
        if resolved.exists():
            return resolved
    return fallback


def _float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _crossed_down(previous: float | None, current: float, *, threshold: float) -> bool:
    if current > threshold:
        return False
    return previous is None or previous > threshold


def _crossed_up(previous: float | None, current: float, *, threshold: float) -> bool:
    if current < threshold:
        return False
    return previous is None or previous < threshold


def _authorise_device(
    settings: Annotated[Settings, Depends(_settings)],
    x_birdie_token: Annotated[str | None, Header(alias="X-Birdie-Token")] = None,
) -> None:
    if settings.device_token is None:
        return
    if x_birdie_token != settings.device_token:
        raise HTTPException(status_code=401, detail="invalid device token")
