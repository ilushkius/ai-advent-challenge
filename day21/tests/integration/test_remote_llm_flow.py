"""Полный цикл демо удалённой LLM (день 30): настоящие HTTP-запросы через туннель.

Тест помечен ``slow`` (по умолчанию не запускается: без работающей ячейки в Colab и
живого туннеля Cloudflare он бессмыслен) и ``remote`` — этот маркер снимает autouse-запрет
``no_real_network`` из ``tests/conftest.py``: адрес туннеля внешний, а подменить его
фейком значит проверять не удалённый сервис. Адрес берётся из ``DAY21_REMOTE_LLM_URL``
или из ``REMOTE_LLM_URL`` в ``day21/.env``. Нет адреса или проверка связи не прошла —
``skip``, а не падение: погасший Colab это нормальное состояние бесплатного тарифа, а
не дефект кода. Всё остальное проверяется строго, потому что сервис ответил: пять
строк по порядку домена, ответы реальной модели (есть токены), провайдер ``remote`` и
отказ клиентского счётчика на N+1-м запросе.

Предел частоты для теста маленький (3, переопределяется ``DAY21_REMOTE_LLM_RATE_LIMIT``):
полный цикл на десяти запросах к модели в Colab идёт минутами, а проверяется тем же
самым кодом пути. Три — минимум, при котором сценарий проходит целиком: столько
запросов тратят три вопроса демо (шаг 5 начинает минуту заново).
"""
import os

import pytest

from backend.core import config
from backend.domain import llm_provider, remote_demo
from backend.services import remote_llm_service
from backend.services.remote_llm_client import RemoteSettings

URL_ENV = "DAY21_REMOTE_LLM_URL"
LIMIT_ENV = "DAY21_REMOTE_LLM_RATE_LIMIT"
TEST_RATE_LIMIT = 3


def _settings() -> RemoteSettings:
    """Настройки прогона: адрес из окружения или ``.env``, маленький предел частоты."""
    url = os.environ.get(URL_ENV, "").strip() or config.REMOTE_LLM_URL
    if not url:
        pytest.skip(f"нет адреса туннеля: задайте {URL_ENV} или REMOTE_LLM_URL в .env")
    limit = int(os.environ.get(LIMIT_ENV, "") or TEST_RATE_LIMIT)
    return RemoteSettings.from_values(url=url, rate_limit=limit,
                                      max_context=config.REMOTE_LLM_MAX_CONTEXT)


@pytest.mark.slow
@pytest.mark.remote
def test_full_demo_cycle_over_tunnel():
    """Пять шагов демо по живому туннелю: таблица, токены, провайдер, отказ на N+1."""
    settings = _settings()
    remote_llm_service.reset_client_cache()
    probe = remote_llm_service.check_connection(settings)
    if not probe["ok"]:
        pytest.skip(f"удалённый сервис недоступен: {probe['message']}")
    assert probe["count"] >= 1, "GET /models обязан вернуть хотя бы одну модель"

    rows = [remote_llm_service.run_step(step.key, settings, reset=index == 0)
            for index, step in enumerate(remote_demo.DEMO_STEPS)]
    summary = remote_demo.summarize_rows(rows)

    assert [row["step"] for row in rows] == list(remote_demo.STEP_KEYS)
    assert summary["errors"] == 0, [row["answer"] for row in rows
                                    if row["status"] != "ok"]
    assert summary["provider"] == llm_provider.PROVIDER_REMOTE
    assert summary["remote_confirmed"] is True
    assert rows[1]["tokens"]["completion_tokens"] > 0, "ответ модели без токенов — не модель"
    assert summary["blocked"] == 1, "счётчик частоты обязан отказать на N+1-м запросе"
    asks = sum(1 for step in remote_demo.DEMO_STEPS
               if step.kind == remote_demo.KIND_ASK)
    assert summary["calls"] == asks + settings.rate_limit
    assert "Rate limit exceeded" in rows[-1]["answer"]
