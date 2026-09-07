"""Пакет backend дня 6: FastAPI-приложение управления агентами DeepSeek.

Модули:
- config.py         — базовый URL DeepSeek, дефолты, чтение DEEPSEEK_API_KEY;
- models.py         — Pydantic-схемы API;
- agent.py          — класс Agent (инкапсулированный вызов DeepSeek + история);
- agent_manager.py  — класс AgentManager (синглтон, пул агентов);
- main.py           — FastAPI-приложение (эндпоинты).
"""
