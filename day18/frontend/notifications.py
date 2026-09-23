"""Уведомления планировщика в основной области (день 18).

Задача, поработавшая в фоне, обязана быть заметной: напоминание сработало, сводка
готова, тик упал — всё это лежит в очереди ``notifications`` и обновляется
фрагментом с ``run_every="5s"``, поэтому уведомление появляется без перезагрузки
страницы.

Показываются только НЕПРОЧИТАННЫЕ: у каждого — кнопка «✔ Прочитано», и после неё
уведомление уходит из области чата (остаётся в истории раздела «🗓 Планировщик»).
Пустая очередь не рисует ничего — «пустого» блока в интерфейсе нет.
"""
from __future__ import annotations

import streamlit as st

from . import api_client, common, scheduler_api


@st.fragment(run_every="5s")
def render_notifications() -> None:
    """Непрочитанные уведомления планировщика (обновляются каждые 5 секунд)."""
    try:
        payload = scheduler_api.api_scheduler_notifications(unread_only=True)
    except api_client.BackendError:
        return  # бэкенд недоступен: про это уже сказано в разделе чата
    items = payload.get("notifications") or []
    if not items:
        return
    for item in items:
        _render_notification(item)


def _render_notification(item: dict) -> None:
    """Одно уведомление: текст с видом и временем плюс кнопка «прочитано»."""
    kind = item.get("kind") or ""
    label = common.NOTIFICATION_KIND_LABELS.get(kind, kind)
    text = f"{label}: {item.get('text') or ''}"
    stamp = common.fmt_time(item.get("created_at"))
    if stamp:
        text += f"  ·  {stamp}"
    columns = st.columns([7, 1])
    with columns[0]:
        if kind == "error":
            st.warning(text)
        else:
            st.info(text)
    with columns[1]:
        if st.button("✔ Прочитано", key=f"notif_read_{item.get('id')}"):
            _mark_read(item.get("id"))


def _mark_read(notification_id) -> None:
    """Отмечает уведомление прочитанным и перерисовывает страницу целиком."""
    try:
        scheduler_api.api_scheduler_mark_read(notification_id)
    except api_client.BackendError as exc:
        st.error(f"Не удалось отметить уведомление: {exc.message}")
        return
    st.rerun(scope="app")
