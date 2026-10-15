"""Раздел «🗂 Ассистент файлов (Day 34)»: цель вместо команды, план, шаги и diff.

Что видно в разделе и зачем именно так.

- **Слева сверху — цель и режим.** Пользователь описывает, чего хочет, а не какой
  файл открыть: «найди все места, где используется ``IndexService``». Рядом лежит
  переключатель ``dry_run``: он включён по умолчанию, потому что прогон МЕНЯЕТ файлы
  папки дня, и первое знакомство с ассистентом не должно ничего ломать. Когда флажок
  снят, раздел прямо предупреждает, что правки будут применены.
- **Кнопки-подсказки** ставят цель в поле И сразу выполняют её: три сценария демо
  покрывают все три исхода дня (только поиск, правка существующего файла, создание
  нового), и щёлкать «Выполнить» после подсказки — лишний шаг.
- **Раскрывашки «План» и «Выполненные шаги» рядом.** План — это то, что ассистент
  собрался сделать (модель его предложила), журнал — то, что он реально сделал.
  Разница между ними и есть ответ на вопрос «почему получилось не то, что я ожидал»;
  поэтому у каждого шага журнала видны и аргументы, и результат.
- **Diff внизу основного блока** — `st.code` с языком ``diff``: он читается как вывод
  ``git diff``, и по нему видно, что именно изменилось, до правки в репозитории.
- **История — отдельный блок.** Список запусков отвечает на «что тут вообще
  происходило», а ``diff`` выбранного запуска запрашивается отдельным эндпоинтом: он
  самый объёмный, и тянуть его в список незачем.

Провайдер ответа — ``llm_provider.PICKER_PROVIDERS`` (DeepSeek первым): прогон идёт в
облако по умолчанию, локальная Ollama — второй провайдер, и её выбор виден в подписи
прогона.
"""
from __future__ import annotations

import json

import streamlit as st

from backend.domain import file_assistant, llm_provider

from . import api_client, file_assistant_api

#: Ключи состояния раздела: цель, режим, провайдер, результат, история и diff.
#: Живут между перезапусками скрипта Streamlit, сбрасываются кнопками раздела.
GOAL_KEY = "fa_goal"
DRY_RUN_KEY = "fa_dry_run"
PROVIDER_KEY = "fa_provider"
RESULT_KEY = "fa_result"
HISTORY_KEY = "fa_history"
DIFF_KEY = "fa_diff"
RUN_KEY = "fa_run"

#: Пределы подписей: цель в кнопке-подсказке, аргументы и ошибка в таблицах.
LABEL_LIMIT = 40
GOAL_LIMIT = 70
REASON_LIMIT = 60
ARGS_LIMIT = 70
ERROR_LIMIT = 80
#: Сколько запусков просит раздел у истории.
HISTORY_LIMIT = 20


def render_file_assistant_section() -> None:
    """Раздел целиком: подсказки, цель с режимом, прогон, результат и история."""
    st.session_state.setdefault(DRY_RUN_KEY, True)
    st.session_state.setdefault(RESULT_KEY, None)
    st.title("🗂 Ассистент файлов (Day 34)")
    st.caption("Ассистент сам решает, какие файлы прочитать и изменить: цель превращается "
               f"в план шагов, а шаги выполняет MCP-сервер ``{file_assistant.FILE_SERVER_NAME}`` "
               "с шестью инструментами — поиск, список, чтение, запись, замена и diff.")
    _hints()
    _controls()
    _result()
    _history()


def _hints() -> None:
    """Три сценария демо: кнопка ставит цель в поле и сразу выполняет её."""
    st.caption("Примеры целей: " + " · ".join(item["goal"]
                                              for item in file_assistant.DEMO_SCENARIOS))
    columns = st.columns(len(file_assistant.DEMO_SCENARIOS))
    for position, (column, scenario) in enumerate(zip(columns,
                                                      file_assistant.DEMO_SCENARIOS)):
        with column:
            if st.button(_short(scenario["label"], LABEL_LIMIT),
                         key=f"fa_goal_{position}",
                         type="primary" if position == 0 else "secondary",
                         help=scenario["goal"]):
                st.session_state[GOAL_KEY] = scenario["goal"]
                _execute(scenario["goal"], _provider(), _dry_run())


def _controls() -> None:
    """Поле цели, режим ``dry_run``, провайдер и кнопка прогона."""
    goal = st.text_area(
        "Цель", key=GOAL_KEY, height=90,
        placeholder="Например: найди все места, где используется IndexService, "
                    "и покажи, как он вызывается")
    st.checkbox("dry_run — только план и предполагаемый diff, файлы не меняются",
                key=DRY_RUN_KEY,
                help="В этом режиме write_file и apply_patch не вызываются вовсе")
    if not st.session_state[DRY_RUN_KEY]:
        st.warning("dry_run выключен: изменения будут применены к файлам day21/")
    provider = st.radio("Провайдер ответа", list(llm_provider.PICKER_PROVIDERS),
                        format_func=llm_provider.label, index=0, horizontal=True,
                        key=PROVIDER_KEY)
    if st.button("🚀 Выполнить", type="primary",
                 help="План строит модель, шаги выполняет MCP-сервер файлов"):
        if not goal.strip():
            st.info("Пустая цель не отправлена: опишите, что нужно сделать с файлами.")
        else:
            _execute(goal, provider, bool(st.session_state[DRY_RUN_KEY]))


def _execute(goal: str, provider: str, dry_run: bool) -> None:
    """Прогон цели: запрос к бэкенду и запись результата в состояние сессии.

    Ошибка бэкенда показывается плашкой, а прежний результат СБРАСЫВАЕТСЯ: старый
    блок «План и шаги» под сообщением об ошибке читался бы как результат нового
    прогона — а текст отказа (например, 422 с проблемами плана) относится не к нему.
    """
    with st.spinner("🗂 Ассистент планирует шаги и выполняет их…"):
        try:
            st.session_state[RESULT_KEY] = file_assistant_api.api_file_assistant_execute(
                goal, provider, dry_run)
        except api_client.BackendError as exc:
            st.session_state[RESULT_KEY] = None
            st.error(exc.message)


def _result() -> None:
    """Блок результата: план, журнал шагов, файлы, diff и сводка."""
    record = st.session_state.get(RESULT_KEY)
    if not record:
        st.info("Прогонов пока нет: задайте цель и нажмите «Выполнить» — либо возьмите "
                "готовую цель из подсказок выше.")
        return
    st.divider()
    st.caption(f"запуск #{record.get('run_id')} · статус **{record.get('status')}** · "
               f"провайдер {llm_provider.label(record.get('provider') or '')} · "
               f"время {int(record.get('duration_ms') or 0) / 1000:.2f} с")
    if record.get("dry_run"):
        st.info(file_assistant.DRY_RUN_NOTE)
    for step in record.get("steps_executed") or []:
        if step.get("error") and step.get("status") == file_assistant.STEP_FAILED:
            st.warning(f"шаг {step.get('step_index')} ({step.get('tool')}): "
                       f"{step['error']}")
    _plan(record.get("plan") or [])
    _steps(record.get("steps_executed") or [])
    _files(record)
    _diff(record)
    st.subheader("📝 Итог")
    st.markdown(record.get("summary") or "_Сводка не получена._")


def _plan(steps: list) -> None:
    """Раскрывашка «🧠 План»: что ассистент собирался сделать и какие аргументы взял."""
    with st.expander("🧠 План", expanded=True):
        if not steps:
            st.caption("Плана нет: прогон не дошёл до планирования.")
            return
        st.dataframe(
            [{"шаг": step.get("step_index"), "инструмент": step.get("tool") or "—",
              "зачем": _short(step.get("reason"), REASON_LIMIT),
              "аргументы": _short(_json(step.get("arguments")), ARGS_LIMIT)}
             for step in steps],
            hide_index=True, use_container_width=True,
        )


def _steps(steps: list) -> None:
    """Раскрывашка «🛠 Выполненные шаги»: статус, время и ошибка каждого шага."""
    with st.expander("🛠 Выполненные шаги", expanded=True):
        if not steps:
            st.caption("Шаги не выполнялись.")
            return
        st.dataframe(
            [{"шаг": step.get("step_index"), "инструмент": step.get("tool") or "—",
              "статус": step.get("status") or "—",
              "мс": int(step.get("duration_ms") or 0),
              "ошибка": _short(step.get("error"), ERROR_LIMIT)}
             for step in steps],
            hide_index=True, use_container_width=True,
        )
        for step in steps:
            with st.expander(f"шаг {step.get('step_index')} · {step.get('tool')}"):
                st.json({"аргументы": step.get("arguments"),
                         "результат": step.get("result")})


def _files(record: dict) -> None:
    """Раскрывашка «📄 Файлы»: что прочитано, изменено и создано."""
    with st.expander("📄 Файлы", expanded=True):
        for label, key in (("прочитаны", "files_read"), ("изменены", "files_modified"),
                           ("созданы", "files_created")):
            st.markdown(f"**{label}:** {_list_text(record.get(key))}")


def _diff(record: dict) -> None:
    """Раскрывашка «🧾 Diff»: unified diff изменений прогона."""
    with st.expander("🧾 Diff", expanded=True):
        diff = str(record.get("diff") or "")
        if not diff:
            st.caption("Diff пуст: прогон не менял файлы.")
            return
        st.code(diff, language="diff")


def _history() -> None:
    """История запусков: таблица, выбор запуска и diff выбранного запуска."""
    st.divider()
    st.subheader("🕓 История запусков")
    if st.button("🔄 Обновить историю"):
        st.session_state.pop(HISTORY_KEY, None)
        st.rerun()
    data = _history_cache()
    if data.get("error"):
        st.warning(f"История не загружена: {data['error']}")
        return
    runs = list(data.get("runs") or [])
    if not runs:
        st.caption("История пуста: прогонов ещё не было.")
        return
    st.dataframe([_row(run) for run in runs], hide_index=True, use_container_width=True)
    run_id = st.selectbox("Запуск", [run["id"] for run in runs],
                          format_func=lambda value: _run_label(runs, value), key=RUN_KEY)
    if st.button("Показать diff"):
        st.session_state[DIFF_KEY] = _cached_diff(run_id)
    cached = st.session_state.get(DIFF_KEY) or {}
    if cached.get("id") != run_id:
        return
    if cached.get("error"):
        st.warning(f"Diff не загружен: {cached['error']}")
    else:
        st.code(cached.get("diff") or file_assistant.NO_PRESUMED_DIFF, language="diff")


def _history_cache() -> dict:
    """Кэш истории: запрос при первом проходе и после нажатия «Обновить»."""
    if HISTORY_KEY not in st.session_state:
        try:
            st.session_state[HISTORY_KEY] = file_assistant_api.api_file_assistant_history(
                HISTORY_LIMIT)
        except api_client.BackendError as exc:
            st.session_state[HISTORY_KEY] = {"count": 0, "runs": [], "error": exc.message}
    return st.session_state.get(HISTORY_KEY) or {}


def _cached_diff(run_id: int) -> dict:
    """Diff выбранного запуска: запрос по требованию, ошибка — тоже данные."""
    try:
        return {"id": run_id, "diff": file_assistant_api.api_file_assistant_diff(
            run_id).get("diff") or "", "error": ""}
    except api_client.BackendError as exc:
        return {"id": run_id, "diff": "", "error": exc.message}


def _row(run: dict) -> dict:
    """Строка таблицы истории: цель, статус, время и сколько файлов тронуто."""
    return {"id": run.get("id"), "цель": _short(run.get("goal"), GOAL_LIMIT),
            "статус": run.get("status") or "—",
            "начат": run.get("started_at") or "—",
            "окончен": run.get("finished_at") or "—",
            "шагов": len(run.get("steps") or []),
            "изменено": len(run.get("files_modified") or []),
            "создано": len(run.get("files_created") or [])}


def _run_label(runs: list, run_id: int) -> str:
    """Подпись запуска в селекторе: «#id · статус · цель»."""
    run = next((item for item in runs if item.get("id") == run_id), {})
    return (f"#{run_id} · {run.get('status') or '—'} · "
            f"{_short(run.get('goal'), GOAL_LIMIT)}")


def _list_text(paths) -> str:
    """Список путей одной строкой; пустой — «—»."""
    items = [str(path) for path in (paths or [])]
    return ", ".join(f"`{path}`" for path in items) if items else "—"


def _provider() -> str:
    """Выбранный провайдер ответа; до первого прохода — значение по умолчанию."""
    return str(st.session_state.get(PROVIDER_KEY) or llm_provider.PROVIDER_DEEPSEEK)


def _dry_run() -> bool:
    """Текущий режим ``dry_run`` (до первого прохода флажок включён)."""
    return bool(st.session_state.get(DRY_RUN_KEY, True))


def _json(value) -> str:
    """Значение для таблицы: JSON одной строкой, без переводов строк."""
    try:
        return json.dumps(value, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(value)


def _short(text, limit: int) -> str:
    """Текст одной строкой, обрезанный до ``limit`` символов."""
    compact = " ".join(str(text or "").split())
    return compact if len(compact) <= limit else compact[:limit - 1] + "…"
