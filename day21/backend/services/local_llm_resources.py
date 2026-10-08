"""Ресурсы локальной модели по данным Ollama (день 29): версия и состояние памяти.

Задание дня требует сравнить варианты не только по качеству и скорости, но и по
потреблению ресурсов. Своих измерений здесь нет: Ollama сама сообщает, сколько
занимает загруженная модель (``GET /api/ps``) и какая у неё версия
(``GET /api/version``) — эти два числа и попадают в отчёт и в раздел интерфейса.

Почему сбой — данные, а не исключение. Метрика ресурсов идёт рядом с ответами
модели: если Ollama не отдала ``size_vram`` или вообще не ответила на ``/api/ps``,
прогон обязан продолжиться, а в отчёте появиться строка «Ollama не сообщила».
Поэтому обе функции возвращают разобранный словарь (``error`` вместо исключения), а
``get`` — точка подмены HTTP в тестах: офлайн-тест сети не открывает.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

import requests

from shared.logging_utils import get_logger

from ..core import config

logger = get_logger(__name__)

__all__ = ["snapshot", "version"]

#: Предел ожидания служебных запросов: они не должны задерживать прогон.
DEFAULT_TIMEOUT = 5.0


def version(*, url: Optional[str] = None, get: Optional[Callable[..., Any]] = None,
            timeout: float = DEFAULT_TIMEOUT) -> str:
    """Версия Ollama (``GET /api/version``); любой сбой — пустая строка.

    Версия попадает в шапку отчёта: у разных сборок Ollama отличаются и набор полей
    ``/api/ps``, и поведение ``num_ctx``, поэтому число нужно зафиксировать рядом с
    результатами, а не вспоминать потом.
    """
    base = str(url or config.LOCAL_LLM_URL).rstrip("/")
    call = get or requests.get
    try:
        response = call(f"{base}/api/version", timeout=timeout)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Версия Ollama не получена (%s): %s", base, exc)
        return ""
    if not isinstance(payload, dict):
        return ""
    return str(payload.get("version") or "")


def snapshot(*, url: Optional[str] = None, get: Optional[Callable[..., Any]] = None,
             timeout: float = DEFAULT_TIMEOUT) -> dict:
    """Загруженные модели и занятая память (``GET /api/ps``).

    Поля ответа Ollama: ``size`` — размер модели целиком, ``size_vram`` — её часть в
    видеопамяти, ``context_length`` — окно контекста загруженного экземпляра.
    ``gpu_percent`` считается здесь (100·``size_vram``/``size``): это то, ради чего
    снимок берётся — видно, влезла модель в VRAM целиком или часть слоёв считает CPU.
    Недостающие поля дают 0/"" (сборки Ollama отличаются), а недоступная служба —
    пустой список моделей с текстом ошибки.
    """
    base = str(url or config.LOCAL_LLM_URL).rstrip("/")
    call = get or requests.get
    try:
        response = call(f"{base}/api/ps", timeout=timeout)
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        logger.warning("Состояние Ollama не получено (%s): %s", base, exc)
        return _empty(f"Ollama недоступна: {exc}")
    if not isinstance(payload, dict):
        return _empty("Ollama вернула не объект JSON")
    models = [_model(item) for item in (payload.get("models") or [])
              if isinstance(item, dict)]
    return {
        "models": models,
        "vram_mb": max((item["vram_mb"] for item in models), default=0),
        "total_mb": max((item["size_mb"] for item in models), default=0),
        "error": "",
    }


def _empty(error: str) -> dict:
    """Снимок без данных: форма та же, что у успешного, поэтому отчёт не ветвится."""
    return {"models": [], "vram_mb": 0, "total_mb": 0, "error": error}


def _model(item: dict) -> dict:
    """Строка загруженной модели: размеры в мегабайтах и доля в видеопамяти."""
    size = int(item.get("size") or 0)
    vram = int(item.get("size_vram") or 0)
    return {
        "name": str(item.get("name") or item.get("model") or ""),
        "size_mb": round(size / 1024 / 1024, 1),
        "vram_mb": round(vram / 1024 / 1024, 1),
        "gpu_percent": round(100 * vram / size, 1) if size else 0.0,
        "context_length": int(item.get("context_length") or 0),
    }
