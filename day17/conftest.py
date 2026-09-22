"""Корневой conftest дня 17: включает корень папки в sys.path для pytest.

Благодаря этому файлу `python -m pytest -q` из папки day17 видит пакет
`backend` (тесты импортируют `from backend.agents.agent import Agent`) — та же
конвенция, что и при запуске приложения из папки дня.
"""
