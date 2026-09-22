"""UI-кадры сценария видео дня 17: реальный рендер Streamlit через AppTest.

Что это.
    Кадры инструкции (``docs/usage.md`` §8) проверяются не только по API
    (``video_scenario.py``), но и по настоящему рендеру интерфейса:
    ``streamlit.testing.v1.AppTest`` запускает ``app.py``, нажимает те же
    кнопки, что и пользователь на записи, и читает то, что увидел бы зритель —
    карточку задачи, подписи и блокировку кнопок, причины отказа, вкладки
    журнала. Память между кадрами не переносится: каждая функция открывает
    СВОЮ сессию, поэтому состояние берётся из бэкенда (SQLite), а не из
    session_state предыдущего кадра.

Почему отдельный модуль.
    Оркестратор про Streamlit ничего не знает и получает кадры как функции,
    принимающие ``check(label, ok, evidence)``. Модуль НЕ импортирует
    оркестратор: иначе ``python scripts/video_scenario.py`` загрузил бы его
    вторым именем модуля.

Границы.
    Бэкенд поднимает оркестратор: адрес прогона лежит в ``DAY17_BACKEND_URL``
    ДО импорта этого модуля (фронтенд читает переменную на импорте
    ``frontend/api_client.py``). Ключ DeepSeek и сеть не нужны.
"""
import logging
import sys
from pathlib import Path

# Скрипт лежит в day17/scripts/, а приложение — в корне дня: добавляем корень дня
# в sys.path, чтобы AppTest мог импортировать пакет frontend из любой рабочей
# директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

from streamlit.testing.v1 import AppTest

from video_scenario_frames import TASK_REPLICA

APP_PATH = DAY_ROOT / "app.py"
CHAT_SECTION = "💬 Чат и память"
TASK_SECTION = "🧭 Состояние задачи"
SECTION_OPTIONS = [
    "💬 Чат и память", "👤 Профиль пользователя", "🧭 Состояние задачи",
    "📏 Инварианты",
]
SEND_LABEL = "🚀 Отправить"
# Нейтральный ответ заглушки бэкенда (``video_scenario_server.NEUTRAL_REPLY``) —
# в тексте ответа виден хвостом после уведомления о неприменённой реплике.
NEUTRAL_REPLY = "Принято, продолжаю по плану."


# ---------- помощники чтения дерева элементов ----------
def _mute_streamlit_noise() -> None:
    """Гасит собственные предупреждения Streamlit в выводе кадров.

    AppTest запускает приложение без ``ScriptRunContext``, поэтому Streamlit
    пишет свои предупреждения (в том числе об устаревании
    ``use_container_width`` в панели задачи) прямо между строками проверок.
    Уровень ставится ПОСЛЕ первого рендера: при разборе конфигурации Streamlit
    возвращает своим логгерам уровень из ``logger.level``, поэтому до него
    настройка не держится (проверено на streamlit 1.64).
    """
    import streamlit.logger as streamlit_logger

    streamlit_logger.set_log_level(logging.ERROR)


def _session(agent_id, section: str = TASK_SECTION) -> AppTest:
    """Свежий AppTest на app.py: активный агент и выбранный раздел.

    ``agent_id=None`` — агента ещё нет (кадр 0 показывает только переключатель
    разделов: у него не может быть состояния из прошлых кадров).
    """
    at = AppTest.from_file(str(APP_PATH), default_timeout=90)
    if agent_id:
        at.session_state["active_agent_id"] = agent_id
    at.run()
    _mute_streamlit_noise()
    at.radio(key="main_section").set_value(section).run()
    return at


def _values(elements) -> list[str]:
    """Значения элементов одной строкой каждый (``label`` — если ``value`` нет)."""
    result = []
    for element in elements:
        value = getattr(element, "value", None)
        if value is None:
            value = getattr(element, "label", "")
        result.append(str(value))
    return result


def _text(*element_lists) -> str:
    """Склейка текстов нескольких списков элементов — для поиска подстроки."""
    chunks = []
    for elements in element_lists:
        chunks.extend(_values(elements))
    return "\n".join(chunks)


def _labels(elements) -> list[str]:
    """Подписи элементов."""
    return [str(getattr(element, "label", "")) for element in elements]


def _button(at: AppTest, key: str):
    """Кнопка по ключу (``None`` — кнопки с таким ключом на странице нет)."""
    for button in at.button:
        if button.key == key:
            return button
    return None


def _button_by_label(at: AppTest, label: str):
    """Кнопка по подписи (у кнопки отправки формы своего ключа нет)."""
    for button in at.button:
        if button.label == label:
            return button
    return None


def _describe(button) -> str:
    """Короткое описание кнопки для отчёта о расхождении."""
    if button is None:
        return "кнопки с таким ключом нет"
    return f"{button.label!r}, disabled={button.disabled}"


def _line(text: str, prefix: str) -> str:
    """Строка текста, начинающаяся с префикса (для доказательства в отчёте)."""
    for line in text.splitlines():
        if line.startswith(prefix):
            return line
    return "строки нет"


def _excerpt(text: str, needle: str, width: int = 120) -> str:
    """Кусок текста вокруг ``needle`` — доказательство проверки подстроки.

    Тексты интерфейса обёрнуты в HTML (``frontend/common.py``), поэтому подстрока
    ищется, а не ищется строка с неё: доказательство показывает, что именно
    нашлось, и честно сообщает, если не нашлось ничего.
    """
    index = text.find(needle)
    if index < 0:
        return f"{needle!r} не найдено в тексте из {len(text)} символов"
    return text[index:index + width]


def _rows(at: AppTest, column: str) -> list:
    """Строки dataframe с колонкой ``column`` (пусто — такой таблицы нет)."""
    for table in at.dataframe:
        frame = table.value
        if column in list(frame.columns):
            return frame.to_dict("records")
    return []


def _locked_captions(at: AppTest) -> list[str]:
    """Строки «🔒 …» из блока «Почему часть переходов недоступна»."""
    return [value for value in _values(at.caption) if value.startswith("🔒 ")]


# ---------- кадры ----------
def frame_0_sections(agent_id, check) -> None:
    """Кадр 0, UI-часть: переключатель четырёх разделов приложения."""
    at = _session(agent_id)
    check("кадр 0: страница отрисована без исключений", not at.exception,
          f"получено: {[str(item.value) for item in at.exception]}")
    options = list(at.radio(key="main_section").options)
    check("кадр 0: переключатель четырёх разделов", options == SECTION_OPTIONS,
          f"получено: {options}")


def frame_1_create_task(agent_id: str, task_id: str, check) -> None:
    """Кадр 1: задача заводится из формы панели «Состояние задачи»."""
    at = _session(agent_id)
    at.text_input(key=f"task_state_new_id_{agent_id}").set_value(task_id)
    at.selectbox(key=f"task_state_stage_{agent_id}").set_value("planning")
    at.button(key=f"task_state_create_btn_{agent_id}").click()
    at.run()

    card = _text(at.markdown)
    check("кадр 1: карточка задачи на этапе planning",
          "**Текущий этап:** 🧭 planning — планирование" in card,
          _line(card, "**Текущий этап:**"))
    check("кадр 1: карточка задачи на шаге gather_requirements",
          "**Текущий шаг:** `gather_requirements`" in card,
          _line(card, "**Текущий шаг:**"))
    check("кадр 1: единственный допустимый следующий этап — paused",
          "**Допустимые следующие этапы:** `paused`" in card,
          _line(card, "**Допустимые следующие этапы:**"))

    expanders = _labels(at.expander)
    check("кадр 1: expander «Почему часть переходов недоступна» есть",
          "🔒 Почему часть переходов недоступна" in expanders,
          f"получено: {expanders}")

    expected = [
        "🔒 ⚙️ execution — выполнение: Нельзя перейти в execution: план не утверждён",
        "🔒 🔍 validation — валидация: Нельзя перейти из planning в validation: "
        "пропущен этап execution",
        "🔒 ✅ done — завершено: Нельзя перейти из planning в done: пропущены "
        "этапы execution и validation",
    ]
    check("кадр 1: три недоступных перехода названы причинами",
          _locked_captions(at) == expected, f"получено: {_locked_captions(at)}")

    for stage, label in (("execution", "➡️ ⚙️ execution — выполнение"),
                         ("validation", "➡️ 🔍 validation — валидация"),
                         ("done", "➡️ ✅ done — завершено")):
        button = _button(at, f"task_transition_{stage}_{task_id}")
        check(f"кадр 1: кнопка {stage} погашена без согласования плана",
              button is not None and button.disabled is True and button.label == label,
              _describe(button))
    pause, advance = (_button(at, f"task_pause_{task_id}"),
                      _button(at, f"task_advance_{task_id}"))
    check("кадр 1: «⏸ Пауза» активна",
          pause is not None and pause.disabled is False
          and pause.label == "⏸ Пауза", _describe(pause))
    check("кадр 1: «⏭ Следующий шаг» активна",
          advance is not None and advance.disabled is False
          and advance.label == "⏭ Следующий шаг", _describe(advance))


def frame_2_step_refusal(agent_id: str, task_id: str, check) -> None:
    """Кадр 2: два шага вперёд, третий упирается в guard плана."""
    at = _session(agent_id)
    for step in ("define_scope", "create_plan"):
        at.button(key=f"task_advance_{task_id}").click().run()
        card = _text(at.markdown)
        check(f"кадр 2: «Следующий шаг» довёл до {step}",
              f"**Текущий шаг:** `{step}`" in card, _line(card, "**Текущий шаг:**"))

    at.button(key=f"task_advance_{task_id}").click().run()
    errors = _values(at.error)
    check("кадр 2: выход из этапа отклонён с причиной",
          "Шаг вперёд не выполнен: Нельзя перейти в execution: план не утверждён"
          in errors, f"получено: {errors}")
    card = _text(at.markdown)
    check("кадр 2: состояние задачи не изменилось",
          "**Текущий этап:** 🧭 planning — планирование" in card
          and "**Текущий шаг:** `create_plan`" in card,
          _line(card, "**Текущий шаг:**"))
    rejected = _rows(at, "причина отказа")
    check("кадр 2: попытка видна во вкладке отказов",
          any(row.get("цель") == "execution"
              and row.get("причина отказа")
              == "Нельзя перейти в execution: план не утверждён" for row in rejected),
          f"строк: {len(rejected)}, {rejected}")


def frame_3_chat_replica(agent_id: str, check) -> None:
    """Кадр 3: реплика «подтверждаю» не подставляет флаг согласования."""
    at = _session(agent_id, CHAT_SECTION)
    at.text_area(key=f"prompt_{agent_id}").set_value(TASK_REPLICA)
    submit = _button_by_label(at, SEND_LABEL)
    check("кадр 3: кнопка отправки реплики доступна в AppTest",
          submit is not None, f"подписи кнопок: {_labels(at.button)}")
    if submit is None:
        return
    submit.click().run()

    conversation = _text(at.markdown)
    notice = ("⚠️ Переход по реплике «advance» не выполнен: Нельзя перейти в "
              "execution: план не утверждён Доступные следующие этапы: paused.")
    check("кадр 3: ответ начинается с уведомления о неприменённой реплике",
          notice in conversation, _excerpt(conversation, "⚠️ Переход по реплике"))
    check("кадр 3: диалог продолжился ответом заглушки",
          NEUTRAL_REPLY in conversation, _excerpt(conversation, NEUTRAL_REPLY))


def frame_4_flags_open_transition(agent_id: str, task_id: str, check) -> None:
    """Кадр 4: флаг «План утверждён» открывает ровно переход в execution."""
    at = _session(agent_id)
    at.checkbox(key=f"task_flag_plan_approved_{task_id}").set_value(True)
    at.button(key=f"task_flags_save_{task_id}").click().run()

    successes = _values(at.success)
    check("кадр 4: сохранение флагов подтверждено",
          "Флаги задачи сохранены." in successes, f"получено: {successes}")
    execution = _button(at, f"task_transition_execution_{task_id}")
    check("кадр 4: кнопка execution стала активной",
          execution is not None and execution.disabled is False, _describe(execution))
    check("кадр 4: причин отказа осталось две",
          len(_locked_captions(at)) == 2, f"получено: {_locked_captions(at)}")

    at.button(key=f"task_transition_execution_{task_id}").click().run()
    card = _text(at.markdown)
    check("кадр 4: переход в execution выполнен",
          "**Текущий этап:** ⚙️ execution — выполнение" in card,
          _line(card, "**Текущий этап:**"))
    check("кадр 4: переход встал на первый шаг implement",
          "**Текущий шаг:** `implement`" in card, _line(card, "**Текущий шаг:**"))

    at.button(key=f"task_advance_{task_id}").click().run()
    card = _text(at.markdown)
    check("кадр 4: следующий шаг дал test_locally",
          "**Текущий шаг:** `test_locally`" in card, _line(card, "**Текущий шаг:**"))
    at.button(key=f"task_advance_{task_id}").click().run()
    errors = _values(at.error)
    check("кадр 4: выход из execution закрыт без согласования реализации",
          "Шаг вперёд не выполнен: Нельзя перейти в validation: реализация "
          "не завершена" in errors, f"получено: {errors}")


def frame_5_pause(agent_id: str, task_id: str, check) -> None:
    """Кадр 5, часть 1: пауза сохраняет этап и шаг."""
    at = _session(agent_id)
    at.button(key=f"task_pause_{task_id}").click().run()

    card = _text(at.markdown)
    check("кадр 5: задача на паузе",
          "**Текущий этап:** ⏸ paused — пауза" in card,
          _line(card, "**Текущий этап:**"))
    check("кадр 5: пауза сохранила шаг test_locally",
          "**Текущий шаг:** `test_locally`" in card, _line(card, "**Текущий шаг:**"))
    pauses = [value for value in _values(at.caption)
              if value.startswith("⏸ Пауза с этапа")]
    check("кадр 5: карточка называет этап возврата",
          any(value.startswith("⏸ Пауза с этапа **execution**") for value in pauses),
          f"получено: {pauses}")
    target = at.selectbox(key=f"task_resume_target_{task_id}")
    check("кадр 5: селектор продолжения стоит на этапе паузы",
          target.value == "execution", f"получено: {target.value!r}")


def frame_5_resume(agent_id: str, task_id: str, check) -> None:
    """Кадр 5, часть 2: продолжение возвращает тот же этап и шаг."""
    at = _session(agent_id)
    at.button(key=f"task_resume_{task_id}").click().run()

    card = _text(at.markdown)
    check("кадр 5: продолжение вернуло этап execution",
          "**Текущий этап:** ⚙️ execution — выполнение" in card,
          _line(card, "**Текущий этап:**"))
    check("кадр 5: продолжение вернуло шаг test_locally",
          "**Текущий шаг:** `test_locally`" in card, _line(card, "**Текущий шаг:**"))


def frame_7_done_terminal(agent_id: str, task_id: str, check) -> None:
    """Кадр 7, UI-часть: у завершённой задачи погашены все кнопки."""
    at = _session(agent_id)
    card = _text(at.markdown)
    check("кадр 7: карточка показывает этап done",
          "**Текущий этап:** ✅ done — завершено" in card,
          _line(card, "**Текущий этап:**"))
    check("кадр 7: из done не объявлено ни одного перехода",
          "**Допустимые следующие этапы:** нет — переходов из этого этапа "
          "не объявлено" in card, _line(card, "**Допустимые следующие этапы:**"))

    for stage in ("planning", "execution", "validation", "paused"):
        button = _button(at, f"task_transition_{stage}_{task_id}")
        check(f"кадр 7: кнопка {stage} погашена",
              button is not None and button.disabled is True, _describe(button))
    for key, label in ((f"task_pause_{task_id}", "⏸ Пауза"),
                       (f"task_advance_{task_id}", "⏭ Следующий шаг")):
        button = _button(at, key)
        check(f"кадр 7: «{label}» погашена",
              button is not None and button.disabled is True, _describe(button))


def frame_9_journal_tabs(agent_id: str, task_id: str, check) -> None:
    """Кадр 9, UI-часть: вкладки журнала, отказы и блок системного промпта."""
    at = _session(agent_id)
    labels = _labels(at.tabs)
    check("кадр 9: три вкладки журнала задачи",
          labels == ["📜 Журнал переходов", "🚫 Попытки недопустимых переходов",
                     "🧩 Блок в системном промпте"],
          f"получено: {labels}")
    accepted = _rows(at, "причина")
    check("кадр 9: состоявшиеся переходы отрисованы",
          bool(accepted), f"строк: {len(accepted)}")
    rejected = _rows(at, "причина отказа")
    check("кадр 9: отклонённые попытки отрисованы",
          bool(rejected), f"строк: {len(rejected)}")

    prompt_blocks = [value for value in _values(at.code)
                     if "Допустимые следующие этапы:" in value]
    check("кадр 9: блок системного промпта называет допустимые этапы",
          bool(prompt_blocks), f"блоков кода: {len(_values(at.code))}")
    check("кадр 9: блок системного промпта запрещает недопустимый переход",
          any("Не пытайся перейти в недопустимый этап — сначала заверши текущий."
              in value for value in prompt_blocks),
          f"получено: {prompt_blocks}")
