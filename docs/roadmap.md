# Roadmap

## Slice 1: Backend Ingest

Done:

- FastAPI app
- SQLite schema
- local media storage
- device status
- media upload
- fixed ROI crop
- classification decision layer
- alert cooldown ledger
- dummy classifier
- sightings API
- Telegram notifier shell

## Slice 2: Real Server Classifier

Done:

- Add a real classifier implementation behind `ImageClassifier`.
- Start with `birder-project/regnet_z_4g_eu-common`.
- Default to `regnet_z_4g_eu-common256px` for CPU-friendly first testing.
- Add a benchmark script for CPU latency on the Intel N150.
- Verified local warm CPU inference at about 31 ms per image with the 256px RegNet model.
- Store model version and top 5 predictions.
- Keep the dummy classifier for tests and offline development.

## Slice 3: Android Camera Node

Target test device: Samsung `SM-A505FN`; Motorola G35 remains supported.

Done:

- Kotlin project scaffold
- CameraX preview/image analysis
- ROI overlay
- grayscale frame-diff motion detector
- still-image capture
- file-backed retry queue
- upload metadata and media to `/events/upload`

Next:

- install on the Motorola G35 and tune motion thresholds against the real feeder
- make ROI adjustable on device
- add WorkManager-backed retries
- add foreground service/screen-off capture mode

## Slice 4: Visit Grouping

- Group motion into one visit.
- Send the first visit notification immediately, then upgrade the stored sighting as better candidates arrive.
- Send one best crop/image.
- Extend the current cooldown ledger into proper visit grouping.

## Slice 5: Gallery Dashboard

- Sightings list
- image/crop/video viewer
- prediction details
- reclassify button
- ROI tuning view
