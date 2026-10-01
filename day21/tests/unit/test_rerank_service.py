"""Служба реранкера: ленивая загрузка, пары, баллы и ошибки (день 23).

Модель в тестах не грузится: пакет ``sentence_transformers`` подменяется фейком, а
общая фикстура дня (``isolated_indexing``) ставит на ``RerankService._load`` ошибку —
этот файл возвращает настоящий ``_load`` (``allow_real_load``), потому что проверяет
именно путь загрузки, но импорт внутри него уходит в поддельный пакет: ни torch, ни
сеть здесь не нужны.
"""
import sys
import types

import pytest

from backend.services import rerank_service as rerank_module
from backend.services.rerank_service import RerankError, RerankService


class FakeCrossEncoder:
    """Подмена кросс-энкодера: помнит пары и отдаёт заданные баллы."""

    def __init__(self, scores=None):
        self._scores = scores
        self.max_seq_length = None
        self.calls = []

    def predict(self, pairs, **kwargs):
        """Баллы по паре на вход: список из ``scores`` или половины на всё."""
        self.calls.append({"pairs": list(pairs), "kwargs": kwargs})
        if self._scores is not None:
            return self._scores
        return [0.5 for _ in pairs]


#: Настоящий ``_load``, снятый ДО фикстур: общая фикстура дня 21 его запрещает.
ORIGINAL_LOAD = RerankService._load


@pytest.fixture(autouse=True)
def allow_real_load(isolated_indexing, monkeypatch):
    """Возвращает службе настоящий ``_load``: импорт внутри уходит в фейк-пакет."""
    monkeypatch.setattr(RerankService, "_load", ORIGINAL_LOAD)


@pytest.fixture
def fake_sentence_transformers(monkeypatch):
    """Пакет ``sentence_transformers`` заменён фейком: torch и сеть не нужны."""
    module = types.ModuleType("sentence_transformers")
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return module


def test_score_loads_model_lazily_and_only_once(fake_sentence_transformers):
    """До первого обращения модели нет; повторный ``score`` её не пересоздаёт."""
    instances = []

    class CountingEncoder(FakeCrossEncoder):
        def __init__(self, name, **kwargs):
            super().__init__()
            instances.append(self)

    fake_sentence_transformers.CrossEncoder = CountingEncoder
    service = RerankService(model_name="test/reranker", cache_dir="cache")

    assert service.loaded is False
    assert instances == []
    assert service.score("q", ["один", "два"]) == [0.5, 0.5]
    assert len(instances) == 1
    service.score("q", ["три"])
    assert len(instances) == 1


def test_score_builds_pairs_in_order_and_passes_batch_size(monkeypatch):
    """Пара на текст, порядок пар = порядок текстов, батч и флаги из конструктора."""
    service = RerankService(model_name="test/reranker", batch_size=7)
    model = FakeCrossEncoder(scores=[0.1, 0.9])
    monkeypatch.setattr(service, "_load", lambda: model)

    scores = service.score("Запрос", ["первый", "второй"])

    assert scores == [0.1, 0.9]
    call = model.calls[0]
    assert call["pairs"] == [("Запрос", "первый"), ("Запрос", "второй")]
    assert call["kwargs"] == {"batch_size": 7, "convert_to_numpy": True,
                              "show_progress_bar": False}


def test_empty_texts_skip_model_load(monkeypatch):
    """Пустой вход — пустой список, модель не грузится зря."""
    service = RerankService()
    monkeypatch.setattr(service, "_load", lambda: pytest.fail("модель не должна грузиться"))

    assert service.score("q", []) == []


def test_load_builds_cross_encoder_with_cache_and_max_length(fake_sentence_transformers):
    """Загрузка зовёт кросс-энкодер с кэшем и выставляет предел токенов."""
    instances = []

    class RecordingEncoder(FakeCrossEncoder):
        def __init__(self, name, **kwargs):
            super().__init__()
            self.name = name
            self.kwargs = kwargs
            instances.append(self)

    fake_sentence_transformers.CrossEncoder = RecordingEncoder
    service = RerankService(model_name="test/reranker", cache_dir="cache-dir",
                            max_length=256)

    assert service.score("q", ["а"]) == [0.5]
    assert len(instances) == 1
    assert instances[0].name == "test/reranker"
    assert instances[0].kwargs == {"cache_folder": "cache-dir"}
    assert instances[0].max_seq_length == 256
    assert service.loaded is True


def test_load_failure_becomes_rerank_error(fake_sentence_transformers):
    """Сбой загрузки — ``RerankError`` с подсказкой про переменную модели."""
    def boom(*args, **kwargs):
        raise OSError("нет сети")

    fake_sentence_transformers.CrossEncoder = boom
    service = RerankService(model_name="test/reranker")

    with pytest.raises(RerankError) as exc:
        service.score("q", ["а"])

    assert "RAG_RERANK_MODEL" in str(exc.value)
    assert service.loaded is False


def test_reset_forgets_model(fake_sentence_transformers):
    """``reset`` забывает модель — нужна повторная загрузка при следующем вызове."""
    fake_sentence_transformers.CrossEncoder = lambda name, **kwargs: FakeCrossEncoder()
    service = RerankService(model_name="test/reranker")

    assert service.score("q", ["а"]) == [0.5]
    assert service.loaded is True
    service.reset()
    assert service.loaded is False


def test_warmup_returns_true_and_loads(fake_sentence_transformers):
    """Успешный прогрев возвращает ``True`` и загружает модель."""
    fake_sentence_transformers.CrossEncoder = lambda name, **kwargs: FakeCrossEncoder()
    service = RerankService(model_name="test/reranker")

    assert service.warmup() is True
    assert service.loaded is True


def test_warmup_swallows_failure(fake_sentence_transformers):
    """``warmup`` не бросает исключений: его неудача не валит старт приложения."""
    def boom(*args, **kwargs):
        raise OSError("нет сети")

    fake_sentence_transformers.CrossEncoder = boom

    assert RerankService().warmup() is False


def test_get_rerank_service_is_singleton(monkeypatch):
    """Служба реранкера одна на процесс: модель весит сотни мегабайт."""
    monkeypatch.setattr(rerank_module, "_service", None)

    assert rerank_module.get_rerank_service() is rerank_module.get_rerank_service()
