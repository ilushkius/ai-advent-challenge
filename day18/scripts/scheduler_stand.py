"""Изолированный бэкенд дня 18 для прогона сценариев планировщика.

Что это.
    Тот же ``backend.api.main:app``, но на СВОЕЙ БД, с офлайн-заглушкой DeepSeek и
    детерминированным источником данных вместо интернета. Прогон сценариев
    (``scripts/scheduler_demo.py``) поднимает этот стенд отдельным процессом и
    стучится в него по HTTP — как это делает интерфейс, — а инструменты
    планировщика вызывает по-настоящему: через свой MCP-сервер по stdio.

Зачем отдельный модуль.
    Сценарий 4 проверяет восстановление задач ПОСЛЕ перезапуска, значит нужен
    настоящий процесс, который можно остановить и поднять снова на той же БД.
    Плюс фон живёт в процессе бэкенда (APScheduler), поэтому прогон обязан идти
    против живого uvicorn, а не против ``TestClient``.

Границы.
    ``agents.db`` не трогается: схема создаётся в БД прогона, а
    ``database.init_db`` глушится — иначе lifespan бэкенда создал бы таблицы в
    базе приложения. Ключ DeepSeek и сеть не нужны: источник данных по умолчанию
    подменён (``StandPosts``), а модель — заглушкой.

Запуск стенда руками (нужен, только чтобы посмотреть на прогон глазами):

    uv run python scripts/scheduler_stand.py --serve --db day18_run.db --port 8100
"""
from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Callable

# Скрипт лежит в day18/scripts/, а пакеты backend и mcp_server — в корне дня:
# добавляем корень дня в sys.path, чтобы запуск работал из любой директории.
DAY_ROOT = Path(__file__).resolve().parents[1]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

import uvicorn  # noqa: E402

from backend.agents.agent import Agent  # noqa: E402
from backend.agents.agent_manager import AgentManager  # noqa: E402
from backend.api import main as api_main  # noqa: E402
from backend.services.schedule_service import ScheduleService  # noqa: E402
from backend.services.scheduler import TaskScheduler  # noqa: E402
from backend.services.source_fetch import fetch_json  # noqa: E402
from backend.storage import database  # noqa: E402
from backend.storage.database import init_db, make_engine, make_session_factory  # noqa: E402
from backend.storage.scheduler_data_store import SchedulerDataStore  # noqa: E402
from backend.storage.scheduler_store import SchedulerStore  # noqa: E402

#: Точка входа стенда: её же запускает ``StandProcess`` ключом ``--serve``.
ENTRY_SCRIPT = Path(__file__)

#: Пределы ожидания: старт процесса и его остановка.
READY_TIMEOUT = 60.0
STOP_TIMEOUT = 15.0

#: Адрес источника у подменённого источника: адрес нужен только как аргумент
#: инструмента (``validate_arguments`` требует http/https), данные стенд отдаёт сам.
STAND_SOURCE_URL = "http://stand.local/posts"

#: Настоящий источник: используется, если у стенда задан ``--source-url``.
LIVE_SOURCE_URL = "https://jsonplaceholder.typicode.com/posts"


class StandPosts:
    """Детерминированный источник данных: счётчик вызовов вместо сети.

    Каждый вызов отдаёт список ДРУГОЙ длины (3, 4 или 5 постов) с другими
    значениями — так в сводке видно, что период пересчитывается, а не повторяет
    первую запись.
    """

    def __init__(self) -> None:
        self.calls = 0

    def __call__(self, url: str) -> list[dict[str, Any]]:
        """Ответ в форме jsonplaceholder: id, автор, заголовок и текст."""
        self.calls += 1
        size = 3 + self.calls % 3
        return [
            {
                "id": self.calls * 10 + index,
                "userId": 1,
                "title": f"пост {self.calls * 10 + index}",
                "body": f"тело {self.calls * 10 + index}",
            }
            for index in range(size)
        ]


class StandStubClient:
    """Офлайн-заглушка DeepSeek: отвечает по блоку планировщика из промпта.

    Не имитирует модель, а доказывает главное: агент действительно поставил
    фоновую задачу и модель об этом узнала (блок «Данные планировщика» в системном
    промпте). Без блока заглушка честно говорит, что данных нет.
    """

    def __init__(self) -> None:
        self.chat = SimpleNamespace(completions=self)

    def create(self, model, messages, temperature=None, max_tokens=None):
        """Ответ в форме OpenAI SDK (её читает ``Agent.generate``)."""
        system = next(
            (item.get("content", "") for item in messages if item.get("role") == "system"),
            "",
        )
        if "## Данные планировщика" in system:
            content = "[заглушка] фоновая задача поставлена: " + system.split(
                "## Данные планировщика", 1)[1].strip().splitlines()[0]
        else:
            content = "[заглушка] фоновой задачи в запросе нет"
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=content),
                                     finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=len(system) // 4,
                                  completion_tokens=len(content) // 4,
                                  total_tokens=(len(system) + len(content)) // 4),
        )


def make_fetcher(source_url: str) -> tuple[Callable[..., Any], str]:
    """Источник данных стенда: подменённый (по умолчанию) или настоящий.

    Возвращает пару «функция чтения, адрес для аргумента инструмента». Настоящий
    источник включается непустым ``--source-url`` — тогда адрес берётся оттуда, а
    чтение идёт через общий ``fetch_json`` (тот же, что в приложении).
    """
    if source_url:
        return fetch_json, source_url
    return StandPosts(), STAND_SOURCE_URL


# ---------- бэкенд прогона ----------
def serve(db_path: Path, port: int, source_url: str = "") -> None:
    """Поднимает FastAPI на указанной БД с заглушками модели и источника.

    Падение не перехватывается: причина видна в терминале и в коде возврата
    дочернего процесса, а оркестратор отвечает таймаутом ожидания готовности.
    """
    engine = make_engine(f"sqlite:///{db_path.as_posix()}")
    init_db(engine)  # таблицы создаём в СВОЕЙ БД, а не в agents.db
    factory = make_session_factory(engine)
    manager = AgentManager(session_factory=factory)

    fetch, label = make_fetcher(source_url)
    store = SchedulerStore(session_factory=factory)
    data = SchedulerDataStore(session_factory=factory)
    scheduler = TaskScheduler(store=store, data=data, fetch=fetch)
    service = ScheduleService(scheduler=scheduler, store=store, data=data, fetch=fetch)

    # Прямой доступ к сессиям дня — тоже на БД прогона.
    database.SessionLocal = factory
    # Lifespan бэкенда вызывает database.init_db(): глушим, чтобы он не создал
    # таблицы в agents.db. Восстановление агентов и планировщика остаётся — им
    # занимается наш менеджер и наш планировщик на БД прогона (это и проверяет
    # сценарий 4).
    database.init_db = lambda *args, **kwargs: None
    # dependencies резолвит эти функции по атрибутам backend.api.main в момент
    # вызова, поэтому одной подмены хватает и роутерам, и lifespan. Модуль
    # импортирован под именем ``api_main``: у стенда своя функция ``main`` — точка
    # входа дочернего процесса, и без псевдонима она заслоняла бы модуль бэкенда.
    api_main.get_manager = lambda: manager
    api_main.get_scheduler = lambda: scheduler
    api_main.get_schedule_service = lambda: service
    # Клиент модели создаётся агентом на вызов (agent.py: self._make_client()).
    Agent._make_client = lambda self: StandStubClient()

    print(
        f"бэкенд прогона: pid={os.getpid()} port={port} db={db_path.name} "
        f"источник={label}",
        flush=True,
    )
    # Свой pid сообщает сам бэкенд: обёртка venv запускает интерпретатор
    # отдельным процессом, поэтому родитель не может узнать его из Popen.
    db_path.with_name(db_path.name + ".pid").write_text(str(os.getpid()), encoding="utf-8")
    uvicorn.run(api_main.app, host="127.0.0.1", port=port, log_level="warning")


# ---------- жизненный цикл процесса ----------
def find_free_port() -> int:
    """Свободный порт на loopback: его получает и стенд, и клиент прогона."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _pid_file(db: Path) -> Path:
    """Обменник pid: файл рядом с БД прогона, игнорируется Git'ом по ``*.pid``."""
    return db.with_name(db.name + ".pid")


def _read_pid(process: subprocess.Popen, db: Path, timeout: float) -> int:
    """pid, который сообщил сам бэкенд (см. ``StandProcess``)."""
    path = _pid_file(db)
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"бэкенд прогона завершился с кодом {process.returncode}")
        if path.exists():
            text = path.read_text(encoding="utf-8").strip()
            if text.isdigit():
                path.unlink(missing_ok=True)
                return int(text)
        time.sleep(0.05)
    raise RuntimeError(f"бэкенд прогона не сообщил свой pid за {timeout:.0f} с")


class StandProcess:
    """Бэкенд прогона как процесс: запуск, готовность, остановка, перезапуск.

    Запуск идёт ОТДЕЛЬНЫМ процессом (как в жизни), потому что фон и БД должны
    принадлежать ему: только так сценарий 4 доказывает, что задачи переживают
    перезапуск, а не «остались в памяти теста».
    """

    def __init__(self, db: Path, port: int, source_url: str = "") -> None:
        self.db = db
        self.port = port
        self.source_url = source_url
        self.process: subprocess.Popen | None = None
        self.pid = 0
        self.pids: list[int] = []

    @property
    def base_url(self) -> str:
        """Адрес стенда (его получает и MCP-сервер, и клиент прогона)."""
        return f"http://127.0.0.1:{self.port}"

    def start(self) -> int:
        """Запускает стенд отдельным процессом и читает его pid."""
        _pid_file(self.db).unlink(missing_ok=True)  # чужой pid прошлого запуска
        command = [sys.executable, str(ENTRY_SCRIPT),
                   "--serve", "--db", str(self.db), "--port", str(self.port)]
        if self.source_url:
            command += ["--source-url", self.source_url]
        self.process = subprocess.Popen(command, cwd=str(DAY_ROOT))
        self.pid = _read_pid(self.process, self.db, READY_TIMEOUT)
        self.pids.append(self.pid)
        return self.pid

    def wait_ready(self, request) -> None:
        """Ждёт, пока стенд начнёт отвечать на ``GET /scheduler/status``.

        ``request`` — функция ``(method, path) -> (код, тело)`` клиента прогона:
        ждать готовности по HTTP надо так же, как это делает интерфейс.
        """
        deadline = time.monotonic() + READY_TIMEOUT
        while time.monotonic() < deadline:
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError(
                    f"бэкенд прогона завершился с кодом {self.process.returncode}"
                )
            try:
                status, _ = request("GET", "/scheduler/status")
            except OSError:  # порт ещё не слушается
                time.sleep(0.2)
                continue
            if status == 200:
                return
            time.sleep(0.2)
        raise RuntimeError(f"бэкенд прогона не ответил за {READY_TIMEOUT:.0f} с")

    def stop(self) -> None:
        """Останавливает стенд: terminate, ожидание, при нужде kill."""
        if self.process is None or self.process.poll() is not None:
            return
        self.process.terminate()
        try:
            self.process.wait(timeout=STOP_TIMEOUT)
        except subprocess.TimeoutExpired:
            print(f"  стенд (pid {self.pid}) не вышел за {STOP_TIMEOUT:.0f} с — kill()",
                  flush=True)
            self.process.kill()
            self.process.wait(timeout=STOP_TIMEOUT)

    def restart(self, request) -> int:
        """Останавливает и поднимает стенд заново на той же БД и порту."""
        self.stop()
        pid = self.start()
        self.wait_ready(request)
        return pid


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Аргументы стенда: он же точка входа дочернего процесса прогона."""
    parser = argparse.ArgumentParser(
        prog="scheduler_stand.py",
        description=(
            "Изолированный бэкенд дня 18 для прогона сценариев планировщика: "
            "своя БД, офлайн-заглушка модели и детерминированный источник данных."
        ),
    )
    parser.add_argument("--serve", action="store_true",
                        help="поднять бэкенд (режим дочернего процесса)")
    parser.add_argument("--db", default="scheduler_run.db",
                        help="файл БД прогона (по умолчанию scheduler_run.db)")
    parser.add_argument("--port", type=int, default=0,
                        help="порт (0 — свободный)")
    parser.add_argument("--source-url", default="",
                        help=("настоящий адрес источника вместо подменённого "
                              "(по умолчанию данные стенда, сеть не нужна)"))
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Поднимает стенд (режим ``--serve``) или подсказывает, как это сделать."""
    args = parse_args(argv)
    if not args.serve:
        print(
            "Стенд запускается прогоном: uv run python scripts/scheduler_demo.py\n"
            "Или вручную: uv run python scripts/scheduler_stand.py --serve "
            "--db scheduler_run.db --port 8100"
        )
        return 0
    serve(Path(args.db), args.port or find_free_port(), args.source_url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
