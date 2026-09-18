"""Автопроверка кадров сценария видео дня 15 (``docs/usage.md`` §8).

Что делает.
    Проходит кадры 0–9 инструкции и печатает доказательство каждого: правила
    допуска, отказ «план не утверждён» с журналом, неприменённую реплику,
    флаг, открывающий ровно один переход, паузу, переживающую перезапуск
    бэкенда, откат со сбросом согласований, терминальный ``done``, отказ на
    предложение модели и журнал задачи. Проверки идут двумя путями: запросами
    к бэкенду по HTTP и реальным рендером интерфейса через
    ``streamlit.testing.v1.AppTest``. Расхождение кода и кадра печатается как
    ``✗`` и останавливает прогон — код возврата 1, поэтому запись видео не
    покажет «прошло молча».

Запуск (из папки дня, ``uv sync`` уже выполнен):

    uv run python scripts/video_scenario.py --all     # все кадры, код 0 — совпало
    uv run python scripts/video_scenario.py --auto    # кадры в браузере вместо человека
    uv run python scripts/video_scenario.py --ui      # стенд для записи: браузер + UI
    uv run python scripts/video_scenario.py --reset   # удалить БД прогона
    uv run python scripts/video_scenario.py --serve --db <файл> --port <порт>
                                                      # только бэкенд кадров

Чем отличаются ``--all``, ``--auto`` и ``--ui``.
    ``--all`` — автоматическая проверка: интерфейс рендерится через AppTest, без
    браузера, и каждая проверка печатается как ``✓``/``✗``. ``--auto`` — тот же
    проход кадров, но в НАСТОЯЩЕМ браузере (Chromium) с темпом демонстрации:
    пауза ``--pace`` (по умолчанию 2 с) между действиями, набор текста по
    символам ``--typing`` (120 мс), наведение и прокрутка перед кликом, строка
    «▸ …» в терминале о текущем действии. По умолчанию весь прогон занимает
    **3–4 минуты** — столько, сколько нужно записи; ``--pace 0.15 --typing 1``
    ускоряет его до минуты (машинная проверка), ``--pace 6`` замедляет до
    спокойного показа, ``--headless`` убирает окно. ``--ui`` — стенд для съёмки:
    кадры проходит человек, а кадр 5 стенд доказывает по Enter.

Что НЕ трогается.
    База приложения ``day15/agents.db``: прогон поднимает uvicorn на СВОЕЙ
    ``video_scenario.db`` (``video_scenario_server.py``) и своём порту. Отчёт
    ``docs/reports/controlled_transitions_demo.md`` тоже не перегенерируется —
    его числа даёт отдельный прогон
    ``uv run python scripts/controlled_transitions_demo.py --all``. Ключ DeepSeek
    и сеть не нужны: модель заменена заглушкой бэкенда прогона.

Один запуск за раз.
    БД прогона одна на все режимы, поэтому второй ``--all`` или ``--ui`` при
    работающем стенде в другом терминале не стартует: он скажет, что
    ``video_scenario.db`` занят, и попросит остановить прошлый прогон (Ctrl+C).
    Приложения пользователя это не касается — у него своя БД.

Модули прогона.
    ``video_scenario_frames.py`` — кадры 0–9 (проверки по HTTP и перезапуск),
    ``video_scenario_ui.py`` — UI-кадры через AppTest,
    ``video_scenario_server.py`` — бэкенд на изолированной БД, заглушка модели
    и жизненный цикл его процесса, ``video_scenario_stand.py`` — стенд для
    съёмки (живой Streamlit в браузере и чек-лист кадров). Здесь остаются печать
    проверок, HTTP-клиент, оркестрация кадров ``--all`` и CLI.
"""
import os
import sys
from pathlib import Path

# Скрипт лежит в day15/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

import video_scenario_frames as frames
from video_scenario_checks import ScenarioFailed, VideoChecks, summary
from video_scenario_client import VIDEO_DB, ApiClient
from video_scenario_server import Backend, UiServer, find_free_port

# Темп режима ``--auto``: пауза между действиями и задержка на символ набора.
# Значения подобраны так, чтобы ВЕСЬ прогон (§8: 10 кадров, ~70 проверок) уложился
# примерно в 3–4 минуты — это темп демонстрации для записи: действия идут заметно,
# экран читается, но не «стоит» по 12 секунд на клик (проверено: 10× медленнее =
# больше двух часов). Совсем без пауз прогон идёт меньше минуты — это машинная
# проверка: ``--pace 0.15 --typing 1``.
AUTO_PACE = 2.0
AUTO_TYPING_MS = 120

def run() -> None:
    """Прогон кадров 0–9: домен, бэкенд, кадры, сводка."""
    checks = VideoChecks()
    backend = Backend(VIDEO_DB, find_free_port())
    try:
        frames.frame_0_rules(checks)
        backend.start()
        client = ApiClient(f"http://127.0.0.1:{backend.port}")
        backend.wait_ready(client)
        print(f"  бэкенд прогона готов: {client.base_url} (pid {backend.pid})",
              flush=True)
        # Фронтенд кэширует адрес бэкенда на импорте frontend/api_client.py,
        # поэтому переменная ставится ДО первого кадра с интерфейсом, а модуль
        # UI-кадров импортируется здесь же: бэкенду прогона (--serve) Streamlit
        # не нужен вовсе.
        os.environ["DAY15_BACKEND_URL"] = client.base_url
        import video_scenario_ui as ui

        agent_id = frames.frame_1(checks, client, ui)
        frames.frame_2(checks, client, agent_id, ui)
        frames.frame_3(checks, client, agent_id, ui)
        frames.frame_4(checks, client, agent_id, ui)
        first_pid = backend.pid
        frames.frame_5(checks, client, agent_id, backend, ui)
        frames.frame_6(checks, client)
        frames.frame_7(checks, client, agent_id, ui)
        frames.frame_8(checks, client, agent_id)
        frames.frame_9(checks, client, agent_id, ui)
        summary(checks, backend, first_pid)
    finally:
        backend.stop()


def run_in_browser(checks: VideoChecks, pace: float, typing_ms: int,
                   headless: bool, backend_port: int, ui_port: int) -> None:
    """Режим ``--auto``: кадры 0–9 в настоящем браузере с человеческим темпом.

    Playwright импортируется здесь, а не на импорте модуля: остальным режимам
    (``--all``, ``--ui``, ``--serve``) браузер не нужен, и платить за него
    секундой запуска незачем. Браузер закрывает сам контекст ``sync_playwright``:
    явный ``close()`` в ``finally`` падал после выхода контекста и ПРЕРЫВАЛ
    остановку бэкенда и Streamlit — те оставались жить и держали БД прогона.
    """
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from video_scenario_browser import WINDOW
    from video_scenario_browser_frames import FRAME_TITLES, Walk

    frames.frame_0_rules(checks)  # таблицы допуска — как в --all
    backend = Backend(VIDEO_DB, backend_port)
    ui = UiServer(ui_port, f"http://127.0.0.1:{backend_port}")
    first_pid = 0
    try:
        backend.start()
        client = ApiClient(ui.backend_url)
        backend.wait_ready(client)
        status, agent = client.create_agent()
        if status != 201:
            raise RuntimeError(
                f"агент прогона не создан: статус {status}, {agent.get('detail')}"
            )
        print(f"  бэкенд прогона: {ui.backend_url} (pid {backend.pid}), "
              f"агент {agent['agent_id']}, БД {VIDEO_DB.name}", flush=True)
        print(f"  браузер: {'без окна (--headless)' if headless else 'видимое окно'}"
              f", темп {pace} с между действиями, набор {typing_ms} мс/символ",
              flush=True)
        ui.start()
        walker = None
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch(headless=headless)
                page = browser.new_page(viewport=WINDOW)
                page.goto(ui.url, wait_until="load")
                page.wait_for_selector('[data-testid="stSidebar"]', timeout=60000)
                page.wait_for_timeout(2500)
                walker = Walk(checks, page, client, pace, typing_ms)
                for number, frame in enumerate((walker.frame_0, walker.frame_1,
                                                walker.frame_2, walker.frame_3,
                                                walker.frame_4)):
                    walker.frame_no = number
                    if number:
                        checks.frame(number, FRAME_TITLES[number])
                    frame()
                walker.frame_no = 5
                checks.frame(5, FRAME_TITLES[5])
                first_pid = walker.frame_5(backend)
                for number in (6, 7, 8, 9):
                    walker.frame_no = number
                    checks.frame(number, FRAME_TITLES[number])
                    getattr(walker, f"frame_{number}")()
            except PlaywrightError as exc:
                # Действие кадра не выполнилось в браузере: тот же контракт, что у
                # несошедшейся проверки — строка и код 1, без трассировки.
                number = walker.frame_no if walker is not None else 0
                raise ScenarioFailed(
                    f"кадр {number}: браузер не выполнил действие — "
                    f"{str(exc).splitlines()[0]}"
                ) from exc
        summary(checks, backend, first_pid)
    finally:
        ui.stop()
        backend.stop()


# ---------- CLI ----------
def reset() -> None:
    """Удаляет БД прогона и её pid-обменник: чистый старт без остатков.

    Файл, открытый другим процессом (прошлый стенд или прогон), на Windows
    удалить нельзя — это не повод падать с трассировкой: говорим, что занято и
    что с этим сделать. Одна БД прогона на всё: пока идёт стенд в другом
    терминале, второй прогон стартовать нельзя.
    """
    for path in (VIDEO_DB, VIDEO_DB.with_name(VIDEO_DB.name + ".pid")):
        if not path.exists():
            print(f"отсутствует: {path.name}")
            continue
        try:
            path.unlink()
        except OSError as exc:
            raise RuntimeError(
                f"{path.name} занят другим процессом "
                f"({exc.strerror or exc}): остановите прошлый прогон или стенд "
                "(Ctrl+C в его терминале) и повторите"
            ) from exc
        print(f"удалено: {path.name}")


def _option(argv: list, name: str) -> str:
    """Значение ключа командной строки; ключа нет — пустая строка.

    Ключ со пропущенным значением (``--ui-port`` в конце строки) — явная ошибка
    вызова, поэтому она не превращается в «взяли значение по умолчанию».
    """
    if name not in argv:
        return ""
    if argv.index(name) + 1 >= len(argv):
        raise SystemExit(f"нужен {name} со значением: см. докстринг модуля")
    return argv[argv.index(name) + 1]


def _guarded(*steps) -> int:
    """Общий контур отказа: шаги подряд, первый сбой — код 1.

    Шаги — это ``reset`` плюс сам прогон: и удаление занятой БД, и расхождение
    кадра обязаны кончаться не трассировкой, а строкой «✗ прогон остановлен».
    ``ScenarioFailed`` — проверка кадра не сошлась, ``RuntimeError`` — сбой
    инфраструктуры (старт/остановка/готовность бэкенда или Streamlit, занятая БД).
    """
    try:
        for step in steps:
            step()
    except (ScenarioFailed, RuntimeError) as exc:
        print(f"\n✗ прогон остановлен: {exc}", flush=True)
        return 1
    return 0


def main(argv: list) -> int:
    """CLI: ``--all``, ``--ui``, ``--reset``, ``--serve``; без ключей — подсказка."""
    if "--reset" in argv:
        return _guarded(reset)
    if "--serve" in argv:
        # Бэкенд поднимается только в дочернем процессе: оркестратору FastAPI не
        # нужен (иначе он создал бы движок на agents.db), поэтому импорт ленивый.
        import video_scenario_server

        db, port = _option(argv, "--db"), _option(argv, "--port")
        if not db or not port:
            raise SystemExit("нужны --db и --port: см. докстринг модуля")
        video_scenario_server.serve(Path(db), int(port))
        return 0
    if "--all" in argv:
        return _guarded(reset, run)
    if "--auto" in argv:
        return _guarded(reset, lambda: run_in_browser(
            VideoChecks(),
            float(_option(argv, "--pace") or AUTO_PACE),
            int(_option(argv, "--typing") or AUTO_TYPING_MS),
            "--headless" in argv,
            int(_option(argv, "--port") or find_free_port()),
            int(_option(argv, "--ui-port") or find_free_port()),
        ))
    if "--ui" in argv:
        import video_scenario_stand

        # Порты необязательны: по умолчанию свободные, фиксированные — чтобы
        # адрес стенда можно было открыть из закладки и запомнить для записи.
        backend_port = int(_option(argv, "--port") or find_free_port())
        ui_port = int(_option(argv, "--ui-port") or find_free_port())
        return _guarded(reset,
                        lambda: video_scenario_stand.stand(backend_port, ui_port))

    print(__doc__)
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
