"""Переключатель разделов основной области: какой раздел дня рисовать (день 34).

Модуль вынесен из ``chat_section``: переключатель разделов и цепочка их отрисовки
занимали там больше сотни строк, а файл стоит на пределе 400 строк, и добавление
нового раздела (дня 34) вывело бы его за лимит. Здесь же лежит список подписей —
единственное место, где раздел становится доступен пользователю.

Разделение обязанностей: ``chat_section`` рисует ЧАТ (карточку агента, панели, диалог
и ввод) и решает, доступен ли он вообще (бэкенд, наличие агентов), а этот модуль —
всё остальное: он получает подпись раздела и рисует его. Поэтому ``render_section``
возвращает ``False`` для чата: его рисовать должен ``chat_section``, у которого есть
своё состояние и своя проверка «агентов пока нет».

Разделы различаются по первому эмодзи подписи (``str.startswith``): эмодзи уникальны,
а порядок подписей в ``SECTIONS`` не влияет ни на что, кроме вида переключателя.
Последней идёт подпись самого нового дня — по ней видно, что добавилось в песочницу.
"""
from __future__ import annotations

import streamlit as st

from . import (
    code_review_section, common, cost_section, dev_assistant_section, file_assistant_section,
    indexing_section, invariant_panel, local_llm_section, local_rag_section,
    local_tuning_section, mcp_section, orchestration_section, pipeline_section, profile_section,
    rag_demo_section, rag_section, release_section, remote_llm_section, scheduler_section,
    support_section, task_panel,
)

#: Подписи разделов в порядке переключателя (последним — самый новый день).
SECTIONS = ("💬 Чат и память", "👤 Профиль пользователя", "🧭 Состояние задачи",
            "📏 Инварианты", "🔌 MCP", "🗓 Планировщик", "🔀 Пайплайны",
            "🌐 Оркестрация", "📦 Индексация", "🖥 Локальная LLM", "💰 Расходы",
            "⚙️ Оптимизация локальной LLM", "🆚 RAG-сравнение", "🧪 RAG-демо",
            "🏠 Локальный RAG", "🛰 Удалённая LLM", "🧑‍💻 Ассистент разработчика (Day 31)",
            "🔎 AI-ревью кода (Day 32)", "🎧 Поддержка пользователей (Day 33)",
            "🗂 Ассистент файлов (Day 34)", "🚀 Подготовка релиза (Day 35)")


def render_switcher() -> str:
    """Переключатель разделов: ``st.radio`` с подписями, возвращает выбранную.

    Разделы переключаются ``st.radio``, а не ``st.tabs``: выбор вкладки Streamlit не
    сохраняет между перезапусками скрипта, а после «Сохранить профиль» нужен
    ``st.rerun`` — с ``radio`` пользователь остаётся в том же разделе.
    """
    return st.radio("Раздел", list(SECTIONS), horizontal=True, key="main_section",
                    label_visibility="collapsed")


def render_section(section: str) -> bool:
    """Рисует раздел дня по подписи; ``False`` — выбран чат (его рисует ``chat_section``)."""
    if section.startswith("👤"):
        profile_section.render_profile_section(common.active_agent())
    elif section.startswith("🧭"):
        task_panel.render_task_panel(common.active_agent())
    elif section.startswith("📏"):
        # Инварианты глобальны: активный агент разделу не нужен.
        invariant_panel.render_invariant_panel()
    elif section.startswith("🔌"):
        # MCP-подключение у процесса одно: активный агент разделу не нужен.
        mcp_section.render_mcp_section()
    elif section.startswith("🗓"):
        # Планировщик — тоже служба процесса, а не свойство агента.
        scheduler_section.render_scheduler_section()
    elif section.startswith("🔀"):
        # Пайплайны дня 19: один прогон по одной цепочке инструментов.
        # Пайплайн — тоже служба процесса: он вызывает инструменты сервера дня.
        pipeline_section.render_pipeline_section()
    elif section.startswith("🌐"):
        # Оркестрация дня 20: флот серверов, план шагов и один флот на процесс.
        orchestration_section.render_orchestration_section()
    elif section.startswith("📦"):
        # Индексация дня 21: документы, два индекса FAISS и поиск — служба процесса.
        indexing_section.render_indexing_section()
    elif section.startswith("🖥"):
        # Локальная LLM (день 26): второй провайдер — Ollama по HTTP. Раздел
        # глобальный: модель живёт вне агентов и вне корпуса.
        local_llm_section.render_local_llm_section()
    elif section.startswith("⚙️"):
        # Оптимизация локальной LLM (день 29): профили настройки и кванты
        # на контрольных вопросах корпуса — служба процесса, не свойство агента.
        local_tuning_section.render_local_tuning_section()
    elif section.startswith("💰"):
        # Расходы на LLM (день 21): журнал, кэш контекста, непиковые часы.
        # Раздел глобальный: считает запросы всех агентов процесса.
        cost_section.render_cost_section()
    elif section.startswith("🆚"):
        # Сравнение ответов с корпусом и без него (день 22): корпус и индекс —
        # тоже служба процесса, а не свойство агента.
        rag_section.render_rag_compare_section()
    elif section.startswith("🧪"):
        # Демо дня 24: десять контрольных вопросов, источники, цитаты и режим
        # «не знаю» — тоже про корпус процесса, а не про агента.
        rag_demo_section.render_rag_demo_section()
    elif section.startswith("🏠"):
        # Локальный RAG (день 28): retrieval локальный, отличается только генератор.
        local_rag_section.render_local_rag_section()
    elif section.startswith("🛰"):
        # Удалённая LLM (день 30): Ollama в Google Colab через туннель Cloudflare.
        # Раздел глобальный: адрес туннеля живёт часами и агентов не касается.
        remote_llm_section.render_remote_llm_section()
    elif section.startswith("🧑‍💻"):  # Ассистент разработчика (день 31).
        dev_assistant_section.render_dev_assistant_section()
    elif section.startswith("🔎"):  # AI-ревью кода (день 32).
        code_review_section.render_code_review_section()
    elif section.startswith("🎧"):  # Поддержка пользователей (день 33).
        support_section.render_support_section()
    elif section.startswith("🗂"):  # Ассистент файлов (день 34).
        file_assistant_section.render_file_assistant_section()
    elif section.startswith("🚀"):  # Подготовка релиза (день 35).
        release_section.render_release_section()
    else:
        return False
    return True
