# Android Camera Node

Target first test device: Samsung `SM-A505FN`. The Motorola G35 path remains supported. Treat the phone as a modest Android camera node, not as the main ML machine.

## Initial Scope

The first Android app is in `android/` and stays boring and reliable:

- Kotlin
- CameraX preview/image analysis
- Fixed region of interest around the feeder/perch
- Low-resolution grayscale frame difference motion detection
- Collect still-image candidates first, then short clips later
- Basic retry queue for failed uploads
- Device status heartbeat
- No on-device classifier in the first Android pass

## Suggested Data Sent With Uploads

- `device_id`
- `visit_id`
- `candidate_index`
- `captured_at`
- `motion_score`
- battery level
- phone model, for example `Samsung SM-A505FN` or `Motorola G35`
- optional temperature if Android exposes it safely
- network state
- app version
- candidate still images for the active visit
- backend-generated encounter animation once at least two candidates arrive
- optional video clip

## Motion Detection Rules

- Analyze only the ROI.
- Downscale before comparing frames.
- Ignore tiny changes.
- Require motion to persist across a short window.
- Open a visit while motion stays active and upload the first candidate immediately.
- Continue uploading a small number of later candidates with the same `visit_id`.
- Close the visit locally after a quiet period; the quiet period does not delay the first upload.
- Let the backend keep one sighting per visit and upgrade the stored frame when a later candidate classifies better.

## Phone Notes

Keep the phone workload small:

- Prefer still-image burst uploads before video.
- Let the backend crop and classify.
- Use a conservative frame analysis size for motion detection.
- Keep any local database as a retry queue, not as the source of truth.
- Start without TensorFlow Lite; add it only if server round-trips become annoying.

## Backend Endpoints To Use

- Fetch config: `GET /config`
- Report status: `POST /device/status`
- Send upload: `POST /events/upload`

## Current Limitations

- Foreground app only; keep it open and powered.
- Fixed ROI only; drag-to-adjust can come later.
- Still images only; short clips can come after visit grouping.
- Upload retry queue is local file based, not WorkManager/Room yet.

## Debug Overlay

The Android app shows current motion score, threshold, consecutive trigger frames, visit state, candidate count, best phone-side motion score, quiet timer, sample count, capture count, successful upload count, and queued upload count. Use it to tell the difference between idle monitoring, active visits, settling visits, and upload failures.
