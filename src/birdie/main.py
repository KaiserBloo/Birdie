from __future__ import annotations

import asyncio

from fastapi import FastAPI

from .api.routes import router
from .classifier import BirderClassifier, DummyBirdClassifier, ImageClassifier
from .config import Settings, load_settings
from .database import init_db
from .telegram import NoopNotifier, TelegramNotifier
from .telegram_commands import TelegramCommandPoller


def create_app(
    settings: Settings | None = None,
    classifier: ImageClassifier | None = None,
    notifier: TelegramNotifier | NoopNotifier | None = None,
) -> FastAPI:
    settings = settings or load_settings()
    settings.ensure_directories()
    init_db(settings.database_path)

    app = FastAPI(
        title="Birdie",
        summary="DIY bird feeder camera backend",
        version="0.1.0",
    )
    app.state.settings = settings
    app.state.classifier = classifier or build_classifier(settings)
    app.state.notifier = notifier or TelegramNotifier.from_settings(settings)
    app.state.telegram_command_task = None

    @app.on_event("startup")
    async def start_telegram_commands() -> None:
        if isinstance(app.state.notifier, TelegramNotifier):
            poller = TelegramCommandPoller(
                settings=settings,
                notifier=app.state.notifier,
            )
            app.state.telegram_command_task = asyncio.create_task(poller.run())

    @app.on_event("shutdown")
    async def stop_telegram_commands() -> None:
        task = app.state.telegram_command_task
        if task is not None:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    app.include_router(router)
    return app


def build_classifier(settings: Settings) -> ImageClassifier:
    if settings.classifier_backend == "dummy":
        return DummyBirdClassifier()
    if settings.classifier_backend == "birder":
        return BirderClassifier(
            birder_model_name=settings.birder_model_name,
            top_k=settings.classifier_top_k,
        )
    raise ValueError(
        f"Unsupported BIRDIE_CLASSIFIER={settings.classifier_backend!r}; "
        "expected 'dummy' or 'birder'."
    )
