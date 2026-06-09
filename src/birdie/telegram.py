from __future__ import annotations

import json
from dataclasses import dataclass
from html import escape
from pathlib import Path
from typing import Any, Protocol

import httpx

from .config import Settings

CAPTION_LIMIT = 1024


@dataclass(frozen=True)
class NotificationResult:
    sent: bool
    message_id: int | None = None


class Notifier(Protocol):
    async def send_text(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> NotificationResult:
        """Send a text notification if configured."""

    async def send_media(
        self,
        media_path: Path,
        caption: str,
        *,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> NotificationResult:
        """Send a media notification if configured."""

    async def send_sighting(
        self,
        sighting: dict[str, Any],
        media_path: Path | None,
    ) -> NotificationResult:
        """Send a sighting notification if configured."""

    async def update_sighting(
        self,
        sighting: dict[str, Any],
        media_path: Path | None,
        *,
        message_id: int,
    ) -> bool:
        """Update a previously sent sighting notification if supported."""


class NoopNotifier:
    async def send_text(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> NotificationResult:
        return NotificationResult(sent=False)

    async def send_media(
        self,
        media_path: Path,
        caption: str,
        *,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> NotificationResult:
        return NotificationResult(sent=False)

    async def send_sighting(
        self,
        sighting: dict[str, Any],
        media_path: Path | None,
    ) -> NotificationResult:
        return NotificationResult(sent=False)

    async def update_sighting(
        self,
        sighting: dict[str, Any],
        media_path: Path | None,
        *,
        message_id: int,
    ) -> bool:
        return False


class TelegramNotifier:
    def __init__(self, *, bot_token: str, chat_id: str) -> None:
        self.bot_token = bot_token
        self.chat_id = chat_id

    @classmethod
    def from_settings(cls, settings: Settings) -> TelegramNotifier | NoopNotifier:
        if not settings.telegram_bot_token or not settings.telegram_chat_id:
            return NoopNotifier()
        return cls(bot_token=settings.telegram_bot_token, chat_id=settings.telegram_chat_id)

    async def send_sighting(
        self,
        sighting: dict[str, Any],
        media_path: Path | None,
    ) -> NotificationResult:
        caption = format_sighting_caption(sighting)

        try:
            if media_path and media_path.exists():
                return await self.send_media(media_path, caption)
            return await self.send_text(caption)
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return NotificationResult(sent=False)

    async def send_text(
        self,
        text: str,
        *,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> NotificationResult:
        base_url = f"https://api.telegram.org/bot{self.bot_token}"
        data = {
            "chat_id": chat_id or self.chat_id,
            "text": _fit_caption(text),
            "parse_mode": "HTML",
        }
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = str(reply_to_message_id)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                response = await client.post(f"{base_url}/sendMessage", data=data)
                response.raise_for_status()
                return NotificationResult(sent=True, message_id=_message_id(response))
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            return NotificationResult(sent=False)

    async def send_media(
        self,
        media_path: Path,
        caption: str,
        *,
        chat_id: str | None = None,
        reply_to_message_id: int | None = None,
    ) -> NotificationResult:
        base_url = f"https://api.telegram.org/bot{self.bot_token}"
        endpoint, field_name = _send_endpoint_and_field(media_path)
        data = {
            "chat_id": chat_id or self.chat_id,
            "caption": _fit_caption(caption),
            "parse_mode": "HTML",
        }
        if reply_to_message_id is not None:
            data["reply_to_message_id"] = str(reply_to_message_id)
        try:
            async with httpx.AsyncClient(timeout=20) as client:
                with media_path.open("rb") as media:
                    response = await client.post(
                        f"{base_url}/{endpoint}",
                        data=data,
                        files={
                            field_name: (
                                media_path.name,
                                media,
                                _media_mime_type(media_path),
                            )
                        },
                    )
                response.raise_for_status()
                return NotificationResult(sent=True, message_id=_message_id(response))
        except (httpx.HTTPError, ValueError, KeyError, TypeError, OSError):
            return NotificationResult(sent=False)

    async def update_sighting(
        self,
        sighting: dict[str, Any],
        media_path: Path | None,
        *,
        message_id: int,
    ) -> bool:
        caption = format_sighting_caption(sighting, updated=True)
        base_url = f"https://api.telegram.org/bot{self.bot_token}"

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                if media_path and media_path.exists():
                    media_type = _telegram_media_type(media_path)
                    media_payload = {
                        "type": media_type,
                        "media": "attach://media",
                        "caption": caption,
                        "parse_mode": "HTML",
                    }
                    with media_path.open("rb") as media:
                        response = await client.post(
                            f"{base_url}/editMessageMedia",
                            data={
                                "chat_id": self.chat_id,
                                "message_id": str(message_id),
                                "media": json.dumps(media_payload),
                            },
                            files={
                                "media": (
                                    media_path.name,
                                    media,
                                    _media_mime_type(media_path),
                                )
                            },
                        )
                    response.raise_for_status()
                    return True

                response = await client.post(
                    f"{base_url}/editMessageCaption",
                    data={
                        "chat_id": self.chat_id,
                        "message_id": str(message_id),
                        "caption": caption,
                        "parse_mode": "HTML",
                    },
                )
                response.raise_for_status()
                return True
        except httpx.HTTPError:
            return False


def format_sighting_caption(sighting: dict[str, Any], *, updated: bool = False) -> str:
    title = "Birdie sighting updated" if updated else "Birdie sighting"
    display_label = sighting.get("display_label")
    status = sighting.get("classification_status", "uncertain")
    confidence = sighting.get("display_confidence")
    timestamp = sighting.get("timestamp")
    predictions = sighting.get("top_predictions", [])
    candidate_count = sighting.get("candidate_count")
    if candidate_count is None:
        candidate_count = 1
    best_candidate_index = sighting.get("best_candidate_index")
    motion_score = sighting.get("motion_score")
    video_path = sighting.get("video_path")

    lines = [f"<b>{escape(title)}</b>"]
    if not display_label or status == "uncertain" or confidence is None:
        lines.append("<b>Result</b>: species uncertain")
    else:
        lines.append(
            f"<b>Result</b>: {escape(str(display_label))} "
            f"({float(confidence):.0%} raw confidence)"
        )

    if candidate_count > 1:
        best_text = (
            f", best frame {best_candidate_index + 1}"
            if isinstance(best_candidate_index, int)
            else ""
        )
        lines.append(f"<b>Visit</b>: {candidate_count} candidate frames{best_text}")
    if motion_score is not None:
        lines.append(f"<b>Motion</b>: {float(motion_score):.3f}")
    if video_path:
        lines.append("<b>Clip</b>: attached")
    if timestamp:
        lines.append(f"<b>Captured</b>: {escape(str(timestamp))}")

    if status != "uncertain" and predictions:
        lines.append("")
        lines.append("<b>Top predictions</b>")
        for index, prediction in enumerate(predictions[:3], start=1):
            species = escape(str(prediction["species"]))
            prediction_confidence = float(prediction["confidence"])
            rank = prediction.get("rank", index)
            lines.append(f"{rank}. {species} ({prediction_confidence:.1%})")

    return _fit_caption("\n".join(lines))


def _fit_caption(caption: str) -> str:
    if len(caption) <= CAPTION_LIMIT:
        return caption
    return caption[: CAPTION_LIMIT - 1].rstrip() + "..."


def _send_endpoint_and_field(path: Path) -> tuple[str, str]:
    media_type = _telegram_media_type(path)
    if media_type == "animation":
        return "sendAnimation", "animation"
    if media_type == "video":
        return "sendVideo", "video"
    return "sendPhoto", "photo"


def _telegram_media_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".gif":
        return "animation"
    if suffix in {".mp4", ".mov", ".webm"}:
        return "video"
    return "photo"


def _media_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix == ".gif":
        return "image/gif"
    if suffix == ".mp4":
        return "video/mp4"
    if suffix == ".webm":
        return "video/webm"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/jpeg"


def _message_id(response: httpx.Response) -> int | None:
    payload = response.json()
    result = payload.get("result")
    if not isinstance(result, dict):
        return None
    message_id = result.get("message_id")
    return int(message_id) if message_id is not None else None
