"""HTTP-часть раздела «🛰 Удалённая LLM» (день 30).

Транспорт общий — ``frontend/api_client.py``; здесь три запроса дня 30: настройки
раздела (значения ``.env``, границы слайдеров и пять шагов демо), проверка связи
через туннель и ОДИН шаг прогона. Пошаговость — не дробление ради дробления:
интерфейс рисует прогресс-бар по факту выполненных шагов, а служба держит клиент в
реестре, поэтому клиентский счётчик частоты переживает отдельные запросы.

Предел ожидания — ``LONG_TIMEOUT`` у обоих вызовов: настоящий предел ставит клиент
на стороне бэкенда (``REMOTE_LLM_TIMEOUT``, 120 с), а фронтенд лишь не должен сдаться
раньше него — иначе пользователь увидит «бэкенд не ответил» вместо причины отказа.
"""
from .api_client import LONG_TIMEOUT, request_json


def api_remote_config() -> dict:
    """GET /llm/remote-config -> адрес, модель, ключ, ручки и шаги демо."""
    return request_json("GET", "/llm/remote-config")


def api_remote_check(settings: dict) -> dict:
    """POST /llm/remote/check -> ``ok`` и текст для индикатора, модели, время.

    Недоступный сервис — это результат проверки (``ok=false`` в 200), а не ошибка
    API: раздел показывает красную плашку с причиной и не падает.
    """
    return request_json("POST", "/llm/remote/check",
                        timeout=LONG_TIMEOUT, json={"settings": dict(settings)})


def api_remote_step(step: str, settings: dict, reset: bool = False) -> dict:
    """POST /llm/remote/step -> строка таблицы прогона для одного шага.

    ``reset`` очищает клиентский счётчик частоты — интерфейс передаёт его на первом
    шаге, чтобы предыдущий прогон не съедал бюджет минуты.
    """
    return request_json("POST", "/llm/remote/step", timeout=LONG_TIMEOUT,
                        json={"settings": dict(settings), "step": step,
                              "reset": bool(reset)})
