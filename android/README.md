# Birdie Android

Android camera node for Birdie. The first test device is currently the Samsung `SM-A505FN`; the Motorola G35 remains supported.

## What It Does

- Uses CameraX preview, image capture, and image analysis.
- Draws a fixed ROI over the feeder area.
- Runs lightweight grayscale frame-diff motion detection inside the ROI.
- Opens a visit when motion persists, uploads the first candidate immediately, then sends later candidates under the same visit ID.
- Lets the backend classify each candidate and keep the best frame for the visit.
- Keeps failed captures in a local pending queue and retries them.

This first slice is intentionally foreground-only. Leave the app open with power connected if possible. A foreground service/screen-off mode can come later after the capture path is proven.

## Build

```powershell
cd android
.\gradlew.bat :app:assembleDebug
```

Debug APK:

```text
android\app\build\outputs\apk\debug\app-debug.apk
```

## Install

Enable Developer Options and USB debugging on the Android phone, connect it over USB, then run:

```powershell
adb devices
adb install -r android\app\build\outputs\apk\debug\app-debug.apk
```

## Backend URL

When using USB during development, create an ADB reverse tunnel:

```powershell
adb reverse tcp:8000 tcp:8000
```

Then the app can use its default backend URL:

```text
http://127.0.0.1:8000
```

When the phone is unplugged, `127.0.0.1` means the phone itself. In that case, set the backend URL to one of:

- your backend LAN address, for example `http://<backend-lan-ip>:8767`
- a Tailscale/WireGuard address if using VPN
- `http://10.0.2.2:8000` only when running in the Android emulator

The FastAPI backend must listen on an address the phone can reach, for example:

```powershell
.\.venv\Scripts\python -m uvicorn birdie.main:create_app --factory --host 0.0.0.0 --port 8000
```

## Controls

- `Status`: sends `/device/status` with phone model, battery, temperature, network state, and app version.
- `Retry`: retries any queued uploads.

Motion capture runs automatically once camera permission is granted.

## Remote Telegram Commands

The backend polls Telegram when `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` are configured.

- `/status`: phone model, battery percentage, charging state, power source, temperature, network, and last seen.
- `/battery`: same status view, focused on power.
- `/screenshot` or `/snapshot`: asks the phone to capture and send a fresh camera frame. Android cannot silently capture the whole OS screen without a user-approved screen-capture session, so this is a camera snapshot.
- `/recent`: latest sighting summary.
- `/ping`: confirms the backend command worker is awake.
- `/help`: command list.

The phone posts status every 60 seconds and polls for commands every 10 seconds while the app is open. The backend sends Telegram device alerts when charging starts/stops, battery crosses low or critical thresholds, temperature crosses the high threshold, or network state changes.

## Debug Overlay

The lower overlay shows:

- `motion`: current ROI frame-difference score and trigger threshold.
- `frames`: consecutive above-threshold frames; a visit starts at `2/2`.
- `visit`: current visit state, candidate frame count, and best motion score seen by the phone.
- `quiet`: quiet time so far versus the visit-close timeout.
- `next`: time until the next candidate frame can be captured during an active visit.
- `samples`: number of luma samples from the ROI.
- `captures`: captures started in this app session.
- `uploads`: successful uploads in this app session.
- `queued`: files waiting for retry.
- `cmd`: remote command poll state and handled/error counts.

If motion score stays above threshold while a bird or screen video is moving, the app keeps the visit open and uploads up to four candidate stills. The first upload happens immediately; the quiet timer only closes the visit. The backend keeps one sighting row per visit and upgrades it when a later candidate classifies better.
