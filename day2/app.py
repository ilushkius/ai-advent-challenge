"""
============================================================
 День 2 AI-челленджа: «Формат ответа»
 Управление детерминизмом, длиной и Stop Sequences через API
============================================================

Стек:  Streamlit + официальный OpenAI SDK (клиент DeepSeek).

Запуск:
    pip install -r requirements.txt
    streamlit run app.py
"""

import html
import json
import os
import time

import streamlit as st
from openai import OpenAI

# ---------------------------------------------------------------------------
# Константы и конфигурация
# ---------------------------------------------------------------------------
APP_TITLE = "🎛️ День 2 · Формат ответа"
APP_SUBTITLE = "Управление детерминизмом, длиной и Stop Sequences через DeepSeek API"

# Официальный endpoint DeepSeek (синтаксис полностью совместим с OpenAI SDK).
# ВАЖНО: корректный адрес — https://api.deepseek.com (с поддоменом "api").
# Адрес "https://deepseek.com" без "api." не принимает API-запросы.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# System-промпт, который автоматически подмешивается в JSON-режиме
SYSTEM_PROMPT_JSON = (
    "Ты — строгий ассистент, который отвечает ТОЛЬКО валидным JSON-объектом. "
    "Не используй markdown-разметку, код-блоки и пояснения до или после JSON. "
    "Все ключи и строковые значения заключай в двойные кавычки."
)

# Человекочитаемые пояснения к finish_reason — для лога и демонстрации на видео
FINISH_REASON_LABELS = {
    "stop": "Модель закончила ответ естественно (или остановлена stop-последовательностью).",
    "length": "Достигнут лимит max_tokens — ответ ОБРЕЗАН.",
    "content_filter": "Ответ отклонён фильтром контента.",
}


# ---------------------------------------------------------------------------
# Вспомогательные функции
# ---------------------------------------------------------------------------
def read_key_from_env_file(path=".env"):
    """Достаёт DEEPSEEK_API_KEY из файла .env (по образцу Дня 1)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" in line:
                    name, value = line.split("=", 1)
                    if name.strip() == "DEEPSEEK_API_KEY":
                        return value.strip().strip('"').strip("'")
    except OSError:
        return None
    return None


def parse_stop_sequences(raw):
    """'КРИТИКА, Конец' -> ['КРИТИКА', 'Конец'] (убираем пробелы и пустые элементы)."""
    if not raw or not raw.strip():
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def build_request_params(prompt, mode, model_name, max_tokens, temperature, seed, stop_list):
    """Собирает полный набор параметров запроса — и для вызова API, и для лога."""
    messages = []
    if mode == "Строгий JSON":
        messages.append({"role": "system", "content": SYSTEM_PROMPT_JSON})
    messages.append({"role": "user", "content": prompt})

    params = {
        "model": model_name,
        "messages": messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if seed is not None:
        params["seed"] = seed
    if stop_list:
        params["stop"] = stop_list
    if mode == "Строгий JSON":
        params["response_format"] = {"type": "json_object"}
    return params


# ---------------------------------------------------------------------------
# Оформление страницы
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="День 2 · Формат ответа",
    page_icon="🎛️",
    layout="wide",
    initial_sidebar_state="expanded",
)

CUSTOM_CSS = """
<style>
    .block-container {padding-top: 2.2rem;}
    .card {
        border: 1px solid rgba(128,128,128,0.25);
        border-radius: 14px;
        padding: 1.1rem 1.3rem;
        background: linear-gradient(145deg, rgba(255,255,255,0.04), rgba(255,255,255,0.01));
        margin-bottom: 0.6rem;
    }
    .tag {
        display: inline-block;
        padding: 0.15rem 0.6rem;
        border-radius: 999px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-right: 0.35rem;
    }
    .tag-green  {background: rgba(46,204,113,0.16); color: #2ecc71;}
    .tag-red    {background: rgba(231,76,60,0.16);  color: #e74c3c;}
    .tag-blue   {background: rgba(52,152,219,0.16); color: #3498db;}
    .tag-orange {background: rgba(243,156,18,0.16); color: #f39c12;}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Шапка приложения
# ---------------------------------------------------------------------------
st.title(APP_TITLE)
st.caption(APP_SUBTITLE)

with st.expander("🧠 Что настраиваем в этом дне?", expanded=False):
    st.markdown(
        """
        **Один и тот же запрос** отправляется в модель с разными параметрами API:

        - **🌡️ Температура (`temperature`)** — управляет *случайностью* выбора токенов.
          `0.0` — максимальный детерминизм (почти одинаковый ответ), `2.0` — максимальная фантазия.
        - **📏 `max_tokens`** — «потолок» длины ответа в токенах. Если модель упёрлась в лимит,
          API вернёт `finish_reason = "length"`, и ответ будет обрезан.
        - **🛑 `stop` (stop sequences)** — список строк: как только модель начинает печатать одну из них,
          генерация немедленно останавливается.
        - **🧾 Режим JSON** — добавляется `system`-промпт и параметр
          `response_format={"type": "json_object"}`, чтобы ответ был валидным JSON.
        - **🎲 Seed** — целое число, которое «замораживает» генерацию: одинаковые
          `seed` + `temperature` + промпт дают ответ **символ в символ** (обход GPU-джиттера).
        """
    )


# ---------------------------------------------------------------------------
# Боковая панель: управляемые настройки запроса
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🎛️ Настройки запроса")
    st.caption("Все настройки применяются к одному и тому же запросу.")

    env_key = os.getenv("DEEPSEEK_API_KEY") or read_key_from_env_file() or ""
    api_key = st.text_input(
        "🔑 API-ключ DeepSeek",
        type="password",
        value=env_key,
        help="Введите ключ здесь — либо задайте переменную окружения DEEPSEEK_API_KEY "
             "или файл .env рядом с приложением.",
    )

    model_name = st.selectbox(
        "🤖 Модель",
        options=["deepseek-chat", "deepseek-reasoner"],
        index=0,
        help="deepseek-chat — основная чат-модель DeepSeek (рекомендуется для этого демо). "
             "deepseek-reasoner может игнорировать temperature и response_format.",
    )

    mode = st.selectbox(
        "🧾 Режим ответа",
        options=["Обычный текст", "Строгий JSON"],
        help="В режиме «Строгий JSON» автоматически добавляются system-промпт "
             "и параметр response_format={'type': 'json_object'}.",
    )

    max_tokens = st.slider(
        "📏 Ограничение длины (max_tokens)",
        min_value=10,
        max_value=3000,
        value=500,
        step=10,
        help="Максимум токенов в ответе. Маленькое значение наглядно показывает finish_reason='length'.",
    )

    temperature = st.slider(
        "🌡️ Температура (детерминизм)",
        min_value=0.0,
        max_value=2.0,
        value=0.7,
        step=0.1,
        help="0.0 — максимальный детерминизм (один и тот же ответ почти всегда), "
             "выше 1.0 — больше креативности и случайности.",
    )
    st.caption("ℹ️ **0.0** — максимальный детерминизм · **2.0** — максимальная фантазия")

    use_seed = st.checkbox(
        "🎲 Фиксировать Seed (100% детерминизм)",
        value=True,
        help="Передаёт параметр seed в API: при одинаковых seed, temperature и промпте "
             "DeepSeek возвращает ответ символ в символ (обход GPU-джиттера).",
    )
    seed_value = st.number_input(
        "Значение Seed",
        value=42,
        step=1,
        min_value=0,
        disabled=not use_seed,
        help="Целое число, с которым модель детерминируется. "
             "Поле отключено, если чекбокс выше выключен.",
    )

    stop_raw = st.text_input(
        "🛑 Stop-последовательности",
        placeholder="КРИТИКА, Конец",
        help="Слова через запятую. Генерация остановится, как только модель начнёт "
             "печатать одно из этих слов.",
    )
    if stop_raw.strip():
        st.caption(f"⚙️ В `stop` уйдёт список: `{parse_stop_sequences(stop_raw)}`")

    run = st.button("🚀 Запустить запрос", type="primary", use_container_width=True)

# ---------------------------------------------------------------------------
# Основная область: ввод запроса
# ---------------------------------------------------------------------------
prompt = st.text_area(
    "✍️ Ваш запрос (User Prompt)",
    value="Придумай 3 идеи для мобильного приложения под Android для отслеживания привычек.",
    height=130,
    help="Этот текст — одинаковый при любых настройках — отправляется модели.",
)

stop_list = parse_stop_sequences(stop_raw)

# ---------------------------------------------------------------------------
# Кнопка «Запустить запрос»: один и тот же запрос + выбранные настройки
# ---------------------------------------------------------------------------
if run:
    if not prompt.strip():
        st.error("❌ Поле запроса пустое. Введите текст и повторите запуск.")
    elif not api_key:
        st.error(
            "❌ API-ключ не найден.\n\n"
            "Укажите его в поле **«🔑 API-ключ DeepSeek»** в боковой панели, "
            "либо задайте переменную окружения `DEEPSEEK_API_KEY` или файл `.env`."
        )
    else:
        params = build_request_params(
            prompt=prompt,
            mode=mode,
            model_name=model_name,
            max_tokens=max_tokens,
            temperature=temperature,
            seed=seed_value if use_seed else None,
            stop_list=stop_list,
        )

        with st.spinner("⏳ Модель генерирует ответ..."):
            try:
                client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

                started = time.monotonic()
                response = client.chat.completions.create(**params)
                elapsed = round(time.monotonic() - started, 2)

                content = response.choices[0].message.content or ""
                finish_reason = response.choices[0].finish_reason
                usage = response.usage

                usage_dict = {}
                if usage is not None:
                    usage_dict = {
                        "prompt_tokens": usage.prompt_tokens,
                        "completion_tokens": usage.completion_tokens,
                        "total_tokens": usage.total_tokens,
                    }

                st.session_state["result"] = {
                    "content": content,
                    "finish_reason": finish_reason,
                    "elapsed_sec": elapsed,
                    "usage": usage_dict,
                    "params": params,
                    "mode": mode,
                }
            except Exception as error:
                st.session_state.pop("result", None)
                st.error(f"❌ Ошибка при обращении к DeepSeek API:\n\n`{error}`")

# ---------------------------------------------------------------------------
# Вкладки: «Результат генерации» и «Технический лог запроса»
# ---------------------------------------------------------------------------
tab_result, tab_log = st.tabs(["📝 Результат генерации", "🔧 Технический лог запроса"])

result = st.session_state.get("result")

with tab_result:
    if result is None:
        st.info("👈 Выберите настройки в боковой панели и нажмите **«🚀 Запустить запрос»**, "
                "чтобы увидеть результат генерации.")
    else:
        content = result["content"]
        finish_reason = result["finish_reason"]

        tag_class = {
            "stop": "tag-green",
            "length": "tag-red",
        }.get(finish_reason, "tag-orange")
        st.markdown(
            f'<span class="tag {tag_class}">finish_reason = {finish_reason}</span>'
            f'<span class="tag tag-blue">{result["usage"].get("total_tokens", "?")} ток.</span>'
            f'<span class="tag tag-blue">{result["elapsed_sec"]} сек</span>',
            unsafe_allow_html=True,
        )
        st.caption(FINISH_REASON_LABELS.get(finish_reason, "Неизвестный статус завершения."))

        m1, m2, m3, m4 = st.columns(4)
        m1.metric("🌡️ Температура", result["params"]["temperature"])
        m2.metric("📏 max_tokens", result["params"]["max_tokens"])
        m3.metric("🛑 Stop-строки", len(result["params"].get("stop", [])))
        m4.metric("🧾 Режим", "JSON" if result["mode"] == "Строгий JSON" else "Текст")

        st.markdown("### 💬 Ответ модели")
        if result["mode"] == "Строгий JSON":
            try:
                parsed = json.loads(content)
                st.json(parsed)
            except json.JSONDecodeError:
                st.warning("⚠️ Ответ не удалось распарсить как JSON — показываем «сырой» текст.")
                st.code(content, language=None)
        else:
            safe_content = html.escape(content).replace("\n", "<br>")
            st.markdown(f'<div class="card">{safe_content}</div>', unsafe_allow_html=True)

        if finish_reason == "length":
            st.warning("⚠️ **Ответ обрезан**: модель упёрлась в лимит `max_tokens`. "
                       "Увеличьте «Ограничение длины» в боковой панели и повторите запрос.")

with tab_log:
    if result is None:
        st.info("Запустите запрос — здесь появится полный технический лог всех параметров, "
                "отправленных в API.")
    else:
        params = result["params"]
        request_log = {
            "endpoint": {
                "base_url": DEEPSEEK_BASE_URL,
                "method": "POST /chat/completions",
            },
            "request": {
                "model": params["model"],
                "messages": params["messages"],
                "max_tokens": params["max_tokens"],
                "temperature": params["temperature"],
                "seed": params.get("seed", None),
                "stop": params.get("stop", []),
                "response_format": params.get("response_format", None),
            },
            "response_meta": {
                "finish_reason": result["finish_reason"],
                "finish_reason_meaning": FINISH_REASON_LABELS.get(result["finish_reason"]),
                "elapsed_sec": result["elapsed_sec"],
                "usage": result["usage"],
            },
        }

        st.markdown("### 📨 Что именно ушло в API")
        st.json(request_log)

        with st.expander("📋 JSON для копирования (удобно для видео и документации)"):
            st.code(json.dumps(request_log, ensure_ascii=False, indent=2), language="json")

        with st.expander("🧭 Как параметры влияют на ответ"):
            st.markdown(
                f"""
                | Параметр | Отправленное значение | Что делает |
                |---|---|---|
                | `temperature` | `{params["temperature"]}` | Чем ближе к `0.0`, тем **детерминированнее** ответ. |
                | `seed` | `{params.get("seed") or "— (не передан)"}` | Фиксирует генерацию: одинаковые seed + temperature + промпт → один и тот же ответ. |
                | `max_tokens` | `{params["max_tokens"]}` | Потолок длины. При достижении — `finish_reason = "length"`. |
                | `stop` | `{params.get("stop") or "— (не передан)"}` | Останавливает генерацию при начале совпадения. |
                | `response_format` | `{params.get("response_format") or "— (не передан)"}` | JSON-режим (включается при выборе «Строгий JSON»). |
                """
            )
