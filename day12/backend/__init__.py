"""Пакет backend дня 12: агенты DeepSeek с тремя слоями памяти и профилем.

День 12 развивает день 11: к слоям памяти и стратегиям управления контекстом
добавляется персонализация — профиль пользователя, подключаемый к системному
промпту каждого запроса.

Модули:
- config.py          — базовый URL DeepSeek, дефолты, чтение DEEPSEEK_API_KEY,
                       лимиты/цены моделей, параметры сжатия, стратегий, памяти
                       и профиля, путь к SQLite-файлу day12/agents.db;
- strategies.py      — Enum Strategy (sliding_window/sticky_facts/branching/
                       summary) и проверка допустимости значения;
- fact_extractor.py  — чистая эвристика извлечения фактов «ключ → значение»;
- context_fsm.py     — стейт-машина сжатия (Enum + паттерн State, день 9);
- context_policy.py  — чистая арифметика сжатия (когда сжимать, что оставить);
- database.py        — SQLAlchemy: движок, сессии и ORM-модели таблиц дня;
- memory_layers.py   — словари-представления слоёв памяти и их тексты;
- memory.py          — MemoryManager: хранение трёх слоёв памяти;
- models/            — Pydantic-схемы API (agent, context, memory, profile);
- profile_values.py  — значения профиля: Enum-перечисления и нормализация;
- profiles.py        — сборка блока персонализации для системного промпта;
- profile_store.py   — чтение/запись профиля пользователя в SQLite;
- demo_profiles.py   — демонстрационные профили для офлайн-сравнения;
- compressor.py      — ContextCompressor: вызов суммаризации и запись конспекта;
- agent.py           — класс Agent (память, токены, prepare_context, стратегии,
                       факты, ветки, метрики, профиль);
- manager_*.py       — миксины AgentManager по доменам (агенты, контекст,
                       статистика, память, профили);
- agent_manager.py   — класс AgentManager (синглтон, пул, стратегии, ветки);
- dependencies.py    — зависимости API-слоя (доступ к менеджеру агентов);
- routers/           — роутеры API по доменам (agents, memory, profiles,
                       context);
- main.py            — FastAPI-приложение: сборка app и подключение роутеров.

Общий пакет ``shared/`` (код, не меняющийся между днями) подключается здесь:
корень репозитория добавляется в ``sys.path`` до импорта подмодулей.
"""
import sys
from pathlib import Path

# Корень репозитория (day12/backend/__init__.py -> корень проекта): из него
# импортируется общий пакет shared/ — код, не меняющийся между днями.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
