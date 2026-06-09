from __future__ import annotations

from birdie.telegram import format_sighting_caption


def test_telegram_caption_uses_decision_label_and_confidence() -> None:
    caption = format_sighting_caption(
        {
            "classification_status": "likely",
            "display_label": "likely Blue Tit",
            "display_confidence": 0.51,
            "timestamp": "2026-06-08T08:42:00+00:00",
            "top_predictions": [
                {"species": "Whooper swan", "confidence": 0.55},
                {"species": "Blue tit", "confidence": 0.51},
                {"species": "Great tit", "confidence": 0.20},
            ],
        }
    )

    assert caption.startswith("<b>Birdie sighting</b>")
    assert "<b>Result</b>: likely Blue Tit (51% raw confidence)" in caption
    assert "<b>Top predictions</b>" in caption
    assert "1. Whooper swan (55.0%)" in caption
    assert "2. Blue tit (51.0%)" in caption


def test_telegram_caption_hides_species_when_uncertain() -> None:
    caption = format_sighting_caption(
        {
            "classification_status": "uncertain",
            "display_label": "species uncertain",
            "display_confidence": None,
            "timestamp": "2026-06-08T08:42:00+00:00",
            "top_predictions": [
                {"species": "Whooper swan", "confidence": 0.12},
                {"species": "Great egret", "confidence": 0.05},
            ],
        }
    )

    assert caption.startswith("<b>Birdie sighting</b>")
    assert "<b>Result</b>: species uncertain" in caption
    assert "Whooper swan" not in caption
