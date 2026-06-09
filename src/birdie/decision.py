from __future__ import annotations

from dataclasses import dataclass

from .classifier import COMMON_UK_GARDEN_BIRDS, Prediction

CONFIDENT_THRESHOLD = 0.65
LIKELY_THRESHOLD = 0.45
COMMON_PRIOR_CLOSE_MARGIN = 0.15

UNKNOWN_LABELS = {"unknown", "unidentified", "bird", "aves"}

COMMON_SPECIES_ALIASES = {
    "european robin": "Robin",
    "robin": "Robin",
    "eurasian blue tit": "Blue Tit",
    "blue tit": "Blue Tit",
    "great tit": "Great Tit",
    "coal tit": "Coal Tit",
    "long tailed tit": "Long-tailed Tit",
    "long-tailed tit": "Long-tailed Tit",
    "eurasian blackbird": "Blackbird",
    "common blackbird": "Blackbird",
    "blackbird": "Blackbird",
    "dunnock": "Dunnock",
    "house sparrow": "House Sparrow",
    "common starling": "Starling",
    "european starling": "Starling",
    "starling": "Starling",
    "european goldfinch": "Goldfinch",
    "goldfinch": "Goldfinch",
    "common chaffinch": "Chaffinch",
    "chaffinch": "Chaffinch",
    "european greenfinch": "Greenfinch",
    "greenfinch": "Greenfinch",
    "common wood pigeon": "Wood Pigeon",
    "wood pigeon": "Wood Pigeon",
    "woodpigeon": "Wood Pigeon",
    "eurasian collared dove": "Collared Dove",
    "collared dove": "Collared Dove",
    "eurasian magpie": "Magpie",
    "magpie": "Magpie",
    "western jackdaw": "Jackdaw",
    "jackdaw": "Jackdaw",
    "carrion crow": "Carrion Crow",
    "eurasian wren": "Wren",
    "wren": "Wren",
    "eurasian nuthatch": "Nuthatch",
    "nuthatch": "Nuthatch",
    "great spotted woodpecker": "Great Spotted Woodpecker",
}


@dataclass(frozen=True)
class ClassificationDecision:
    classification_status: str
    display_label: str
    display_confidence: float | None
    decision_reason: str


def decide_classification(predictions: list[Prediction]) -> ClassificationDecision:
    if not predictions:
        return ClassificationDecision(
            classification_status="uncertain",
            display_label="species uncertain",
            display_confidence=None,
            decision_reason="no classifier predictions were available",
        )

    top = predictions[0]
    top_common_species = common_species_name(top.species)
    if _is_unknown(top.species):
        common_alternative = _best_common_prediction(predictions[1:])
        if common_alternative and common_alternative.confidence >= LIKELY_THRESHOLD:
            return _likely_common_prior_decision(common_alternative, top)
        return ClassificationDecision(
            classification_status="uncertain",
            display_label="species uncertain",
            display_confidence=None,
            decision_reason="top classifier prediction was unknown",
        )

    if top_common_species:
        if top.confidence >= CONFIDENT_THRESHOLD:
            return ClassificationDecision(
                classification_status="confident",
                display_label=top_common_species,
                display_confidence=top.confidence,
                decision_reason="top prediction is a common UK garden species above the confident threshold",
            )
        if top.confidence >= LIKELY_THRESHOLD:
            return ClassificationDecision(
                classification_status="likely",
                display_label=f"likely {top_common_species}",
                display_confidence=top.confidence,
                decision_reason="top prediction is a common UK garden species above the likely threshold",
            )
        return ClassificationDecision(
            classification_status="uncertain",
            display_label="species uncertain",
            display_confidence=None,
            decision_reason="top common-species prediction was below the likely threshold",
        )

    common_alternative = _best_common_prediction(predictions[1:])
    if common_alternative and _is_common_alternative_close(top, common_alternative):
        return _likely_common_prior_decision(common_alternative, top)

    return ClassificationDecision(
        classification_status="uncertain",
        display_label="species uncertain",
        display_confidence=None,
        decision_reason="top prediction was not in the common UK garden prior",
    )


def common_species_name(species: str) -> str | None:
    normalized = _normalize_species(species)
    if normalized in COMMON_SPECIES_ALIASES:
        return COMMON_SPECIES_ALIASES[normalized]

    for common_species in COMMON_UK_GARDEN_BIRDS:
        if normalized == _normalize_species(common_species):
            return common_species
    return None


def _best_common_prediction(predictions: list[Prediction]) -> Prediction | None:
    common_predictions = [
        prediction for prediction in predictions if common_species_name(prediction.species)
    ]
    if not common_predictions:
        return None
    return max(common_predictions, key=lambda prediction: prediction.confidence)


def _is_common_alternative_close(top: Prediction, alternative: Prediction) -> bool:
    return (
        alternative.confidence >= LIKELY_THRESHOLD
        and top.confidence - alternative.confidence <= COMMON_PRIOR_CLOSE_MARGIN
    )


def _likely_common_prior_decision(
    common_prediction: Prediction,
    top_prediction: Prediction,
) -> ClassificationDecision:
    common_name = common_species_name(common_prediction.species) or common_prediction.species
    return ClassificationDecision(
        classification_status="likely",
        display_label=f"likely {common_name}",
        display_confidence=common_prediction.confidence,
        decision_reason=(
            "common UK garden prior preferred a plausible close prediction "
            f"over raw top prediction {top_prediction.species!r}"
        ),
    )


def _is_unknown(species: str) -> bool:
    return _normalize_species(species) in UNKNOWN_LABELS


def _normalize_species(species: str) -> str:
    normalized = (
        species.lower()
        .replace("-", " ")
        .replace("_", " ")
        .replace("'", "")
        .replace(".", "")
        .strip()
    )
    return " ".join(normalized.split())
