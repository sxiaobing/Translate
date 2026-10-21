"""Application configuration and secrets access."""

from __future__ import annotations

import os
import sys
from pathlib import Path


DEEPSEEK_API_URL = "https://api.deepseek.com/chat/completions"
DEEPSEEK_MODEL = "deepseek-chat"
REQUEST_TIMEOUT_SECONDS = 60.0

# Screen text is normally horizontal, so skipping the angle classifier saves
# model loading and inference time. Set SCREEN_TRANSLATOR_OCR_ANGLE=1 when
# recognizing rotated or vertical text is more important than latency.
OCR_USE_ANGLE_CLS = os.environ.get("SCREEN_TRANSLATOR_OCR_ANGLE", "").strip().lower() in {
    "1",
    "true",
    "yes",
    "on",
}


def application_dir() -> Path:
    """Return the folder containing the exe or the project entry point."""

    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    override = os.environ.get("SCREEN_TRANSLATOR_APP_DIR", "").strip()
    if override:
        return Path(override).resolve()
    return Path(__file__).resolve().parent


def bundled_ocr_models_dir() -> str | None:
    """Return the shipped PaddleOCR model cache when it is available."""

    candidate = application_dir() / "models" / "paddleocr"
    return str(candidate) if candidate.is_dir() else None


def get_api_key() -> str | None:
    """Return the configured API key without logging or persisting it."""

    value = os.environ.get("DEEPSEEK_API_KEY", "").strip()
    return value or None
