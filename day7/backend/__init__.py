"""Пакет backend дня 7: FastAPI-приложение агентов DeepSeek с памятью в SQLite.

Модули:
- config.py         — базовый URL DeepSeek, дефолты, чтение DEEPSEEK_API_KEY,
                      путь к SQLite-файлу day7/agents.db;
- database.py       — SQLAlchemy: движок, сессии, ORM-модели agents и messages;
- models.py         — Pydantic-схемы API;
- agent.py          — класс Agent (контекстная память: self.messages + SQLite);
- agent_manager.py  — класс AgentManager (синглтон, пул агентов, restore);
- main.py           — FastAPI-приложение (эндпоинты).
"""
