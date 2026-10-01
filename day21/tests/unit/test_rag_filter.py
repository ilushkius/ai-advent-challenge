"""Доменные правила отбора RAG (день 23): режимы, реранк, порог отсечения.

Проверяются чистые функции ``backend/domain/rag_filter.py``: каталог режимов и их
настройки, нормализация баллов кросс-энкодера, отбор текста пары, раскладка баллов
реранкера по кандидатам и отсечение по порогу. Ни модели, ни сети здесь нет.
"""
import pytest

from backend.domain import rag_filter


def test_resolve_rag_mode_defaults_and_rejects_unknown():
    """Пусто — базовый режим (день 22), незнакомое имя — ``None`` для отказа."""
    assert rag_filter.resolve_rag_mode(None) == rag_filter.RAG_MODE_BASELINE
    assert rag_filter.resolve_rag_mode("") == rag_filter.RAG_MODE_BASELINE
    assert rag_filter.resolve_rag_mode("  ") == rag_filter.RAG_MODE_BASELINE
    assert rag_filter.resolve_rag_mode("rerank") == rag_filter.RAG_MODE_RERANK
    assert rag_filter.resolve_rag_mode("нет-такого") is None


def test_mode_catalog_covers_all_modes():
    """Каталог режимов описывает ровно четыре имени для ``/rag/config`` и селектора."""
    catalog = rag_filter.mode_catalog()

    assert [item["name"] for item in catalog] == list(rag_filter.RAG_MODES)
    assert {item["name"] for item in catalog} == {
        "baseline", "rewrite", "rerank", "rerank_filter"}
    for item in catalog:
        assert set(item) == {"name", "label", "rewrite", "rerank", "min_score"}
        assert item["label"]


def test_mode_knobs_rerank_filter_uses_domain_threshold():
    """Настройки ``rerank_filter`` несут балл реранкера и порог из домена."""
    knobs = rag_filter.mode_knobs(rag_filter.RAG_MODE_RERANK_FILTER)

    assert knobs == {"rewrite": False, "rerank": True,
                     "min_score": rag_filter.RAG_FILTER_MIN_SCORE}
    # Копия, а не сам словарь домена: правка ответа не меняет каталог.
    knobs["rerank"] = False
    assert rag_filter.RAG_MODE_KNOBS[rag_filter.RAG_MODE_RERANK_FILTER]["rerank"] is True
    # Незнакомое имя — безопасные значения базового режима.
    assert rag_filter.mode_knobs("нет-такого")["rerank"] is False


def test_normalize_rerank_scores_passthrough_and_sigmoid():
    """Баллы в ``[0, 1]`` не трогаются; логиты приводятся логистикой монотонно."""
    assert rag_filter.normalize_rerank_scores([0.2, 0.9]) == [0.2, 0.9]
    assert rag_filter.normalize_rerank_scores([]) == []

    results = rag_filter.normalize_rerank_scores([2.0, -2.0])

    assert all(0.0 < value < 1.0 for value in results)
    assert results[0] > results[1]


def test_candidate_text_prefers_content_and_truncates():
    """Текст пары берётся из ``content``; длиннее предела — обрезается."""
    long_text = "я" * (rag_filter.RAG_RERANK_MAX_CHARS + 50)

    assert rag_filter.candidate_text({"content": long_text}) == \
        long_text[:rag_filter.RAG_RERANK_MAX_CHARS]
    assert rag_filter.candidate_text({"preview": "превью"}) == "превью"
    assert rag_filter.candidate_text({}) == ""


def test_apply_rerank_sorts_by_score_and_keeps_ties():
    """Балл реранкера добавляется и сортирует кандидатов; равные баллы — порядок входа."""
    hits = [{"chunk_id": "a"}, {"chunk_id": "b"}, {"chunk_id": "c"}]

    ranked = rag_filter.apply_rerank(hits, [0.2, 0.9, 0.5])

    assert [hit["chunk_id"] for hit in ranked] == ["b", "c", "a"]
    assert [hit[rag_filter.SCORE_FIELD_RERANK] for hit in ranked] == [0.9, 0.5, 0.2]
    # Исходные хиты не мутируются: реранк возвращает копии.
    assert rag_filter.SCORE_FIELD_RERANK not in hits[0]

    tied = rag_filter.apply_rerank(
        [{"chunk_id": "x"}, {"chunk_id": "y"}], [0.4, 0.4])
    assert [hit["chunk_id"] for hit in tied] == ["x", "y"]


def test_apply_rerank_rejects_length_mismatch():
    """Рассинхрон длин — ошибка вызывающего, а не молчаливый сдвиг баллов."""
    with pytest.raises(ValueError):
        rag_filter.apply_rerank([{"chunk_id": "a"}], [0.1, 0.2])


def test_filter_hits_none_returns_same_list():
    """Без порога список возвращается тем же объектом."""
    hits = [{"score": 0.1}, {"score": 0.9}]

    assert rag_filter.filter_hits(hits, None) is hits


def test_filter_hits_drops_weak_and_treats_missing_as_zero():
    """Порог выбрасывает слабых и сохраняет сильных; отсутствующий балл — 0.0."""
    hits = [{"chunk_id": "strong", "score": 0.8},
            {"chunk_id": "weak", "score": 0.2},
            {"chunk_id": "none"}]

    kept = rag_filter.filter_hits(hits, 0.5)

    assert [hit["chunk_id"] for hit in kept] == ["strong"]
    assert rag_filter.filter_hits(hits, 0.0) == hits


def test_score_field_and_empty_warning():
    """Поле балла зависит от реранка, а предупреждение несёт порог с двумя знаками."""
    assert rag_filter.score_field(True) == rag_filter.SCORE_FIELD_RERANK
    assert rag_filter.score_field(False) == rag_filter.SCORE_FIELD_HYBRID
    assert "0.50" in rag_filter.filtered_empty_warning(0.5)
