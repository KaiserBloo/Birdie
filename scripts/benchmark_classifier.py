from __future__ import annotations

import argparse
import statistics
import sys
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageDraw

from birdie.classifier import BirderClassifier, ClassifierUnavailableError


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark a Birder classifier model.")
    parser.add_argument("--model", default="regnet_z_4g_eu-common256px")
    parser.add_argument("--image", type=Path, default=None)
    parser.add_argument("--runs", type=int, default=5)
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    image_path = args.image or create_sample_image()
    classifier = BirderClassifier(birder_model_name=args.model, top_k=args.top_k)

    try:
        print(f"loading model={args.model}")
        start = time.perf_counter()
        first_predictions = classifier.classify(image_path)
        load_and_first_ms = (time.perf_counter() - start) * 1000
    except ClassifierUnavailableError as exc:
        print(str(exc), file=sys.stderr)
        return 2

    timings: list[float] = []
    for _ in range(max(0, args.runs - 1)):
        start = time.perf_counter()
        classifier.classify(image_path)
        timings.append((time.perf_counter() - start) * 1000)

    print(f"image={image_path}")
    print(f"load_plus_first_inference_ms={load_and_first_ms:.1f}")
    if timings:
        print(f"warm_mean_ms={statistics.mean(timings):.1f}")
        print(f"warm_min_ms={min(timings):.1f}")
        print(f"warm_max_ms={max(timings):.1f}")

    print("top_predictions=")
    for prediction in first_predictions:
        print(f"  {prediction.rank}. {prediction.species}: {prediction.confidence:.2%}")
    return 0


def create_sample_image() -> Path:
    path = Path(tempfile.gettempdir()) / "birdie-classifier-sample.jpg"
    image = Image.new("RGB", (512, 512), color=(185, 195, 176))
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 390, 512, 512), fill=(126, 95, 67))
    draw.ellipse((185, 170, 340, 315), fill=(72, 54, 40))
    draw.ellipse((292, 130, 395, 228), fill=(86, 64, 45))
    draw.ellipse((365, 160, 376, 171), fill=(10, 10, 8))
    draw.polygon([(394, 179), (450, 196), (394, 209)], fill=(193, 142, 44))
    draw.rectangle((120, 318, 430, 350), fill=(84, 61, 41))
    image.save(path, format="JPEG", quality=90)
    return path


if __name__ == "__main__":
    raise SystemExit(main())
