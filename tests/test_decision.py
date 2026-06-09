from __future__ import annotations

from birdie.classifier import Prediction
from birdie.decision import decide_classification


def test_decision_confident_for_high_common_species() -> None:
    decision = decide_classification(
        [
            _prediction("Eurasian blue tit", 0.82, 1),
            _prediction("Great tit", 0.08, 2),
        ]
    )

    assert decision.classification_status == "confident"
    assert decision.display_label == "Blue Tit"
    assert decision.display_confidence == 0.82


def test_decision_likely_for_medium_common_species() -> None:
    decision = decide_classification([_prediction("European robin", 0.52, 1)])

    assert decision.classification_status == "likely"
    assert decision.display_label == "likely Robin"
    assert decision.display_confidence == 0.52


def test_decision_uncertain_for_low_common_species() -> None:
    decision = decide_classification([_prediction("Great tit", 0.24, 1)])

    assert decision.classification_status == "uncertain"
    assert decision.display_label == "species uncertain"
    assert decision.display_confidence is None


def test_decision_prefers_close_common_alternative_over_rare_top_prediction() -> None:
    decision = decide_classification(
        [
            _prediction("Whooper swan", 0.55, 1),
            _prediction("Great tit", 0.48, 2),
        ]
    )

    assert decision.classification_status == "likely"
    assert decision.display_label == "likely Great Tit"
    assert decision.display_confidence == 0.48
    assert "common UK garden prior" in decision.decision_reason


def test_decision_treats_azure_winged_magpie_as_magpie_hint() -> None:
    decision = decide_classification([_prediction("Azure-winged magpie", 0.49, 1)])

    assert decision.classification_status == "likely"
    assert decision.display_label == "likely Magpie"
    assert decision.display_confidence == 0.49


def test_decision_uncertain_for_rare_top_without_close_common_alternative() -> None:
    decision = decide_classification(
        [
            _prediction("Whooper swan", 0.55, 1),
            _prediction("Great tit", 0.22, 2),
        ]
    )

    assert decision.classification_status == "uncertain"
    assert decision.display_label == "species uncertain"
    assert decision.display_confidence is None


def test_decision_uncertain_for_unknown_top_prediction() -> None:
    decision = decide_classification(
        [
            _prediction("Unknown", 0.70, 1),
            _prediction("Blue tit", 0.31, 2),
        ]
    )

    assert decision.classification_status == "uncertain"
    assert decision.display_label == "species uncertain"
    assert decision.display_confidence is None


def _prediction(species: str, confidence: float, rank: int) -> Prediction:
    return Prediction(
        species=species,
        confidence=confidence,
        rank=rank,
        model_name="test-model",
    )
