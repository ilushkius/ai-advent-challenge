"""Кадры сценария дня 17, которые проход выполняет в реальном браузере.

Что это.
    Класс ``Walk`` — по методу на кадр §8 инструкции: что нажать, что ввести, что
    должно появиться на экране. Механика браузера (клики, ожидания, сверки)
    приходит из ``video_scenario_browser.BrowserActions``, поэтому здесь нет ни
    одного селектора Playwright — только действия сценария и проверки. Заголовки
    кадров печатает запуск (``video_scenario.run_in_browser``), нумерация — как в
    §8: 0 — интро, 1 — заведение задачи, …, 9 — журнал задачи.
"""
from video_scenario_browser import (
    BLOCKED_TAB, CHAT_SECTION, TASK_SECTION, BrowserActions,
)
from video_scenario_frames import (
    PROPOSAL_PROMPT, PROPOSAL_TASK_ID, TASK_ID, TASK_REPLICA,
)


class Walk(BrowserActions):
    """Кадры 0–9: клики и сверки того, что видно на экране."""

    # --- кадры ---
    def frame_0(self) -> None:
        """Кадр 0, UI-часть: переключатель четырёх разделов на экране."""
        options = [item.strip() for item in self.page.locator(
            '[data-testid="stRadio"] label').all_inner_texts()]
        self.checks.check(self.label("переключатель четырёх разделов"),
                          all(item in options for item in (
                              CHAT_SECTION, "👤 Профиль пользователя", TASK_SECTION,
                              "📏 Инварианты")),
                          f"получено: {options}")

    def frame_1(self) -> None:
        """Кадр 1: задача заводится через форму панели."""
        self.section(TASK_SECTION)
        self.type_slowly(self.main.get_by_label("Новая задача (task_id)"), TASK_ID,
                         f"ввожу task_id «{TASK_ID}»")
        self.say("начальный этап оставляю planning (значение по умолчанию)")
        self.click(self.main.get_by_role("button", name="➕ Создать задачу"),
                   "создаю задачу")
        self.expect("карточка на этапе planning",
                    "Текущий этап: 🧭 planning — планирование")
        self.expect("шаг gather_requirements", "Текущий шаг: gather_requirements")
        self.expect("единственный доступный этап — paused",
                    "Допустимые следующие этапы: paused")
        self.open_lock_reasons()
        expected = [
            "🔒 ⚙️ execution — выполнение: Нельзя перейти в execution: план не утверждён",
            "🔒 🔍 validation — валидация: Нельзя перейти из planning в validation: "
            "пропущен этап execution",
            "🔒 ✅ done — завершено: Нельзя перейти из planning в done: пропущены "
            "этапы execution и validation",
        ]
        self.checks.check(self.label("три причины отказа названы строками"),
                          self.lock_reasons() == expected,
                          f"получено: {self.lock_reasons()}")
        for stage in ("execution", "validation", "done"):
            self.button_state(f"кнопка {stage} погашена", stage, True)
        self.button_state("«⏸ Пауза» активна", "paused", False)

    def frame_2(self) -> None:
        """Кадр 2: «Следующий шаг» упирается в guard, попытка идёт в журнал."""
        self.advance("первый шаг этапа", "define_scope")
        self.advance("второй шаг этапа", "create_plan")
        self.advance("третий шаг — этап не согласован")
        self.expect("отказ назван красным сообщением",
                    "Шаг вперёд не выполнен: Нельзя перейти в execution: "
                    "план не утверждён")
        self.expect("состояние задачи прежнее", "Текущий шаг: create_plan")
        self.click(self.page.get_by_role("tab", name=BLOCKED_TAB),
                   "открываю вкладку отклонённых попыток")
        status, journal = self.client.history(TASK_ID)
        last = (journal.get("entries") or [{}])[-1]
        self.checks.check(self.label("попытка лежит в журнале с целью execution"),
                          status == 200 and last.get("accepted") is False
                          and last.get("to_stage") == "execution",
                          f"статус {status}: {last.get('to_stage')} / "
                          f"{last.get('reason')}")

    def frame_3(self) -> None:
        """Кадр 3: реплика не подставляет флаг согласования."""
        self.chat(TASK_REPLICA)
        self.expect("ответ начинается с уведомления о реплике",
                    "⚠️ Переход по реплике «advance» не выполнен: Нельзя перейти "
                    "в execution: план не утверждён Доступные следующие этапы: paused.")
        self.expect("диалог продолжился ответом агента",
                    "Принято, продолжаю по плану.")
        status, state = self.client.state(TASK_ID)
        self.checks.check(self.label("реплика не изменила состояние задачи"),
                          (state.get("stage"), state.get("current_step"))
                          == ("planning", "create_plan"),
                          f"{state.get('stage')}/{state.get('current_step')}")

    def frame_4(self) -> None:
        """Кадр 4: флаг открывает ровно тот же переход."""
        self.section(TASK_SECTION)
        self.flags("📝 План утверждён")
        self.save_flags()
        self.open_lock_reasons()
        self.checks.check(self.label("причин отказа осталось две"),
                          len(self.lock_reasons()) == 2,
                          f"получено: {self.lock_reasons()}")
        self.button_state("кнопка execution активна", "execution", False)
        self.click(self.button("execution"), "перехожу в execution по кнопке")
        self.expect("задача в execution на шаге implement",
                    "Текущий шаг: implement")
        self.advance("локальная проверка реализации", "test_locally")
        self.advance("попытка выйти из execution без согласования")
        self.expect("выход из execution закрыт",
                    "Шаг вперёд не выполнен: Нельзя перейти в validation: "
                    "реализация не завершена")

    def frame_5(self, backend: Backend) -> int:
        """Кадр 5: пауза переживает перезапуск бэкенда; возвращает pid процесса 1."""
        self.click(self.button("paused"), "ставлю задачу на паузу")
        self.expect("задача на паузе", "Текущий этап: ⏸ paused — пауза")
        self.expect("пауза сохранила шаг test_locally",
                    "Текущий шаг: test_locally")
        first_pid = backend.pid
        self.say(f"останавливаю бэкенд (pid {first_pid}) — как Ctrl+C в терминале")
        second_pid = backend.restart(self.client)
        self.say(f"бэкенд поднят заново: pid {second_pid} на той же БД")
        status, state = self.client.state(TASK_ID)
        self.checks.check(self.label("другой процесс, состояние прочитано из SQLite"),
                          second_pid != first_pid
                          and (state.get("stage"), state.get("paused_from_stage"))
                          == ("paused", "execution"),
                          f"pid {first_pid} → {second_pid}, "
                          f"{state.get('stage')}/{state.get('paused_from_stage')}")
        self.settle(0.5)
        self.click(self.button("▶️ Продолжить"),
                   "продолжаю задачу кнопкой на этапе паузы")
        self.expect("продолжение вернуло execution/test_locally",
                    "Текущий шаг: test_locally")
        return first_pid

    def frame_6(self) -> None:
        """Кадр 6: откат с validation на execution сбрасывает согласования."""
        self.flags("⚙️ Реализация завершена")
        self.save_flags()
        self.click(self.button("validation"), "перехожу в validation")
        self.expect("validation/review", "Текущий шаг: review")
        self.advance("проверка тестов", "run_tests")
        self.click(self.button("execution"), "откатываюсь в execution кнопкой этапа")
        self.expect("откат вернул execution/implement", "Текущий шаг: implement")
        status, state = self.client.state(TASK_ID)
        context = state.get("context") or {}
        self.checks.check(self.label("согласования сброшены, план утверждён остался"),
                          "implementation_complete" not in context
                          and "validation_passed" not in context
                          and context.get("plan_approved") is True,
                          f"context: {context}")
        blocked = {item.get("stage"): item.get("reason")
                   for item in state.get("blocked") or []}
        self.checks.check(self.label("кнопка validation снова погашена с причиной"),
                          blocked.get("validation")
                          == "Нельзя перейти в validation: реализация не завершена",
                          f"получено: {blocked.get('validation')}")

    def frame_7(self) -> None:
        """Кадр 7: done терминален — погашены все кнопки."""
        self.flags("⚙️ Реализация завершена")
        self.save_flags()
        self.click(self.button("validation"), "перехожу в validation")
        self.expect("validation/review", "Текущий шаг: review")
        self.flags("✅ Валидация пройдена")
        self.save_flags()
        self.click(self.button("done"), "завершаю задачу")
        self.expect("карточка показывает done",
                    "Текущий этап: ✅ done — завершено")
        self.expect("из done не объявлено переходов",
                    "Допустимые следующие этапы: нет — переходов из этого этапа "
                    "не объявлено")
        for stage in ("planning", "execution", "validation", "paused"):
            self.button_state(f"кнопка {stage} погашена", stage, True)
        self.button_state("кнопка «Следующий шаг» погашена", "⏭ Следующий шаг", True)
        status, body = self.client.transition(TASK_ID, "paused")
        self.checks.check(self.label("попытка паузы из done — 400 с причиной"),
                          status == 400 and str(body.get("detail", "")).startswith(
                              "Нельзя перейти из done: этап done терминальный"),
                          f"статус {status}: {body.get('detail')}")

    def frame_8(self) -> None:
        """Кадр 8: предложение модели перейти в done не выполняется."""
        self.say(f"в боковой панели завожу вторую задачу «{PROPOSAL_TASK_ID}»")
        self.type_slowly(self.sidebar.get_by_label("Новая задача (task_id)"),
                         PROPOSAL_TASK_ID, "печатаю task_id второй задачи")
        self.click(self.sidebar.get_by_role("button", name="➕ Создать задачу"),
                   "создаю задачу в боковой панели")
        self.type_slowly(self.main.get_by_label("Новая задача (task_id)"),
                         PROPOSAL_TASK_ID, "завожу состояние второй задачи")
        self.click(self.main.get_by_role("button", name="➕ Создать задачу"),
                   "создаю состояние второй задачи")
        self.expect("вторая задача на planning",
                    "Текущий этап: 🧭 planning — планирование")
        self.advance("вторая задача: определение границ", "define_scope")
        self.advance("вторая задача: план описан", "create_plan")
        self.flags("📝 План утверждён")
        self.save_flags()
        self.click(self.button("execution"), "вторая задача: переход в execution")
        self.advance("вторая задача: локальная проверка", "test_locally")
        self.flags("⚙️ Реализация завершена")
        self.save_flags()
        self.click(self.button("validation"), "вторая задача: переход в validation")
        self.expect("вторая задача на validation/review", "Текущий шаг: review")
        self.chat(PROPOSAL_PROMPT)
        self.expect("ответ заменён отказом",
                    "🚧 Ответ предлагает переход в done, но это недопустимо. "
                    "Нельзя перейти в done: валидация не пройдена")
        status, state = self.client.state(PROPOSAL_TASK_ID)
        self.checks.check(self.label("состояние задачи не изменилось"),
                          (state.get("stage"), state.get("current_step"))
                          == ("validation", "review"),
                          f"{state.get('stage')}/{state.get('current_step')}")

    def frame_9(self) -> None:
        """Кадр 9: журнал первой задачи и блок системного промпта."""
        self.say(f"возвращаю активную задачу «{TASK_ID}» через боковую панель")
        # Селектор «Активная задача» перечисляет только задачи рабочей памяти;
        # первая задача заведена формой панели (состояние без записи памяти),
        # поэтому её в селекторе нет — и «человек» вернёт её тем же способом,
        # каким заводил вторую: формой «Новая задача» в боковой панели.
        self.type_slowly(self.sidebar.get_by_label("Новая задача (task_id)"),
                         TASK_ID, f"печатаю task_id «{TASK_ID}»")
        self.click(self.sidebar.get_by_role("button", name="➕ Создать задачу"),
                   "делаю задачу активной")
        self.section(TASK_SECTION)
        self.expect("панель показывает завершённую задачу",
                    "Текущий этап: ✅ done — завершено")
        for tab in ("📜 Журнал переходов", BLOCKED_TAB, "🧩 Блок в системном промпте"):
            self.click(self.page.get_by_role("tab", name=tab),
                       f"открываю вкладку «{tab}»")
        status, journal = self.client.history(TASK_ID)
        entries = journal.get("entries") or []
        rejected = [item for item in entries if item.get("accepted") is False]
        reasons = [item.get("reason") for item in rejected]
        self.checks.check(self.label("в журнале есть состоявшиеся и отклонённые записи"),
                          bool(entries) and len(rejected) >= 2,
                          f"всего {len(entries)}, отклонённых {len(rejected)}")
        for reason in ("Нельзя перейти в execution: план не утверждён",
                       "Нельзя перейти из done: этап done терминальный"):
            self.checks.check(self.label(f"в отказах есть «{reason[:36]}…»"),
                              reason in reasons, f"получено: {reasons}")
        self.expect("блок промпта называет допустимые этапы",
                    "Не пытайся перейти в недопустимый этап — сначала заверши "
                    "текущий.")
        for task_id, rows in (
            (TASK_ID, entries),
            (PROPOSAL_TASK_ID, self.client.history(PROPOSAL_TASK_ID)[1].get("entries") or []),
        ):
            accepted = sum(1 for item in rows if item.get("accepted"))
            print(f"  задача {task_id}: всего {len(rows)}, состоявшихся {accepted}, "
                  f"отклонённых {len(rows) - accepted}", flush=True)


# Заголовки кадров печатает проход: нумерация — как в §8 инструкции.
FRAME_TITLES = {
    1: "завести задачу: форма панели, клики в браузере",
    2: "«Следующий шаг» упирается в guard: состояние не меняется",
    3: "реплика не подставляет флаг: согласие — это данные",
    4: "флаг открывает ровно тот же переход, что просил сценарий",
    5: "пауза переживает перезапуск бэкенда (два разных процесса)",
    6: "откат сбрасывает согласования: старое согласие недействительно",
    7: "done терминален: погашены все кнопки и отклонена пауза",
    8: "предложение модели не выполняется: ответ заменён отказом",
    9: "журнал задачи: состоявшиеся переходы и отклонённые попытки",
}
