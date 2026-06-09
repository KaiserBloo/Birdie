from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from .classifier import Prediction
from .decision import common_species_name, decide_classification


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def upsert_device(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    name: str,
    phone_model: str | None = None,
    battery_level: float | None = None,
    battery_status: str | None = None,
    is_charging: bool | None = None,
    power_source: str | None = None,
    temperature_c: float | None = None,
    network_state: str | None = None,
    app_version: str | None = None,
    seen_at: datetime | None = None,
) -> dict[str, Any]:
    now = utc_now()
    seen_at = seen_at or now
    connection.execute(
        """
        INSERT INTO devices (
            id, name, phone_model, battery_level, battery_status, is_charging,
            power_source, temperature_c, network_state, last_seen, app_version,
            created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(id) DO UPDATE SET
            name = excluded.name,
            phone_model = excluded.phone_model,
            battery_level = excluded.battery_level,
            battery_status = excluded.battery_status,
            is_charging = excluded.is_charging,
            power_source = excluded.power_source,
            temperature_c = excluded.temperature_c,
            network_state = excluded.network_state,
            last_seen = excluded.last_seen,
            app_version = excluded.app_version
        """,
        (
            device_id,
            name,
            phone_model,
            battery_level,
            battery_status,
            _bool_to_db(is_charging),
            power_source,
            temperature_c,
            network_state,
            seen_at.isoformat(),
            app_version,
            now.isoformat(),
        ),
        )
    connection.commit()
    return get_device(connection, device_id)


def get_device(connection: sqlite3.Connection, device_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM devices WHERE id = ?", (device_id,)).fetchone()
    if row is None:
        raise LookupError(device_id)
    return _device_from_row(row)


def latest_device(connection: sqlite3.Connection) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT *
        FROM devices
        ORDER BY last_seen DESC
        LIMIT 1
        """
    ).fetchone()
    if row is None:
        return None
    return _device_from_row(row)


def ensure_device(connection: sqlite3.Connection, *, device_id: str) -> dict[str, Any]:
    try:
        return get_device(connection, device_id)
    except LookupError:
        return upsert_device(
            connection,
            device_id=device_id,
            name=device_id,
            phone_model=None,
            battery_level=None,
            battery_status=None,
            is_charging=None,
            power_source=None,
            temperature_c=None,
            network_state=None,
            app_version=None,
        )


def create_sighting(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    device_id: str | None,
    timestamp: datetime,
    predictions: list[Prediction],
    roi: dict[str, float],
    metadata: dict[str, Any],
    media_path: str | None,
    cropped_image_path: str | None,
    video_path: str | None,
    motion_score: float | None,
    visit_id: str | None = None,
    candidate_index: int | None = None,
    candidate_score: float | None = None,
    last_candidate_at: datetime | None = None,
    candidate_count: int = 1,
) -> dict[str, Any]:
    now = utc_now()
    top = predictions[0] if predictions else None
    decision = decide_classification(predictions)
    candidate_score = (
        candidate_score if candidate_score is not None else score_candidate(predictions)
    )
    last_candidate_at = last_candidate_at or timestamp
    connection.execute(
        """
        INSERT INTO sightings (
            id, device_id, timestamp, species_guess, confidence, classification_status,
            display_label, display_confidence, decision_reason, top_predictions_json,
            roi_json, metadata_json, media_path, cropped_image_path, video_path,
            motion_score, classifier_model, visit_id, candidate_count,
            best_candidate_index, best_candidate_score, last_candidate_at,
            alert_sent_at, telegram_message_id, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            sighting_id,
            device_id,
            timestamp.isoformat(),
            top.species if top else None,
            top.confidence if top else None,
            decision.classification_status,
            decision.display_label,
            decision.display_confidence,
            decision.decision_reason,
            json.dumps(_prediction_payload(predictions)),
            json.dumps(roi),
            json.dumps(metadata),
            media_path,
            cropped_image_path,
            video_path,
            motion_score,
            top.model_name if top else None,
            visit_id,
            candidate_count,
            candidate_index,
            candidate_score,
            last_candidate_at.isoformat(),
            None,
            None,
            now.isoformat(),
        ),
    )
    _insert_predictions(connection, sighting_id=sighting_id, predictions=predictions)
    connection.commit()
    return get_sighting(connection, sighting_id)


def get_sighting_by_visit(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    visit_id: str,
) -> dict[str, Any] | None:
    row = connection.execute(
        """
        SELECT * FROM sightings
        WHERE device_id = ? AND visit_id = ?
        """,
        (device_id, visit_id),
    ).fetchone()
    if row is None:
        return None
    return _sighting_from_row(connection, row)


def upsert_visit_candidate(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    device_id: str,
    visit_id: str,
    candidate_index: int | None,
    timestamp: datetime,
    predictions: list[Prediction],
    roi: dict[str, float],
    metadata: dict[str, Any],
    media_path: str | None,
    cropped_image_path: str | None,
    video_path: str | None,
    motion_score: float | None,
) -> tuple[dict[str, Any], bool, bool]:
    existing = get_sighting_by_visit(connection, device_id=device_id, visit_id=visit_id)
    candidate_score = score_candidate(predictions)
    if existing is None:
        return (
            create_sighting(
                connection,
                sighting_id=sighting_id,
                device_id=device_id,
                timestamp=timestamp,
                predictions=predictions,
                roi=roi,
                metadata=metadata,
                media_path=media_path,
                cropped_image_path=cropped_image_path,
                video_path=video_path,
                motion_score=motion_score,
                visit_id=visit_id,
                candidate_index=candidate_index,
                candidate_score=candidate_score,
                last_candidate_at=timestamp,
            ),
            True,
            True,
        )

    connection.execute(
        """
        UPDATE sightings
        SET candidate_count = candidate_count + 1,
            last_candidate_at = ?
        WHERE id = ?
        """,
        (timestamp.isoformat(), existing["id"]),
    )
    existing_score = existing.get("best_candidate_score")
    should_replace = existing_score is None or candidate_score > float(existing_score)
    if should_replace:
        _replace_best_candidate(
            connection,
            sighting_id=existing["id"],
            predictions=predictions,
            roi=roi,
            metadata=metadata,
            media_path=media_path,
            cropped_image_path=cropped_image_path,
            video_path=video_path,
            motion_score=motion_score,
            candidate_index=candidate_index,
            candidate_score=candidate_score,
            last_candidate_at=timestamp,
        )
    connection.commit()
    return get_sighting(connection, existing["id"]), False, should_replace


def latest_alert_sent_at(
    connection: sqlite3.Connection,
    *,
    device_id: str | None,
) -> datetime | None:
    if device_id:
        row = connection.execute(
            """
            SELECT alert_sent_at
            FROM sightings
            WHERE device_id = ? AND alert_sent_at IS NOT NULL
            ORDER BY alert_sent_at DESC
            LIMIT 1
            """,
            (device_id,),
        ).fetchone()
    else:
        row = connection.execute(
            """
            SELECT alert_sent_at
            FROM sightings
            WHERE alert_sent_at IS NOT NULL
            ORDER BY alert_sent_at DESC
            LIMIT 1
            """
        ).fetchone()

    if row is None:
        return None
    return datetime.fromisoformat(row["alert_sent_at"])


def should_send_alert(
    connection: sqlite3.Connection,
    *,
    device_id: str | None,
    event_time: datetime,
    cooldown_seconds: int,
) -> bool:
    previous_alert = latest_alert_sent_at(connection, device_id=device_id)
    if previous_alert is None:
        return True
    return (event_time - previous_alert).total_seconds() >= cooldown_seconds


def mark_alert_sent(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    telegram_message_id: int | None = None,
    sent_at: datetime | None = None,
) -> dict[str, Any]:
    sent_at = sent_at or utc_now()
    connection.execute(
        """
        UPDATE sightings
        SET alert_sent_at = ?,
            telegram_message_id = ?
        WHERE id = ?
        """,
        (sent_at.isoformat(), telegram_message_id, sighting_id),
    )
    connection.commit()
    return get_sighting(connection, sighting_id)


def record_visit_candidate(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    visit_id: str,
    candidate_index: int | None,
    captured_at: datetime,
    media_path: str | None,
    cropped_image_path: str | None,
    video_path: str | None,
    motion_score: float | None,
    candidate_score: float,
) -> None:
    connection.execute(
        """
        INSERT INTO visit_candidates (
            id, sighting_id, visit_id, candidate_index, captured_at,
            media_path, cropped_image_path, video_path, motion_score,
            candidate_score, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            str(uuid4()),
            sighting_id,
            visit_id,
            candidate_index,
            captured_at.isoformat(),
            media_path,
            cropped_image_path,
            video_path,
            motion_score,
            candidate_score,
            utc_now().isoformat(),
        ),
    )
    connection.commit()


def list_visit_candidates(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT *
        FROM visit_candidates
        WHERE sighting_id = ?
        ORDER BY candidate_index IS NULL, candidate_index ASC, captured_at ASC
        """,
        (sighting_id,),
    ).fetchall()
    return [dict(row) for row in rows]


def set_sighting_video_path(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    video_path: str | None,
) -> dict[str, Any]:
    connection.execute(
        "UPDATE sightings SET video_path = ? WHERE id = ?",
        (video_path, sighting_id),
    )
    connection.commit()
    return get_sighting(connection, sighting_id)


def create_remote_command(
    connection: sqlite3.Connection,
    *,
    device_id: str | None,
    command: str,
    payload: dict[str, Any] | None = None,
    telegram_chat_id: str | None = None,
    telegram_message_id: int | None = None,
) -> dict[str, Any]:
    command_id = str(uuid4())
    now = utc_now()
    connection.execute(
        """
        INSERT INTO remote_commands (
            id, device_id, command, status, payload_json, result_json,
            telegram_chat_id, telegram_message_id, requested_at
        )
        VALUES (?, ?, ?, 'pending', ?, '{}', ?, ?, ?)
        """,
        (
            command_id,
            device_id,
            command,
            json.dumps(payload or {}),
            telegram_chat_id,
            telegram_message_id,
            now.isoformat(),
        ),
    )
    connection.commit()
    return get_remote_command(connection, command_id)


def claim_next_remote_command(
    connection: sqlite3.Connection,
    *,
    device_id: str,
    stale_after_seconds: int = 120,
) -> dict[str, Any] | None:
    now = utc_now()
    stale_cutoff = (now.timestamp() - stale_after_seconds)
    rows = connection.execute(
        """
        SELECT *
        FROM remote_commands
        WHERE (device_id = ? OR device_id IS NULL)
          AND status IN ('pending', 'claimed')
        ORDER BY requested_at ASC
        """,
        (device_id,),
    ).fetchall()
    command: dict[str, Any] | None = None
    for row in rows:
        candidate = _remote_command_from_row(row)
        if candidate["status"] == "pending":
            command = candidate
            break
        claimed_at = candidate.get("claimed_at")
        if claimed_at and datetime.fromisoformat(claimed_at).timestamp() < stale_cutoff:
            command = candidate
            break

    if command is None:
        return None

    connection.execute(
        """
        UPDATE remote_commands
        SET status = 'claimed',
            claimed_at = ?
        WHERE id = ?
        """,
        (now.isoformat(), command["id"]),
    )
    connection.commit()
    return get_remote_command(connection, command["id"])


def get_remote_command(
    connection: sqlite3.Connection,
    command_id: str,
) -> dict[str, Any]:
    row = connection.execute(
        "SELECT * FROM remote_commands WHERE id = ?",
        (command_id,),
    ).fetchone()
    if row is None:
        raise LookupError(command_id)
    return _remote_command_from_row(row)


def complete_remote_command(
    connection: sqlite3.Connection,
    *,
    command_id: str,
    result: dict[str, Any] | None = None,
) -> dict[str, Any]:
    connection.execute(
        """
        UPDATE remote_commands
        SET status = 'completed',
            result_json = ?,
            completed_at = ?,
            error_message = NULL
        WHERE id = ?
        """,
        (json.dumps(result or {}), utc_now().isoformat(), command_id),
    )
    connection.commit()
    return get_remote_command(connection, command_id)


def fail_remote_command(
    connection: sqlite3.Connection,
    *,
    command_id: str,
    error_message: str,
) -> dict[str, Any]:
    connection.execute(
        """
        UPDATE remote_commands
        SET status = 'failed',
            error_message = ?,
            completed_at = ?
        WHERE id = ?
        """,
        (error_message, utc_now().isoformat(), command_id),
    )
    connection.commit()
    return get_remote_command(connection, command_id)


def list_sightings(connection: sqlite3.Connection, *, limit: int = 50) -> list[dict[str, Any]]:
    rows = connection.execute(
        """
        SELECT * FROM sightings
        ORDER BY timestamp DESC, created_at DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    return [_sighting_from_row(connection, row) for row in rows]


def get_sighting(connection: sqlite3.Connection, sighting_id: str) -> dict[str, Any]:
    row = connection.execute("SELECT * FROM sightings WHERE id = ?", (sighting_id,)).fetchone()
    if row is None:
        raise LookupError(sighting_id)
    return _sighting_from_row(connection, row)


def replace_predictions(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    predictions: list[Prediction],
) -> dict[str, Any]:
    top = predictions[0] if predictions else None
    decision = decide_classification(predictions)
    connection.execute("DELETE FROM predictions WHERE sighting_id = ?", (sighting_id,))
    connection.execute(
        """
        UPDATE sightings
        SET species_guess = ?,
            confidence = ?,
            classification_status = ?,
            display_label = ?,
            display_confidence = ?,
            decision_reason = ?,
            top_predictions_json = ?,
            classifier_model = ?,
            best_candidate_score = ?
        WHERE id = ?
        """,
        (
            top.species if top else None,
            top.confidence if top else None,
            decision.classification_status,
            decision.display_label,
            decision.display_confidence,
            decision.decision_reason,
            json.dumps(_prediction_payload(predictions)),
            top.model_name if top else None,
            score_candidate(predictions),
            sighting_id,
        ),
    )
    _insert_predictions(connection, sighting_id=sighting_id, predictions=predictions)
    connection.commit()
    return get_sighting(connection, sighting_id)


def score_candidate(predictions: list[Prediction]) -> float:
    decision = decide_classification(predictions)
    confidence = decision.display_confidence or 0.0
    if decision.classification_status == "confident":
        return 300.0 + confidence
    if decision.classification_status == "likely":
        return 200.0 + confidence

    top = predictions[0] if predictions else None
    if top is None:
        return 0.0
    if common_species_name(top.species):
        return 100.0 + top.confidence
    if top.species.strip().lower() != "unknown":
        return 10.0 + top.confidence
    return 0.0


def _replace_best_candidate(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    predictions: list[Prediction],
    roi: dict[str, float],
    metadata: dict[str, Any],
    media_path: str | None,
    cropped_image_path: str | None,
    video_path: str | None,
    motion_score: float | None,
    candidate_index: int | None,
    candidate_score: float,
    last_candidate_at: datetime,
) -> None:
    top = predictions[0] if predictions else None
    decision = decide_classification(predictions)
    connection.execute("DELETE FROM predictions WHERE sighting_id = ?", (sighting_id,))
    connection.execute(
        """
        UPDATE sightings
        SET species_guess = ?,
            confidence = ?,
            classification_status = ?,
            display_label = ?,
            display_confidence = ?,
            decision_reason = ?,
            top_predictions_json = ?,
            roi_json = ?,
            metadata_json = ?,
            media_path = ?,
            cropped_image_path = ?,
            video_path = COALESCE(?, video_path),
            motion_score = ?,
            classifier_model = ?,
            best_candidate_index = ?,
            best_candidate_score = ?,
            last_candidate_at = ?
        WHERE id = ?
        """,
        (
            top.species if top else None,
            top.confidence if top else None,
            decision.classification_status,
            decision.display_label,
            decision.display_confidence,
            decision.decision_reason,
            json.dumps(_prediction_payload(predictions)),
            json.dumps(roi),
            json.dumps(metadata),
            media_path,
            cropped_image_path,
            video_path,
            motion_score,
            top.model_name if top else None,
            candidate_index,
            candidate_score,
            last_candidate_at.isoformat(),
            sighting_id,
        ),
    )
    _insert_predictions(connection, sighting_id=sighting_id, predictions=predictions)


def _insert_predictions(
    connection: sqlite3.Connection,
    *,
    sighting_id: str,
    predictions: list[Prediction],
) -> None:
    for prediction in predictions:
        connection.execute(
            """
            INSERT INTO predictions (id, sighting_id, species, confidence, rank, model_name)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(uuid4()),
                sighting_id,
                prediction.species,
                prediction.confidence,
                prediction.rank,
                prediction.model_name,
            ),
        )


def _prediction_payload(predictions: list[Prediction]) -> list[dict[str, Any]]:
    return [
        {
            "species": prediction.species,
            "confidence": prediction.confidence,
            "rank": prediction.rank,
            "model_name": prediction.model_name,
        }
        for prediction in predictions
    ]


def _sighting_from_row(connection: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    prediction_rows = connection.execute(
        """
        SELECT species, confidence, rank, model_name
        FROM predictions
        WHERE sighting_id = ?
        ORDER BY rank ASC
        """,
        (row["id"],),
    ).fetchall()
    sighting = dict(row)
    sighting["roi"] = json.loads(sighting.pop("roi_json") or "{}")
    sighting["metadata"] = json.loads(sighting.pop("metadata_json") or "{}")
    sighting["top_predictions"] = [dict(prediction) for prediction in prediction_rows]
    return sighting


def _device_from_row(row: sqlite3.Row) -> dict[str, Any]:
    device = dict(row)
    if device.get("is_charging") is not None:
        device["is_charging"] = bool(device["is_charging"])
    return device


def _remote_command_from_row(row: sqlite3.Row) -> dict[str, Any]:
    command = dict(row)
    command["payload"] = json.loads(command.pop("payload_json") or "{}")
    command["result"] = json.loads(command.pop("result_json") or "{}")
    return command


def _bool_to_db(value: bool | None) -> int | None:
    if value is None:
        return None
    return 1 if value else 0
