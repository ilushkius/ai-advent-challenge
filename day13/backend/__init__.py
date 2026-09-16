"""Пакет backend дня 13: агенты DeepSeek с тремя слоями памяти и состоянием задачи.

День 13 развивает день 12: к слоям памяти, стратегиям управления контекстом и
персонализации добавляется СОСТОЯНИЕ ЗАДАЧИ как конечный автомат.

Слои (каждый — подпапка пакета; файл лежит в папке своего слоя):

- ``core/``     — конфигурация (``config``) и зависимости роутов
                  (``dependencies``): доступ к ``AgentManager`` и помощники 404;
- ``domain/``   — чистые правила и данные без БД и LLM: ``strategies``,
                  ``context_fsm`` / ``context_policy`` (сжатие), ``fact_extractor``,
                  ``memory_layers``, ``profile_values`` / ``profiles`` /
                  ``demo_profiles``, ``task_fsm`` / ``task_prompt`` /
                  ``task_intent``;
- ``storage/``  — доступ к БД: ``database`` (движок, сессии, реэкспорт ORM),
                  ``task_store`` (состояние задачи и журнал переходов),
                  ``memory_rows`` (ORM-строки → словари API/UI);
- ``services/`` — прикладные сервисы: ``compressor`` (суммаризация и конспект),
                  ``task_state`` (переходы состояния задачи);
- ``agents/``   — ``agent`` (``Agent``), ``memory`` (``MemoryManager``),
                  ``profile_store``, ``agent_manager`` (``AgentManager``) и
                  миксины ``manager_*`` по доменам;
- ``models/``   — ORM-таблицы SQLAlchemy по доменам (``agent``, ``message``,
                  ``memory``, ``context``, ``user_profile``, ``task_state``);
- ``schemas/``  — Pydantic-схемы API по доменам (``agent``, ``context``,
                  ``memory``, ``profile``, ``task``);
- ``api/``      — FastAPI: роутеры по доменам (``agents``, ``context``,
                  ``memory``, ``profiles``, ``tasks``) и сборка приложения
                  (``main`` — ``uvicorn backend.api.main:app``);
- ``utils/``    — собственных утилит нет: общий код живёт в ``shared/``.

Общий пакет ``shared/`` (код, не меняющийся между днями) подключается здесь:
корень репозитория добавляется в ``sys.path`` до импорта подмодулей.
"""
import sys
from pathlib import Path

# Корень репозитория (day13/backend/__init__.py -> корень проекта): из него
# импортируется общий пакет shared/ — код, не меняющийся между днями.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))
