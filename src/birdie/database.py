from __future__ import annotations

import sqlite3
from pathlib import Path

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS devices (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    phone_model TEXT,
    battery_level REAL,
    battery_status TEXT,
    is_charging INTEGER,
    power_source TEXT,
    temperature_c REAL,
    network_state TEXT,
    last_seen TEXT NOT NULL,
    app_version TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sightings (
    id TEXT PRIMARY KEY,
    device_id TEXT,
    timestamp TEXT NOT NULL,
    species_guess TEXT,
    confidence REAL,
    classification_status TEXT NOT NULL DEFAULT 'uncertain',
    display_label TEXT NOT NULL DEFAULT 'species uncertain',
    display_confidence REAL,
    decision_reason TEXT NOT NULL DEFAULT 'legacy sighting without decision metadata',
    top_predictions_json TEXT NOT NULL,
    roi_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    media_path TEXT,
    cropped_image_path TEXT,
    video_path TEXT,
    motion_score REAL,
    classifier_model TEXT,
    visit_id TEXT,
    candidate_count INTEGER NOT NULL DEFAULT 1,
    best_candidate_index INTEGER,
    best_candidate_score REAL,
    last_candidate_at TEXT,
    alert_sent_at TEXT,
    telegram_message_id INTEGER,
    created_at TEXT NOT NULL,
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS predictions (
    id TEXT PRIMARY KEY,
    sighting_id TEXT NOT NULL,
    species TEXT NOT NULL,
    confidence REAL NOT NULL,
    rank INTEGER NOT NULL,
    model_name TEXT NOT NULL,
    FOREIGN KEY(sighting_id) REFERENCES sightings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS visit_candidates (
    id TEXT PRIMARY KEY,
    sighting_id TEXT NOT NULL,
    visit_id TEXT NOT NULL,
    candidate_index INTEGER,
    captured_at TEXT NOT NULL,
    media_path TEXT,
    cropped_image_path TEXT,
    video_path TEXT,
    motion_score REAL,
    candidate_score REAL,
    created_at TEXT NOT NULL,
    FOREIGN KEY(sighting_id) REFERENCES sightings(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS remote_commands (
    id TEXT PRIMARY KEY,
    device_id TEXT,
    command TEXT NOT NULL,
    status TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    result_json TEXT NOT NULL DEFAULT '{}',
    telegram_chat_id TEXT,
    telegram_message_id INTEGER,
    error_message TEXT,
    requested_at TEXT NOT NULL,
    claimed_at TEXT,
    completed_at TEXT,
    FOREIGN KEY(device_id) REFERENCES devices(id) ON DELETE SET NULL
);
"""


def connect(database_path: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db(database_path: Path) -> None:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    with connect(database_path) as connection:
        connection.executescript(SCHEMA)
        _ensure_columns(connection)


def _ensure_columns(connection: sqlite3.Connection) -> None:
    required_columns = {
        "devices": {
            "phone_model": "TEXT",
            "battery_status": "TEXT",
            "is_charging": "INTEGER",
            "power_source": "TEXT",
            "temperature_c": "REAL",
            "network_state": "TEXT",
        },
        "sightings": {
            "classification_status": "TEXT NOT NULL DEFAULT 'uncertain'",
            "display_label": "TEXT NOT NULL DEFAULT 'species uncertain'",
            "display_confidence": "REAL",
            "decision_reason": "TEXT NOT NULL DEFAULT 'legacy sighting without decision metadata'",
            "roi_json": "TEXT NOT NULL DEFAULT '{}'",
            "metadata_json": "TEXT NOT NULL DEFAULT '{}'",
            "visit_id": "TEXT",
            "candidate_count": "INTEGER NOT NULL DEFAULT 1",
            "best_candidate_index": "INTEGER",
            "best_candidate_score": "REAL",
            "last_candidate_at": "TEXT",
            "alert_sent_at": "TEXT",
            "telegram_message_id": "INTEGER",
        },
    }
    for table_name, columns in required_columns.items():
        existing = {
            row["name"]
            for row in connection.execute(f"PRAGMA table_info({table_name})").fetchall()
        }
        for column_name, column_sql in columns.items():
            if column_name not in existing:
                connection.execute(
                    f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_sql}"
                )
    connection.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_sightings_device_visit
        ON sightings(device_id, visit_id)
        WHERE visit_id IS NOT NULL
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_visit_candidates_sighting
        ON visit_candidates(sighting_id, candidate_index)
        """
    )
    connection.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_remote_commands_device_status
        ON remote_commands(device_id, status, requested_at)
        """
    )
    connection.commit()
