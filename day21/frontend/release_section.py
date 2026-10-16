"""Раздел «🚀 Подготовка релиза (Day 35)»: теги, версия, CHANGELOG и проверки.

Раздел — витрина одной кнопки: «🚀 Подготовить релиз» запускает прогон, в котором
коммиты диапазона читает MCP-сервер ``file_server``, тип версии и пункты CHANGELOG
предлагает модель, проверки готовности идут подпроцессами ``pytest``, а файлы
(``CHANGELOG.md``, ``day21/docs/RELEASE_NOTES.md``, ``README.md``) записываются через
тот же MCP. Раздел не решает ничего сам: он показывает то, что вернул бэкенд.

``dry_run`` включён по умолчанию и это не украшение: прогон делает десятки секунд
работы и меняет ФАЙЛЫ РЕПОЗИТОРИЯ (корневой CHANGELOG и README, заметки релиза), а
раздел открывается одним движением. Поэтому предпросмотр — состояние по умолчанию, а
предупреждение о выключенном режиме стоит рядом с флажком.

Выгрузка (``⬇️ Скачать CHANGELOG.md``) берёт файл из ЗАПИСИ прогона на бэкенде, а не с
диска: скачать можно и ``dry_run`` — он показывает, что было бы записано.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import llm_provider, release

from . import api_client, release_api

#: Ключи состояния раздела: теги, выбор диапазона, режим, провайдер, результат,
#: история и кэш выгрузки. Живут между перезапусками скрипта Streamlit и сбрасываются
#: кнопками раздела.
TAGS_KEY = "rl_tags"
FROM_KEY = "rl_from"
TO_KEY = "rl_to"
VERSION_KEY = "rl_version"
DRY_RUN_KEY = "rl_dry_run"
PROVIDER_KEY = "rl_provider"
RESULT_KEY = "rl_result"
HISTORY_KEY = "rl_history"
EXPORT_KEY = "rl_export"

#: Подписи метрик для таблицы: форма «много» из домена (числа в таблице всегда «14 тегов»).
METRIC_LABELS = {key: forms[2] for key, *forms in release.METRIC_LABELS}
#: Сколько символов хвоста вывода команды показывать (полный текст — в самой команде).
TAIL_LIMIT = 400
#: Что предложить в поле версии, пока пользователь ничего не ввёл.
VERSION_HINT = "auto"

HELP_TAGS = ("Коммиты диапазона читает MCP-сервер `file_server` (инструменты "
             "git-истории), версию и пункты CHANGELOG предлагает модель. SemVer: "
             "breaking — major, feat — minor, всё остальное — patch; версия `auto` "
             "считается от последнего раздела `CHANGELOG.md`.")
HELP_DRY_RUN = ("dry_run: показывается план и diff, инструменты записи (write_file, "
                "apply_patch) не вызываются")


def render_release_section() -> None:
    """Раздел целиком: подсказки, выбор диапазона, прогон, результат и история."""
    st.title("🚀 Подготовка релиза (Day 35)")
    st.caption("Версия по коммитам, раздел CHANGELOG, заметки о релизе, проверки "
               "готовности и запись файлов через MCP-сервер `file_server`.")
    st.session_state.setdefault(DRY_RUN_KEY, True)
    st.session_state.setdefault(RESULT_KEY, None)
    st.session_state.setdefault(EXPORT_KEY, {})
    _controls()
    _result()
    _history()


# ---------- управление ----------
def _controls() -> None:
    """Диапазон тегов, версия, режим ``dry_run``, провайдер и кнопка прогона."""
    st.caption(HELP_TAGS)
    tags = _tags()
    if tags.get("error"):
        st.error(tags["error"])
    names = [str(tag.get("name")) for tag in (tags.get("tags") or [])]
    # По умолчанию начало диапазона — ПРЕДЫДУЩИЙ тег (список идёт от свежих к старым):
    # диапазон «самый свежий тег..HEAD» чаще всего пуст, и прогон отвечал бы «нет
    # коммитов» на первое же нажатие кнопки.
    from_index = 1 if len(names) > 1 else 0
    row = st.columns([1, 1, 1, 0.7])
    with row[0]:
        from_tag = st.selectbox("От тега", names or ["day1"], index=from_index, key=FROM_KEY)
    with row[1]:
        to_tag = st.selectbox("До тега", ["HEAD", *names], key=TO_KEY)
    with row[2]:
        version = st.text_input("Версия", key=VERSION_KEY, placeholder=VERSION_HINT,
                                help="`auto` — тип изменения определит модель")
    with row[3]:
        if st.button("🔄 Обновить теги"):
            st.session_state.pop(TAGS_KEY, None)
            st.rerun()
    dry_run = st.checkbox("dry_run — предпросмотр: файлы не меняются", key=DRY_RUN_KEY,
                          help=HELP_DRY_RUN)
    if not dry_run:
        st.warning("dry_run выключен: CHANGELOG.md, RELEASE_NOTES.md и README.md будут "
                   "изменены")
    provider = st.radio("Провайдер ответа", list(llm_provider.PICKER_PROVIDERS),
                        format_func=llm_provider.label, index=0, horizontal=True,
                        key=PROVIDER_KEY)
    if st.button("🚀 Подготовить релиз", type="primary"):
        _prepare(from_tag, to_tag, version or VERSION_HINT, provider, bool(dry_run))


def _tags() -> dict:
    """Теги для селекторов: запрос при первом проходе; отказ — данные, а не исключение."""
    cached = st.session_state.get(TAGS_KEY)
    if cached is not None:
        return cached
    try:
        cached = release_api.api_release_tags()
    except api_client.BackendError as exc:
        cached = {"count": 0, "tags": [], "error": exc.message}
    st.session_state[TAGS_KEY] = cached
    return cached


def _prepare(from_tag: str, to_tag: str, version: str, provider: str,
             dry_run: bool) -> None:
    """Прогон релиза: запрос к бэкенду и запись результата в состояние сессии."""
    with st.spinner("🚀 Собираю коммиты, определяю версию и генерирую CHANGELOG…"):
        try:
            record = release_api.api_release_prepare(from_tag, to_tag, version, provider,
                                                     dry_run)
        except api_client.BackendError as exc:
            st.session_state[RESULT_KEY] = None
            st.session_state[EXPORT_KEY] = {}
            st.error(exc.message)
            return
    st.session_state[RESULT_KEY] = record
    # Выгрузка и история — про КОНКРЕТНЫЙ прогон и его место в списке: кэш прошлого
    # прогона после нового показывал бы чужие файлы и устаревшую историю.
    st.session_state[EXPORT_KEY] = {}
    st.session_state.pop(HISTORY_KEY, None)
    st.rerun()


# ---------- результат ----------
def _result() -> None:
    """Блок результата: версия, CHANGELOG, проверки, правки, метрики и выгрузка."""
    record = st.session_state.get(RESULT_KEY)
    if not record:
        return
    _version_block(record)
    _changelog_block(record)
    _checks_block(record)
    _changes_block(record)
    _metrics_block(record)
    _export_block(record)
    _notes_block(record)


def _version_block(record: dict) -> None:
    """Версия, её тип, диапазон и причина выбора; «💥 Breaking changes» — в раскрывашке."""
    st.subheader("🏷 Определение версии")
    st.markdown(f"**{record['version']}** · тип изменения: `{record['version_bump']}` · "
                f"{record['from_label']} → {record['to_label']}")
    st.caption(record["version_reason"])
    breaking = record.get("breaking_changes") or []
    with st.expander(f"💥 Breaking changes: {len(breaking)}"):
        st.markdown("\n".join(f"- {item}" for item in breaking)
                    or "_Несовместимых изменений нет._")


def _changelog_block(record: dict) -> None:
    """Готовый раздел CHANGELOG и счётчики пунктов."""
    st.subheader("📝 CHANGELOG")
    changelog = record["changelog"]
    st.code(changelog["section"], language="markdown")
    kept = sum(len(changelog[key]) for key in release.GROUP_ORDER)
    st.caption(f"Ключевых пунктов: {kept}, свёрнуто: {changelog['minor_count']} коммитов "
               f"(отброшено сверх предела 20: {changelog['dropped_count']})")


def _checks_block(record: dict) -> None:
    """Проверки готовности: четыре строки таблицы и вывод команд в раскрывашке."""
    st.subheader("✅ Проверки готовности")
    checks = record["checks"]
    coverage = float(checks.get("coverage_percent") or 0.0)
    rows = [
        {"проверка": "тесты", "значение": "пройдены" if checks["tests_passed"] else "провалены",
         "итог": "✅" if checks["tests_passed"] else "❌"},
        {"проверка": "покрытие", "значение": f"{coverage:.1f}%",
         "итог": "✅" if coverage else "❌"},
        {"проверка": "README.md", "значение": checks["files"].get("readme", {}).get("path", ""),
         "итог": "✅" if checks["readme_exists"] else "❌"},
        {"проверка": "docs/architecture.md",
         "значение": checks["files"].get("docs", {}).get("path", ""),
         "итог": "✅" if checks["docs_exists"] else "❌"},
    ]
    st.dataframe(rows, hide_index=True, use_container_width=True)
    with st.expander("🧾 Вывод команд"):
        for command in checks.get("commands") or []:
            st.text(f"{command['command']} → код {command['returncode']}")
            st.text(str(command.get("tail") or "")[:TAIL_LIMIT])


def _changes_block(record: dict) -> None:
    """План правки файлов и предпросмотр diff-а (в ``dry_run`` — только он)."""
    st.subheader("🧾 Предполагаемые изменения")
    if record.get("dry_run"):
        st.caption(release.VERDICT_DRY_RUN)
    preview = record.get("diff_preview") or {}
    for entry in record.get("files_to_modify") or []:
        path = entry["path"]
        label = f"{path} — {entry['tool']}"
        if entry.get("skipped"):
            label += " (пропущено)"
        with st.expander(label):
            if entry.get("note"):
                st.caption(entry["note"])
            if entry.get("error"):
                st.error(entry["error"])
            st.code(preview.get(path) or "—", language="diff")


def _metrics_block(record: dict) -> None:
    """Метрики проекта из инструмента ``get_project_metrics``."""
    metrics = record.get("metrics") or {}
    st.subheader("📊 Метрики проекта")
    rows = [{"метрика": label, "значение": metrics[key]}
            for key, label in METRIC_LABELS.items() if key in metrics]
    if rows:
        st.dataframe(rows, hide_index=True, use_container_width=True)
    else:
        st.caption("метрики не собраны: MCP-инструмент метрик недоступен")


def _export_block(record: dict) -> None:
    """Выгрузка раздела CHANGELOG: файл берётся из записи прогона на бэкенде."""
    st.subheader("⬇️ Выгрузка")
    run_id = int(record["run_id"])
    cache = st.session_state.setdefault(EXPORT_KEY, {})
    if run_id not in cache:
        try:
            cache[run_id] = release_api.api_release_export_bytes(run_id, "changelog")
        except api_client.BackendError as exc:
            cache[run_id] = {"error": exc.message}
    value = cache[run_id]
    if isinstance(value, dict):
        st.warning(str(value.get("error") or "выгрузка недоступна"))
        return
    data, name = value
    st.download_button("⬇️ Скачать CHANGELOG.md", data=data,
                       file_name=name or "CHANGELOG.md", mime="text/markdown")
    st.caption(f"Файл выгрузки: `{name}` (ZIP со обоими файлами — `both` в API)")


def _notes_block(record: dict) -> None:
    """Заметки прогона: пропуски правок, отказы модели и непройденные проверки."""
    notes = record.get("notes") or []
    if not notes:
        return
    with st.expander(f"ℹ️ Заметки прогона: {len(notes)}"):
        for line in notes:
            st.info(line)


# ---------- история ----------
def _history() -> None:
    """История релизов: таблица запусков (тексты разделов в неё не входят)."""
    st.subheader("🗂 История релизов")
    history = _history_cache()
    if history.get("error"):
        st.error(history["error"])
        return
    runs = history.get("runs") or []
    if not runs:
        st.caption("Релизов пока нет: прогон появится здесь сразу после подготовки.")
        return
    st.dataframe([_history_row(run) for run in runs], hide_index=True,
                 use_container_width=True)


def _history_cache() -> dict:
    """Кэш истории: запрос при первом проходе и после каждого прогона."""
    cached = st.session_state.get(HISTORY_KEY)
    if cached is not None:
        return cached
    try:
        cached = release_api.api_release_history()
    except api_client.BackendError as exc:
        cached = {"count": 0, "runs": [], "error": exc.message}
    st.session_state[HISTORY_KEY] = cached
    return cached


def _history_row(run: dict) -> dict:
    """Строка таблицы истории: диапазон, версия, проверки, файлы и время начала."""
    files = run.get("files_modified") or []
    return {"id": run.get("id"), "от": run.get("from_tag"), "до": run.get("to_tag"),
            "версия": run.get("version"),
            "проверки": "✅" if run.get("checks_passed") else "❌",
            "файлов": len(files), "статус": run.get("status"),
            "начат": str(run.get("started_at") or "")[:19].replace("T", " ")}
