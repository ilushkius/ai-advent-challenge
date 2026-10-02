"""Мини-чат с RAG и памятью задачи (день 25): отдельное приложение на порту 8502.

``streamlit run`` кладёт в ``sys.path`` папку самого скрипта (``day21/mini_chat/``),
а не корень дня, поэтому корень добавляется здесь: без этого не импортируются ни
``mini_chat.*``, ни ``frontend.api_client``.

Запуск из папки day21/::

    uv run streamlit run mini_chat/app.py --server.port 8502

Рядом должен работать бэкенд: ``uvicorn backend.api.main:app --port 8000`` — мини-чат
ходит в него по HTTP и на порту 8501 с основной песочницей не пересекается.
"""
import sys
from pathlib import Path

DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

import streamlit as st  # noqa: E402 — путь к корню дня добавлен выше

from mini_chat import panels  # noqa: E402

st.set_page_config(page_title="Мини-чат с RAG и памятью · День 25",
                   page_icon="💬", layout="wide")
panels.render_sidebar()
panels.render_chat()
