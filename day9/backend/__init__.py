"""Пакет backend дня 9: агенты DeepSeek со сжатием истории диалога.

Модули:
- config.py          — базовый URL DeepSeek, дефолты, чтение DEEPSEEK_API_KEY,
                       лимиты/цены моделей, параметры сжатия истории, путь к
                       SQLite-файлу day9/agents.db;
- context_fsm.py     — стейт-машина управления контекстом (Enum + паттерн State);
- context_policy.py  — чистая арифметика сжатия (когда сжимать, что оставить);
- database.py        — SQLAlchemy: движок, сессии, ORM-модели agents, messages,
                       summaries, token_usage;
- models.py          — Pydantic-схемы API;
- compressor.py      — ContextCompressor: вызов суммаризации и запись конспекта;
- agent.py           — класс Agent (память, подсчёт токенов, сжатие, метрики);
- agent_manager.py   — класс AgentManager (синглтон, пул агентов, restore);
- main.py            — FastAPI-приложение (эндпоинты).
"""
