"""Роутер API: подготовка релиза (день 35) — ``/release/*``.

Шесть эндпоинтов:

- ``POST /release/prepare`` — прогон подготовки релиза. ``400`` — пустые теги, версия
  не ``X.Y.Z``, версия ниже предложенной или незнакомый провайдер (``ValueError``
  службы); ``500`` — MCP-сервер файлов не поднялся или инструмент не сработал
  (``ReleaseError``) либо отказала модель во время прогона (``RAGUpstreamError``);
- ``GET /release/tags`` — теги репозитория для селекторов раздела; ``500`` — сервер
  файлов недоступен (``ReleaseError``);
- ``GET /release/health`` — проверки готовности (тесты, покрытие, файлы) без MCP:
  всегда ``200``, потому что это ответ о состоянии проекта, а не о релизе;
- ``GET /release/metrics`` — метрики проекта инструментом git-истории; ``500`` — как
  у тегов;
- ``GET /release/history`` — релизы от свежих к старым, всегда ``200``: пустая история
  это ``count: 0``, а не ошибка; ``404`` здесь не бывает (список, а не запись);
- ``POST /release/export`` — выгрузка файлов релиза: ``changelog`` и ``release_notes``
  отдаются текстом, ``both`` — ZIP-архивом с обоими файлами. ``400`` — неизвестное
  значение ``file``, ``404`` — запуска с таким ``run_id`` нет
  (``ReleaseRunNotFoundError`` хранилища).

Схемы берутся из своего модуля (``..schemas.release``), а не из пакета ``..schemas``:
``schemas/__init__.py`` стоит на пределе 400 строк, и дни 30–34 сделали так же.
Служба — через ``backend.core.dependencies``, то есть по атрибуту ``backend.api.main``
в момент вызова: тесты подменяют одну точку (``main.get_release_service``), и подмену
видят и роутер, и ``lifespan``.
"""
from __future__ import annotations

import io
import zipfile

from fastapi import APIRouter, HTTPException, Response

from ..core import dependencies
from ..domain.release import HISTORY_LIMIT
from ..schemas.release import (
    ReleaseExportIn,
    ReleaseHealthOut,
    ReleaseHistoryOut,
    ReleaseMetricsOut,
    ReleasePrepareIn,
    ReleasePrepareOut,
    ReleaseTagsOut,
)
from ..services.rag_errors import RAGUpstreamError
from ..services.release_service import ReleaseError
from ..storage.release_store import ReleaseRunNotFoundError

router = APIRouter()

#: Выгрузка одного файла: значение ``file`` → (имя файла, ключ записи запуска).
EXPORT_FILES = {"changelog": ("CHANGELOG.md", "changelog"),
                "release_notes": ("RELEASE_NOTES.md", "release_notes")}
#: Выгрузка архива: значение ``file`` по умолчанию и имена файлов внутри него.
EXPORT_BOTH = "both"
EXPORT_ARCHIVE_FILES = (("CHANGELOG.md", "changelog"),
                        ("RELEASE_NOTES.md", "release_notes"))
REASON_UNKNOWN_FILE = ("Неизвестный файл выгрузки: {file!r}. Доступны: both, changelog, "
                       "release_notes")


def _error(exc: Exception) -> HTTPException:
    """Доменное исключение дня 35 в HTTP-ответ: 400 — запрос, 500 — сбой прогона."""
    if isinstance(exc, ValueError):
        return HTTPException(status_code=400, detail=str(exc))
    return HTTPException(status_code=500, detail=str(exc))


def _file_response(body: bytes, media_type: str, filename: str) -> Response:
    """Ответ-файл с именем в ``Content-Disposition`` (браузер скачивает, а не открывает)."""
    return Response(content=body, media_type=media_type,
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})


@router.post("/release/prepare", response_model=ReleasePrepareOut)
def prepare_release(payload: ReleasePrepareIn) -> ReleasePrepareOut:
    """Готовит релиз диапазона тегов: версия, CHANGELOG, проверки и файлы.

    Требует ``DEEPSEEK_API_KEY`` (или запущенной Ollama для ``provider="local"``) для
    версии и пунктов CHANGELOG; недоступная модель не мешает прогону — тип изменения
    и пункты определит детерминированное правило, а причина будет видна в
    ``version_reason`` и в ``notes``. MCP-сервер файлов, наоборот, обязателен:
    без него нет ни коммитов, ни записи.

    Коды: ``400`` — пустые теги, версия не ``X.Y.Z``, версия ниже предложенной или
    незнакомый провайдер; ``500`` — сбой MCP или модели.
    """
    service = dependencies.get_release_service()
    try:
        result = service.prepare_release(payload.from_tag, payload.to_tag,
                                        payload.version, payload.provider,
                                        payload.dry_run)
    except (ReleaseError, ValueError) as exc:
        raise _error(exc) from exc
    except RAGUpstreamError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return ReleasePrepareOut(**result)


@router.get("/release/tags", response_model=ReleaseTagsOut)
def read_tags() -> ReleaseTagsOut:
    """Теги репозитория с датами и коммитами (500 — сервер файлов недоступен)."""
    try:
        return ReleaseTagsOut(**dependencies.get_release_service().tags())
    except ReleaseError as exc:
        raise _error(exc) from exc


@router.get("/release/health", response_model=ReleaseHealthOut)
def read_health() -> ReleaseHealthOut:
    """Проверки готовности без MCP и модели: тесты, покрытие и файлы (всегда 200)."""
    return ReleaseHealthOut(**dependencies.get_release_service().health())


@router.get("/release/metrics", response_model=ReleaseMetricsOut)
def read_metrics() -> ReleaseMetricsOut:
    """Метрики проекта: теги, коммиты, файлы, тесты, серверы и ассистенты."""
    try:
        return ReleaseMetricsOut(**dependencies.get_release_service().metrics())
    except ReleaseError as exc:
        raise _error(exc) from exc


@router.get("/release/history", response_model=ReleaseHistoryOut)
def read_history(limit: int = HISTORY_LIMIT) -> ReleaseHistoryOut:
    """История релизов от свежих к старым (всегда 200, тексты разделов не входят)."""
    return ReleaseHistoryOut(**dependencies.get_release_service().history(limit))


@router.post("/release/export")
def export_release(payload: ReleaseExportIn) -> Response:
    """Выгружает файлы релиза: ``changelog``/``release_notes`` текстом, ``both`` — ZIP.

    Выгрузка идёт из ЗАПИСИ запуска, а не из файлов на диске: тот же релиз можно
    скачать и после правок файлов, и он совпадёт с тем, что записал прогон.
    """
    name = str(payload.file or EXPORT_BOTH).strip().lower()
    if name != EXPORT_BOTH and name not in EXPORT_FILES:
        raise HTTPException(status_code=400,
                            detail=REASON_UNKNOWN_FILE.format(file=payload.file))
    try:
        record = dependencies.get_release_service().export(payload.run_id)
    except ReleaseRunNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    if name == EXPORT_BOTH:
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
            for filename, key in EXPORT_ARCHIVE_FILES:
                archive.writestr(filename, str(record.get(key) or ""))
        return _file_response(buffer.getvalue(), "application/zip",
                              f"release-{record['version']}.zip")
    filename, key = EXPORT_FILES[name]
    return _file_response(str(record.get(key) or "").encode("utf-8"),
                          "text/markdown; charset=utf-8", filename)
