"""Прогон профилей локальной модели на кейсе RAG (день 29).

Что происходит. ``POST /llm/tune`` превращается в пары «модель × профиль», каждая из
которых гоняет один и тот же набор вопросов десять раз через
``RAGService.rag_query(provider="local", profile=...)``. Поиск по корпусу не меняется
вообще: день 29 оптимизирует генерацию, поэтому сравнивать надо именно её.

Почему по варианту за запрос, а не всё сразу. Прогон четырёх вариантов (две модели на
два профиля) — это десятки минут локальной модели, и один HTTP-запрос на всё упирается
в таймаут и не показывает прогресса. Поэтому интерфейс и скрипт вызывают эндпоинт по
разу на пару, а сводку считает домен ``local_tuning_eval`` — один и тот же и для
сервиса, и для интерфейса, и для отчёта.

Отказы. Сбой одного вызова — строка ``mode="error"`` (как в парном прогоне дня 28), а
не срыв варианта; отказ запроса (``RAGRejected``: пустой вопрос, незнакомая стратегия,
пустой индекс) уходит наверх и становится 400/409. Если ошибками кончились ВСЕ строки
всех вариантов, это уже не прогон, а недоступная Ollama — ``LocalLLMError`` с текстом
причины (роутер отдаёт 502).
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from ..core import config
from ..domain import llm_provider, local_tuning, local_tuning_eval, rag_mode, rag_demo
from .local_llm_client import LocalLLMError
from .local_llm_resources import snapshot, version
from .rag_errors import RAGUpstreamError

__all__ = ["run"]


def run(service: Any, *, questions: Optional[Iterable[str]] = None,
        profiles: Optional[Iterable[str]] = None,
        models: Optional[Iterable[str]] = None,
        top_k: Optional[int] = None,
        strategy: Optional[str] = None) -> dict:
    """Прогоняет варианты на наборе вопросов и отдаёт строки, ресурсы и сводку.

    ``snapshot``/``version`` берутся из модуля (точка подмены в тестах): метрика
    ресурсов не имеет права срывать прогон, поэтому её сбой приходит данными.
    """
    texts = _questions(questions)
    names = list(profiles or local_tuning.PROFILES)
    catalog = {item.question: item for item in rag_demo.load_questions()}
    params = [local_tuning.create(name).as_dict() for name in names]
    pairs = [(model, name) for model in (models or [config.LOCAL_LLM_MODEL])
             for name in names]
    before = snapshot()
    variants = [_variant(service, model, name, texts, catalog, top_k, strategy)
                for model, name in pairs]
    _check_errors(variants)
    summary = local_tuning_eval.summary(variants)
    return {
        "url": config.LOCAL_LLM_URL,
        "model": config.LOCAL_LLM_MODEL,
        "ollama_version": version(),
        "active_profile": (local_tuning.LOCAL_LLM_PROFILE
                           if local_tuning.active(llm_provider.PROVIDER_LOCAL) else ""),
        "profiles": params,
        "top_k": rag_mode.RAG_DEFAULT_TOP_K if top_k is None else int(top_k),
        "strategy": rag_mode.resolve_rag_strategy(strategy),
        "variants": variants,
        "pairs": summary["pairs"],
        "best": summary["best"],
        "ps_before": before,
        "total_ms": summary["total_ms"],
    }


def _questions(questions: Optional[Iterable[str]]) -> List[str]:
    """Вопросы прогона: заданные списком или десять контрольных вопросов демо.

    Пустое поле запроса (``None``) и пустой список значат одно: прогонять нечего, и
    берётся набор демо — как у ``POST /rag/demo-run`` без тела.
    """
    if not questions:
        return [item.question for item in rag_demo.load_questions()]
    return [str(item).strip() for item in questions if str(item or "").strip()]


def _variant(service: Any, model: str, name: str, texts: List[str],
             catalog: Dict[str, rag_demo.DemoQuestion],
             top_k: Optional[int], strategy: Optional[str]) -> dict:
    """Вариант «профиль × модель»: параметры, строки на каждый вопрос и ресурсы после."""
    profile = local_tuning.create(name, model=(model or None))
    rows = [_row(service, text, catalog.get(text), profile, model, top_k, strategy)
            for text in texts]
    return {
        "params": profile.as_dict(),
        "resources": _resources(rows),
        "rows": rows,
        "summary": local_tuning_eval.summarize(rows),
    }


def _row(service: Any, text: str, question: Optional[rag_demo.DemoQuestion],
         profile: local_tuning.TuningProfile, model: str,
         top_k: Optional[int], strategy: Optional[str]) -> dict:
    """Строка вопроса: запись ответа локальной модели и метрики дня 29.

    Вопрос вне набора демо ожиданий не имеет — строка считается без них (вердикт
    ``без ожиданий``), прогон из-за этого не срывается: гонять можно и свой список.
    """
    try:
        record = service.rag_query(text, top_k, strategy,
                                   provider=llm_provider.PROVIDER_LOCAL, profile=profile)
    except RAGUpstreamError as exc:
        record = _failure(text, exc)
    expected = question if question is not None else rag_demo.DemoQuestion(question=text)
    return local_tuning_eval.quality_row(expected, record, profile=profile, model=model)


def _failure(question: str, exc: Exception) -> dict:
    """Синтетическая запись упавшего вызова: те же поля, что читает строка прогона."""
    return {"mode": "error", "question": question, "answer": "", "provider": "",
            "fallback": True, "warning": str(exc), "grounding": "", "sources": [],
            "quotes": [], "quotes_verified": False, "confidence": 0.0,
            "chunks_used": 0, "context_tokens": 0, "tokens": None, "duration_ms": 0}


def _resources(rows: List[dict]) -> dict:
    """Ресурсы варианта: снимок ``/api/ps`` плюс измеренные прогрев и скорость.

    Снимок берётся ПОСЛЕ вопросов варианта: к этому моменту модель загружена, и
    ``size_vram``/``context_length`` относятся именно к ней, а не к соседнему тегу.
    ``load_ms`` — максимум по строкам (прогрев случается один раз, на первом запросе).
    """
    measured = local_tuning_eval.summarize(rows)
    return {**snapshot(),
            "load_ms": max((int(row.get("load_ms") or 0) for row in rows), default=0),
            "tokens_per_second": measured["avg_tokens_per_second"]}


def _check_errors(variants: List[dict]) -> None:
    """Все строки упали — это недоступная Ollama, а не результат прогона (502)."""
    rows = [row for variant in variants for row in variant["rows"]]
    failed = [row for row in rows if row.get("mode") == local_tuning_eval.MODE_ERROR]
    if rows and len(failed) == len(rows):
        raise LocalLLMError(str(failed[0].get("warning") or "локальная модель недоступна"))
