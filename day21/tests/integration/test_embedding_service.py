"""Служба эмбеддингов: ленивая загрузка, батчи, нормализация и ошибки (день 21).

``sentence_transformers`` подменяется лёгким фейком: тесты не должны скачивать веса
и грузить torch. Проверяется контракт службы — что она ленива (модель создаётся один
раз и только при первом обращении), что выставляет ``max_seq_length`` (без этого
чанк в 512 токенов молча обрезался бы до 128) и что сбой загрузки приходит
``EmbeddingError`` с понятным текстом, а не голым исключением библиотеки.
"""
import sys
import types

import numpy as np
import pytest

from backend.services.embedding_service import EmbeddingError, EmbeddingService


class FakeModel:
    """Подмена ``SentenceTransformer``: считает созданные экземпляры и вызовы encode."""

    instances: list = []
    fail_with: Exception | None = None

    def __init__(self, name, cache_folder=None):
        if FakeModel.fail_with is not None:
            raise FakeModel.fail_with
        self.name = name
        self.cache_folder = cache_folder
        self.max_seq_length = None
        self.calls: list = []
        FakeModel.instances.append(self)

    def get_sentence_embedding_dimension(self):
        """Размерность векторов фейка."""
        return 4

    def encode(self, texts, **kwargs):
        """Нормализованные векторы формы ``(n, 4)`` с записью аргументов вызова."""
        self.calls.append({"texts": list(texts), **kwargs})
        rows = np.arange(len(texts) * 4, dtype=np.float32).reshape(len(texts), 4) + 1.0
        norms = np.linalg.norm(rows, axis=1, keepdims=True)
        return rows / norms


@pytest.fixture(autouse=True)
def fake_sentence_transformers(monkeypatch):
    """Подменяет пакет ``sentence_transformers`` фейком на время теста."""
    FakeModel.instances = []
    FakeModel.fail_with = None
    module = types.SimpleNamespace(SentenceTransformer=FakeModel)
    monkeypatch.setitem(sys.modules, "sentence_transformers", module)
    return FakeModel


#: Настоящий ``_load``, снятый ДО фикстур: этот файл проверяет именно загрузку модели —
#: общая фикстура дня 21 запрещает её (настоящая модель весит сотни мегабайт).
ORIGINAL_LOAD = EmbeddingService._load


@pytest.fixture(autouse=True)
def allow_real_load(monkeypatch):
    """Возвращает службе настоящий ``_load``: библиотека уже подменена фейком."""
    monkeypatch.setattr(EmbeddingService, "_load", ORIGINAL_LOAD)


def _service(**overrides):
    """Служба эмбеддингов с фейковым бэкендом отключённой ленивости."""
    params = {"cache_dir": "index/models", "batch_size": 2, "max_seq_length": 512}
    params.update(overrides)
    return EmbeddingService(**params)


def test_model_is_loaded_lazily():
    """До первого обращения модель не создаётся: старт бэкенда не тянет torch."""
    service = _service()
    assert service.loaded is False
    assert service.dimension == 0
    assert FakeModel.instances == []


def test_encode_returns_normalized_batches():
    """Векторы приходят формой ``(n, dim)``, ``float32`` и единичной длины."""
    service = _service(batch_size=2)
    vectors = service.encode(["первый", "второй", "третий"])
    assert vectors.shape == (3, 4)
    assert vectors.dtype == np.float32
    norms = np.linalg.norm(vectors, axis=1)
    assert np.allclose(norms, 1.0, atol=1e-5)
    assert service.loaded is True
    assert service.dimension == 4


def test_encode_splits_into_batches_and_passes_flags():
    """Батчи идут по ``batch_size``, а нормализация и numpy выставляются явно."""
    service = _service(batch_size=2)
    service.encode(["a", "b", "c", "d", "e"])
    model = FakeModel.instances[0]
    assert [len(call["texts"]) for call in model.calls] == [2, 2, 1]
    for call in model.calls:
        assert call["normalize_embeddings"] is True
        assert call["convert_to_numpy"] is True
        assert call["batch_size"] == 2
        assert call["show_progress_bar"] is False


def test_encode_one_shape():
    """Один текст — вектор формы ``(dim,)``."""
    vector = _service().encode_one("запрос")
    assert vector.shape == (4,)
    assert vector.dtype == np.float32


def test_model_loaded_once():
    """Повторный ``encode`` не пересоздаёт модель: она живёт до ``reset``."""
    service = _service()
    service.encode(["первый"])
    service.encode(["второй"])
    assert len(FakeModel.instances) == 1


def test_max_seq_length_is_applied():
    """``max_seq_length`` выставляется модели (иначе чанк в 512 токенов обрежется)."""
    service = _service(max_seq_length=512, cache_dir="index/models")
    service.encode(["текст"])
    model = FakeModel.instances[0]
    assert model.max_seq_length == 512
    assert model.cache_folder == "index/models"


def test_empty_input_gives_empty_matrix():
    """Пустой вход — пустая матрица формы ``(0, dim)`` без исключения."""
    service = _service()
    vectors = service.encode([])
    assert vectors.shape == (0, 4)


def test_load_failure_becomes_embedding_error():
    """Сбой загрузки модели — ``EmbeddingError`` с подсказкой про кэш и переменную."""
    FakeModel.fail_with = OSError("нет сети")
    service = _service(model_name="my/model")
    with pytest.raises(EmbeddingError) as exc:
        service.encode(["текст"])
    assert "my/model" in str(exc.value)
    assert "DAY21_EMBEDDING_MODEL" in str(exc.value)


def test_warmup_returns_false_on_failure():
    """``warmup`` не бросает исключений: его неудача не валит старт приложения."""
    FakeModel.fail_with = OSError("нет сети")
    assert _service().warmup() is False


def test_warmup_returns_true_on_success():
    """Успешный прогрев возвращает ``True`` и загружает модель."""
    service = _service()
    assert service.warmup() is True
    assert service.loaded is True


def test_reset_forgets_model():
    """``reset`` забывает загруженную модель (нужно тестам и подмене модели)."""
    service = _service()
    service.encode(["текст"])
    service.reset()
    assert service.loaded is False
    assert service.dimension == 0
    service.encode(["текст"])
    assert len(FakeModel.instances) == 2


def test_model_name_is_reported():
    """Имя модели видно снаружи: оно попадает в отчёт прогона."""
    service = _service(model_name="some/model")
    assert service.model_name == "some/model"
