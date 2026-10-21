"""PaddleOCR integration and reading-order text normalization."""

from __future__ import annotations

import re
import os
import threading
from typing import Any

from PIL import Image

from config import OCR_USE_ANGLE_CLS, bundled_ocr_models_dir


class OcrError(RuntimeError):
    """A user-facing OCR failure."""


_engine = None
_engine_lock = threading.Lock()
_inference_lock = threading.Lock()


def using_bundled_models() -> bool:
    """Return whether OCR is configured to use the models in this release."""

    return bundled_ocr_models_dir() is not None


def _get_engine():
    global _engine
    if _engine is not None:
        return _engine
    with _engine_lock:
        if _engine is not None:
            return _engine
        try:
            # PaddlePaddle 3.x may select OneDNN automatically on Windows CPU.
            # PaddleOCR 2.x models can fail there with a missing fused-conv filter;
            # force the portable CPU inference path instead.
            os.environ["FLAGS_use_mkldnn"] = "0"
            models_dir = bundled_ocr_models_dir()
            if models_dir is not None:
                os.environ["PADDLE_OCR_BASE_DIR"] = models_dir
            import paddle

            if hasattr(paddle, "set_flags"):
                paddle.set_flags({"FLAGS_use_mkldnn": False})
            from paddleocr import PaddleOCR
        except ImportError as exc:
            raise OcrError("未安装 PaddleOCR 依赖，请先执行 pip install -r requirements.txt。") from exc

        try:
            _engine = PaddleOCR(
                use_angle_cls=OCR_USE_ANGLE_CLS,
                lang="ch",
                show_log=False,
                enable_mkldnn=False,
            )
        except TypeError:
            # Some PaddleOCR versions removed show_log.
            try:
                _engine = PaddleOCR(
                    use_angle_cls=OCR_USE_ANGLE_CLS,
                    lang="ch",
                    enable_mkldnn=False,
                )
            except Exception as exc:
                raise OcrError(f"PaddleOCR 初始化失败：{exc}") from exc
        except Exception as exc:
            raise OcrError(f"PaddleOCR 初始化失败：{exc}") from exc
        return _engine


def warm_up_ocr() -> None:
    """Load models and run one small inference while the UI is idle."""

    try:
        import numpy as np
        from PIL import ImageDraw
    except ImportError as exc:
        raise OcrError("未安装 OCR 运行依赖，请先执行 pip install -r requirements.txt。") from exc

    engine = _get_engine()
    image = Image.new("RGB", (480, 96), "white")
    ImageDraw.Draw(image).text((20, 36), "OCR warmup 123", fill="black")
    array = np.asarray(image)
    try:
        with _inference_lock:
            engine.ocr(array, cls=OCR_USE_ANGLE_CLS)
    except TypeError:
        with _inference_lock:
            engine.ocr(array)
    except Exception as exc:
        raise OcrError(f"OCR 预热失败：{exc}") from exc


def _box_metrics(box: Any) -> tuple[float, float, float]:
    points = []
    try:
        for point in box:
            points.append((float(point[0]), float(point[1])))
    except (TypeError, ValueError, IndexError):
        return 0.0, 0.0, 10.0
    if not points:
        return 0.0, 0.0, 10.0
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return min(xs), (min(ys) + max(ys)) / 2.0, max(10.0, max(ys) - min(ys))


def _collect_items(result: Any) -> list[tuple[Any, str, float]]:
    """Handle the list format used by PaddleOCR 2.x and common 3.x output."""

    items: list[tuple[Any, str, float]] = []
    if isinstance(result, dict):
        texts = result.get("rec_texts") or result.get("texts")
        boxes = result.get("rec_boxes") or result.get("dt_polys") or result.get("boxes")
        scores = result.get("rec_scores") or result.get("scores") or []
        if texts is not None and boxes is not None:
            for index, text in enumerate(texts):
                box = boxes[index] if index < len(boxes) else []
                score = float(scores[index]) if index < len(scores) else 1.0
                items.append((box, str(text), score))
        return items

    if isinstance(result, (list, tuple)):
        # A recognition pair is [four-point box, (text, confidence)].
        if len(result) == 2 and isinstance(result[1], (list, tuple)):
            box, value = result
            if isinstance(value, (list, tuple)) and value and isinstance(value[0], str):
                score = float(value[1]) if len(value) > 1 else 1.0
                items.append((box, value[0], score))
                return items
        for child in result:
            items.extend(_collect_items(child))
    return items


def _join_fragments(fragments: list[str]) -> str:
    cjk = re.compile(r"[\u3400-\u9fff]")
    output = ""
    for fragment in fragments:
        fragment = re.sub(r"\s+", " ", fragment).strip()
        if not fragment:
            continue
        if output and not (cjk.search(output[-1]) or cjk.search(fragment[0])):
            output += " "
        output += fragment
    return output


def recognize_text(image: Image.Image) -> str:
    """Recognize text and arrange boxes into top-to-bottom, left-to-right lines."""

    try:
        import numpy as np
    except ImportError as exc:
        raise OcrError("未安装 numpy 依赖，请先执行 pip install -r requirements.txt。") from exc

    engine = _get_engine()
    rgb = image.convert("RGB")
    array = np.asarray(rgb)
    try:
        with _inference_lock:
            result = engine.ocr(array, cls=OCR_USE_ANGLE_CLS)
    except TypeError:
        try:
            with _inference_lock:
                result = engine.ocr(array)
        except Exception as exc:
            raise OcrError(f"OCR 识别失败：{exc}") from exc
    except Exception as exc:
        raise OcrError(f"OCR 识别失败：{exc}") from exc

    raw_items = _collect_items(result)
    items: list[tuple[float, float, float, str]] = []
    for box, text, score in raw_items:
        if score < 0.25:
            continue
        clean = re.sub(r"\s+", " ", text).strip()
        if not clean:
            continue
        x, center_y, height = _box_metrics(box)
        items.append((center_y, x, height, clean))
    if not items:
        raise OcrError("未识别到文字，请选择包含清晰文字的区域。")

    lines: list[dict[str, Any]] = []
    for center_y, x, height, text in sorted(items, key=lambda item: (item[0], item[1])):
        matching = None
        for line in lines:
            tolerance = max(10.0, height * 0.6, line["height"] * 0.6)
            if abs(center_y - line["center_y"]) <= tolerance:
                matching = line
                break
        if matching is None:
            matching = {"center_y": center_y, "height": height, "count": 0, "items": []}
            lines.append(matching)
        matching["items"].append((x, text))
        count = matching["count"]
        matching["center_y"] = (matching["center_y"] * count + center_y) / (count + 1)
        matching["count"] = count + 1

    lines.sort(key=lambda line: line["center_y"])
    text_lines = []
    for line in lines:
        fragments = [text for _x, text in sorted(line["items"], key=lambda item: item[0])]
        joined = _join_fragments(fragments)
        if joined:
            text_lines.append(joined)
    if not text_lines:
        raise OcrError("未识别到文字，请选择包含清晰文字的区域。")
    return "\n".join(text_lines)
