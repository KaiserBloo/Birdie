from __future__ import annotations

import asyncio
import json
from datetime import datetime
from html import escape
from typing import Any

import httpx

from .config import Settings
from .database import connect
from .repository import create_remote_command, latest_device, list_sightings
from .telegram import TelegramNotifier


class TelegramCommandPoller:
    def __init__(self, *, settings: Settings, notifier: TelegramNotifier) -> None:
        self.settings = settings
        self.notifier = notifier
        self.offset: int | None = None
        self.base_url = f"https://api.telegram.org/bot{notifier.bot_token}"

    async def run(self) -> None:
        await self._set_bot_commands()
        await self._skip_existing_updates()
        while True:
            try:
                await self._poll_once()
            except asyncio.CancelledError:
                raise
            except Exception:
                await asyncio.sleep(5)

    async def _skip_existing_updates(self) -> None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.get(f"{self.base_url}/getUpdates", params={"timeout": 0})
                response.raise_for_status()
                updates = response.json().get("result", [])
                if updates:
                    self.offset = int(updates[-1]["update_id"]) + 1
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self.offset = None

    async def _set_bot_commands(self) -> None:
        commands = [
            {"command": "status", "description": "Show phone, battery, power, network"},
            {"command": "battery", "description": "Show battery and charging state"},
            {"command": "screenshot", "description": "Send a fresh camera snapshot"},
            {"command": "snapshot", "description": "Alias for screenshot"},
            {"command": "recent", "description": "Show last sighting summary"},
            {"command": "ping", "description": "Check Birdie backend"},
            {"command": "help", "description": "List Birdie commands"},
        ]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(
                    f"{self.base_url}/setMyCommands",
                    data={"commands": json.dumps(commands)},
                )
                response.raise_for_status()
        except httpx.HTTPError:
            return

    async def _poll_once(self) -> None:
        params: dict[str, Any] = {
            "timeout": 25,
            "allowed_updates": json.dumps(["message"]),
        }
        if self.offset is not None:
            params["offset"] = self.offset

        async with httpx.AsyncClient(timeout=35) as client:
            response = await client.get(f"{self.base_url}/getUpdates", params=params)
            response.raise_for_status()
            updates = response.json().get("result", [])

        for update in updates:
            self.offset = int(update["update_id"]) + 1
            await self._handle_update(update)

    async def _handle_update(self, update: dict[str, Any]) -> None:
        message = update.get("message")
        if not isinstance(message, dict):
            return
        chat = message.get("chat") or {}
        chat_id = str(chat.get("id", ""))
        if chat_id != str(self.settings.telegram_chat_id):
            return
        text = str(message.get("text") or "").strip()
        if not text.startswith("/"):
            return

        command = text.split(maxsplit=1)[0].split("@", 1)[0].lower()
        message_id = int(message.get("message_id"))
        if command in {"/help", "/start"}:
            await self.notifier.send_text(_help_text(), reply_to_message_id=message_id)
        elif command in {"/ping"}:
            await self.notifier.send_text("Birdie is awake.", reply_to_message_id=message_id)
        elif command in {"/status", "/battery"}:
            await self._send_status(reply_to_message_id=message_id)
        elif command in {"/screenshot", "/snapshot"}:
            await self._queue_snapshot(chat_id=chat_id, message_id=message_id)
        elif command in {"/recent", "/last"}:
            await self._send_recent(reply_to_message_id=message_id)
        else:
            await self.notifier.send_text(
                "Unknown command. Send /help for Birdie commands.",
                reply_to_message_id=message_id,
            )

    async def _send_status(self, *, reply_to_message_id: int) -> None:
        with connect(self.settings.database_path) as connection:
            device = latest_device(connection)
        if device is None:
            await self.notifier.send_text(
                "No phone has checked in yet.",
                reply_to_message_id=reply_to_message_id,
            )
            return
        await self.notifier.send_text(
            _format_device_status(device),
            reply_to_message_id=reply_to_message_id,
        )

    async def _queue_snapshot(self, *, chat_id: str, message_id: int) -> None:
        with connect(self.settings.database_path) as connection:
            device = latest_device(connection)
            if device is None:
                await self.notifier.send_text(
                    "No phone has checked in yet, so I cannot request a snapshot.",
                    reply_to_message_id=message_id,
                )
                return
            command = create_remote_command(
                connection,
                device_id=device["id"],
                command="snapshot",
                telegram_chat_id=chat_id,
                telegram_message_id=message_id,
            )
        await self.notifier.send_text(
            f"Snapshot requested ({escape(command['id'][:8])}). The phone should reply with a camera frame on its next poll.",
            reply_to_message_id=message_id,
        )

    async def _send_recent(self, *, reply_to_message_id: int) -> None:
        with connect(self.settings.database_path) as connection:
            sightings = list_sightings(connection, limit=1)
        if not sightings:
            await self.notifier.send_text(
                "No sightings recorded yet.",
                reply_to_message_id=reply_to_message_id,
            )
            return
        await self.notifier.send_text(
            _format_recent_sighting(sightings[0]),
            reply_to_message_id=reply_to_message_id,
        )


def _help_text() -> str:
    return "\n".join(
        [
            "<b>Birdie commands</b>",
            "/status - phone, battery, power, network",
            "/battery - same status, focused on power",
            "/screenshot - send a fresh camera snapshot",
            "/snapshot - alias for /screenshot",
            "/recent - last sighting summary",
            "/ping - check the backend is awake",
        ]
    )


def _format_device_status(device: dict[str, Any]) -> str:
    lines = ["<b>Birdie phone status</b>"]
    lines.append(f"<b>Device</b>: {escape(str(device['id']))}")
    if device.get("phone_model"):
        lines.append(f"<b>Model</b>: {escape(str(device['phone_model']))}")
    if device.get("battery_level") is not None:
        lines.append(f"<b>Battery</b>: {float(device['battery_level']):.0f}%")
    if device.get("battery_status"):
        lines.append(f"<b>Status</b>: {escape(str(device['battery_status']))}")
    if device.get("power_source"):
        lines.append(f"<b>Power</b>: {escape(str(device['power_source']))}")
    if device.get("temperature_c") is not None:
        lines.append(f"<b>Temp</b>: {float(device['temperature_c']):.1f}C")
    if device.get("network_state"):
        lines.append(f"<b>Network</b>: {escape(str(device['network_state']))}")
    if device.get("last_seen"):
        lines.append(f"<b>Last seen</b>: {escape(_format_timestamp(device['last_seen']))}")
    return "\n".join(lines)


def _format_recent_sighting(sighting: dict[str, Any]) -> str:
    lines = ["<b>Last Birdie sighting</b>"]
    lines.append(f"<b>Result</b>: {escape(str(sighting.get('display_label') or 'species uncertain'))}")
    if sighting.get("display_confidence") is not None:
        lines.append(f"<b>Confidence</b>: {float(sighting['display_confidence']):.0%}")
    if sighting.get("candidate_count") is not None:
        lines.append(f"<b>Candidates</b>: {int(sighting['candidate_count'])}")
    if sighting.get("video_path"):
        lines.append("<b>Clip</b>: attached to sighting")
    if sighting.get("timestamp"):
        lines.append(f"<b>Captured</b>: {escape(_format_timestamp(sighting['timestamp']))}")
    return "\n".join(lines)


def _format_timestamp(value: object) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)
