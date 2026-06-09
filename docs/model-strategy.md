# Model Strategy

## First Server Classifier

Start with `birder-project/regnet_z_4g_eu-common`, using `regnet_z_4g_eu-common256px` first for CPU friendliness on the Intel N150.

The backend already exposes a small classifier interface:

- input: image path
- output: ranked predictions with species, confidence, rank, and model name

That keeps the ingest API stable while models change.

The upload path creates a fixed ROI crop when the still image is valid. Classifiers should receive the cropped image first and only fall back to the original image when cropping fails or the event is video-only.

## Classification Policy

Do not blindly trust the top label. Use:

- top 5 predictions
- confidence threshold
- UK/common garden bird prior
- uncertainty handling

Suggested message behavior:

- High confidence and plausible species: send the species.
- Medium confidence: send "likely species".
- Low confidence: send "bird detected, species uncertain".
- Rare/non-UK prediction with close common alternative: mark uncertain or prefer the common plausible species.

Implemented policy fields:

- `species_guess` and `confidence`: raw top classifier output.
- `top_predictions`: raw top-k classifier output.
- `classification_status`: `confident`, `likely`, or `uncertain`.
- `display_label`: the label intended for Telegram/dashboard display.
- `display_confidence`: confidence belonging to the displayed label.
- `decision_reason`: human-readable policy explanation.

Current thresholds:

- confident: common UK garden species at `0.65` or higher.
- likely: common UK garden species at `0.45` or higher.
- common-prior override: common species at `0.45` or higher and within `0.15` of a non-common raw top prediction.

## Phone Role

The Motorola G35 should not run the first production classifier. Use it for CameraX capture, ROI motion detection, metadata, and retry-safe uploads. Revisit TensorFlow Lite later only if a local rough guess proves useful.

## Runtime Switch

The backend supports:

- `BIRDIE_CLASSIFIER=dummy` for fast development and tests.
- `BIRDIE_CLASSIFIER=birder` for real server-side inference.
- `BIRDIE_BIRDER_MODEL=regnet_z_4g_eu-common256px` by default.

Before leaving Birder enabled for live alerts, run:

```powershell
.\.venv\Scripts\python -m pip install -e ".[classifier]"
.\.venv\Scripts\python scripts\benchmark_classifier.py
```

## First Local Benchmark

On this Windows dev machine with `regnet_z_4g_eu-common256px`:

- first load plus first inference: about 12.6 seconds, including the initial model setup
- warm CPU inference: about 31 ms per image
- downloaded weight file: `models/regnet_z_4g_eu-common256px.pt`, about 109 MB

The synthetic sample image is only for plumbing verification, not accuracy evaluation. Use real feeder crops before drawing conclusions about species quality.

## Common UK Garden Prior

- Robin
- Blue Tit
- Great Tit
- Coal Tit
- Long-tailed Tit
- Blackbird
- Dunnock
- House Sparrow
- Starling
- Goldfinch
- Chaffinch
- Greenfinch
- Wood Pigeon
- Collared Dove
- Magpie
- Jackdaw
- Carrion Crow
- Wren
- Nuthatch
- Great Spotted Woodpecker
