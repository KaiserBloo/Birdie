from __future__ import annotations

import argparse
from io import BytesIO
from typing import Any

import httpx
from PIL import Image, ImageDraw


def main() -> None:
    parser = argparse.ArgumentParser(description="Post a sample Birdie event.")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--device-id", default="motorola-g35-window")
    parser.add_argument("--token", default=None)
    args = parser.parse_args()

    endpoint = args.url.rstrip("/") + "/events/upload"
    headers = {"X-Birdie-Token": args.token} if args.token else {}
    response = httpx.post(
        endpoint,
        headers=headers,
        data={
            "device_id": args.device_id,
            "device_name": "Window feeder phone",
            "phone_model": "Motorola G35",
            "motion_score": "0.82",
            "battery_level": "73",
            "network_state": "wifi",
            "app_version": "dev-sample",
            "roi_x": "0.20",
            "roi_y": "0.18",
            "roi_width": "0.60",
            "roi_height": "0.64",
        },
        files={"image": ("sample-bird.jpg", sample_image_bytes(), "image/jpeg")},
        timeout=20,
    )
    response.raise_for_status()
    print_summary(response.json())


def sample_image_bytes() -> bytes:
    image = Image.new("RGB", (960, 720), color=(188, 198, 176))
    draw = ImageDraw.Draw(image)

    draw.rectangle((0, 540, 960, 720), fill=(120, 98, 76))
    draw.rectangle((380, 180, 620, 640), fill=(88, 68, 48))
    draw.ellipse((420, 270, 590, 430), fill=(68, 54, 40))
    draw.ellipse((530, 220, 640, 330), fill=(76, 60, 44))
    draw.ellipse((608, 258, 620, 270), fill=(12, 12, 10))
    draw.polygon([(640, 278), (705, 295), (640, 310)], fill=(196, 142, 44))
    draw.rectangle((300, 465, 700, 505), fill=(94, 72, 48))

    output = BytesIO()
    image.save(output, format="JPEG", quality=90)
    return output.getvalue()


def print_summary(payload: dict[str, Any]) -> None:
    print(f"sighting_id={payload['id']}")
    print(f"species_guess={payload['species_guess']}")
    print(f"confidence={payload['confidence']}")
    print(f"classification_status={payload['classification_status']}")
    print(f"display_label={payload['display_label']}")
    print(f"display_confidence={payload['display_confidence']}")
    print(f"roi={payload['roi']}")
    for kind, url in payload["media_urls"].items():
        print(f"{kind}_url={url}")


if __name__ == "__main__":
    main()
