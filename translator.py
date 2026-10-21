"""DeepSeek text translation client."""

from __future__ import annotations

import json
import threading
from collections.abc import Callable

import httpx

from config import DEEPSEEK_API_URL, DEEPSEEK_MODEL, REQUEST_TIMEOUT_SECONDS, get_api_key


class TranslatorError(RuntimeError):
    """A user-facing translation failure."""


TARGET_LANGUAGES = {
    "简体中文": "简体中文",
    "English": "English",
    "日本語": "日本語",
    "한국어": "한국어",
    "Français": "Français",
    "Deutsch": "Deutsch",
    "Español": "Español",
    "Русский": "Русский",
}

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    """Reuse TLS connections between screenshots."""

    global _client
    if _client is not None:
        return _client
    with _client_lock:
        if _client is None:
            _client = httpx.Client(
                timeout=httpx.Timeout(REQUEST_TIMEOUT_SECONDS, connect=10.0),
                limits=httpx.Limits(
                    max_connections=4,
                    max_keepalive_connections=2,
                    keepalive_expiry=300.0,
                ),
            )
    return _client


def close_translator() -> None:
    """Release pooled HTTP connections during application shutdown."""

    global _client
    with _client_lock:
        client = _client
        _client = None
    if client is not None:
        client.close()


def _build_request(text: str, target_language: str, *, stream: bool = False) -> dict:
    api_key = get_api_key()
    if not api_key:
        raise TranslatorError("未配置 DEEPSEEK_API_KEY，请先设置 DeepSeek API Key。")
    language = TARGET_LANGUAGES.get(target_language, target_language).strip()
    if not language:
        raise TranslatorError("未选择目标语言。")

    payload = {
        "model": DEEPSEEK_MODEL,
        "temperature": 0.1,
        "stream": stream,
        "messages": [
            {
                "role": "system",
                "content": (
                    f"You are a professional translator. Translate the user's text into {language}. "
                    "Output only the translation, preserve paragraph and line breaks, and do not add explanations."
                ),
            },
            {"role": "user", "content": text},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "text/event-stream" if stream else "application/json",
    }
    return {"headers": headers, "json": payload}


def _raise_http_error(exc: httpx.HTTPStatusError) -> None:
    status = exc.response.status_code
    if status == 401:
        message = "DeepSeek API Key 无效或已失效。"
    elif status == 429:
        message = "DeepSeek 请求过于频繁或额度不足，请稍后重试。"
    else:
        message = f"DeepSeek 接口返回 HTTP {status}。"
    raise TranslatorError(message) from exc


def _extract_content(data: dict) -> str:
    try:
        return data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise TranslatorError("DeepSeek 返回的数据格式异常。") from exc


def _extract_delta(data: dict) -> str:
    try:
        content = data["choices"][0]["delta"].get("content")
    except (KeyError, IndexError, AttributeError, TypeError):
        return ""
    return content if isinstance(content, str) else ""


def translate_text(text: str, target_language: str) -> str:
    """Translate plain OCR text through DeepSeek Chat Completions."""

    request = _build_request(text, target_language)
    try:
        response = _get_client().post(
            DEEPSEEK_API_URL,
            **request,
        )
        response.raise_for_status()
    except httpx.TimeoutException as exc:
        raise TranslatorError("请求 DeepSeek 超时，请检查网络后重试。") from exc
    except httpx.HTTPStatusError as exc:
        _raise_http_error(exc)
    except httpx.RequestError as exc:
        raise TranslatorError(f"无法连接 DeepSeek：{exc}") from exc

    try:
        data = response.json()
        translated = _extract_content(data)
    except ValueError as exc:
        raise TranslatorError("DeepSeek 返回的数据格式异常。") from exc
    if not isinstance(translated, str) or not translated.strip():
        raise TranslatorError("DeepSeek 未返回有效译文。")
    return translated.strip()


def translate_text_stream(
    text: str,
    target_language: str,
    on_delta: Callable[[str], None],
) -> str:
    """Translate while emitting text deltas as soon as DeepSeek returns them."""

    request = _build_request(text, target_language, stream=True)
    pieces: list[str] = []
    try:
        with _get_client().stream(
            "POST",
            DEEPSEEK_API_URL,
            **request,
        ) as response:
            response.raise_for_status()
            for raw_line in response.iter_lines():
                line = raw_line.strip()
                if not line or line.startswith(":") or not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if data == "[DONE]":
                    break
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    continue
                delta = _extract_delta(event)
                if delta:
                    pieces.append(delta)
                    on_delta(delta)
    except httpx.TimeoutException as exc:
        raise TranslatorError("请求 DeepSeek 超时，请检查网络后重试。") from exc
    except httpx.HTTPStatusError as exc:
        _raise_http_error(exc)
    except httpx.RequestError as exc:
        raise TranslatorError(f"无法连接 DeepSeek：{exc}") from exc

    translated = "".join(pieces).strip()
    if not translated:
        raise TranslatorError("DeepSeek 未返回有效译文。")
    return translated
