from __future__ import annotations

import sys
import types
import builtins
from pathlib import Path

import pytest

from birdie.classifier import BirderClassifier, ClassifierUnavailableError
from birdie.config import Settings
from birdie.main import build_classifier


def test_birder_classifier_maps_top_predictions(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    image = tmp_path / "bird.jpg"
    image.write_bytes(b"image")

    birder_module = types.ModuleType("birder")
    classification_module = types.ModuleType("birder.inference.classification")

    class Net:
        def __init__(self) -> None:
            self.eval_called = False

        def eval(self) -> None:
            self.eval_called = True

    class ModelInfo:
        class_to_idx = {
            "Blue Tit": 0,
            "Robin": 1,
            "Blackbird": 2,
        }

    def load_pretrained_model_and_transform(model_name: str, inference: bool) -> tuple:
        assert model_name == "regnet_z_4g_eu-common256px"
        assert inference is True
        return Net(), ModelInfo(), "transform"

    def infer_image(net: Net, image_path: str, transform: str) -> tuple:
        assert image_path == str(image)
        assert transform == "transform"
        return [[0.21, 0.72, 0.40]], None

    birder_module.load_pretrained_model_and_transform = load_pretrained_model_and_transform
    classification_module.infer_image = infer_image
    monkeypatch.setitem(sys.modules, "birder", birder_module)
    monkeypatch.setitem(sys.modules, "birder.inference", types.ModuleType("birder.inference"))
    monkeypatch.setitem(sys.modules, "birder.inference.classification", classification_module)

    classifier = BirderClassifier(
        birder_model_name="regnet_z_4g_eu-common256px",
        top_k=2,
    )

    predictions = classifier.classify(image)

    assert [prediction.species for prediction in predictions] == ["Robin", "Blackbird"]
    assert [prediction.confidence for prediction in predictions] == [0.72, 0.4]
    assert predictions[0].model_name == "birder:regnet_z_4g_eu-common256px"


def test_birder_classifier_reports_missing_dependency(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    real_import = builtins.__import__

    def fail_birder_import(name: str, *args, **kwargs):
        if name == "birder" or name.startswith("birder."):
            raise ImportError("no birder here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fail_birder_import)

    classifier = BirderClassifier()

    with pytest.raises(ClassifierUnavailableError, match="dependencies are not installed"):
        classifier.classify(tmp_path / "bird.jpg")


def test_build_classifier_selects_birder(tmp_path: Path) -> None:
    settings = Settings(
        app_name="Birdie",
        data_dir=tmp_path,
        database_path=tmp_path / "birdie.db",
        media_dir=tmp_path / "media",
        device_token=None,
        telegram_bot_token=None,
        telegram_chat_id=None,
        alert_cooldown_seconds=900,
        default_roi={"x": 0.25, "y": 0.25, "width": 0.50, "height": 0.50},
        classifier_backend="birder",
        birder_model_name="regnet_z_4g_eu-common256px",
        classifier_top_k=3,
    )

    classifier = build_classifier(settings)

    assert isinstance(classifier, BirderClassifier)
    assert classifier.birder_model_name == "regnet_z_4g_eu-common256px"
    assert classifier.top_k == 3
