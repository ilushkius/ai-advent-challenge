"""Бэкенд автопроверки кадров сценария видео дня 17 (``video_scenario.py``).

Что это.
    FastAPI-приложение дня на ИЗОЛИРОВАННОЙ БД прогона с офлайн-заглушкой
    DeepSeek плюс жизненный цикл процесса: свободный порт, запуск дочернего
    процесса, ожидание готовности, остановка. Нужно потому, что кадры 1–9
    сценария проверяются не только по API, но и реальным рендером Streamlit
    (``streamlit.testing.v1.AppTest``): интерфейсу нужен живой бэкенд по HTTP,
    а не ``TestClient`` в своём процессе. Поэтому прогон поднимает настоящий
    uvicorn и стучится в него так же, как это делает фронтенд, а кадр 5
    перезапускает процесс, чтобы пауза доказывалась чтением из SQLite.

Почему отдельный модуль, а не ``controlled_transitions_demo.py``.
    Демо-скрипт работает напрямую с ``AgentManager`` (без HTTP) — к нему
    Streamlit не подключится. Здесь поднимается сервер, а подмены те же, что в
    ``tests/e2e/test_task_transitions_api.py``: своя фабрика сессий, подмена
    ``main.get_manager`` (``backend/core/dependencies.py`` резолвит его в момент
    вызова) и заглушка клиента модели.

Границы.
    ``agents.db`` не трогается: таблицы создаются в БД прогона, а
    ``database.init_db`` глушится, чтобы lifespan бэкенда не создавал схему в
    базе приложения. Ключ DeepSeek и сеть не нужны. Дочерний процесс — точка
    входа прогона (``video_scenario.py --serve``), поэтому и ``uv run python
    scripts/video_scenario.py --all``, и прямой вызов запускают бэкенд одинаково.
"""
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.request import urlopen

# Скрипт лежит в day17/scripts/, а пакет backend — в корне дня: добавляем корень
# дня в sys.path, чтобы запуск работал из любой рабочей директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

import uvicorn

from backend.agents.agent import Agent
from backend.agents.agent_manager import AgentManager
from backend.api import main
from backend.storage import database
from backend.storage.database import init_db, make_engine, make_session_factory

# Точка входа прогона: её же запускает ``start_server`` ключом ``--serve``.
ENTRY_SCRIPT = Path(__file__).with_name("video_scenario.py")

# Нейтральный ответ заглушки: им проверяется уведомление о неприменённой
# реплике (кадр 3), чтобы в ответе не оказалось сразу двух объяснений.
NEUTRAL_REPLY = "Принято, продолжаю по плану."

# Ответ-предложение перехода: его распознаёт ``detect_stage_proposal``.
PROPOSAL_REPLY = "Задача завершена, можно сдавать."

# По этому слову в последней реплике пользователя заглушка отвечает
# предложением перехода — как во фразе кадра 8.
PROPOSAL_MARKER = "сдавать"

READY_TIMEOUT = 30.0   # сек: ожидание готовности бэкенда прогона
STOP_TIMEOUT = 10.0    # сек: ожидание остановки дочернего процесса
UI_READY_TIMEOUT = 60.0  # сек: Streamlit стартует дольше бэкенда
UI_HEALTH_PATH = "/_stcore/health"  # эндпоинт готовности Streamlit


class ScenarioStubClient:
    """Офлайн-заглушка DeepSeek: ответ зависит от реплики пользователя.

    Не имитирует модель: кадру 8 нужно, чтобы ответ содержал фразу-предложение
    перехода в ``done``, а кадру 3 — нейтральный ответ, на фоне которого видно
    уведомление о неприменённой реплике.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        """Ответ в форме OpenAI SDK (её читает ``Agent.generate``)."""
        prompt = ""
        for message in reversed(list(messages or [])):
            if message.get("role") == "user":
                prompt = message.get("content") or ""
                break
        content = (
            PROPOSAL_REPLY if PROPOSAL_MARKER in prompt.lower() else NEUTRAL_REPLY
        )
        return SimpleNamespace(
            choices=[SimpleNamespace(
                message=SimpleNamespace(content=content), finish_reason="stop",
            )],
            usage=SimpleNamespace(
                prompt_tokens=64, completion_tokens=len(content) // 4,
                total_tokens=64 + len(content) // 4,
            ),
        )


# ---------- бэкенд прогона ----------
def serve(db_path: Path, port: int) -> None:
    """Поднимает FastAPI на указанной БД с офлайн-заглушкой модели.

    Падение не перехватывается: причина видна в терминале и в коде возврата
    дочернего процесса, а оркестратор отвечает таймаутом ожидания готовности.
    """
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)  # таблицы создаём в СВОЕЙ БД, а не в agents.db
    factory = make_session_factory(engine)
    manager = AgentManager(session_factory=factory)

    # Прямой доступ к сессиям дня (мимо менеджера) — тоже на БД прогона.
    database.SessionLocal = factory
    # Lifespan бэкенда вызывает database.init_db(): глушим, чтобы он не создал
    # таблицы в agents.db. Восстановление агентов (restore_from_db) остаётся —
    # его получает наш менеджер и читает ту же БД прогона (нужно кадру 5).
    database.init_db = lambda *args, **kwargs: None
    # backend/core/dependencies.py читает main.get_manager в момент вызова,
    # поэтому одной подмены достаточно всем роутерам.
    main.get_manager = lambda: manager
    # Клиент модели создаётся агентом на вызов (agent.py: self._make_client()),
    # поэтому подмены класса хватает всем агентам процесса.
    Agent._make_client = lambda self: ScenarioStubClient()

    print(
        f"бэкенд сценария: pid={os.getpid()} port={port} db={db_path.name}",
        flush=True,
    )
    # Свой pid сообщает сам бэкенд: обёртка venv запускает интерпретатор
    # отдельным процессом, поэтому родитель не может узнать его из Popen.
    db_path.with_name(db_path.name + ".pid").write_text(
        str(os.getpid()), encoding="utf-8"
    )
    uvicorn.run(main.app, host="127.0.0.1", port=port, log_level="warning")


# ---------- жизненный цикл процесса ----------
def find_free_port() -> int:
    """Свободный порт на loopback: он печатается и уходит фронтенду кадров."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _pid_file(db: Path) -> Path:
    """Обменник pid: файл рядом с БД прогона, игнорируется Git'ом по ``*.pid``."""
    return db.with_name(db.name + ".pid")


def _read_pid(process: subprocess.Popen, db: Path, timeout: float) -> int:
    """pid, который сообщил сам бэкенд (см. ``Backend``).

    Ждём до ``timeout``: до этого дочерний процесс успевает импортировать
    зависимости дня. Смерть процесса видна сразу — причина уже напечатана им
    самим в унаследованный stderr.
    """
    path = _pid_file(db)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"бэкенд завершился с кодом {process.returncode}")
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text.isdigit():
                path.unlink(missing_ok=True)
                return int(text)
        time.sleep(0.05)
    raise RuntimeError(f"бэкенд не сообщил свой pid за {timeout:.0f} с")


class Backend:
    """Бэкенд прогона как процесс: запуск, готовность, остановка, pid.

    pid бэкенда сообщает сам процесс (``serve`` пишет его рядом с БД): в venv
    ``.venv/Scripts/python.exe`` — обёртка, которая запускает интерпретатор
    ОТДЕЛЬНЫМ процессом, поэтому ``Popen.pid`` не равен pid приложения. Кадру 5
    нужны два РАЗНЫХ pid на одной БД — это и есть доказательство того, что
    пауза пережила перезапуск процесса.
    """

    def __init__(self, db: Path, port: int) -> None:
        self.db = db
        self.port = port
        self.process: subprocess.Popen | None = None
        self.pid = 0

    def start(self) -> int:
        """Запускает бэкенд отдельным процессом и читает его pid."""
        _pid_file(self.db).unlink(missing_ok=True)  # чужой pid прошлого запуска
        self.process = subprocess.Popen(
            [sys.executable, str(ENTRY_SCRIPT),
             "--serve", "--db", str(self.db), "--port", str(self.port)],
            cwd=str(DAY_ROOT),
        )
        self.pid = _read_pid(self.process, self.db, READY_TIMEOUT)
        return self.pid

    def wait_ready(self, client: Any) -> None:
        """Ждёт, пока приложение начнёт отвечать на ``GET /``.

        ``client`` — HTTP-клиент прогона (``video_scenario.ApiClient``): нужен
        только его метод ``request``.
        """
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"бэкенд завершился с кодом {self.process.returncode}"
                )
            try:
                status, _ = client.request("GET", "/")
            except OSError:  # порт ещё не слушается (RequestException → OSError)
                time.sleep(0.2)
                continue
            if status == 200:
                return
            time.sleep(0.2)
        raise RuntimeError(f"бэкенд не ответил за {READY_TIMEOUT:.0f} с")

    def stop(self) -> None:
        """Останавливает бэкенд: terminate, ожидание, при нужде kill."""
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"  бэкенд (pid {self.pid}) не вышел за {STOP_TIMEOUT:.0f} с "
                  "— kill()", flush=True)
            self.process.kill()
            self.process.wait(timeout=STOP_TIMEOUT)

    def restart(self, client: Any) -> int:
        """Останавливает и поднимает заново на той же БД и порту."""
        self.stop()
        pid = self.start()
        self.wait_ready(client)
        return pid


class UiServer:
    """Живой Streamlit-стенд: настоящий ``streamlit run app.py`` для записи видео.

    Нужен отдельно от ``Backend``: ``--all`` проверяет интерфейс через AppTest
    (без браузера и без визуальной картинки), а видео снимают глазами, поэтому
    стенд поднимает настоящий Streamlit на изолированном бэкенде прогона —
    фронтенд читает адрес бэкенда из ``DAY17_BACKEND_URL`` (иначе ушёл бы на
    порт 8000 к приложению пользователя) — и открывает адрес в браузере.
    """

    def __init__(self, port: int, backend_url: str) -> None:
        self.port = port
        self.backend_url = backend_url
        self.process: subprocess.Popen | None = None

    @property
    def url(self) -> str:
        """Адрес стенда (его печатают и открывают в браузере)."""
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> str:
        """Поднимает Streamlit на бэкенде прогона и возвращает адрес стенда."""
        env = dict(os.environ, DAY17_BACKEND_URL=self.backend_url)
        self.process = subprocess.Popen(
            [sys.executable, "-m", "streamlit", "run", "app.py",
             "--server.port", str(self.port),
             "--server.headless", "true",       # браузер открываем сами
             # Предупреждения Streamlit (устаревание use_container_width в панели
             # задачи) сыпались бы между строками кадров и мешали читать запись:
             # нужен только ERROR и выше — настоящие ошибки остаются видны.
             "--logger.level", "error",
             "--browser.gatherUsageStats", "false"],
            cwd=str(DAY_ROOT), env=env,
        )
        self.wait_ready()
        return self.url

    def wait_ready(self) -> None:
        """Ждёт эндпоинт здоровья Streamlit (``/_stcore/health``)."""
        deadline = time.monotonic() + UI_READY_TIMEOUT
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"Streamlit завершился с кодом {self.process.returncode}"
                )
            try:
                with urlopen(f"{self.url}{UI_HEALTH_PATH}", timeout=2) as response:
                    if response.status == 200:
                        return
            except OSError:  # порт ещё не слушается либо приложение не готово
                time.sleep(0.3)
                continue
            time.sleep(0.3)
        raise RuntimeError(f"Streamlit не ответил за {UI_READY_TIMEOUT:.0f} с")

    def stop(self) -> None:
        """Останавливает Streamlit: terminate, ожидание, при нужде kill."""
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"  Streamlit не вышел за {STOP_TIMEOUT:.0f} с — kill()",
                  flush=True)
            self.process.kill()
            self.process.wait(timeout=STOP_TIMEOUT)
