"""
============================================================
 День 5 AI-челленджа: «Сравнение трёх моделей Hugging Face»
 Один запрос → три модели разного размера (2B / 8B / 72B)
 через Hugging Face Inference API (OpenAI-совместимый эндпоинт)
============================================================

Стек: Streamlit + официальный OpenAI SDK.

Что делает приложение:
  - отправляет один и тот же запрос последовательно трём моделям;
  - для каждой модели замеряет время ответа, токены (вход/выход/всего) и
    показывает стоимость (Inference API цену не возвращает → «бесплатно»);
  - считает эвристическую оценку качества ответа 0–10 и показывает
    сравнительную таблицу;
  - умеет сохранять отчёт эксперимента в day5/results.md.

Запуск (из папки day5):
    pip install -r requirements.txt
    streamlit run app.py
"""

import html
import os
import re
import time
from datetime import date
from pathlib import Path

import streamlit as st
from openai import OpenAI

# ---------------------------------------------------------------------------
# Константы и конфигурация эксперимента
# ---------------------------------------------------------------------------

APP_TITLE = "⚖️ День 5 · Сравнение трёх моделей Hugging Face"
APP_SUBTITLE = (
    "Один и тот же запрос отправляется в модели разного размера "
    "(2B / 8B / 72B) — сравниваем время, токены, стоимость и качество ответа."
)

APP_DIR = Path(__file__).resolve().parent
RESULTS_PATH = APP_DIR / "results.md"
ENV_FILE = APP_DIR / ".env"

# OpenAI-совместимый эндпоинт Hugging Face Inference API (чат-модели).
HF_BASE_URL = "https://api-inference.huggingface.co/v1"
HF_TOKEN_ENV = "HF_TOKEN"

# Набор моделей эксперимента. Порядок вставки = порядок опроса и таблицы:
# слабая → средняя → сильная.
MODELS = {
    "слабая": {"model_id": "google/gemma-2-2b-it", "size": "2B"},
    "средняя": {"model_id": "meta-llama/Llama-3.1-8B-Instruct", "size": "8B"},
    "сильная": {"model_id": "Qwen/Qwen2.5-72B-Instruct", "size": "72B"},
}

DEFAULT_PROMPT = (
    "Объясни, что такое RAG-система простыми словами, с примерами. "
    "Ответ должен быть не длиннее 5 предложений."
)

# Ограничение числа предложений из промпта по умолчанию — используется
# эвристической оценкой качества.
SENTENCE_LIMIT = 5

FINISH_REASON_LABELS = {
    "stop": "Модель закончила ответ естественно.",
    "length": "Ответ обрезан лимитом длины токенов.",
    "content_filter": "Ответ отклонён фильтром контента.",
}

# Практические рекомендации для отчёта results.md: какая роль — под какие
# задачи. Текст статичен (см. design.md, D8).
RECOMMENDATIONS = {
    "слабая": (
        "`google/gemma-2-2b-it` (2B) лучше всего подходит для прототипов и "
        "быстрых экспериментов: задач, где важны скорость, бесплатность и "
        "низкая сложность ответа (короткие FAQ, классификация, извлечение "
        "простых фактов), а качество можно проверить глазами."
    ),
    "средняя": (
        "`meta-llama/Llama-3.1-8B-Instruct` (8B) — сбалансированный выбор для "
        "продакшена: стабильные ответы среднего качества без долгого ожидания "
        "(ассистенты, суммаризация, генерация кода средней сложности), когда "
        "топ-модель избыточна."
    ),
    "сильная": (
        "`Qwen/Qwen2.5-72B-Instruct` (72B) лучше всего подходит для сложных "
        "рассуждений: многошаговая логика, глубокий анализ, сложные "
        "инструкции и задачи высокого качества, где готовы ждать дольше."
    ),
}

# Человекочитаемая подпись про стоимость для карточек/таблицы.
FREE_COST_TEXT = "бесплатно (биллинг Inference API отсутствует)"


# ---------------------------------------------------------------------------
# Чистые функции: ключ, метрики, оценка качества (не зависят от Streamlit)
# ---------------------------------------------------------------------------


def _read_env_file_token(path: Path):
    """Читает HF_TOKEN из .env-файла простым парсером (без python-dotenv)."""
    if not Path(path).exists():
        return None
    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip().upper() == HF_TOKEN_ENV:
            return value.strip().strip('"').strip("'")
    return None


def resolve_token():
    """Ключ Hugging Face: day5/.env → переменная окружения HF_TOKEN → None.

    Возвращает строку ключа или None, если ключ нигде не задан.
    """
    token = _read_env_file_token(ENV_FILE)
    if not token:
        token = os.environ.get(HF_TOKEN_ENV, "").strip()
    return token or None


def count_sentences(text: str) -> int:
    """Грубое число предложений в тексте (эвристика, без nltk).

    Граница предложения — точка/восклицательный/вопросительный знак (включая
    «…»), после которого идёт пробел или конец текста. Сокращения вида «т.е.»
    могут посчитаться за два предложения — для оценки качества это допустимо.
    """
    if not text or not text.strip():
        return 0
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    return sum(1 for part in parts if part.strip())


def format_duration(elapsed_sec):
    """Секунды → строка вида «1.23», при отсутствии значения — «—»."""
    if elapsed_sec is None:
        return "—"
    return f"{elapsed_sec:.2f}"


def _usage_get(usage, attr):
    """Достаёт поле из usage: объекта (openai) или dict."""
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage.get(attr)
    return getattr(usage, attr, None)


def tokens_from_usage(usage):
    """Токены из usage: {'input', 'output', 'total'}.

    Отсутствующие значения → None (провайдер не вернул состав токенов).
    Если total не передан, но есть input+output — считаем сумму.
    """
    prompt = _usage_get(usage, "prompt_tokens")
    completion = _usage_get(usage, "completion_tokens")
    total = _usage_get(usage, "total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    return {"input": prompt, "output": completion, "total": total}


def _tokens_cell(tokens):
    """Токены → ячейка таблицы: «12 / 45 / 57» или «недоступно»."""
    tokens = tokens or {}
    values = [tokens.get("input"), tokens.get("output"), tokens.get("total")]
    if all(v is None for v in values):
        return "недоступно"
    return " / ".join("—" if v is None else str(v) for v in values)


def format_cost(usage=None, model_id=""):
    """Стоимость ответа: цена провайдера (если вернул) или «бесплатно».

    Стандарт OpenAI-совместимого API цену в ответе не отдаёт, а тариф
    Inference API не биллингует за токены — поэтому по умолчанию «бесплатно».
    Если в usage всё же пришло поле price/cost, показываем его.
    """
    price = None
    if usage is not None:
        price = _usage_get(usage, "price")
        if price is None:
            price = _usage_get(usage, "cost")
    if price is not None:
        try:
            return f"≈ ${float(price):.6f}"
        except (TypeError, ValueError):
            return f"≈ {price}"
    return FREE_COST_TEXT


def quality_assessment(text, finish_reason, sentence_limit=SENTENCE_LIMIT):
    """Эвристическая оценка ответа по шкале 0–10.

    Прозрачный рубрикатор (design.md, D6):
      - лимит предложений (≤ sentence_limit) — до 4 баллов, −1 за каждое
        лишнее предложение;
      - раскрытие темы RAG (расшифровка, поиск/извлечение, генерация,
        контекст/база знаний) — до 3 баллов (по 1 за найденную группу);
      - наличие примера — до 2 баллов;
      - полнота завершения (finish_reason == "stop") — 1 балл.

    Возвращает dict {"score": int, "reasons": [str]} — обоснование для UI и
    отчёта. Оценка — грубый эвристический фильтр, не «мнение» LLM.
    """
    if not text or not text.strip():
        return {"score": 0, "reasons": ["Пустой ответ модели (0 баллов)."]}

    score = 0
    reasons = []

    # 1. Соблюдение лимита предложений (до 4 баллов).
    sentences = count_sentences(text)
    if sentences <= sentence_limit:
        score += 4
        reasons.append(
            f"Соблюдён лимит: {sentences} из ≤{sentence_limit} предложений (+4)."
        )
    else:
        over = sentences - sentence_limit
        earned = max(0, 4 - over)
        score += earned
        reasons.append(
            f"Лимит превышен на {over}: {sentences} предложений вместо "
            f"≤{sentence_limit} (получено {earned}/4)."
        )

    # 2. Раскрытие темы RAG (до 3 баллов, по 1 за группу понятий).
    lowered = text.lower()
    concept_groups = [
        ("расшифровка «Retrieval-Augmented Generation»",
         ["retrieval-augmented generation", "retrieval augmented generation"]),
        ("термин поиска/извлечения",
         ["поиск", "извлеч", "retriev"]),
        ("термин генерации",
         ["генерац", "generation", "генеративн"]),
        ("контекст/источник/база знаний",
         ["контекст", "база знаний", "базой знаний", "knowledge",
          "документ", "источник"]),
    ]
    matched = 0
    for label, keys in concept_groups:
        if matched >= 3:
            break
        if any(key in lowered for key in keys):
            matched += 1
            reasons.append(f"Раскрыта тема: {label} (+1).")
    score += matched

    # 3. Наличие примера (до 2 баллов).
    example_markers = ["например", "к примеру", "напр.", "пример:"]
    if any(marker in lowered for marker in example_markers):
        score += 2
        reasons.append("Присутствует пример (+2).")

    # 4. Полнота завершения (1 балл за finish_reason = "stop").
    if finish_reason == "stop":
        score += 1
        reasons.append("Ответ завершён полностью, finish_reason=stop (+1).")
    elif finish_reason == "length":
        reasons.append("Ответ обрезан лимитом токенов (finish_reason=length).")
    else:
        reasons.append(f"Необычный статус завершения: {finish_reason!r}.")

    return {"score": min(score, 10), "reasons": reasons}


def _ok_models(results):
    """Успешные записи сравнения."""
    return [rec for rec in results if rec.get("status") == "ok"]


def _table_row(rec):
    """Одна строка markdown-таблицы по записи сравнения."""
    status = rec.get("status")
    role = rec.get("role", "—")
    model_id = rec.get("model_id", "—")
    if status == "ok":
        time_cell = format_duration(rec.get("elapsed_sec"))
        tokens_cell = _tokens_cell(rec.get("tokens"))
        cost = rec.get("cost") or FREE_COST_TEXT
        quality = rec.get("quality") or {}
        quality_cell = (
            f"{quality.get('score', '—')}/10"
            if quality.get("score") is not None
            else "—"
        )
        status_cell = "✅ успех"
    else:
        time_cell = "—"
        tokens_cell = "—"
        cost = "—"
        quality_cell = "—"
        status_cell = "❌ ошибка"
    return (
        f"| {role} | `{model_id}` | {time_cell} | {tokens_cell} "
        f"| {cost} | {quality_cell} | {status_cell} |"
    )


def build_table_markdown(results):
    """Сводная сравнительная таблица в markdown (для UI и отчёта)."""
    lines = [
        "| Роль | Модель | Время, с | Токены (вх / вых / всего) | Стоимость | Качество | Статус |",
        "|---|---|---|---|---|---|---|",
    ]
    lines.extend(_table_row(rec) for rec in results)
    return "\n".join(lines)


def _observations(results):
    """Короткие наблюдения по прогону для раздела выводов отчёта."""
    ok = _ok_models(results)
    notes = []
    if not ok:
        notes.append(
            "Все три модели завершились ошибкой — сравнить метрики в этом "
            "прогоне не удалось, проверьте ключ HF_TOKEN и доступ к моделям."
        )
        return notes
    fastest = min(ok, key=lambda rec: rec.get("elapsed_sec") or float("inf"))
    notes.append(
        f"Быстрее всего ответила модель «{fastest['role']}» "
        f"(`{fastest['model_id']}`, {format_duration(fastest.get('elapsed_sec'))} с)."
    )
    tokenized = [rec for rec in ok if (rec.get("tokens") or {}).get("total")]
    if tokenized:
        longest = max(tokenized, key=lambda rec: rec["tokens"]["total"])
        notes.append(
            f"Самый длинный ответ (по токенам) — у модели «{longest['role']}» "
            f"(`{longest['model_id']}`, {longest['tokens']['total']} ток.) — "
            "это ожидаемо для больших моделей и не всегда означает лучшее качество."
        )
    scored = [rec for rec in ok if (rec.get("quality") or {}).get("score") is not None]
    if scored:
        best = max(scored, key=lambda rec: rec["quality"]["score"])
        notes.append(
            f"Высшая эвристическая оценка качества — у модели «{best['role']}» "
            f"(`{best['model_id']}`, {best['quality']['score']}/10). "
            "Помните: это грубый автоматический фильтр, финальное суждение — "
            "за человеком."
        )
    return notes


def _md_quote(text):
    """Текст ответа → блок-цитата markdown (переносы строк сохраняются)."""
    return "\n".join(f"> {line}" for line in (text or "").splitlines())


def build_report_text(prompt, results, models=None):
    """Markdown-отчёт эксперимента (для day5/results.md).

    Чистая функция: не зависит от Streamlit, её можно вызывать из консоли.
    """
    models = models or MODELS
    lines = []
    lines.append("# 🔬 День 5. Сравнение моделей Hugging Face")
    lines.append("")
    lines.append(
        f"_Эксперимент выполнен: {date.today().isoformat()}. По одному прогону "
        "на модель; время включает «холодный старт» серверного инференса HF._"
    )
    lines.append("")
    lines.append("## Участники эксперимента")
    lines.append("")
    lines.append("| Роль | Модель | Размер |")
    lines.append("|---|---|---|")
    for role, cfg in models.items():
        lines.append(f"| {role} | `{cfg['model_id']}` | {cfg['size']} |")
    lines.append("")

    lines.append("## Запрос")
    lines.append("")
    lines.append(_md_quote(prompt))
    lines.append("")

    lines.append("## Ответы и метрики")
    lines.append("")
    for rec in results:
        role = rec.get("role", "—")
        model_id = rec.get("model_id", "—")
        size = rec.get("size", "")
        lines.append(f"### 🏷️ {role} · `{model_id}` ({size})")
        lines.append("")
        if rec.get("status") != "ok":
            lines.append("**Статус:** ❌ ошибка")
            lines.append("")
            lines.append(f"_{rec.get('error_message', 'Неизвестная ошибка.')}_")
            lines.append("")
            continue
        tokens = rec.get("tokens") or {}
        lines.append(f"- **Время ответа:** {format_duration(rec.get('elapsed_sec'))} с")
        lines.append(
            "- **Токены:** вход {inp} / выход {out} / всего {total}".format(
                inp=tokens.get("input", "—"),
                out=tokens.get("output", "—"),
                total=tokens.get("total", "—"),
            )
        )
        lines.append(f"- **Стоимость:** {rec.get('cost') or FREE_COST_TEXT}")
        lines.append(f"- **finish_reason:** `{rec.get('finish_reason')}`")
        quality = rec.get("quality") or {}
        if quality.get("score") is not None:
            lines.append(f"- **Оценка качества (эвристика):** {quality['score']}/10")
            for reason in quality.get("reasons", []):
                lines.append(f"  - {reason}")
        lines.append("")
        lines.append("**Ответ модели:**")
        lines.append("")
        lines.append(_md_quote(rec.get("content") or ""))
        lines.append("")

    lines.append("## 📊 Сравнительная таблица")
    lines.append("")
    lines.append(build_table_markdown(results))
    lines.append("")

    lines.append("## 📝 Выводы и практические рекомендации")
    lines.append("")
    for role in models:
        lines.append(f"- **{role.capitalize()}:** {RECOMMENDATIONS[role]}")
    lines.append("")
    notes = _observations(results)
    for note in notes:
        lines.append(f"- {note}")
    lines.append("")
    lines.append("> Как выбирать модель под задачу: прототип и быстрые "
                 "эксперименты → слабая модель; продакшен с балансом "
                 "качество/скорость → средняя; сложные рассуждения и "
                 "максимальное качество → сильная. Решение принимайте по "
                 "метрикам таблицы и качеству ответа на ваших данных.")
    lines.append("")
    lines.append("---")
    lines.append("")
    lines.append("*Оценка качества 0–10 — эвристический фильтр приложения "
                 "(лимит предложений, ключевые понятия, наличие примера, "
                 "полнота завершения), а не экспертная оценка.*")
    return "\n".join(lines)


def save_report(prompt, results, path=None):
    """Записывает markdown-отчёт в файл (по умолчанию day5/results.md)."""
    target = Path(path) if path else RESULTS_PATH
    target.write_text(build_report_text(prompt, results), encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# Работа с API: одиночный запрос + последовательный прогон с изоляцией ошибок
# ---------------------------------------------------------------------------


def _new_error_record(role, cfg, message):
    """Запись результата для модели, завершившейся ошибкой."""
    return {
        "role": role,
        "model_id": cfg["model_id"],
        "size": cfg.get("size", ""),
        "status": "error",
        "error_message": message,
        "content": None,
        "elapsed_sec": None,
        "finish_reason": None,
        "tokens": {"input": None, "output": None, "total": None},
        "cost": "—",
        "quality": None,
    }


def _friendly_error(exc, model_id):
    """Короткое понятное сообщение об ошибке модели (без traceback)."""
    message = (str(exc) or exc.__class__.__name__).strip().replace("\n", " ")
    if len(message) > 300:
        message = message[:300] + "…"
    lowered = message.lower()
    if "401" in message or "unauthorized" in lowered:
        hint = " Неверный ключ HF_TOKEN или нет доступа к модели."
        return f"`{model_id}`: {message}{hint}"
    if "403" in message or "forbidden" in lowered or "gated" in lowered:
        hint = (" Модель gated: откройте доступ на странице модели в Hugging "
                "Face (Agree and access repository).")
        return f"`{model_id}`: {message}{hint}"
    if "429" in message or "rate limit" in lowered:
        hint = " Превышен лимит запросов бесплатного тарифа — повторите позже."
        return f"`{model_id}`: {message}{hint}"
    return f"`{model_id}`: {message}"


def query_one(client, model_cfg, prompt):
    """Один запрос к модели; возвращает запись-результат (status="ok").

    При ошибке API исключение пробрасывается наверх — изоляцией занимается
    run_comparison().
    """
    model_id = model_cfg["model_id"]
    start = time.perf_counter()
    response = client.chat.completions.create(
        model=model_id,
        messages=[{"role": "user", "content": prompt}],
    )
    elapsed_sec = time.perf_counter() - start

    choice = response.choices[0]
    content = (choice.message.content or "").strip()
    finish_reason = choice.finish_reason
    usage = response.usage
    tokens = tokens_from_usage(usage)

    return {
        "status": "ok",
        "content": content,
        "elapsed_sec": elapsed_sec,
        "finish_reason": finish_reason,
        "tokens": tokens,
        "cost": format_cost(usage, model_id),
        "quality": quality_assessment(content, finish_reason),
    }


def run_comparison(client, models, prompt, progress_cb=None):
    """Последовательно опрашивает все модели; ошибка одной не мешает другим.

    progress_cb(done, total, role, model_id) вызывается перед запросом к
    каждой модели (для прогресс-бара в UI).
    """
    results = []
    keys = list(models)
    total = len(keys)
    for index, role in enumerate(keys, start=1):
        cfg = models[role]
        if progress_cb is not None:
            progress_cb(index, total, role, cfg["model_id"])
        try:
            record = query_one(client, cfg, prompt)
        except Exception as exc:  # noqa: BLE001 — изоляция ошибок моделей
            record = _new_error_record(role, cfg, _friendly_error(exc, cfg["model_id"]))
        else:
            record.update(
                {"role": role, "model_id": cfg["model_id"], "size": cfg.get("size", "")}
            )
        results.append(record)
    return results


# ---------------------------------------------------------------------------
# Streamlit UI: отрисовка результатов
# ---------------------------------------------------------------------------

ANSWER_CARD_HTML = (
    '<div style="border:1px solid rgba(128,128,128,0.3); border-radius:12px; '
    'padding:0.9rem 1.1rem; margin:0.3rem 0; '
    'background:rgba(128,128,128,0.07);">{content}</div>'
)


def _render_model_card(rec):
    """Карточка одной модели: метрики, ответ (безопасный вывод), оценка."""
    role = rec.get("role", "—")
    model_id = rec.get("model_id", "—")
    size = rec.get("size", "")
    title = f"🏷️ {role} · `{model_id}` ({size})"
    if rec.get("status") != "ok":
        with st.expander(f"❌ {title}", expanded=True):
            st.error(f"Модель не ответила: {rec.get('error_message', 'неизвестная ошибка')}")
        return

    with st.expander(f"✅ {title}", expanded=True):
        tokens = rec.get("tokens") or {}
        col_time, col_tokens, col_cost, col_end = st.columns(4)
        col_time.metric("⏱️ Время", f"{format_duration(rec.get('elapsed_sec'))} с")
        col_tokens.metric("🔢 Токены (вх/вых/всего)", _tokens_cell(tokens))
        col_cost.metric("💰 Стоимость", rec.get("cost") or FREE_COST_TEXT)
        col_end.metric("🏁 finish_reason", rec.get("finish_reason") or "—")
        st.caption(FINISH_REASON_LABELS.get(rec.get("finish_reason"), ""))

        st.markdown("**💬 Ответ модели:**")
        safe_content = html.escape(rec.get("content") or "").replace("\n", "<br>")
        st.markdown(ANSWER_CARD_HTML.format(content=safe_content), unsafe_allow_html=True)

        if rec.get("finish_reason") == "length":
            st.warning("⚠️ Ответ обрезан лимитом токенов модели.")

        quality = rec.get("quality") or {}
        if quality.get("score") is not None:
            with st.expander(f"🧮 Оценка качества: {quality['score']}/10 — почему"):
                for reason in quality.get("reasons", []):
                    st.markdown(f"- {reason}")
                st.caption("Эвристический фильтр по тексту; финальное суждение — за человеком.")


def _render_results(results):
    """Карточки всех моделей (в порядке прогона)."""
    for rec in results:
        _render_model_card(rec)


def _render_save_section(results, prompt_text):
    """Кнопка сохранения отчёта в day5/results.md."""
    st.markdown("### 💾 Отчёт эксперимента")
    if st.button("Сохранить отчёт в results.md", type="secondary"):
        try:
            path = save_report(prompt_text, results)
        except OSError as exc:
            st.error(f"Не удалось записать файл: {exc}")
        else:
            st.success(f"Отчёт сохранён: `{path}`")
    st.caption(
        "Файл `day5/results.md` создаётся/перезаписывается рядом с `app.py`. "
        "После этого его можно закоммитить как результат эксперимента."
    )


def _run_and_store(token, prompt):
    """Создаёт клиент HF, выполняет сравнение и кладёт результат в session_state."""
    progress = st.progress(0.0, text="Подготовка…")

    def _update_progress(done, total, role, model_id):
        progress.progress(done / total, text=f"Опрашиваю «{role}» — `{model_id}`…")

    # Таймаут 300 с: серверный инференс 72B может долго «прогреваться».
    client = OpenAI(base_url=HF_BASE_URL, api_key=token, timeout=300)
    results = run_comparison(client, MODELS, prompt, progress_cb=_update_progress)
    progress.progress(1.0, text="Готово")

    st.session_state["day5_results"] = results
    st.session_state["day5_last_prompt"] = prompt

    ok_count = sum(1 for rec in results if rec.get("status") == "ok")
    if ok_count == len(results):
        st.success("✅ Все три модели ответили.")
    elif ok_count:
        st.warning(
            f"Сравнение завершено: ответили {ok_count} из {len(results)} "
            "моделей, остальные — с ошибкой (см. карточки ниже)."
        )
    else:
        st.error("Ни одна модель не ответила — причины в карточках ниже.")


def main():
    """Главная функция приложения (вызывается Streamlit при каждом rerun)."""
    st.set_page_config(
        page_title="День 5 · Сравнение трёх моделей Hugging Face",
        page_icon="⚖️",
        layout="wide",
    )

    st.title(APP_TITLE)
    st.caption(APP_SUBTITLE)

    with st.expander("🧭 Что и зачем мы сравниваем"):
        st.markdown(
            "Это исследовательский день: **один и тот же запрос** отправляется в "
            "три модели разного размера через Hugging Face Inference API "
            "(OpenAI-совместимый эндпоинт). Модели отвечают по очереди, "
            "приложение замеряет метрики:"
        )
        st.markdown("- ⏱️ **время ответа** (включает «холодный старт» серверного инференса);")
        st.markdown("- 🔢 **токены**: входные / выходные / всего (если провайдер вернул usage);")
        st.markdown("- 💰 **стоимость**: тариф Inference API не биллингует — «бесплатно»;")
        st.markdown("- 🧮 **оценку качества** 0–10 — эвристический фильтр по тексту ответа.")
        st.markdown("Участники эксперимента:")
        st.markdown(
            "| Роль | Модель | Размер |\n|---|---|---|\n"
            + "\n".join(
                f"| {role} | `{cfg['model_id']}` | {cfg['size']} |"
                for role, cfg in MODELS.items()
            )
        )
        st.caption(
            "Оценка качества — грубый автоматический фильтр (лимит предложений, "
            "ключевые понятия, пример, полнота завершения); окончательный вывод "
            "о качестве делает человек."
        )

    with st.sidebar:
        st.markdown("### 🔑 Ключ Hugging Face")
        auto_token = resolve_token()
        if auto_token:
            st.success("Ключ найден: `day5/.env` или переменная окружения `HF_TOKEN`.")
        else:
            st.info("Ключ не найден: задайте `HF_TOKEN` в `.env`/окружении или введите ниже.")
        manual_token = st.text_input(
            "HF_TOKEN (ручной ввод)", type="password", key="manual_hf_token"
        )
        st.caption("Порядок: `day5/.env` → переменная окружения → ручной ввод.")

    prompt = st.text_area(
        "✍️ Запрос (одинаковый для всех трёх моделей)",
        value=DEFAULT_PROMPT,
        height=130,
    )

    if st.button("🚀 Сравнить модели", type="primary", use_container_width=True):
        token = (auto_token or "").strip() or (manual_token or "").strip()
        if not token:
            st.warning(
                "⚠️ Ключ `HF_TOKEN` не задан. Добавьте его в `day5/.env`, "
                "в переменную окружения или введите вручную в боковой панели."
            )
        else:
            _run_and_store(token, prompt)

    results = st.session_state.get("day5_results")
    if not results:
        st.info("👆 Нажмите «Сравнить модели» — здесь появятся ответы, метрики и таблица.")
        return

    st.markdown("---")
    st.markdown("## 📊 Результаты сравнения")
    _render_results(results)

    st.markdown("### 📋 Сравнительная таблица")
    st.markdown(build_table_markdown(results))
    st.caption(
        "Время включает «холодный старт» серверного инференса; повторный "
        "«тёплый» прогон обычно быстрее. «недоступно» в токенах — провайдер "
        "не вернул usage."
    )

    st.markdown("---")
    _render_save_section(results, st.session_state.get("day5_last_prompt", prompt))


if __name__ == "__main__":
    # Streamlit исполняет скрипт как __main__ (см. script_runner),
    # а при обычном импорте (python -c, тесты чистой логики) UI не запускается.
    main()







