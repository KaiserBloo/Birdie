# Birdie

DIY bird feeder camera software for an Android phone, a local Python backend, bird classification, media storage, video clips, remote Telegram commands, and Telegram alerts.

## Current Slice

This repo starts with the backend foundation:

- FastAPI API for device status, motion events, media uploads, sightings, and media retrieval
- SQLite storage for devices, sightings, and predictions
- Local filesystem media storage
- Fixed ROI cropping before classification
- Upload metadata for modest Android camera nodes such as the Motorola G35
- Classification decision layer with confident/likely/uncertain user labels
- Telegram alert cooldown tracking and remote commands
- Visit-aware alerts: first candidate can notify immediately, later better candidates update the stored Telegram message
- Phone-side MP4 visit clips: the Android app records a real video during a visit, uploads it separately from still classification frames, and the backend attaches it to the same sighting
- Model-agnostic classifier interface with a deterministic dummy classifier
- Tests for the main ingest flow

The Android app lives in `android/`. A polished dashboard is still a separate follow-up slice.

## Quick Start

```powershell
python -m venv .venv
.\.venv\Scripts\python -m pip install -e ".[dev]"
.\.venv\Scripts\python -m uvicorn birdie.main:create_app --factory --reload
```

Then open:

- API docs: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/health
- Sightings JSON: http://127.0.0.1:8000/sightings

Sightings store both raw model output and a safer display decision:

- `species_guess` / `confidence`: raw top model prediction
- `top_predictions`: raw top-k model predictions
- `classification_status`: `confident`, `likely`, or `uncertain`
- `display_label` / `display_confidence`: what alerts should show
- `decision_reason`: why the policy chose that status

## Example Upload

```powershell
curl.exe -F "device_id=android-window-phone" `
  -F "phone_model=Motorola G35" `
  -F "motion_score=0.82" `
  -F "roi_x=0.25" `
  -F "roi_y=0.25" `
  -F "roi_width=0.50" `
  -F "roi_height=0.50" `
  -F "image=@C:\path\to\bird.jpg" `
  http://127.0.0.1:8000/events/upload
```

Or post a generated sample event:

```powershell
.\.venv\Scripts\python scripts\post_sample_event.py
```

## Real Classifier

The default backend uses the deterministic dummy classifier so development stays fast. To enable Birder:

```powershell
.\.venv\Scripts\python -m pip install -e ".[classifier]"
$env:BIRDIE_CLASSIFIER="birder"
$env:BIRDIE_BIRDER_MODEL="regnet_z_4g_eu-common256px"
.\.venv\Scripts\python scripts\benchmark_classifier.py
.\.venv\Scripts\python -m uvicorn birdie.main:create_app --factory --reload
```

`regnet_z_4g_eu-common256px` is the default because it should be kinder to the Intel N150. Use `regnet_z_4g_eu-common` if the 384px model proves worth the extra CPU time.

## Configuration

Copy `.env.example` to `.env` or set environment variables directly.

| Variable | Purpose |
| --- | --- |
| `BIRDIE_DATA_DIR` | Root runtime data directory |
| `BIRDIE_DATABASE_PATH` | SQLite database path |
| `BIRDIE_MEDIA_DIR` | Stored image/video directory |
| `BIRDIE_DEVICE_TOKEN` | Optional shared token for Android requests |
| `BIRDIE_ALERT_COOLDOWN_SECONDS` | Alert grouping/cooldown window |
| `BIRDIE_CLASSIFIER` | `dummy` or `birder` |
| `BIRDIE_BIRDER_MODEL` | Birder model name, defaults to `regnet_z_4g_eu-common256px` |
| `BIRDIE_CLASSIFIER_TOP_K` | Number of predictions to store |
| `BIRDIE_LOW_BATTERY_PERCENT` | Telegram low-battery alert threshold |
| `BIRDIE_CRITICAL_BATTERY_PERCENT` | Telegram critical-battery alert threshold |
| `BIRDIE_HIGH_TEMPERATURE_C` | Telegram high-temperature alert threshold |
| `TELEGRAM_BOT_TOKEN` | Optional Telegram bot token |
| `TELEGRAM_CHAT_ID` | Optional Telegram chat ID |

When Telegram credentials are configured, Birdie sends a photo alert for the first upload in a visit. If a later candidate in the same visit classifies better, Birdie edits that Telegram message with the improved photo and caption instead of sending another notification. When the phone uploads the visit MP4, Birdie updates the same sighting with the clip.

Telegram commands include `/status`, `/battery`, `/screenshot` or `/snapshot`, `/recent`, `/ping`, and `/help`. The screenshot command sends a fresh camera frame from the phone.

## Docker / Coolify

Birdie can run as a Docker Compose service:

```powershell
docker compose up --build
```

The compose file exposes the backend on host port `8767` by default and persists all runtime state under the `birdie_data` volume mounted at `/data`.

For the mini-PC Coolify deployment, see [deploy/coolify.md](deploy/coolify.md). The Android phone should use the mini-PC Tailscale address, for example:

```text
http://<mini-pc-tailscale-name-or-ip>:8767
```

## Tests

```powershell
.\.venv\Scripts\python -m pytest
```

## Android App

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

See [android/README.md](android/README.md) for Motorola G35 setup and install notes.
