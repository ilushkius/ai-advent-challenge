"""HTTP-часть раздела «🚀 Подготовка релиза» (день 35).

Транспорт общий — ``frontend/api_client.py``; здесь запросы дня 35: прогон релиза,
теги, проверки готовности, метрики, история и выгрузка файла.

Предел ожидания у всех запросов раздела — ``LONG_TIMEOUT``: прогон релиза идёт
десятками секунд (два обращения к модели на пачку коммитов, вызовы MCP и два прогона
``pytest`` внутри проверок), и общего предела в 90 секунд ему мало.

Выгрузка живёт здесь, а не в ``api_client``: тот отдаёт JSON, а ``POST /release/export``
отвечает файлом или ZIP-архивом, и имя файла приходит заголовком
``Content-Disposition``, а не телом ответа.
"""
import requests

from .api_client import BACKEND_URL, LONG_TIMEOUT, BackendError, _extract_error, request_json

#: Сколько запусков запрашивает история раздела, если предел не задан явно.
HISTORY_LIMIT = 20


def api_release_prepare(from_tag: str, to_tag: str, version: str = "auto",
                        provider: str = "", dry_run: bool = True) -> dict:
    """POST /release/prepare -> версия, раздел CHANGELOG, проверки и план правки.

    Пустой ``provider`` в тело не попадает: «поле не задано» и «поле пустое» для
    службы одно и то же, но лишние поля в запросе мешают читать журнал вызовов.
    """
    payload = {"from_tag": from_tag, "to_tag": to_tag, "version": version,
               "dry_run": bool(dry_run)}
    if provider:
        payload["provider"] = provider
    return request_json("POST", "/release/prepare", timeout=LONG_TIMEOUT, json=payload)


def api_release_tags() -> dict:
    """GET /release/tags -> теги репозитория с датами и коммитами (500 — нет сервера)."""
    return request_json("GET", "/release/tags", timeout=LONG_TIMEOUT)


def api_release_health() -> dict:
    """GET /release/health -> проверки готовности без MCP (всегда 200)."""
    return request_json("GET", "/release/health", timeout=LONG_TIMEOUT)


def api_release_metrics() -> dict:
    """GET /release/metrics -> метрики проекта инструментом git-истории."""
    return request_json("GET", "/release/metrics", timeout=LONG_TIMEOUT)


def api_release_history(limit: int = HISTORY_LIMIT) -> dict:
    """GET /release/history -> релизы от свежих к старым (всегда 200)."""
    return request_json("GET", "/release/history", params={"limit": int(limit)},
                        timeout=LONG_TIMEOUT)


def api_release_export_bytes(run_id: int, file: str = "changelog") -> tuple:
    """Скачивание файла релиза: ``(байты, имя файла)``.

    Ошибка бэкенда переводится в ``BackendError`` тем же текстом, что у остальных
    запросов раздела: раздел показывает сообщение, а не стек. Имя файла берётся из
    заголовка ``Content-Disposition`` (по умолчанию — значение ``file``): у ZIP-архива
    оно своё (``release-X.Y.Z.zip``), и подставлять его вручную значило бы дублировать
    правило сервера.
    """
    resp = requests.post(f"{BACKEND_URL}/release/export",
                         json={"run_id": int(run_id), "file": file},
                         timeout=LONG_TIMEOUT)
    if resp.status_code >= 400:
        raise BackendError(_extract_error(resp), resp.status_code)
    disposition = str(resp.headers.get("Content-Disposition") or "")
    marker = "filename="
    name = file
    if marker in disposition:
        name = disposition.split(marker, 1)[1].strip().strip('"') or file
    return resp.content, name
