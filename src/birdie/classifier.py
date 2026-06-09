from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

COMMON_UK_GARDEN_BIRDS: tuple[str, ...] = (
    "Robin",
    "Blue Tit",
    "Great Tit",
    "Coal Tit",
    "Long-tailed Tit",
    "Blackbird",
    "Dunnock",
    "House Sparrow",
    "Starling",
    "Goldfinch",
    "Chaffinch",
    "Greenfinch",
    "Wood Pigeon",
    "Collared Dove",
    "Magpie",
    "Jackdaw",
    "Carrion Crow",
    "Wren",
    "Nuthatch",
    "Great Spotted Woodpecker",
)


@dataclass(frozen=True)
class Prediction:
    species: str
    confidence: float
    rank: int
    model_name: str


class ImageClassifier(Protocol):
    model_name: str

    def classify(self, image_path: Path) -> list[Prediction]:
        """Return ranked predictions for an image."""


class ClassifierUnavailableError(RuntimeError):
    """Raised when a configured classifier cannot be loaded or run."""


class DummyBirdClassifier:
    """Deterministic placeholder until the first real bird model is wired in."""

    model_name = "dummy-garden-prior-v0"

    def classify(self, image_path: Path) -> list[Prediction]:
        digest = hashlib.sha256(image_path.read_bytes()).digest()
        start = digest[0] % len(COMMON_UK_GARDEN_BIRDS)
        species = COMMON_UK_GARDEN_BIRDS[start:] + COMMON_UK_GARDEN_BIRDS[:start]

        top_confidence = 0.45 + (digest[1] / 255) * 0.28
        remaining = max(0.0, 1.0 - top_confidence)
        weights = (0.38, 0.27, 0.20, 0.15)
        scores = [top_confidence] + [remaining * weight for weight in weights]

        return [
            Prediction(
                species=name,
                confidence=round(score, 4),
                rank=rank,
                model_name=self.model_name,
            )
            for rank, (name, score) in enumerate(zip(species[:5], scores), start=1)
        ]


class BirderClassifier:
    """Birder-backed classifier using pretrained European common-bird models."""

    def __init__(
        self,
        *,
        birder_model_name: str = "regnet_z_4g_eu-common256px",
        top_k: int = 5,
    ) -> None:
        self.birder_model_name = birder_model_name
        self.model_name = f"birder:{birder_model_name}"
        self.top_k = max(1, top_k)
        self._runtime: tuple[Any, Any, Any, Any, dict[int, str]] | None = None

    def classify(self, image_path: Path) -> list[Prediction]:
        net, _model_info, transform, infer_image, labels_by_index = self._load_runtime()
        try:
            probabilities, _embedding = infer_image(net, str(image_path), transform)
        except Exception as exc:  # pragma: no cover - exercised with real Birder runtime.
            raise ClassifierUnavailableError(
                f"Birder inference failed for {image_path}: {exc}"
            ) from exc

        ranked = _rank_probabilities(probabilities, self.top_k)
        return [
            Prediction(
                species=labels_by_index.get(index, f"class_{index}"),
                confidence=round(confidence, 4),
                rank=rank,
                model_name=self.model_name,
            )
            for rank, (index, confidence) in enumerate(ranked, start=1)
        ]

    def _load_runtime(self) -> tuple[Any, Any, Any, Any, dict[int, str]]:
        if self._runtime is not None:
            return self._runtime

        try:
            import birder
            from birder.inference.classification import infer_image
        except ImportError as exc:
            raise ClassifierUnavailableError(
                "Birder classifier dependencies are not installed. "
                'Install them with: .\\.venv\\Scripts\\python -m pip install -e ".[classifier]"'
            ) from exc

        try:
            net, model_info, transform = birder.load_pretrained_model_and_transform(
                self.birder_model_name,
                inference=True,
            )
            if hasattr(net, "eval"):
                net.eval()
        except Exception as exc:  # pragma: no cover - depends on external model runtime.
            raise ClassifierUnavailableError(
                f"Could not load Birder model {self.birder_model_name!r}: {exc}"
            ) from exc

        labels_by_index = _labels_by_index(model_info)
        self._runtime = (net, model_info, transform, infer_image, labels_by_index)
        return self._runtime


def _rank_probabilities(probabilities: Any, top_k: int) -> list[tuple[int, float]]:
    values = probabilities
    if hasattr(values, "detach"):
        values = values.detach().cpu()
    if hasattr(values, "numpy"):
        values = values.numpy()
    if hasattr(values, "tolist"):
        values = values.tolist()
    if values and isinstance(values[0], list):
        values = values[0]

    indexed_scores = [(index, float(score)) for index, score in enumerate(values)]
    indexed_scores.sort(key=lambda item: item[1], reverse=True)
    return indexed_scores[:top_k]


def _labels_by_index(model_info: Any) -> dict[int, str]:
    class_to_idx = _get_model_info_value(model_info, "class_to_idx")
    if not class_to_idx:
        return {}
    return {int(index): str(label) for label, index in class_to_idx.items()}


def _get_model_info_value(model_info: Any, key: str) -> Any:
    if isinstance(model_info, dict):
        return model_info.get(key)
    return getattr(model_info, key, None)
