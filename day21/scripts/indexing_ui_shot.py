"""Снимок раздела «📦 Индексация» для отчёта (Playwright).

Скрипт делает ровно то, что делает человек: поднимает бэкенд дня и Streamlit на
своих портах, открывает страницу, переключается на раздел «📦 Индексация», нажимает
«🚀 Запустить демо-индексацию» и ждёт, пока появится таблица сравнения стратегий —
признак того, что прогон дошёл до сравнения. Затем делается PNG в
``docs/reports/indexing_ui.png``, процессы закрываются.

Зачем отдельный скрипт, а не шаг прогона: браузер нужен только для картинки, а
отчёт обязан собираться и без него (``docs/usage.md``). Поэтому любая неудача —
нет Chromium, не поднялся порт, прогон не дошёл до сравнения — печатается причиной,
а скрипт возвращает пустую строку: прогон дня продолжается, а в разделе «Артефакты»
отчёта появляется строка «скриншот не сделан».

Запуск из папки day21/ (браузер ставится один раз)::

    uv run playwright install chromium
    uv run python scripts/indexing_ui_shot.py
    uv run python scripts/indexing_ui_shot.py --timeout 300 --report docs/reports/ui.png
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# Скрипт лежит в day21/scripts/, а приложение — в корне дня: рабочая директория
# процессов именно корень дня (там .env и пути SQLite дня).
DAY_ROOT = Path(__file__).resolve().parents[1]

#: Порты по умолчанию: те же, что в инструкции запуска (docs/usage.md).
BACKEND_PORT = 8000
UI_PORT = 8501

#: Сколько ждать готовности бэкенда и Streamlit перед открытием браузера.
START_TIMEOUT = 90

#: Подпись, по которой видно, что прогон дошёл до сравнения стратегий.
COMPARISON_MARKER = "Сравнение стратегий"

#: Кнопка запуска демо-прогона и подпись раздела (те же, что в разделе интерфейса).
DEMO_BUTTON = "🚀 Запустить демо-индексацию"
SECTION_LABEL = "📦 Индексация"


def main(argv=None) -> int:
    """Делает снимок раздела; при любой неудаче печатает причину и код 1."""
    args = _parse_args(argv)
    target = Path(args.report)
    reason = shot(target, timeout=args.timeout,
                  backend_port=args.backend_port, ui_port=args.ui_port)
    if reason is None:
        print(f"скриншот: {target}")
        return 0
    print(f"скриншот не сделан: {reason}")
    return 1


def shot(target: Path, *, timeout: int, backend_port: int = BACKEND_PORT,
         ui_port: int = UI_PORT) -> str | None:
    """Снимок раздела «📦 Индексация»; ``None`` — получилось, иначе причина отказа."""
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:  # playwright не установлен (группа dev не синхронизирована)
        return f"playwright недоступен ({exc}): uv sync --dev"
    backend = _spawn_backend(backend_port)
    if isinstance(backend, str):
        return backend
    ui = _spawn_ui(ui_port, backend_port)
    if isinstance(ui, str):
        _stop([backend])
        return ui
    try:
        waited = _wait_ports(backend_port, ui_port)
        if waited:
            return waited
        with sync_playwright() as playwright:
            try:
                browser = playwright.chromium.launch()
            except PlaywrightError as exc:
                return (f"Chromium не запустился ({str(exc).splitlines()[0]}): "
                        "uv run playwright install chromium")
            try:
                return _capture(browser, target, ui_port, timeout)
            finally:
                browser.close()
    finally:
        _stop([ui, backend])


def _capture(browser, target: Path, ui_port: int, timeout: int) -> str | None:
    """Открывает раздел, запускает демо-прогон и делает снимок."""
    from playwright.sync_api import Error as PlaywrightError

    page = browser.new_page(viewport={"width": 1560, "height": 1200})
    try:
        page.goto(f"http://127.0.0.1:{ui_port}", wait_until="load", timeout=60000)
        page.wait_for_selector('[data-testid="stSidebar"]', timeout=60000)
        page.wait_for_timeout(2500)
        page.get_by_text(SECTION_LABEL, exact=False).first.click()
        page.wait_for_timeout(1500)
        page.get_by_role("button", name=DEMO_BUTTON).click()
    except PlaywrightError as exc:
        return f"интерфейс не отвечает на действия ({str(exc).splitlines()[0]})"
    try:
        page.wait_for_selector(f"text={COMPARISON_MARKER}", timeout=timeout * 1000)
    except PlaywrightError:
        return (f"прогон не дошёл до сравнения за {timeout} с: проверьте, скачана ли "
                "модель эмбеддингов (index/models) и работает ли бэкенд")
    page.wait_for_timeout(1500)
    target.parent.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(target), full_page=True)
    return None


def _spawn_backend(port: int):
    """Поднимает бэкенд дня; строка — причина отказа, иначе процесс."""
    return _spawn([sys.executable, "-m", "uvicorn", "backend.api.main:app",
                   "--port", str(port)], port, "бэкенд", health="docs")


def _spawn_ui(port: int, backend_port: int):
    """Поднимает Streamlit с адресом бэкенда прогона в окружении."""
    env = dict(os.environ, DAY21_BACKEND_URL=f"http://127.0.0.1:{backend_port}")
    return _spawn([sys.executable, "-m", "streamlit", "run", "app.py",
                   "--server.port", str(port), "--server.headless", "true"],
                  port, "Streamlit", env=env, health="_stcore/health")


def _spawn(command: list, port: int, title: str, *, env=None, health: str = ""):
    """Запускает процесс дня из корня дня и проверяет, что порт занялся им."""
    if _port_busy(port):
        return (f"порт {port} уже занят: остановите прошлый запуск {title} "
                "(или задайте другой порт ключом)")
    try:
        process = subprocess.Popen(command, cwd=str(DAY_ROOT), env=env,
                                   stdout=subprocess.DEVNULL,
                                   stderr=subprocess.DEVNULL)
    except OSError as exc:
        return f"{title} не запустился: {exc}"
    time.sleep(0.5)
    if process.poll() is not None:
        return (f"{title} завершился сразу (код {process.returncode}): "
                "проверьте зависимости (uv sync) и занятость портов")
    return process


def _wait_ports(backend_port: int, ui_port: int) -> str | None:
    """Ждёт готовности обоих портов; текст ошибки — если не дождались."""
    deadline = time.time() + START_TIMEOUT
    for port, path, title in ((backend_port, "docs", "бэкенд"),
                              (ui_port, "_stcore/health", "Streamlit")):
        while time.time() < deadline:
            if _http_ok(port, path):
                break
            time.sleep(0.5)
        else:
            return f"{title} не поднялся на порту {port} за {START_TIMEOUT} с"
    return None


def _http_ok(port: int, path: str) -> bool:
    """Отвечает ли сервис на порту (любой HTTP-ответ считается готовностью)."""
    url = f"http://127.0.0.1:{port}/{path}"
    try:
        with urllib.request.urlopen(url, timeout=3):
            return True
    except urllib.error.HTTPError:
        return True
    except OSError:
        return False


def _port_busy(port: int) -> bool:
    """Занят ли порт: свой прогон не должен подниматься поверх чужого."""
    with socket.socket() as probe:
        probe.settimeout(0.5)
        return probe.connect_ex(("127.0.0.1", port)) == 0


def _stop(processes: list) -> None:
    """Останавливает процессы прогона (молча: сбой остановки не должен мешать)."""
    for process in processes:
        try:
            process.terminate()
            process.wait(timeout=15)
        except Exception:  # noqa: BLE001 — остановка вспомогательного процесса
            try:
                process.kill()
            except Exception:  # noqa: BLE001 — процесс уже мёртв
                pass


def _parse_args(argv):
    """Разбирает аргументы: путь снимка, таймаут ожидания и порты."""
    parser = argparse.ArgumentParser(
        description="Снимок раздела «📦 Индексация» для отчёта дня 21",
    )
    parser.add_argument("--report", default="docs/reports/indexing_ui.png",
                        help="куда положить PNG (по умолчанию docs/reports/indexing_ui.png)")
    parser.add_argument("--timeout", type=int, default=1800,
                        help="сколько секунд ждать окончания демо-прогона")
    parser.add_argument("--backend-port", type=int, default=BACKEND_PORT)
    parser.add_argument("--ui-port", type=int, default=UI_PORT)
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
