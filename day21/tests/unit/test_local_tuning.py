"""Тесты домена настройки локальной модели (день 29): профили, строки и сводка.

Проверяется то, на чём стоит прогон: значения профилей (в том числе чтение модульных
констант, которые заполняются из окружения), правило «кто получил профиль», вердикты
строки по правилу дня 24 и ранжирование вариантов. Модель и сеть не нужны: строки
прогона — обычные словари, как их собирает служба.
"""
import pytest

from backend.core import config
from backend.domain import local_tuning, local_tuning_eval, rag_mode, rag_demo

#: Вопрос набора демо: ожидания заданы, поэтому вердикт строки проверяем целиком.
QUESTION = rag_demo.DemoQuestion(
    question="Чему равен CHARS_PER_PAGE?",
    expected_mode="rag",
    expected_sources=("day21-backend-services-document_loader.py",),
)

#: Вопрос вне корпуса: ожидание — режим «не знаю» (вторая половина набора демо).
UNKNOWN = rag_demo.DemoQuestion(question="Какая погода будет в Москве в выходные?",
                                expected_mode="dont_know")

#: Источник, который считается ожидаемым (сравнение — по буквам и цифрам).
SOURCE = {"source": "day21-backend-services-document_loader.py", "title": "",
          "section": "", "chunk_id": "c1", "score": 0.6, "vector_score": 0.6,
          "lexical_score": 0.0, "rerank_score": None}


def record(**kwargs) -> dict:
    """Запись ответа локальной модели: успешный ответ по корпусу с цитатой."""
    base = {"mode": "rag", "answer": "Корпус: CHARS_PER_PAGE равен 1800 символов.",
            "sources": [SOURCE], "quotes": [{"quote": "Корпус ..."}],
            "quotes_verified": True, "confidence": 1.0,
            "grounding": rag_mode.GROUNDED_VERDICT, "duration_ms": 1000,
            "tokens": {"prompt_tokens": 900, "completion_tokens": 40,
                       "tokens_per_second": 20.0, "load_ms": 3000}}
    base.update(kwargs)
    return base


# ---------- профили ----------
def test_tuned_profile_reads_module_constants(monkeypatch):
    """tuned берёт значения из констант модуля: правка `.env` меняет профиль целиком."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_TEMPERATURE", 0.5)
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_NUM_CTX", 6144)
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_CHAT_MAX_TOKENS", 256)

    profile = local_tuning.tuned_profile()

    assert (profile.temperature, profile.num_ctx, profile.max_tokens) == (0.5, 6144, 256)
    assert profile.system_prompt == local_tuning.LOCAL_TUNED_RAG_PROMPT
    assert profile.name == local_tuning.PROFILE_TUNED
    assert profile.label == local_tuning.PROFILE_LABELS[local_tuning.PROFILE_TUNED]


def test_baseline_profile_matches_day26():
    """baseline — поведение дня 26: температура конфига, окно Ollama, без своих ручек."""
    profile = local_tuning.baseline_profile()

    assert profile.temperature == config.DEFAULT_TEMPERATURE
    assert profile.num_ctx == local_tuning.BASELINE_NUM_CTX
    assert profile.max_tokens is None and profile.system_prompt is None


def test_create_with_model_fills_cache_key_and_title():
    """Модель варианта попадает в ключ кэша клиентов и в подпись варианта."""
    profile = local_tuning.create("tuned", model="qwen2.5-coder:14b-instruct-q3_K_M")

    assert profile.model == "qwen2.5-coder:14b-instruct-q3_K_M"
    assert profile.key == "tuned|qwen2.5-coder:14b-instruct-q3_K_M"
    assert profile.title == "tuned (qwen2.5-coder:14b-instruct-q3_K_M)"
    assert local_tuning.create("baseline").key == "baseline|*"


def test_create_unknown_profile_raises():
    """Незнакомое имя — ошибка: роутер обязан ответить 400, а не подменить профиль."""
    with pytest.raises(ValueError) as exc:
        local_tuning.create("быстрый")

    assert "быстрый" in str(exc.value) and "tuned" in str(exc.value)


def test_active_needs_local_provider_and_tuned_value(monkeypatch):
    """Профиль получает только локальный провайдер, и только при значении tuned."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_TUNED)

    assert local_tuning.active("local").name == local_tuning.PROFILE_TUNED
    assert local_tuning.active("deepseek") is None
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_BASELINE)
    assert local_tuning.active("local") is None


def test_active_tolerates_unknown_value(monkeypatch):
    """Битое значение в `.env` — поведение дня 26, а не исключение на каждом запросе."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", "быстрый")

    assert local_tuning.active("local") is None


def test_explicit_profile_wins_over_environment(monkeypatch):
    """Явный профиль важнее окружения: прогон сравнивает варианты, не трогая `.env`."""
    monkeypatch.setattr(local_tuning, "LOCAL_LLM_PROFILE", local_tuning.PROFILE_TUNED)
    baseline = local_tuning.baseline_profile()

    assert local_tuning.profile_for("local", baseline) is baseline
    assert local_tuning.profile_for("local", None).name == local_tuning.PROFILE_TUNED


def test_prompt_for_falls_back_to_call_site():
    """Без профиля и без своего промпта берётся промпт вызывающего кода."""
    assert local_tuning.prompt_for(None, "промпт дня 26") == "промпт дня 26"
    assert local_tuning.prompt_for(local_tuning.baseline_profile(), "день 26") == "день 26"
    assert local_tuning.prompt_for(local_tuning.tuned_profile(), "день 26") == \
        local_tuning.LOCAL_TUNED_RAG_PROMPT


def test_resolve_profile_reads_env_file_and_rejects_bad_value(tmp_path):
    """Значение берётся из файла `.env`, а битое — заменяется значением по умолчанию."""
    path = tmp_path / ".env"
    path.write_text("# комментарий\nLOCAL_LLM_PROFILE=baseline\n", encoding="utf-8")

    assert local_tuning.resolve_profile({}, path) == local_tuning.PROFILE_BASELINE
    assert local_tuning.resolve_profile({"LOCAL_LLM_PROFILE": "tuned"}, path) == "tuned"
    assert local_tuning.resolve_profile({"LOCAL_LLM_PROFILE": "нет"}, path) == \
        local_tuning.PROFILE_DEFAULT
    assert local_tuning.resolve_profile({}, tmp_path / "missing.env") == \
        local_tuning.PROFILE_DEFAULT


def test_resolve_number_rejects_garbage():
    """Нечисловая настройка — предупреждение и значение по умолчанию, не исключение."""
    assert local_tuning.resolve_number("X", 512, int, {"X": "256"}) == 256
    assert local_tuning.resolve_number("X", 512, int, {"X": "много"}) == 512
    assert local_tuning.resolve_number("X", 512, int, {}) == 512


# ---------- строка прогона ----------
@pytest.mark.parametrize("question, changes, expected", [
    (QUESTION, {}, rag_demo.VERDICT_OK),
    (UNKNOWN, {"mode": "dont_know", "sources": [], "quotes": [],
               "quotes_verified": False, "grounding": "", "confidence": 0.0},
     rag_demo.VERDICT_DONT_KNOW_OK),
    (UNKNOWN, {}, rag_demo.VERDICT_MODE_MISMATCH),
    (QUESTION, {"fallback": True}, rag_demo.VERDICT_FALLBACK),
    (QUESTION, {"sources": [{"source": "другой.md"}]}, rag_demo.VERDICT_SOURCE_MISS),
    (QUESTION, {"quotes_verified": False, "confidence": 0.3}, rag_demo.VERDICT_UNCITED),
])
def test_quality_row_applies_day24_verdict(question, changes, expected):
    """Вердикт строки — правило дня 24 (откат → режим → источник → цитаты)."""
    row = local_tuning_eval.quality_row(question, record(**changes),
                                        profile=local_tuning.tuned_profile(),
                                        model="qwen2.5-coder:14b")

    assert row["verdict"] == expected
    assert row["profile"] == "tuned" and row["model"] == "qwen2.5-coder:14b"


def test_quality_row_carries_tokens_and_speed():
    """Строка несёт токены, скорость, прогрев и опору — из неё считается сводка."""
    row = local_tuning_eval.quality_row(QUESTION, record(),
                                        profile=local_tuning.tuned_profile(),
                                        model="qwen2.5-coder:14b")

    assert (row["prompt_tokens"], row["completion_tokens"]) == (900, 40)
    assert row["tokens_per_second"] == 20.0 and row["load_ms"] == 3000
    assert row["grounding_ok"] is True and row["quotes_verified"] is True
    assert row["mode_match"] is True and row["sources_found"] is True
    assert row["quote_count"] == 1 and row["answer_chars"] == len(row["answer"])


def test_quality_row_without_expectations_has_no_verdict():
    """Вопрос вне набора демо: ожиданий нет, режим без RAG — вердикт «без ожиданий»."""
    row = local_tuning_eval.quality_row(
        rag_demo.DemoQuestion(question="свой вопрос"),
        {"mode": "no_rag", "answer": "Ответ.", "duration_ms": 10},
        profile=local_tuning.baseline_profile(), model="m")

    assert row["verdict"] == rag_demo.VERDICT_NONE
    assert row["mode_match"] is True and row["sources_found"] is False
    assert row["completion_tokens"] == 0 and row["tokens_per_second"] == 0.0


# ---------- сводка варианта ----------
def test_summarize_counts_quality_and_skips_dont_know_time():
    """Среднее время — только по ответам модели; «не знаю» и ошибки в него не входят."""
    rows = [
        local_tuning_eval.quality_row(QUESTION, record(duration_ms=2000),
                                      profile=None, model="m"),
        local_tuning_eval.quality_row(UNKNOWN,
                                      record(mode="dont_know", sources=[], quotes=[],
                                             quotes_verified=False, grounding="",
                                             duration_ms=20000, tokens=None),
                                      profile=None, model="m"),
        local_tuning_eval.quality_row(QUESTION, {"mode": "error", "answer": "",
                                                 "duration_ms": 0},
                                      profile=None, model="m"),
    ]

    summary = local_tuning_eval.summarize(rows)

    assert summary["questions"] == 3
    assert summary["verdict_ok"] == 2 and summary["errors"] == 1
    assert summary["avg_ms"] == 2000, "время «не знаю» занизило бы скорость генерации"
    assert summary["avg_tokens_per_second"] == 20.0
    assert summary["completion_tokens"] == 40


def test_summarize_of_empty_rows_is_zero():
    """Пустой вариант: нули по всем счётчикам (полная форма, а не деление на ноль)."""
    assert local_tuning_eval.summarize([]) == {
        "questions": 0, "verdict_ok": 0, "mode_match": 0, "sources_found": 0,
        "quotes_verified": 0, "grounding_ok": 0, "errors": 0, "avg_ms": 0,
        "avg_tokens_per_second": 0.0, "completion_tokens": 0, "avg_answer_chars": 0.0,
    }


# ---------- сравнение вариантов ----------
def _summary(verdicts: int, quotes: int, grounding: int, avg_ms: int) -> dict:
    """Сводка варианта для проверки ранжирования: только поля, по которым оно идёт."""
    return {"verdict_ok": verdicts, "quotes_verified": quotes,
            "grounding_ok": grounding, "avg_ms": avg_ms}


def test_compare_prefers_quality_then_speed():
    """Сначала ранг (вердикты, цитаты, опора), при равенстве — меньшее среднее время."""
    assert local_tuning_eval.compare(_summary(8, 5, 5, 9000),
                                      _summary(9, 5, 5, 9000)) == \
        local_tuning_eval.VERDICT_TUNED_BETTER
    assert local_tuning_eval.compare(_summary(9, 5, 5, 9000),
                                      _summary(8, 5, 5, 9000)) == \
        local_tuning_eval.VERDICT_BASELINE_BETTER
    assert local_tuning_eval.compare(_summary(8, 5, 5, 9000),
                                      _summary(8, 5, 4, 1000)) == \
        local_tuning_eval.VERDICT_BASELINE_BETTER
    assert local_tuning_eval.compare(_summary(8, 5, 5, 9000),
                                      _summary(8, 5, 5, 3000)) == \
        local_tuning_eval.VERDICT_TUNED_BETTER
    assert local_tuning_eval.compare(_summary(8, 5, 5, 9000),
                                      _summary(8, 5, 5, 9000)) == \
        local_tuning_eval.VERDICT_SAME


def _variant(profile: str, model: str, **summary) -> dict:
    """Вариант прогона: параметры, пустые строки и сводка по переданным числам."""
    return {"params": {"profile": profile, "model": model}, "rows": [],
            "resources": {}, "summary": _summary(**summary)}


def test_summary_pairs_baseline_with_other_profiles():
    """Пары строятся внутри одной модели: вердикт, разница качества и ускорение."""
    variants = [
        _variant("baseline", "q14", verdicts=8, quotes=5, grounding=5, avg_ms=9000),
        _variant("tuned", "q14", verdicts=8, quotes=6, grounding=6, avg_ms=3000),
        _variant("baseline", "q3", verdicts=7, quotes=4, grounding=4, avg_ms=4000),
        _variant("tuned", "q3", verdicts=8, quotes=6, grounding=6, avg_ms=2500),
    ]

    result = local_tuning_eval.summary(variants)

    assert [pair["model"] for pair in result["pairs"]] == ["q14", "q3"]
    first = result["pairs"][0]
    assert first["verdict"] == local_tuning_eval.VERDICT_TUNED_BETTER
    assert first["quality_delta"] == 0 and first["speedup"] == 3.0
    assert result["pairs"][1]["quality_delta"] == 1
    assert result["pairs"][1]["speedup"] == 1.6
    assert result["best"] == "tuned (q3)", "при равном ранге выигрывает более быстрый"


def test_summary_without_baseline_has_no_pairs():
    """Только tuned: пар нет, но лучший вариант и суммарное время считаются."""
    variants = [_variant("tuned", "q14", verdicts=8, quotes=5, grounding=5, avg_ms=3000)]

    result = local_tuning_eval.summary(variants)

    assert result["pairs"] == [] and result["best"] == "tuned (q14)"
    assert result["total_ms"] == 0 and result["variants"] == variants
