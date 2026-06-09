from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from .classifier import COMMON_UK_GARDEN_BIRDS


@dataclass(frozen=True)
class Settings:
    app_name: str
    data_dir: Path
    database_path: Path
    media_dir: Path
    device_token: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    alert_cooldown_seconds: int
    default_roi: dict[str, float]
    classifier_backend: str = "dummy"
    birder_model_name: str = "regnet_z_4g_eu-common256px"
    classifier_top_k: int = 5
    common_species: tuple[str, ...] = COMMON_UK_GARDEN_BIRDS
    low_battery_percent: int = 20
    critical_battery_percent: int = 10
    high_temperature_c: float = 42.0

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.media_dir.mkdir(parents=True, exist_ok=True)


def load_settings() -> Settings:
    env_file = _load_env_file(Path.cwd() / ".env")
    data_dir = _path_from_env("BIRDIE_DATA_DIR", "data", env_file)
    database_path = _path_from_env(
        "BIRDIE_DATABASE_PATH",
        str(data_dir / "birdie.db"),
        env_file,
    )
    media_dir = _path_from_env("BIRDIE_MEDIA_DIR", str(data_dir / "media"), env_file)

    return Settings(
        app_name="Birdie",
        data_dir=data_dir,
        database_path=database_path,
        media_dir=media_dir,
        device_token=_blank_to_none(_env("BIRDIE_DEVICE_TOKEN", env_file)),
        telegram_bot_token=_blank_to_none(_env("TELEGRAM_BOT_TOKEN", env_file)),
        telegram_chat_id=_blank_to_none(_env("TELEGRAM_CHAT_ID", env_file)),
        alert_cooldown_seconds=int(
            _env("BIRDIE_ALERT_COOLDOWN_SECONDS", env_file, "900")
        ),
        default_roi={"x": 0.25, "y": 0.25, "width": 0.50, "height": 0.50},
        classifier_backend=_env("BIRDIE_CLASSIFIER", env_file, "dummy").strip().lower(),
        birder_model_name=_env(
            "BIRDIE_BIRDER_MODEL",
            env_file,
            "regnet_z_4g_eu-common256px",
        ).strip(),
        classifier_top_k=int(_env("BIRDIE_CLASSIFIER_TOP_K", env_file, "5")),
        low_battery_percent=int(_env("BIRDIE_LOW_BATTERY_PERCENT", env_file, "20")),
        critical_battery_percent=int(
            _env("BIRDIE_CRITICAL_BATTERY_PERCENT", env_file, "10")
        ),
        high_temperature_c=float(_env("BIRDIE_HIGH_TEMPERATURE_C", env_file, "42")),
    )


def _env(name: str, values: dict[str, str], default: str = "") -> str:
    return os.getenv(name) or values.get(name) or default


def _path_from_env(name: str, default: str, values: dict[str, str]) -> Path:
    value = Path(_env(name, values, default)).expanduser()
    if value.is_absolute():
        return value
    return Path.cwd() / value


def _load_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}

    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, value = line.split("=", 1)
        name = name.strip()
        value = value.strip().strip('"').strip("'")
        if name:
            values[name] = value
    return values


def _blank_to_none(value: str | None) -> str | None:
    if value is None:
        return None
    value = value.strip()
    return value or None
