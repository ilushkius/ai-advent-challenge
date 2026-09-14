"""Пакет backend дня 11: агенты DeepSeek со стратегиями управления контекстом.

День 11 развивает день 9: к сжатию истории добавляются три новые стратегии
сборки контекста и переключатель между ними.

Модули:
- config.py          — базовый URL DeepSeek, дефолты, чтение DEEPSEEK_API_KEY,
                       лимиты/цены моделей, параметры сжатия и стратегий, путь
                       к SQLite-файлу day11/agents.db;
- strategies.py      — Enum Strategy (sliding_window/sticky_facts/branching/
                       summary) и проверка допустимости значения;
- fact_extractor.py  — чистая эвристика извлечения фактов «ключ → значение»;
- context_fsm.py     — стейт-машина сжатия (Enum + паттерн State, день 9);
- context_policy.py  — чистая арифметика сжатия (когда сжимать, что оставить);
- database.py        — SQLAlchemy: движок, сессии, ORM-модели agents, messages,
                       summaries, token_usage, facts, checkpoints;
- models.py          — Pydantic-схемы API;
- compressor.py      — ContextCompressor: вызов суммаризации и запись конспекта;
- agent.py           — класс Agent (память, токены, prepare_context, стратегии,
                       факты, ветки, метрики);
- agent_manager.py   — класс AgentManager (синглтон, пул, стратегии, ветки);
- main.py            — FastAPI-приложение (эндпоинты).
"""
