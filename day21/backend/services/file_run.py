"""Исполнение плана ассистента файлов (день 34): ``FileRun``.

``FileRun`` ведёт ОДИН прогон: проходит шаги плана по порядку, ведёт журнал, следит за
списками прочитанных, изменённых и созданных файлов, собирает итоговый diff и просит у
модели сводку. Служба (``file_assistant_service``) отвечает за план, историю и
контракт API — поэтому это отдельный модуль, а не ещё двести строк внутри службы.

Правила исполнения одного шага:

- **маркер ``$generate``** разрешается ОДНИМ запросом модели на все оставшиеся маркеры
  (``_resolve``), и запрос ленивый — при первом шаге с маркером: к этому моменту в
  журнале уже есть результаты поиска и чтения, из которых берутся и путь, и якорь
  замены. Поэтому ``_resolve`` получает журнал, а не догадки;
- **правка файла требует текущего содержимого**: оно берётся из журнала, если файл уже
  читался, иначе — внутренним шагом ``read_file`` (``_current_text``). Без текущего
  текста нельзя ни проверить якорь, ни показать предполагаемый diff;
- **``dry_run`` не вызывает write-инструменты вовсе** — вместо вызова считается
  предполагаемый diff из аргументов плана. Обещание «файлы не меняются» должно
  выполняться буквально: проверка «мы ничего не записали, потому что не дошли» ничего
  не стоит;
- **первый неуспешный шаг останавливает прогон**: остальные шаги попадают в журнал со
  статусом ``skipped`` и в БД не попадают как выполненные. Так в истории видно и что
  успело случиться, и на чём остановилось.

``_touch`` раскладывает путь записи в «созданные» или «изменённые» по ответу
инструмента (``WriteResult.created``): только он знает, был файл на диске до записи.
"""
from __future__ import annotations

import json
import time
from typing import Any, Callable, Dict, Optional, Tuple

from shared.logging_utils import get_logger

from ..core import config
from ..domain import file_assistant
from ..domain import file_assistant_plan as plan_rules
from ..domain import file_assistant_report as report
from . import rag_llm
from .file_mcp import FileMCPCalls
from .rag_errors import RAGUpstreamError

logger = get_logger(__name__)

__all__ = ["FileRun", "RESULT_CHARS", "STEP_SKIP_NOTE"]

#: Что записать в шаг, который не выполнялся из-за сбоя предыдущего.
STEP_SKIP_NOTE = "шаг не выполнялся: прогон остановлен на шаге {index}"
#: Предел результата шага в ответе API: раздел интерфейса показывает его ``st.json``,
#: и выгрузка файла целиком сделала бы ответ нечитаемым, а строку истории — тяжёлой.
RESULT_CHARS = 4000


class FileRun:
    """Один прогон плана: журнал шагов, списки файлов, diff и сводка."""

    def __init__(self, *, goal: str, plan: list, client: Any, mcp: FileMCPCalls,
                 dry_run: bool = False, sleep: Callable[[float], None] = time.sleep) -> None:
        self._goal = goal
        self._plan = plan
        self._client = client
        self._mcp = mcp
        self._dry_run = bool(dry_run)
        self._sleep = sleep
        self._steps: list = []
        self._read_contents: Dict[str, str] = {}
        self._files_read: list = []
        self._files_modified: list = []
        self._files_created: list = []
        self._problems: Dict[int, str] = {}

    def execute(self) -> dict:
        """Проходит шаги плана и возвращает исход прогона.

        Исход содержит журнал шагов, обновлённый план (аргументы после разрешения
        маркеров), три списка файлов, diff и сводку — ровно то, что служба кладёт в
        историю и в ответ API.
        """
        failed = self._steps_loop()
        diff = self._diff()
        summary = self._summary(diff)
        return {"steps": self._steps, "plan": self._plan, "failed": failed,
                "files_read": self._files_read, "files_modified": self._files_modified,
                "files_created": self._files_created, "diff": diff, "summary": summary}

    # ---------- шаги ----------
    def _steps_loop(self) -> bool:
        """Идёт по плану, исполняя шаги; ``True`` — прогон остановлен на сбое."""
        resolved = failed = False
        for step in self._plan:
            index = int(step["step_index"])
            tool = str(step["tool"])
            reason = str(step.get("reason") or "")
            if failed:
                self._steps.append(_record(index, tool, step.get("arguments"), reason,
                                           ok=False, status=file_assistant.STEP_SKIPPED,
                                           error=STEP_SKIP_NOTE.format(index=index)))
                continue
            if plan_rules.needs_generation(step.get("arguments") or {}) and not resolved:
                resolved = True
                self._resolve()
            arguments = dict(step.get("arguments") or {})
            if plan_rules.needs_generation(arguments):
                failed = self._fail(index, tool, arguments, reason,
                                    file_assistant.REASON_GENERATE_FAILED.format(
                                        index=index, tool=tool,
                                        error=(self._problems.get(index)
                                               or "аргументы не заполнены моделью")))
                continue
            path = str(arguments.get("path") or "")
            if tool in file_assistant.WRITE_TOOLS:
                failed = self._write_step(index, tool, arguments, reason, path)
            else:
                failed = self._read_step(index, tool, arguments, reason, path)
        return failed

    def _write_step(self, index: int, tool: str, arguments: dict, reason: str,
                    path: str) -> bool:
        """Шаг правки файла: ``dry_run`` считает diff, обычный режим вызывает инструмент.

        Текущее содержимое нужно ТОЛЬКО в ``dry_run``: настоящий ``apply_patch`` сам
        читает файл, и лишний вызов чтения перед каждым шагом был бы платой за то,
        что инструмент и так делает.
        """
        if self._dry_run:
            guessed = report.presumed_diff(path, self._current_text(path, index), tool,
                                           arguments)
            if not guessed:
                return self._fail(index, tool, arguments, reason,
                                  file_assistant.REASON_PATCH_ANCHOR.format(
                                      index=index, path=path))
            self._steps.append(_record(index, tool, arguments, reason, ok=True,
                                       status=file_assistant.STEP_SKIPPED,
                                       result={"dry_run": True,
                                               "presumed_diff": guessed}))
            return False
        ok, payload, error, duration = self._mcp.call(tool, arguments)
        self._steps.append(_record(index, tool, arguments, reason, ok=ok,
                                   status=_status(ok), error=error,
                                   duration_ms=duration, result=_result(payload)))
        if not ok:
            return True
        _touch(payload, path, tool, self._files_modified, self._files_created)
        self._read_contents.pop(path, None)     # файл изменился: следующее чтение — заново
        return False

    def _read_step(self, index: int, tool: str, arguments: dict, reason: str,
                   path: str) -> bool:
        """Шаг чтения, поиска, списка или diff-а: вызов инструмента и запись в журнал."""
        ok, payload, error, duration = self._mcp.call(tool, arguments)
        if ok and tool == file_assistant.TOOL_READ_FILE:
            _remember(payload, path, self._read_contents, self._files_read)
        self._steps.append(_record(index, tool, arguments, reason, ok=ok,
                                   status=_status(ok), error=error,
                                   duration_ms=duration, result=_result(payload)))
        return not ok

    def _fail(self, index: int, tool: str, arguments: dict, reason: str,
              error: str) -> bool:
        """Записывает неуспешный шаг и возвращает ``True`` (прогон остановлен)."""
        self._steps.append(_record(index, tool, arguments, reason, ok=False,
                                   status=file_assistant.STEP_FAILED, error=error))
        return True

    def _current_text(self, path: str, index: int) -> str:
        """Текущее содержимое файла перед правкой: из журнала или внутренним чтением.

        Внутреннее чтение нужно, когда модель не прочитала файл перед правкой: без
        текущего текста нельзя ни проверить якорь замены, ни показать предполагаемый
        diff. Сбой чтения прогон не отменяет (``write_file`` мог создавать файл,
        которого ещё нет): текущим содержимым считается пустая строка, а причина видна
        в шаге журнала. Номер шага у внутреннего чтения — номер шага, для которого оно
        сделано: по журналу видно, к чему относится чтение.
        """
        if path in self._read_contents:
            return self._read_contents[path]
        ok, payload, error, duration = self._mcp.call(file_assistant.TOOL_READ_FILE,
                                                      {"path": path})
        if ok and isinstance(payload, dict):
            _remember(payload, path, self._read_contents, self._files_read)
        self._steps.append(_record(
            index, file_assistant.TOOL_READ_FILE, {"path": path},
            file_assistant.INTERNAL_READ_REASON, ok=True,
            status=file_assistant.STEP_OK if ok else file_assistant.STEP_SKIPPED,
            error=error, duration_ms=duration,
            result=_result(payload) if ok else {"file_found": False}))
        return self._read_contents.get(path, "")

    # ---------- вторая фаза ----------
    def _resolve(self) -> None:
        """Вторая фаза: конкретные аргументы вместо маркера ``$generate``.

        Запрос к модели идёт лениво — при первом шаге с маркером: к этому моменту
        журнал уже содержит результаты исполненных шагов, и модель берёт из них и путь,
        и якорь замены. Неразобранный или неполный ответ повторяется один раз с
        подсказкой о причине; после второй неудачи шаги с маркером помечаются
        неуспешными, и прогон останавливается.

        Якорь ``old_text`` проверяется по УЖЕ прочитанному содержимому: если файл в
        журнале есть, а фрагмента в нём нет, лучше потратить повтор модели, чем
        записать в журнал заведомо провальный шаг. Если файл не читался, проверка
        ложится на сам инструмент — он ответит тем же текстом «прочитайте файл и
        повторите».
        """
        pending = [step for step in self._plan
                   if plan_rules.needs_generation(step.get("arguments") or {})]
        indices = [int(step["step_index"]) for step in pending]
        problem = ""
        for attempt in range(file_assistant.MAX_GENERATE_ATTEMPTS):
            system, question = plan_rules.build_generate_prompt(
                self._goal, pending, report.render_step_context(self._steps))
            if problem:
                question = f"{question}\n\nПредыдущий ответ не принят: {problem}"
            try:
                result = rag_llm.call_with_retry(
                    self._sleep, self._client.generate_with_context, system=system,
                    context=file_assistant.catalog_text(), question=question,
                    task_type=config.LLM_TASK_CODE, agent_id=file_assistant.AGENT_ID,
                    temperature=0.0, max_tokens=config.LLM_MAX_RESPONSE_TOKENS_LONG)
            except RAGUpstreamError as exc:
                self._problems = {index: str(exc) for index in indices}
                return
            found = plan_rules.parse_generate(rag_llm.response_text(result), indices)
            if found is None:
                problem = ("ответ не разобран как JSON с аргументами всех "
                           "запрошенных шагов")
                logger.warning("Ассистент файлов: аргументы не разрешены (попытка %d)",
                               attempt + 1)
                continue
            problem = _anchor_problem(found, self._read_contents)
            if not problem:
                for other in self._plan:
                    fresh = found.get(int(other["step_index"]))
                    if fresh:
                        other["arguments"] = fresh
                return
            logger.warning("Ассистент файлов: аргументы отклонены: %s", problem)
        self._problems = {index: problem or "аргументы не получены" for index in indices}

    # ---------- diff и сводка ----------
    def _diff(self) -> str:
        """Итоговый diff прогона: блок на каждый затронутый файл с шапкой ``# diff``.

        В ``dry_run`` инструменты диффа не вызываются: файлы не менялись, и
        единственный честный diff — предполагаемый, собранный по шагам плана. В
        обычном режиме по каждому пути вызывается ``get_file_diff``: у изменённого
        файла это ``git diff HEAD``, у созданного — diff, который сервер синтезирует
        сам (``git`` неотслеживаемые файлы не показывает). Сбой инструмента диффа
        прогон не отменяет: его текст попадает в блок вместо diff-а.
        """
        if self._dry_run:
            blocks = [_guessed_block(step) for step in self._steps if step.get("result")]
            return "\n\n".join(block for block in blocks if block)
        blocks = []
        for path in [*self._files_modified, *self._files_created]:
            ok, payload, error, _ = self._mcp.call(file_assistant.TOOL_GET_FILE_DIFF,
                                                   {"path": path})
            text = str(payload) if ok and isinstance(payload, str) else (error or "")
            blocks.append(f"# diff: {path}\n{text or file_assistant.NO_PRESUMED_DIFF}")
        return "\n\n".join(blocks)

    def _summary(self, diff: str) -> str:
        """Сводка прогона от модели: журнал шагов и diff как контекст.

        Сбой модели на этом шаге НЕ отменяет прогон: файлы уже прочитаны и изменены, и
        журнал с diff-ом сами по себе результат. Тогда в поле сводки уходит честный
        текст ``PLAN_FAILED_ANSWER``, а не выдуманный отчёт.
        """
        context = "\n\n".join([report.render_step_context(self._steps), diff])
        try:
            result = rag_llm.answer(self._sleep, self._client,
                                    system=file_assistant.SUMMARY_SYSTEM_PROMPT,
                                    context=context, question=self._goal,
                                    agent_id=file_assistant.AGENT_ID)
        except RAGUpstreamError as exc:
            logger.warning("Ассистент файлов: сводка не получена: %s", exc)
            return file_assistant.PLAN_FAILED_ANSWER.format(error=exc)
        return rag_llm.response_text(result)


def _record(index: int, tool: str, arguments: Any, reason: str, *, ok: bool, status: str,
            error: str = "", duration_ms: int = 0,
            result: Optional[dict] = None) -> dict:
    """Строка журнала шага: ровно поля схемы ответа ``FileAssistantStepOut``."""
    return {"step_index": int(index), "tool": str(tool),
            "arguments": dict(arguments or {}), "reason": str(reason), "ok": bool(ok),
            "status": status, "duration_ms": int(duration_ms), "error": str(error),
            "result": result}


def _status(ok: bool) -> str:
    """Статус шага журнала: ``ok`` или ``failed`` (``skipped`` ставится отдельно)."""
    return file_assistant.STEP_OK if ok else file_assistant.STEP_FAILED


def _result(payload: Any, limit: int = RESULT_CHARS) -> Optional[dict]:
    """Результат шага в форме словаря: у списка и строки значение лежит полем ``value``.

    Схема API описывает результат шага объектом, а инструменты отвечают по-разному
    (``search_in_files`` — списком совпадений, ``get_file_diff`` — текстом). Обёртка
    приводит формы к одному виду, поэтому раздел интерфейса показывает ``st.json`` без
    ветвлений. Слишком длинный результат заменяется превью: он дублируется в истории, а
    ``read_file`` длинного файла превратил бы строку БД в мегабайты.
    """
    if payload is None:
        return None
    data = payload if isinstance(payload, dict) else {"value": payload}
    text = json.dumps(data, ensure_ascii=False)
    if len(text) <= limit:
        return data
    return {"truncated": True, "chars": len(text), "preview": text[:limit]}


def _remember(payload: Any, path: str, read_contents: dict, files_read: list) -> None:
    """Запоминает прочитанное содержимое и путь для последующих шагов и отчёта."""
    content = str((payload or {}).get("content") or "")
    read_contents[path] = content
    _add(files_read, str((payload or {}).get("path") or path))


def _touch(payload: Any, path: str, tool: str, files_modified: list,
           files_created: list) -> None:
    """Раскладывает путь записи в «созданные» или «изменённые» по ответу инструмента.

    Различие берётся у инструмента (``WriteResult.created``), а не у домена: только он
    знает, был файл на диске до записи, и догадка «судя по пути, это новый ADR»
    разошлась бы с фактом.
    """
    record = payload if isinstance(payload, dict) else {}
    target = str(record.get("path") or path)
    if tool == file_assistant.TOOL_WRITE_FILE and record.get("created"):
        _add(files_created, target)
    else:
        _add(files_modified, target)


def _add(paths: list, path: str) -> None:
    """Добавляет путь без повторов, сохраняя порядок первого появления."""
    if path and path not in paths:
        paths.append(path)


def _guessed_block(step: dict) -> str:
    """Блок предполагаемого diff-а одного шага (режим ``dry_run``)."""
    guessed = str((step.get("result") or {}).get("presumed_diff") or "")
    if not guessed:
        return ""
    path = (step.get("arguments") or {}).get("path")
    return f"# предполагаемый diff: {path}\n{guessed}"


def _anchor_problem(found: dict, read_contents: dict) -> str:
    """Проверка аргументов второй фазы до исполнения: пути и якорь замены.

    Якорь ``old_text`` обязан встречаться в прочитанном содержимом файла: иначе
    ``apply_patch`` вернёт «текст для замены не найден», а прогон остановится на шаге,
    который можно было исправить одним повтором модели.
    """
    for index in sorted(found):
        arguments = found[index] or {}
        for name in ("path", "directory"):
            if name in arguments:
                problem = plan_rules.path_problem(arguments[name])
                if problem:
                    return f"шаг {index}: {name}={arguments[name]!r}: {problem}"
        anchor = arguments.get("old_text")
        if isinstance(anchor, str) and anchor and "path" in arguments:
            current = read_contents.get(str(arguments["path"]))
            if current is not None and anchor not in current:
                return file_assistant.REASON_PATCH_ANCHOR.format(
                    index=index, path=arguments["path"])
    return ""
