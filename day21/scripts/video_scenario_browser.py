"""Набор действий прогона в реальном браузере: клики, сверки, темп «человека».

Что это.
    Базовый класс ``BrowserActions`` для автоматического прохода кадров
    (``--auto``): он умеет то, из чего состоит любой кадр, — прокрутить элемент
    в поле зрения, навести на него мышь, подождать, кликнуть, набрать текст по
    символам, дождаться нужной строки на странице и сверить её через
    ``VideoChecks``. Темп задаётся паузой между действиями и задержкой набора:
    именно из этого складывается «человеческий» ход кадров на записи.

Почему отдельный модуль.
    Кадры (``video_scenario_browser_frames.py``) читаются как сценарий: что
    нажать в кадре 4 и что проверить. Механика браузера — здесь, чтобы в кадрах
    не было ни одного селектора Playwright. Запуск (бэкенд, Streamlit, окно
    Chromium) — в точке входа: она уже владеет жизненным циклом процессов.
"""
import time
from typing import Any

from playwright.sync_api import Error as PlaywrightError

from video_scenario_checks import VideoChecks
from video_scenario_client import ApiClient

CHAT_SECTION = "💬 Чат и память"
TASK_SECTION = "🧭 Состояние задачи"
SEND_LABEL = "🚀 Отправить"
LOCK_EXPANDER = "🔒 Почему часть переходов недоступна"
BLOCKED_TAB = "🚫 Попытки недопустимых переходов"
WINDOW = {"width": 1500, "height": 1000}

# Подписи кнопок-этапов: те же, что рисует frontend/task_transitions.py.
STAGE_BUTTONS = {
    "planning": "➡️ 🧭 planning — планирование",
    "execution": "➡️ ⚙️ execution — выполнение",
    "validation": "➡️ 🔍 validation — валидация",
    "done": "➡️ ✅ done — завершено",
    "paused": "⏸ Пауза",
}



class BrowserActions:
    """Действия и сверки кадра в браузере; кадры добавляет наследник ``Walk``."""

    def __init__(self, checks: VideoChecks, page: Any, client: ApiClient,
                 pace: float, typing_ms: int) -> None:
        self.checks = checks
        self.page = page
        self.client = client
        self.pause_ms = int(pace * 1000)
        self.typing_ms = typing_ms
        self.frame_no = 0
        self.main = page.locator('[data-testid="stMain"]')
        self.sidebar = page.locator('[data-testid="stSidebar"]')

    # --- действия «как человек» ---
    def label(self, text: str) -> str:
        """Метка проверки с номером кадра: в выводе видно, какой кадр сверяется."""
        return f"кадр {self.frame_no}: {text}"

    def say(self, text: str) -> None:
        """Строка о текущем действии: по ней зритель следит за прогоном."""
        print(f"  ▸ {text}", flush=True)

    def settle(self, factor: float = 1.0) -> None:
        """Пауза между действиями — из неё и складывается человеческий темп."""
        self.page.wait_for_timeout(int(self.pause_ms * factor))

    def click(self, locator: Any, what: str) -> None:
        """Прокрутка, наведение, пауза, клик — так движение видно на записи.

        Повторяются только идемпотентные шаги (прокрутка и наведение): сам клик
        идёт один раз, потому что второй клик по кнопке шага сдвинул бы задачу
        дважды. Случайную перерисовку узла Playwright обрабатывает внутри клика —
        он сам берёт элемент заново, если тот отцепился.
        """
        self.say(what)
        target = locator.first

        def aim() -> None:
            target.scroll_into_view_if_needed(timeout=15000)
            target.hover(timeout=15000)
            self.settle(0.4)

        self.act(aim, what)
        target.click(timeout=15000)
        self.settle()

    def act(self, apply, what: str) -> None:
        """Выполняет ИДЕМПОТЕНТНОЕ действие с одним повтором.

        Streamlit перерисовывает страницу после каждого действия, поэтому узел
        может «отцепиться» между наведением и кликом. Повтор берёт элемент
        заново; если и он не удался — ошибка уходит наверх и кадр честно падает.
        """
        for attempt in (1, 2):
            try:
                apply()
                return
            except PlaywrightError:
                if attempt == 2:
                    raise
                self.say(f"{what}: страница перерисовалась, повторяю действие")
                self.settle(1.0)

    def type_slowly(self, locator: Any, text: str, what: str) -> None:
        """Набор текста по символам: в кадре видно, что печатает «человек».

        Повторять безопасно: поле сначала очищается (``fill("")``), поэтому
        повтор набирает тот же текст с нуля, а не удваивает его.
        """
        self.say(what)

        def apply() -> None:
            target = locator.first
            target.scroll_into_view_if_needed(timeout=15000)
            target.click(timeout=15000)
            target.fill("")
            target.press_sequentially(text, delay=self.typing_ms)

        self.act(apply, what)
        self.settle()

    def section(self, name: str) -> None:
        """Переключение раздела: radio основной области, не заголовок панели."""
        self.click(self.page.locator('[data-testid="stRadio"]').get_by_text(
            name, exact=True), f"открываю раздел «{name}»")

    # --- сверка с тем, что видно на странице ---
    def text(self) -> str:
        """Текст основной области: карточка, подписи, ответы агента."""
        return self.main.inner_text()

    def expect(self, label: str, needle: str, timeout: float = 25.0) -> None:
        """Ждёт строку на странице и сверяет её (ожидание и есть ход кадра)."""
        deadline = time.monotonic() + timeout
        text = self.text()
        while needle not in text and time.monotonic() < deadline:
            self.page.wait_for_timeout(250)
            text = self.text()
        found = needle in text
        where = text.find(needle)
        shown = text[max(0, where):where + 120] if found else f"нет строки {needle!r}"
        self.checks.check(self.label(label), found, shown)
        self.settle(0.5)

    def button(self, stage_or_name: str) -> Any:
        """Кнопка основной области: по этапу (``execution``) или по подписи."""
        name = STAGE_BUTTONS.get(stage_or_name, stage_or_name)
        return self.main.get_by_role("button", name=name).first

    def button_state(self, label: str, stage_or_name: str, disabled: bool) -> None:
        """Сверяет блокировку кнопок: то же, что видит зритель на экране."""
        name = STAGE_BUTTONS.get(stage_or_name, stage_or_name)
        states = [item.is_disabled() for item in
                  self.main.get_by_role("button", name=name).all()]
        self.checks.check(self.label(label),
                          bool(states) and all(state is disabled for state in states),
                          f"кнопок {len(states)}, disabled={states}")
        self.settle(0.5)

    def flags(self, *labels: str) -> None:
        """Отмечает чекбоксы флагов и сверяет, что они действительно отмечены.

        Клик мышью по квадратику невозможен: ``input`` чекбокса визуально скрыт
        (Streamlit рисует его спаном ``clip: rect(0,0,0,0)``), а у самого
        флажка нет видимой кнопки. Поэтому состояние ставится напрямую через
        ``set_checked(force=True)`` — это тот же переключатель, что у клика, но
        идемпотентный, и результат сразу видно в чекбоксе на экране.
        """
        for label in labels:
            box = self.main.locator(f'input[aria-label="{label}"]')
            self.say(f"отмечаю флаг «{label}»")
            # Именно set_checked(force=True): сам input у чекбокса визуально скрыт
            # (Streamlit рисует его спаном clip: rect(0,0,0,0)), а установка
            # состояния, в отличие от клика, идемпотентна — повтор не снимет
            # флажок, который только что отметили.
            self.act(lambda: box.first.set_checked(True, force=True, timeout=15000),
                     f"флаг «{label}»")
            self.settle(0.5)
            self.checks.check(self.label(f"флаг «{label}» отмечен"),
                              box.first.is_checked(),
                              f"checked={box.first.is_checked()}")

    def save_flags(self) -> None:
        """«💾 Сохранить флаги» и подтверждение, что они сохранены."""
        self.click(self.button("💾 Сохранить флаги"), "сохраняю флаги")
        self.expect("флаги сохранены", "Флаги задачи сохранены.")

    def open_lock_reasons(self) -> None:
        """Разворачивает «🔒 Почему часть переходов недоступна» (причины на экране).

        После каждого перерисовывания expander снова закрыт, поэтому его
        открывают перед тем кадром, где причины нужны глазам зрителя.
        """
        self.click(self.main.get_by_text(LOCK_EXPANDER),
                   "разворачиваю причины недоступных переходов")

    def lock_reasons(self) -> list:
        """Строки «🔒 …» из блока причин."""
        return [item for item in self.main.locator(
            '[data-testid="stCaptionContainer"]').all_inner_texts()
            if item.startswith("🔒 ")]

    def advance(self, what: str, expected_step: str = "") -> None:
        """«⏭ Следующий шаг» и (если задан) сверка шага после него."""
        self.click(self.button("⏭ Следующий шаг"), f"нажимаю «Следующий шаг» — {what}")
        if expected_step:
            self.expect(f"шаг задачи — {expected_step}",
                        f"Текущий шаг: {expected_step}")

    def chat(self, message: str) -> None:
        """Отправляет реплику: набор по символам и ожидание ответа агента."""
        self.section(CHAT_SECTION)
        self.type_slowly(self.main.get_by_label("Сообщение агенту"), message,
                         f"печатаю реплику «{message}»")
        self.click(self.main.get_by_role("button", name=SEND_LABEL),
                   "отправляю реплику и жду ответ агента")
