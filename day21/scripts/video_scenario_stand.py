"""Стенд для съёмки видео дня 17: живой Streamlit в браузере, кадры — руками.

Что это.
    Режим ``--ui`` точки входа: поднимает изолированный бэкенд прогона
    (``video_scenario_server.Backend``), НАСТОЯЩИЙ ``streamlit run app.py`` на нём
    (``UiServer``) и открывает адрес в браузере пользователя. Печатает чек-лист
    кадров §8 инструкции: что нажать и что должно получиться. Кадр 5 (пауза,
    переживающая перезапуск) стенд доказывает сам — по Enter перезапускает
    бэкенд на той же БД и печатает прочитанное из SQLite состояние.

Зачем отдельно от ``--all``.
    ``--all`` проверяет интерфейс через ``streamlit.testing`` — быстро и строго,
    но картинки не показывает; для записи нужны браузер и живые клики. Оба режима
    описывают одни и те же кадры, поэтому чек-лист здесь повторяет значения
    проверок (``video_scenario_frames``), а после съёмки полезно прогнать
    ``--all``: он поймает расхождение кода и текста кадров.

Границы.
    Кадры проходит человек — стенд ничего не нажимает за него. Логика проверок
    живёт в ``video_scenario_frames.py`` и ``video_scenario_ui.py``; здесь только
    запуск, чек-лист и остановка.
"""
import webbrowser

from video_scenario_client import VIDEO_DB, ApiClient
from video_scenario_frames import (
    PROPOSAL_PROMPT, PROPOSAL_TASK_ID, TASK_ID, TASK_REPLICA,
)
from video_scenario_server import Backend, UiServer

# Чек-лист кадров: перед экраном он заменяет чтение §8 инструкции. Значения те же,
# что проверяет ``--all``: расхождение между чек-листом и кодом ловит
# соответствующий кадр автоматической проверки.
STAND_FRAMES: tuple = (
    ("Кадр 0 — интро",
     "показать backend/domain/task_state_machine.py (ALLOWED_TRANSITIONS, GUARDS, "
     "_REFUSAL_TEXTS) и переключатель четырёх разделов"),
    ("Кадр 1 — завести задачу",
     f"«🧭 Состояние задачи»: task_id `{TASK_ID}`, начальный этап planning → "
     "«➕ Создать задачу». Должно быть: 🧭 planning, шаг `gather_requirements`, "
     "допустимые этапы `paused`, три строки «🔒 …» с причинами, кнопки "
     "execution/validation/done погашены, «⏸ Пауза» активна"),
    ("Кадр 2 — «Следующий шаг» упирается в guard",
     "два нажатия «⏭ Следующий шаг» (define_scope, create_plan), третье — красное "
     "«Шаг вперёд не выполнен: Нельзя перейти в execution: план не утверждён», этап "
     "и шаг прежние; вкладка «🚫 Попытки недопустимых переходов» — строка с целью "
     "execution"),
    ("Кадр 3 — реплика не подставляет флаг",
     f"в чате отправить «{TASK_REPLICA}»: ответ начинается с «⚠️ Переход по реплике "
     "«advance» не выполнен: … Доступные следующие этапы: paused.», состояние "
     "задачи прежнее"),
    ("Кадр 4 — флаг открывает ровно тот же переход",
     "чекбокс «📝 План утверждён» → «💾 Сохранить флаги» («Флаги задачи сохранены.»), "
     "нажать «➡️ ⚙️ execution — выполнение» → execution/implement, затем два нажатия "
     "«⏭ Следующий шаг»: test_locally, потом отказ «реализация не завершена»"),
    ("Кадр 5 — пауза переживает перезапуск бэкенда",
     "«⏸ Пауза» → paused/test_locally; дальше нажмите Enter в терминале стенда: он "
     "перезапустит бэкенд на той же БД и напечатает состояние из SQLite. После "
     "этого в браузере «▶️ Продолжить» → execution/test_locally"),
    ("Кадр 6 — откат сбрасывает согласования",
     "«⚙️ Реализация завершена» → «💾 Сохранить флаги» → «➡️ 🔍 validation» → «⏭ "
     "Следующий шаг» (run_tests) → «➡️ ⚙️ execution» (откат): чекбоксы реализации и "
     "валидации сняты, «📝 План утверждён» остался, кнопка validation снова погашена "
     "с причиной «реализация не завершена»"),
    ("Кадр 7 — done терминален",
     "«⚙️ Реализация завершена» → validation → «✅ Валидация пройдена» → «➡️ ✅ done — "
     "завершено»: погашены все кнопки этапов, «⏸ Пауза» и «⏭ Следующий шаг», в карточке "
     "«Допустимые следующие этапы: нет — переходов из этого этапа не объявлено»"),
    ("Кадр 8 — предложение модели не выполняется",
     f"боковая панель «🗂 Задача и сессия»: новая задача `{PROPOSAL_TASK_ID}` → "
     "«➕ Создать задачу», затем в панели завести её состояние и довести до "
     f"validation/review; в чате спросить «{PROPOSAL_PROMPT}» → ответ заменён "
     "отказом «🚧 Ответ предлагает переход в done, но это недопустимо. …»"),
    ("Кадр 9 — журнал и отчёт",
     "вкладки «📜 Журнал переходов» (создание, шаги, флаги, откат, завершение), "
     "«🚫 Попытки недопустимых переходов» (все отказы) и «🧩 Блок в системном промпте»; "
     "числа отчёта — отдельным прогоном: uv run python "
     "scripts/controlled_transitions_demo.py --all"),
)


def _pause(prompt: str) -> bool:
    """Ждёт Enter; Ctrl+C или конец ввода — ``False`` (стенд пора гасить)."""
    try:
        input(prompt)
        return True
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def print_checklist() -> None:
    """Печатает чек-лист кадров: что нажать и что должно получиться."""
    print("\n  Кадры §8 — те же значения проверяет --all:", flush=True)
    for title, what in STAND_FRAMES:
        print(f"    {title}: {what}")
    print()


def stand(backend_port: int, ui_port: int) -> None:
    """Стенд для съёмки: изолированный бэкенд, живой Streamlit и браузер.

    Кадры проходит человек (по печатному чек-листу): так видео показывает
    реальный интерфейс, а не его текстовый отчёт. Кадр 5 стенд доказывает сам —
    по Enter перезапускает бэкенд на той же БД и печатает состояние из SQLite,
    поэтому пауза подтверждается двумя pid, как и в ``--all``.
    """
    backend = Backend(VIDEO_DB, backend_port)
    ui = UiServer(ui_port, f"http://127.0.0.1:{backend_port}")
    try:
        backend.start()
        client = ApiClient(ui.backend_url)
        backend.wait_ready(client)
        status, agent = client.create_agent()
        if status != 201:
            raise RuntimeError(
                f"агент стенда не создан: статус {status}, {agent.get('detail')}"
            )
        print(f"  бэкенд стенда: {ui.backend_url} (pid {backend.pid}), "
              f"агент {agent['agent_id']}, БД {VIDEO_DB.name}", flush=True)
        print(f"  стенд поднят: {ui.start()}", flush=True)
        print_checklist()

        webbrowser.open(ui.url)
        print("  браузер открыт; кадры 0–4 — в нём, кадр 5 — по Enter ниже",
              flush=True)
        if not _pause("  ⏎ Enter после «⏸ Пауза» — перезапустить бэкенд "
                      "на той же БД: "):
            return
        first_pid = backend.pid
        second_pid = backend.restart(client)
        status, state = client.state(TASK_ID)
        print(f"  бэкенд перезапущен: pid {first_pid} → {second_pid}; состояние "
              f"из SQLite: {state.get('stage')}/"
              f"{(state.get('paused_from_stage') or '—')}/"
              f"{state.get('current_step')}", flush=True)
        print("  в браузере: «▶️ Продолжить» → execution/test_locally, "
              "дальше кадры 6–9", flush=True)
        if not _pause("  ⏎ Enter — закончить съёмку и остановить стенд: "):
            return
    finally:
        ui.stop()
        backend.stop()
    print(f"  стенд остановлен; БД прогона {VIDEO_DB.name} осталась для "
          "повторной сверки", flush=True)
