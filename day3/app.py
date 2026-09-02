"""
============================================================
 День 3 AI-челленджа: «Разные способы рассуждения ИИ»
 Прямой ответ · Пошаговое решение · Мета-промпт · Консилиум экспертов
 через DeepSeek API (клиент OpenAI SDK)
============================================================

Стек: Streamlit + официальный OpenAI SDK (клиент DeepSeek).

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
APP_TITLE = "🧠 День 3 · Способы рассуждения ИИ"
APP_SUBTITLE = (
    "Одна и та же задача решается четырьмя разными «стратегиями мышления»: "
    "Прямой ответ · Пошаговое решение · Мета-промпт · Консилиум экспертов"
)

# Официальный endpoint DeepSeek (синтаксис полностью совместим с OpenAI SDK).
# ВАЖНО: корректный адрес — https://api.deepseek.com (с поддоменом "api").
# Адрес "https://deepseek.com" без "api." не принимает API-запросы.
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# Классическая задача «куры и кролики»: на ней LLM без рассуждений часто ошибается.
DEFAULT_PROMPT = (
    "У фермера есть ферма, на ней живут куры и кролики. "
    "Всего у них 35 голов и 94 ноги. "
    "Сколько кур и сколько кроликов у фермера? Реши задачу."
)

# Варианты способов рассуждения — порядок совпадает с выпадающим списком в sidebar.
REASONING_METHODS = [
    "Прямой ответ (Zero-Shot)",
    "Пошаговое решение (Chain of Thought)",
    "Мета-промпт (Prompt-v-Prompt)",
    "Консилиум экспертов (Persona Prompting)",
]

# Способ, который обрабатывается отдельной двухэтапной логикой
META_METHOD = "Мета-промпт (Prompt-v-Prompt)"

# System-промпты для «одноэтапных» способов рассуждения
# (мета-промпт обрабатывается отдельно — он двухэтапный, см. run_meta_stage)
REASONING_SYSTEM_PROMPTS = {
    "Прямой ответ (Zero-Shot)": (
        "Ты — лаконичный ассистент. Дай только прямой, краткий ответ на задачу "
        "без лишних рассуждений и объяснений."
    ),
    "Пошаговое решение (Chain of Thought)": (
        "Ты — внимательный математик. Твоя задача — решать задачи строго пошагово, "
        "подробно расписывая логику каждого действия (Chain of Thought). "
        "Обязательно выдели финальный ответ."
    ),
    "Консилиум экспертов (Persona Prompting)": (
        "Ты — организатор консилиума экспертов. Собери группу из трех виртуальных специалистов: "
        "Математика-аналитика, Инженера-логиста и Критика. Пусть каждый из них по очереди выскажет "
        "свое решение задачи. В конце сформируй итоговый, проверенный и скорректированный ответ "
        "на основе их мнений."
    ),
}

# Короткие подсказки для каждого способа (показываются в UI и в техническом логе)
REASONING_METHOD_HINTS = {
    "Прямой ответ (Zero-Shot)": (
        "Модель отвечает сразу, без явной цепочки рассуждений, — поэтому часто ошибается "
        "на задачах вроде «куры и кролики»."
    ),
    "Пошаговое решение (Chain of Thought)": (
        "System-промпт принуждает модель рассуждать вслух: каждый шаг расписывается, "
        "в конце выделяется финальный ответ."
    ),
    "Мета-промпт (Prompt-v-Prompt)": (
        "Двухэтапная схема: Шаг А — модель сама пишет себе «идеальный» промпт для задачи; "
        "Шаг Б — этот промпт отправляется модели как финальный запрос."
    ),
    "Консилиум экспертов (Persona Prompting)": (
        "System-промпт заставляет модель поочерёдно сыграть трёх экспертов "
        "(Математик-аналитик, Инженер-логист, Критик) и собрать итоговый ответ."
    ),
}

# System-промпт, который автоматически добавляется поверх способа в JSON-режиме
SYSTEM_PROMPT_JSON = (
    "Ты — строгий ассистент, который отвечает ТОЛЬКО валидным JSON-объектом. "
    "Не используй markdown-разметку, код-блоки и пояснения до или после JSON. "
    "Все ключи и строковые значения заключай в двойные кавычки."
)

# Инструкция для скрытого «Этапа А» мета-промпта: модель пишет идеальный промпт для задачи
META_PROMPT_INSTRUCTION = (
    "Напиши идеальный, развернутый промпт для решения следующей задачи: {user_prompt}"
)

# Щедрый «потолок» токенов для Этапа А, чтобы сгенерированный промпт не обрезался
META_MAX_TOKENS = 600

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


def build_system_messages(reasoning_method, json_mode):
    """
    Собирает список system-сообщений под выбранный способ рассуждения:
    * ролевой промпт способа (если он предусмотрен для метода);
    * поверх него — промпт строгого JSON, когда включён «Строгий JSON».
    """
    system_messages = []
    method_prompt = REASONING_SYSTEM_PROMPTS.get(reasoning_method)
    if method_prompt:
        system_messages.append({"role": "system", "content": method_prompt})
    if json_mode:
        system_messages.append({"role": "system", "content": SYSTEM_PROMPT_JSON})
    return system_messages


def build_request_params(system_messages, user_content, model_name, max_tokens,
                         temperature, seed, stop_list, json_mode):
    """Собирает полный набор параметров финального запроса — и для вызова API, и для лога."""
    messages = list(system_messages) + [{"role": "user", "content": user_content}]

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
    if json_mode:
        params["response_format"] = {"type": "json_object"}
    return params


def usage_to_dict(usage):
    """Объект Usage от OpenAI SDK -> обычный dict для session_state и лога."""
    if usage is None:
        return {}
    return {
        "prompt_tokens": usage.prompt_tokens,
        "completion_tokens": usage.completion_tokens,
        "total_tokens": usage.total_tokens,
    }


def run_meta_stage(client, user_prompt, model_name, temperature, seed):
    """
    Шаг А мета-промпта: скрытый «быстрый» запрос, в котором модель пишет
    развёрнутый промпт для исходной задачи. Вернёт (промпт, meta_log) —
    промпт станет user-запросом финального (Шага Б) вызова.
    """
    instruction = META_PROMPT_INSTRUCTION.format(user_prompt=user_prompt)
    stage_params = {
        "model": model_name,
        "messages": [{"role": "user", "content": instruction}],
        "max_tokens": META_MAX_TOKENS,
        "temperature": temperature,
    }
    if seed is not None:
        stage_params["seed"] = seed

    started = time.monotonic()
    response = client.chat.completions.create(**stage_params)
    elapsed = round(time.monotonic() - started, 2)

    generated_prompt = response.choices[0].message.content or ""
    finish_reason = response.choices[0].finish_reason

    meta_log = {
        "instruction": instruction,
        "stage_params": stage_params,
        "generated_prompt": generated_prompt,
        "finish_reason": finish_reason,
        "elapsed_sec": elapsed,
        "usage": usage_to_dict(response.usage),
    }
    return generated_prompt, meta_log


# ---------------------------------------------------------------------------
# Оформление страницы
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="День 3 · Способы рассуждения ИИ",
    page_icon="🧠",
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

with st.expander("🧠 Что исследуем в этом дне?", expanded=False):
    st.markdown(
        """
        **Одна и та же задача** («куры и кролики») отправляется в модель с разными
        стратегиями рассуждения:

        - **⚡ Прямой ответ (Zero-Shot)** — без цепочки рассуждений: модель «выстреливает»
          первое, что придёт в голову, поэтому на таких задачах часто ошибается.
        - **🧮 Пошаговое решение (Chain of Thought)** — system-промпт заставляет модель
          подробно расписывать каждый шаг и в конце выделять финальный ответ.
        - **🔁 Мета-промпт (Prompt-v-Prompt)** — двухэтапная схема: сначала модель сама
          пишет себе «идеальный» промпт для задачи, затем решает её по собственному промпту.
        - **👥 Консилиум экспертов (Persona Prompting)** — модель поочерёдно играет трёх
          специалистов (Математик-аналитик, Инженер-логист, Критик) и собирает итоговый ответ.

        **Настройки Дня 2** (`temperature`, `max_tokens`, `seed`, `stop`, JSON-режим)
        по-прежнему работают поверх выбранного способа рассуждения — их влияние удобно
        видно в техническом логе.
        """
    )


# ---------------------------------------------------------------------------
# Боковая панель: управляемые настройки запроса
# ---------------------------------------------------------------------------
with st.sidebar:
    st.header("🎛️ Настройки запроса")
    st.caption("Все настройки применяются к одной и той же задаче.")

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

    # --- НОВОЕ В ДНЕ 3: выбор способа рассуждения ---
    reasoning_method = st.selectbox(
        "🧠 Способ рассуждения",
        options=REASONING_METHODS,
        index=0,
        help="От выбора зависят system-промпт и логика вызова DeepSeek. "
             "«Мета-промпт» выполняется в два запроса к API (Шаг А + Шаг Б).",
    )
    st.caption(REASONING_METHOD_HINTS[reasoning_method])

    mode = st.selectbox(
        "🧾 Режим ответа",
        options=["Обычный текст", "Строгий JSON"],
        help="В режиме «Строгий JSON» поверх system-промпта способа добавляется инструкция "
             "отвечать только валидным JSON и параметр "
             "response_format={'type': 'json_object'}.",
    )

    max_tokens = st.slider(
        "📏 Ограничение длины (max_tokens)",
        min_value=10,
        max_value=3000,
        value=500,
        step=10,
        help="Максимум токенов в ответе. Маленькое значение наглядно показывает "
             "finish_reason='length'.",
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
        "🎲 Фиксировать Seed (детерминизм)",
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
# Основная область: ввод задачи
# ---------------------------------------------------------------------------
prompt = st.text_area(
    "✍️ Ваш запрос (User Prompt)",
    value=DEFAULT_PROMPT,
    height=130,
    help="Задача «куры и кролики» специально выбрана как классическая ловушка: "
         "без цепочки рассуждений LLM часто даёт неверный ответ.",
)

stop_list = parse_stop_sequences(stop_raw)
json_mode = mode == "Строгий JSON"

# ---------------------------------------------------------------------------
# Кнопка «Запустить запрос»: одна и та же задача + выбранный способ рассуждения
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
        try:
            client = OpenAI(api_key=api_key, base_url=DEEPSEEK_BASE_URL)

            # 1. System-сообщения: ролевой промпт способа + (опционально) JSON-инструкция
            system_messages = build_system_messages(reasoning_method, json_mode)

            # 2. Финальный user-текст: исходная задача либо промпт, сгенерированный на Этапе А
            final_user_content = prompt
            meta_log = None

            # --- Мета-промпт (двухэтапная схема: Шаг А -> Шаг Б) ---
            if reasoning_method == META_METHOD:
                with st.spinner("🧪 Этап А · ИИ пишет «идеальный» промпт для задачи..."):
                    generated_prompt, meta_log = run_meta_stage(
                        client=client,
                        user_prompt=prompt,
                        model_name=model_name,
                        temperature=temperature,
                        seed=seed_value if use_seed else None,
                    )
                if not generated_prompt.strip():
                    raise RuntimeError("Этап А мета-промпта вернул пустой ответ.")
                if meta_log["finish_reason"] == "length":
                    st.warning(
                        "⚠️ Промежуточный промпт (Этап А) обрезан лимитом токенов — "
                        "он всё равно будет использован как запрос Этапа Б."
                    )
                final_user_content = generated_prompt

            # 3. Собираем параметры финального запроса (для вызова API и технического лога)
            params = build_request_params(
                system_messages=system_messages,
                user_content=final_user_content,
                model_name=model_name,
                max_tokens=max_tokens,
                temperature=temperature,
                seed=seed_value if use_seed else None,
                stop_list=stop_list,
                json_mode=json_mode,
            )

            with st.spinner("⏳ Модель решает задачу..."):
                started = time.monotonic()
                response = client.chat.completions.create(**params)
                elapsed = round(time.monotonic() - started, 2)

            content = response.choices[0].message.content or ""
            finish_reason = response.choices[0].finish_reason

            st.session_state["result"] = {
                "content": content,
                "finish_reason": finish_reason,
                "elapsed_sec": elapsed,
                "usage": usage_to_dict(response.usage),
                "params": params,
                "reasoning_method": reasoning_method,
                "system_messages": system_messages,
                "meta_log": meta_log,
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
        st.info("👈 Выберите способ рассуждения и настройки в боковой панели, "
                "затем нажмите **«🚀 Запустить запрос»**, чтобы увидеть результат.")
    else:
        content = result["content"]
        finish_reason = result["finish_reason"]
        reasoning_method = result["reasoning_method"]

        tag_class = {
            "stop": "tag-green",
            "length": "tag-red",
        }.get(finish_reason, "tag-orange")
        st.markdown(
            f'<span class="tag {tag_class}">finish_reason = {finish_reason}</span>'
            f'<span class="tag tag-blue">🧠 {reasoning_method}</span>'
            f'<span class="tag tag-orange">{result["usage"].get("total_tokens", "?")} ток.</span>'
            f'<span class="tag tag-orange">{result["elapsed_sec"]} сек</span>',
            unsafe_allow_html=True,
        )
        st.caption(FINISH_REASON_LABELS.get(finish_reason, "Неизвестный статус завершения."))
        st.caption(REASONING_METHOD_HINTS.get(reasoning_method, ""))

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
        st.info("Запустите запрос — здесь появится полный технический лог: итоговый "
                "system_prompt, параметры запроса и промежуточные этапы.")
    else:
        params = result["params"]
        system_messages = result["system_messages"]
        reasoning_method = result["reasoning_method"]
        meta_log = result.get("meta_log")

        st.markdown("### 🧠 Способ рассуждения")
        st.markdown(f"**{reasoning_method}**")
        st.caption(REASONING_METHOD_HINTS.get(reasoning_method, ""))

        st.markdown("### ⚙️ Итоговый system_prompt, отправленный в API")
        if system_messages:
            for idx, message in enumerate(system_messages, start=1):
                st.markdown(f"**System-сообщение №{idx}:**")
                st.code(message["content"], language="text")
        else:
            st.info("System-промпт не отправлялся: в режиме «Мета-промпт» инструкции "
                    "для модели зашиты в промпт, сгенерированный на Этапе А.")

        if meta_log is not None:
            with st.expander("🧪 Мета-промпт · промежуточный этап (Шаг А)", expanded=True):
                col_left, col_right = st.columns(2)
                col_left.markdown("**Запрос к модели (Шаг А):**")
                col_left.code(meta_log["instruction"], language="text")
                col_right.markdown("**Промпт, сгенерированный моделью (уходит в Шаг Б):**")
                col_right.code(meta_log["generated_prompt"], language="text")
                st.caption(
                    f"`finish_reason = {meta_log['finish_reason']}` · "
                    f"{meta_log['elapsed_sec']} сек · "
                    f"{meta_log['usage'].get('total_tokens', '?')} ток. · "
                    f"max_tokens этапа А: {meta_log['stage_params']['max_tokens']}"
                )

        st.markdown("### 📨 Что именно ушло в финальный вызов (Шаг Б)")
        request_log = {
            "endpoint": {
                "base_url": DEEPSEEK_BASE_URL,
                "method": "POST /chat/completions",
            },
            "reasoning_method": reasoning_method,
            "request": {
                "model": params["model"],
                "system_prompt": [m["content"] for m in system_messages] if system_messages else None,
                "user_prompt": params["messages"][-1]["content"],
                "max_tokens": params["max_tokens"],
                "temperature": params["temperature"],
                "seed": params.get("seed", None),
                "stop": params.get("stop", []),
                "response_format": params.get("response_format", None),
            },
            "meta_stage": None if meta_log is None else {
                "instruction": meta_log["instruction"],
                "generated_prompt": meta_log["generated_prompt"],
                "finish_reason": meta_log["finish_reason"],
                "elapsed_sec": meta_log["elapsed_sec"],
                "usage": meta_log["usage"],
            },
            "response_meta": {
                "finish_reason": result["finish_reason"],
                "finish_reason_meaning": FINISH_REASON_LABELS.get(result["finish_reason"]),
                "elapsed_sec": result["elapsed_sec"],
                "usage": result["usage"],
            },
        }
        st.json(request_log)

        with st.expander("📋 JSON для копирования (удобно для видео и документации)"):
            st.code(json.dumps(request_log, ensure_ascii=False, indent=2), language="json")

        with st.expander("🧭 Как параметры влияют на ответ"):
            st.markdown(
                f"""
                | Параметр | Отправленное значение | Что делает |
                |---|---|---|
                | `reasoning_method` | `{reasoning_method}` | Определяет system-промпт и схему вызова (для мета-промпта — два запроса к API). |
                | `system_prompt` | см. блок «Итоговый system_prompt» | Задаёт роль и инструкцию рассуждения для модели. |
                | `temperature` | `{params["temperature"]}` | Чем ближе к `0.0`, тем **детерминированнее** ответ. |
                | `seed` | `{params.get("seed") or "— (не передан)"}` | Фиксирует генерацию: одинаковые seed + temperature + промпт → один и тот же ответ. |
                | `max_tokens` | `{params["max_tokens"]}` | Потолок длины. При достижении — `finish_reason = "length"`. |
                | `stop` | `{params.get("stop") or "— (не передан)"}` | Останавливает генерацию при начале совпадения. |
                | `response_format` | `{params.get("response_format") or "— (не передан)"}` | JSON-режим, добавляется поверх system-промпта способа при выборе «Строгий JSON». |
                """
            )
