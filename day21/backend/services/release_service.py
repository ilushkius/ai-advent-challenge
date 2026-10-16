"""Подготовка релиза (день 35): git-коммиты + модель → CHANGELOG, заметки и README.

Служба — сшивка, а не хранилище правил. Правила живут рядом в трёх модулях, и каждый
отвечает за своё:

- ``domain/release.py``, ``domain/release_text.py`` — что такое следующая версия, как
  разложить пункты по группам, как выглядит раздел и где он встаёт в файле;
- ``services/release_files.py`` — чтение текущих текстов, план правки и запись через
  MCP (там же ``ReleaseError``);
- ``services/release_llm.py`` — разговор с моделью пачками коммитов и разбор её ответа;
- ``services/release_checks.py`` — проверки готовности (тесты, покрытие, файлы).

Здесь остаётся последовательность: коммиты диапазона и изменённые файлы через MCP,
базовая версия из шапки ``CHANGELOG.md``, тип изменения и пункты от модели, проверки,
запись трёх файлов и строка истории в SQLite.

Три решения, которые важны при чтении кода:

- **``dry_run`` — не «урезанный прогон», а полный**: модель, проверки и предпросмотр
  diff-а выполняются, отличаются только два последних шага — инструменты записи не
  вызываются, и ``files_modified`` остаётся пустым;
- **модель не обязательна**: отказ модели даёт детерминированный результат (правило по
  меткам коммитов), причина видна в ``version_reason`` и в заметках, и наружу из этого
  модуля такая ошибка не выходит;
- **MCP обязателен**: без сервера файлов нет ни коммитов, ни возможности записать —
  это ``ReleaseError`` (роутер отвечает 500), и строка запуска закрывается ``failed``,
  чтобы не осталась висеть в ``running``.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Optional

from shared.deepseek_client import make_client
from shared.logging_utils import get_logger

from ..core import config
from ..domain import llm_provider, release
from ..storage.release_store import ReleaseRunNotFoundError, ReleaseStore
from . import rag_llm, release_checks, release_files, release_llm
from .file_mcp import FileMCPCalls
from .rag_errors import RAGUpstreamError
from .release_files import ReleaseError

logger = get_logger(__name__)

__all__ = ["ReleaseError", "ReleaseService", "get_release_service", "make_release_client"]


def make_release_client():
    """Клиент DeepSeek службы релиза: ключ резолвится в момент вызова.

    Служба собирается на старте приложения, а ``.env`` правится без перезапуска,
    поэтому проверка ключа отложена до первого прогона (как у служб дней 31–34).
    """
    api_key = config.resolve_api_key()
    if not api_key:
        raise RuntimeError(
            "Ключ API не задан: укажите DEEPSEEK_API_KEY в файле day21/.env "
            "или в переменной окружения"
        )
    return make_client(api_key, config.DEEPSEEK_BASE_URL, config.REQUEST_TIMEOUT)


class ReleaseService:
    """Сборка релиза: коммиты, версия, CHANGELOG, проверки и запись файлов."""

    def __init__(self, *, llm_client: Optional[Any] = None,
                 mcp_client: Optional[Any] = None,
                 mcp_target: str = release.FILE_SERVER_TARGET,
                 mcp_cwd: Optional[object] = None,
                 store: Optional[Any] = None,
                 checks: Optional[Callable[[], dict]] = None,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._llm_client = llm_client
        self._llm_clients: Dict[str, Any] = {}
        self._mcp = FileMCPCalls(target=mcp_target, cwd=mcp_cwd, client=mcp_client)
        #: Хранилище без состояния, как ``FileAssistantStore``: своего синглтона на
        #: процесс ему не нужно, поэтому оно создаётся сразу.
        self._store = store if store is not None else ReleaseStore()
        #: Проверки подменяются целиком (скрипт ``--no-checks``, юнит-тесты): служба
        #: знает только то, что это функция без аргументов, возвращающая словарь.
        self._checks = checks or release_checks.run_checks
        self._sleep = sleep

    # ---------- зависимости ----------
    @property
    def mcp(self) -> FileMCPCalls:
        """Обвязка вызовов файлового сервера (одна на прогон и на процесс)."""
        return self._mcp

    @property
    def server(self) -> Any:
        """MCP-клиент файлового сервера: подменённый или подключённый один раз."""
        return self._mcp.server

    def llm_client_for(self, provider: Optional[str] = None) -> Any:
        """Клиент ответа провайдера; подменённый клиент важнее имени провайдера."""
        return rag_llm.client_for(
            self._llm_clients, None if self._llm_client is not None else provider, None,
            stub=self._llm_client, agent_id=release.AGENT_ID,
            client_factory=make_release_client)

    # ---------- контракт ----------
    def prepare_release(self, from_tag: str, to_tag: str, version: str = "auto",
                        provider: str = "deepseek", dry_run: bool = False) -> dict:
        """Готовит релиз диапазона тегов и возвращает полный отчёт прогона.

        ``ValueError`` — пустые теги, версия не ``X.Y.Z``, версия ниже предложенной
        или незнакомый провайдер (роутер отвечает 400); ``ReleaseError`` — MCP-сервер
        файлов недоступен (500). Любой из этих путей закрывает строку запуска статусом
        ``failed``: незавершённый прогон не должен висеть в ``running``.
        """
        start_tag = str(from_tag or "").strip()
        end_tag = str(to_tag or "").strip()
        if not start_tag or not end_tag:
            raise ValueError(release.REASON_EMPTY_TAGS)
        version_arg = str(version or "auto").strip() or "auto"
        if version_arg != "auto" and release.version_tuple(version_arg) is None:
            raise ValueError(release.REASON_BAD_VERSION.format(version=version_arg))
        name = llm_provider.resolve(provider)
        started = time.perf_counter()
        client = self.llm_client_for(provider)
        run_id = self._store.create_run(from_tag=start_tag, to_tag=end_tag,
                                       version=version_arg,
                                       status=release.STATUS_RUNNING,
                                       started_at=datetime.now(timezone.utc))["id"]
        try:
            return self._release(run_id=run_id, from_tag=start_tag, to_tag=end_tag,
                                 version_arg=version_arg, provider=name, client=client,
                                 dry_run=dry_run, started=started)
        except (ReleaseError, ValueError, RAGUpstreamError) as exc:
            self._store.update_run(run_id, status=release.STATUS_FAILED,
                                  finished_at=datetime.now(timezone.utc))
            logger.warning("Релиз: прогон %s закрыт как failed: %s", run_id, exc)
            raise

    def tags(self) -> dict:
        """Теги репозитория для селекторов раздела (сбой MCP — ``ReleaseError``)."""
        payload = release_files.call(self._mcp, release.TOOL_GET_TAGS, {})
        tags = payload if isinstance(payload, list) else []
        return {"count": len(tags), "tags": tags}

    def health(self) -> dict:
        """Готовность релиза: прогон проверок без MCP (всегда отвечает, не бросает)."""
        checks = self._checks()
        return {"checks": checks, "checks_passed": bool(checks.get("passed"))}

    def metrics(self) -> dict:
        """Метрики проекта инструментом git-истории (сбой MCP — ``ReleaseError``)."""
        payload = release_files.call(self._mcp, release.TOOL_PROJECT_METRICS, {})
        return {"metrics": payload if isinstance(payload, dict) else {}}

    def history(self, limit: int = release.HISTORY_LIMIT) -> dict:
        """История релизов от свежих к старым (тексты разделов в список не входят)."""
        runs = self._store.list_runs(limit)
        return {"count": len(runs), "runs": runs}

    def export(self, run_id: int) -> dict:
        """Один запуск с текстами разделов; нет такого — ``ReleaseRunNotFoundError``."""
        record = self._store.run(run_id)
        if record is None:
            raise ReleaseRunNotFoundError(f"Запуск подготовки релиза {run_id} не найден")
        return record

    # ---------- прогон ----------
    def _release(self, *, run_id: int, from_tag: str, to_tag: str, version_arg: str,
                 provider: str, client: Any, dry_run: bool, started: float) -> dict:
        """Шаги прогона в порядке исполнения (см. докстринг модуля)."""
        notes: list[str] = []
        commits = release_files.call(self._mcp, release.TOOL_COMMITS_BETWEEN,
                                     {"from_tag": from_tag, "to_tag": to_tag})
        if not isinstance(commits, list) or not commits:
            raise ValueError(release.REASON_NO_COMMITS.format(from_tag=from_tag,
                                                              to_tag=to_tag))
        changed = release_files.call(self._mcp, release.TOOL_CHANGED_FILES_BETWEEN,
                                     {"from_tag": from_tag, "to_tag": to_tag})
        changed_files = [str(path) for path in changed] if isinstance(changed, list) else []

        tags_ok, tags_payload, tags_error = release_files.try_call(
            self._mcp, release.TOOL_GET_TAGS, {})
        if not tags_ok:
            notes.append(release.WARN_TAGS_UNAVAILABLE.format(error=tags_error))
        tag_names = ({str(tag.get("name")) for tag in tags_payload}
                     if tags_ok and isinstance(tags_payload, list) else set())
        metrics_ok, metrics_payload, metrics_error = release_files.try_call(
            self._mcp, release.TOOL_PROJECT_METRICS, {})
        if not metrics_ok:
            notes.append(release.WARN_METRICS_UNAVAILABLE.format(error=metrics_error))
        metrics = metrics_payload if metrics_ok and isinstance(metrics_payload, dict) else {}
        from_label = (from_tag if from_tag in tag_names
                      else release.TAG_MISSING_FROM.format(tag=from_tag))
        to_label = (to_tag if to_tag in tag_names or to_tag == "HEAD"
                    else release.TAG_MISSING_TO.format(tag=to_tag))

        current_changelog, truncated = release_files.read(self._mcp, release.CHANGELOG_PATH)
        if current_changelog is None:
            notes.append(release.WARN_CHANGELOG_MISSING.format(path=release.CHANGELOG_PATH))
            current_changelog = ""
        elif truncated:
            notes.append(release.WARN_CHANGELOG_TRUNCATED.format(
                path=release.CHANGELOG_PATH))
        base = release.latest_version(current_changelog) or release.BASE_VERSION_FALLBACK

        bump, reason, breaking, features, fixes = release_llm.version_analysis(
            client, commits, sleep=self._sleep)
        suggested = release.bump_version(base, bump)
        if version_arg == "auto":
            final, version_reason = suggested, reason
        else:
            given = release.version_tuple(version_arg)
            if given < release.version_tuple(suggested):
                raise ValueError(release.REASON_VERSION_BELOW.format(
                    given=version_arg, suggested=suggested, reason=reason))
            final = f"{given[0]}.{given[1]}.{given[2]}"
            version_reason = release.REASON_EXPLICIT.format(suggested=suggested,
                                                           reason=reason)

        kept, dropped, minor_count, note = release_llm.changelog_groups(
            client, commits, changed_files, sleep=self._sleep)
        if note:
            notes.append(note)
        date = datetime.now(timezone.utc).date().isoformat()
        section = release.render_changelog_section(final, date, kept, minor_count)
        notes_text = release.render_release_notes(final, date, kept, minor_count, metrics)
        readme_section = release.render_readme_section(final, date, metrics)

        current_readme, _readme_truncated = release_files.read(self._mcp, release.README_PATH)
        if current_readme is None:
            notes.append(release.WARN_CHANGELOG_MISSING.format(path=release.README_PATH))
            current_readme = ""
        current_notes, _notes_truncated = release_files.read(self._mcp,
                                                            release.RELEASE_NOTES_PATH)
        changes = release_files.plan_files(final, current_changelog, current_readme)
        diffs = release_files.diff_preview(changes, section, notes_text, readme_section,
                                           current_changelog, current_readme,
                                           current_notes or "")
        if not dry_run:
            for entry in changes:
                if not entry["skipped"]:
                    release_files.write(entry, section, notes_text, readme_section,
                                        current_changelog, self._mcp, notes)
        files_modified = [entry["path"] for entry in changes if entry["ok"]]

        checks = self._checks()
        checks_passed = bool(checks.get("passed"))
        if not checks_passed:
            # Имена проверок есть не всегда: при ``--no-checks`` (скрипт) список команд
            # и файлов пуст, и заметка говорит о пропуске словами самих проверок.
            failed = (", ".join(release_checks.failed_names(checks))
                      or ", ".join(checks.get("notes") or []) or "не выполнялись")
            notes.append(release.WARN_CHECKS_FAILED.format(failed=failed))
        if dry_run:
            status = release.STATUS_DRY_RUN
        else:
            written = all(entry["ok"] or entry["skipped"] for entry in changes)
            status = release.STATUS_COMPLETED if written else release.STATUS_FAILED
        self._store.update_run(
            run_id, status=status, finished_at=datetime.now(timezone.utc), version=final,
            version_reason=version_reason, changelog=section, release_notes=notes_text,
            checks_passed=checks_passed, files_modified=files_modified)
        return {
            "run_id": run_id, "from_tag": from_tag, "to_tag": to_tag,
            "from_label": from_label, "to_label": to_label, "version": final,
            "version_reason": version_reason, "version_bump": bump,
            "breaking_changes": breaking, "features": features, "fixes": fixes,
            "changelog": {"added": kept["added"], "changed": kept["changed"],
                          "fixed": kept["fixed"], "removed": kept["removed"],
                          "breaking": kept["breaking"], "minor_count": minor_count,
                          "section": section, "dropped_count": dropped},
            "release_notes": notes_text, "checks": checks, "checks_passed": checks_passed,
            "files_to_modify": changes, "diff_preview": diffs, "metrics": metrics,
            "notes": notes, "commits_count": len(commits), "changed_files": changed_files,
            "duration_ms": int((time.perf_counter() - started) * 1000),
            "provider": provider, "status": status, "dry_run": bool(dry_run),
        }

    # ---------- жизненный цикл ----------
    def close(self) -> None:
        """Закрывает СВОЁ соединение с файловым сервером (подменённое не трогает)."""
        self._mcp.close()


#: Служба процесса: соединение с файловым сервером одно на процесс, как у остальных.
_service: Optional[ReleaseService] = None
_service_lock = threading.Lock()


def get_release_service() -> ReleaseService:
    """Служба подготовки релиза процесса (точка подмены: ``main.get_release_service``)."""
    global _service
    with _service_lock:
        if _service is None:
            _service = ReleaseService()
        return _service
