"""Раздел «🛰 Удалённая LLM (Day 30)»: Ollama в Colab, подключённый через туннель.

Раздел существует ради одной кнопки: настройки видны на экране, «Проверить соединение»
делает GET /models и зажигает зелёный или красный индикатор, а «🚀 Прогнать демо одной
кнопкой» прогоняет пять шагов сценария и заполняет таблицу с ответами, временем,
провайдером и статусом. Прогон идёт отдельными HTTP-запросами по шагу
(``frontend/remote_llm_api``), поэтому прогресс-бар отражает реальный ход: видно, какой
именно шаг ждёт ответа из Colab.

Ограничения дня 30 показаны на экране, а не спрятаны в отчёт: предел частоты считает
КЛИЕНТ (``RemoteLLMClient``), окно контекста уходит в Ollama как ``options.num_ctx``,
а адрес туннеля живёт часами. Недоступный сервис — это строка таблицы с причиной и
предупреждение, а не падение раздела.

Умолчания полей приходят от бэкенда (``GET /llm/remote-config``): иначе предзаполненное
поле UI и настройка, которой реально отвечает служба, разошлись бы после правки ``.env``.
"""
from __future__ import annotations

import streamlit as st

from backend.domain import llm_provider
from backend.domain.remote_demo import KIND_RATE, summarize_rows

from . import api_client, common, remote_llm_api

#: Ключи виджетов: по ним значения живут между перезапусками скрипта Streamlit.
URL_KEY = "remote_llm_url"
MODEL_KEY = "remote_llm_model"
KEY_KEY = "remote_llm_api_key"
RATE_KEY = "remote_llm_rate_limit"
CTX_KEY = "remote_llm_max_context"
#: Результаты держим в состоянии сессии: прогон не должен пропадать при перерисовке.
CHECK_KEY = "remote_llm_check"
DEMO_KEY = "remote_llm_demo"

#: Сколько символов видно в таблице; полный ответ — в раскрывашке строки.
ANSWER_LIMIT = 200
QUESTION_LIMIT = 90
#: Три вопроса демо (шаги 2–4) идут в одно окно минуты, поэтому сценарий целиком
#: проходит при лимите от трёх запросов; шаг 5 начинает минуту заново.
MIN_DEMO_RATE_LIMIT = 3


def render_remote_llm_section() -> None:
    """Раздел целиком: настройки, кнопки и таблица последнего прогона."""
    st.subheader("🛰 Удалённая LLM (Day 30) — Ollama в Google Colab")
    st.caption(
        "Модель работает не на этой машине: ячейка в Colab поднимает Ollama, туннель "
        "Cloudflare отдаёт её наружу, а программа ходит по HTTP на адрес туннеля. "
        "Адрес живёт часами: перезапуск ячейки даёт новый — впишите его заново. "
        "Предел частоты считает клиент, окно контекста уходит в Ollama."
    )
    try:
        config = remote_llm_api.api_remote_config()
    except api_client.BackendError as exc:
        st.error(f"Бэкенд недоступен, раздел настраивать нечем: {exc.message}")
        return
    settings = _controls(config)
    _actions(settings, config)
    _demo_results(config)


def _controls(config: dict) -> dict:
    """Поля и слайдеры: значения из ``.env``, каждое переопределяется на экране."""
    _default(URL_KEY, str(config.get("url") or ""))
    _default(MODEL_KEY, str(config.get("model") or ""))
    _default(KEY_KEY, str(config.get("api_key") or ""))
    _default(RATE_KEY, _clamped(config.get("rate_limit"), config.get("rate_limit_min"),
                                config.get("rate_limit_max")))
    _default(CTX_KEY, _clamped(config.get("max_context"), config.get("max_context_min"),
                               config.get("max_context_max")))
    left, right = st.columns([3, 2])
    with left:
        url = st.text_input("Base URL туннеля (…/v1)", key=URL_KEY,
                            placeholder="https://xxxx.trycloudflare.com/v1/",
                            help="Адрес из ячейки Colab; /v1 в конце — часть адреса сервиса")
        model = st.text_input("Модель", key=MODEL_KEY,
                              help="Тег модели Ollama, например qwen2.5-coder:7b")
    with right:
        rate_limit = st.slider("Rate limit (запросов в минуту)",
                               min_value=int(config.get("rate_limit_min") or 1),
                               max_value=int(config.get("rate_limit_max") or 30),
                               key=RATE_KEY,
                               help="Счётчик RemoteLLMClient: на N+1-м запросе в минуту "
                                    "клиент отвечает ошибкой 429, не отправляя запрос")
        max_context = st.slider("Max context (токенов)",
                                min_value=int(config.get("max_context_min") or 1024),
                                max_value=int(config.get("max_context_max") or 8192),
                                step=1024, key=CTX_KEY,
                                help="Уходит в Ollama как options.num_ctx: больше окно — "
                                     "длиннее контекст, больше памяти и времени на ответ")
    if int(rate_limit) < MIN_DEMO_RATE_LIMIT:
        st.caption(f"⚠️ Три вопроса шагов 2–4 идут в общее окно минуты: при лимите "
                   f"{int(rate_limit)} демо дойдёт до отказа раньше пятого шага "
                   f"(полный сценарий проходит при лимите от {MIN_DEMO_RATE_LIMIT}).")
    with st.expander("Ключ доступа (Ollama его не проверяет)"):
        api_key = st.text_input("API key", key=KEY_KEY,
                                help="Подставляется в заголовок Authorization: Bearer; "
                                     "подойдёт любая непустая строка")
        st.caption(f"Ждём один запрос до {float(config.get('timeout') or 0):.0f} с: "
                   f"на бесплатном GPU модель отвечает медленно.")
    return {"url": str(url).strip(), "model": str(model).strip(),
            "api_key": str(api_key).strip(), "rate_limit": int(rate_limit),
            "max_context": int(max_context)}


def _actions(settings: dict, config: dict) -> None:
    """Кнопки раздела: проверка связи, прогон одной кнопкой и корень туннеля."""
    check_col, run_col, webui_col = st.columns([1, 2, 1])
    with check_col:
        pressed = st.button("🔌 Проверить соединение", key="remote_check_press")
    with run_col:
        run = st.button("🚀 Прогнать демо одной кнопкой", type="primary",
                        key="remote_run_press")
    webui = _webui_url(settings["url"])
    with webui_col:
        if webui:
            st.link_button("🌐 Открыть Open WebUI", webui,
                           help="Корень туннеля: адрес без служебного /v1")
    if pressed:
        _check(settings)
    _check_state()
    if run:
        _run_demo(settings, config)


def _check(settings: dict) -> None:
    """GET /models по туннелю: результат кладём в состояние сессии и показываем сразу."""
    with st.spinner("Проверяю связь: GET /models через туннель…"):
        try:
            st.session_state[CHECK_KEY] = remote_llm_api.api_remote_check(settings)
        except api_client.BackendError as exc:
            st.session_state[CHECK_KEY] = {"ok": False, "message": exc.message,
                                           "models": [], "count": 0,
                                           "url": settings["url"]}


def _check_state() -> None:
    """Индикатор связи: зелёный, красный или «ещё не проверяли»."""
    result = st.session_state.get(CHECK_KEY)
    if not result:
        st.info("Связь ещё не проверялась: нажмите «🔌 Проверить соединение» — "
                "на адрес туннеля уйдёт GET /models.")
        return
    if result.get("ok"):
        st.success(str(result.get("message") or "Соединение установлено"))
    else:
        st.error(f"Соединение не установлено: {result.get('message')}")
    models = list(result.get("models") or [])
    if models:
        st.caption("Модели по туннелю: " + ", ".join(models))
    st.caption(f"Адрес проверки: {result.get('url') or '—'}; "
               f"GET /models занял {int(result.get('duration_ms') or 0) / 1000:.2f} с.")


def _run_demo(settings: dict, config: dict) -> None:
    """Пять шагов по одному HTTP-запросу на шаг: прогресс-бар отражает реальный ход.

    Прогон обрывается на первой ошибке шага (кроме шага про частоту): если туннель
    умер, четыре следующих шага — это четыре ожидания по 120 с, а не новый результат.
    """
    steps = list(config.get("steps") or [])
    total = len(steps) or 1
    rows: list[dict] = []
    aborted = ""
    progress = st.progress(0.0, text="Готовлю прогон…")
    for index, step in enumerate(steps):
        title = str(step.get("title") or step.get("key") or "")
        progress.progress(index / total, text=f"Шаг {index + 1} из {total}: {title} — "
                                             f"запрос ушёл на удалённый сервис, ждём…")
        try:
            row = remote_llm_api.api_remote_step(str(step.get("key") or ""), settings,
                                                 reset=(index == 0))
        except api_client.BackendError as exc:
            rows.append(_transport_row(step, settings, exc.message))
            aborted = f"{title}: {exc.message}"
            break
        rows.append(row)
        if row.get("status") != "ok" and step.get("kind") != KIND_RATE:
            aborted = f"{title}: {row.get('answer')}"
            break
    progress.progress(1.0, text=f"Прогон завершён: шагов {len(rows)} из {total}")
    st.session_state[DEMO_KEY] = {"rows": rows, "settings": dict(settings),
                                  "aborted": aborted, "steps_total": total,
                                  "summary": summarize_rows(rows)}


def _demo_results(config: dict) -> None:
    """Таблица прогона, сводка и полные ответы — то, что видно на видео."""
    result = st.session_state.get(DEMO_KEY)
    if not result:
        st.caption("Таблица заполнится после нажатия «🚀 Прогнать демо одной кнопкой».")
        return
    settings = result.get("settings") or {}
    st.markdown("#### Результаты прогона")
    st.caption(f"{settings.get('url') or '—'} · модель {settings.get('model') or '—'} · "
               f"лимит {settings.get('rate_limit')} запросов в минуту · "
               f"окно контекста {settings.get('max_context')} токенов")
    if result.get("aborted"):
        st.warning(f"Прогон прерван на шаге «{result['aborted']}». Перезапустите ячейку в "
                   f"Colab, вставьте новый адрес туннеля и повторите прогон.")
    rows = list(result.get("rows") or [])
    if rows:
        st.dataframe([_table_row(row) for row in rows], width="stretch",
                     hide_index=True)
    _summary(result.get("summary") or {}, config)
    _answers(rows)


def _summary(summary: dict, config: dict) -> None:
    """Сводка: запросы, среднее время, успешные шаги, ошибки и кто отвечал."""
    st.markdown("##### Итог")
    window = int(float(config.get("rate_window_seconds") or 0))
    columns = st.columns(5)
    columns[0].metric("Запросов к модели", str(int(summary.get("requests") or 0)))
    columns[1].metric("Среднее время",
                      f"{int(summary.get('avg_ok_ms') or 0) / 1000:.2f} с")
    columns[2].metric("Шагов без ошибок",
                      f"{int(summary.get('success') or 0)}/{int(summary.get('steps') or 0)}")
    columns[3].metric("Ошибок", str(int(summary.get("errors") or 0)))
    confirmed = bool(summary.get("remote_confirmed"))
    columns[4].metric("Провайдер ответов", str(summary.get("provider") or "—"),
                      delta="✅ подтверждён" if confirmed else "⚠️ не подтверждён")
    st.caption(f"Дошло до удалённого сервиса: {int(summary.get('calls') or 0)} запросов; "
               f"отклонил клиентский лимит: {int(summary.get('blocked') or 0)}; "
               f"окно лимита {window} с; GET /models в счёт вызовов модели не входит.")
    if confirmed:
        st.success("Подтверждение: все ответы таблицы принёс провайдер remote — это "
                   "удалённая модель в Colab, а не облачный API.")
    else:
        st.warning("Провайдер ответов не подтвердился как remote: смотрите строки таблицы.")


def _answers(rows: list[dict]) -> None:
    """Полные ответы и мелочи шага: в таблице видны только первые 200 символов."""
    for row in rows:
        mark = "✅" if row.get("status") == "ok" else "❌"
        title = str(row.get("title") or row.get("step") or "")
        with st.expander(f"{mark} {title}"):
            st.markdown(f"**Запрос:** {common.esc(row.get('question') or '—')}")
            st.markdown(f"**Ответ** (`{row.get('provider') or '—'}`, "
                        f"модель `{row.get('model') or '—'}`):")
            st.text(str(row.get("answer") or ""))
            for line in _details(row):
                st.caption(line)


def _details(row: dict) -> list[str]:
    """Мелочи строки: время, токены, состояние счётчика частоты и итоги шага про лимит."""
    lines = [f"Время: {int(row.get('duration_ms') or 0) / 1000:.2f} с · "
             f"запросов к модели на шаге: {int(row.get('calls') or 0)}"]
    tokens = row.get("tokens") or {}
    if tokens:
        lines.append(f"Токены: подсказка {tokens.get('prompt_tokens', 0)}, "
                     f"ответ {tokens.get('completion_tokens', 0)}, "
                     f"всего {tokens.get('total_tokens', 0)}, "
                     f"{float(tokens.get('tokens_per_second') or 0):.1f} ток./с")
    counter = row.get("rate_limit") or {}
    if counter:
        lines.append(f"Счётчик частоты: {counter.get('used')} из {counter.get('limit')} "
                     f"за {int(float(counter.get('window_seconds') or 0))} с")
    if row.get("limit") is not None:
        lines.append(f"Лимит шага: {row.get('limit')} запросов в минуту; прошло "
                     f"{row.get('sent')}, отклонил клиент {row.get('blocked')}")
    if row.get("sample"):
        lines.append(f"Последний ответ до отказа: {row.get('sample')}")
    if row.get("models"):
        lines.append("Модели сервиса: " + ", ".join(row["models"]))
    return lines


def _table_row(row: dict) -> dict:
    """Строка таблицы: шаг, запрос, ответ (200 символов), время, провайдер, статус."""
    return {
        "шаг": str(row.get("title") or row.get("step") or ""),
        "запрос": _short(row.get("question"), QUESTION_LIMIT),
        "ответ": _short(row.get("answer"), ANSWER_LIMIT),
        "время, с": round(int(row.get("duration_ms") or 0) / 1000, 2),
        "провайдер": str(row.get("provider") or "—"),
        "статус": "✅ ок" if row.get("status") == "ok" else "❌ ошибка",
    }


def _transport_row(step: dict, settings: dict, message: str) -> dict:
    """Строка для отказа транспорта: шаг не доехал, причина — в поле ответа."""
    key = str(step.get("key") or "")
    return {"step": key, "title": str(step.get("title") or key),
            "question": str(step.get("question") or ""), "answer": message,
            "duration_ms": 0, "provider": llm_provider.PROVIDER_REMOTE,
            "model": settings.get("model") or "", "status": "error", "calls": 0}


def _webui_url(url: str) -> str:
    """Корень туннеля: адрес без служебного ``/v1`` — там Open WebUI или Ollama."""
    text = str(url or "").strip().rstrip("/")
    for suffix in ("/v1", "/api"):
        if text.endswith(suffix):
            text = text[: -len(suffix)]
    text = text.rstrip("/")
    return text if text.startswith("http") else ""


def _default(key: str, value: object) -> None:
    """Умолчание виджета из ответа бэкенда — один раз на сессию, правки не затираем."""
    st.session_state.setdefault(key, value)


def _clamped(value: object, low: object, high: object) -> int:
    """Значение в границах слайдера: ноль и мусор из ``.env`` не должны ронять виджет."""
    bottom, top = int(low or 1), int(high or 1)
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        number = 0
    return max(bottom, min(top, number)) if number else bottom


def _short(text: object, limit: int) -> str:
    """Первые ``limit`` символов ответа одной строкой — для таблицы."""
    flat = " ".join(str(text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"
