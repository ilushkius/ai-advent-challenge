"""Пакет UI дня 12 (Streamlit): модули интерфейса, разложенные по доменам.

Модули не выполняют ``st.*`` на импорте — только определения и константы;
страницу собирает ``app.py``: ``set_page_config`` → ``common.init_state()`` →
``sidebar.render_sidebar()`` → ``chat_section.render_main_area()``.
"""
