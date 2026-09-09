# День 7 — Агент DeepSeek с контекстной памятью (FastAPI + Streamlit + SQLite)

Веб-приложение развивает день 6: каждый LLM-агент теперь ведёт **полный диалог
с памятью**. Каждая реплика (`user`/`assistant`) сохраняется в **SQLite**, при
каждом запросе в DeepSeek уходит **вся история сообщений**, а не один последний
промпт. Диалоги переживают перезапуск бэкенда: при старте агенты и их история
восстанавливаются из базы.

## Архитектура

```
Streamlit (порт 8501) ── HTTP (requests) ──► FastAPI (порт 8000) ──► DeepSeek API
                                              │                        https://api.deepseek.com
                                              │
                                              ▼
                                     AgentManager (синглтон)
                                        └─ Agent × N (конфигурация + self.messages)
                                              │
                                              ▼
                                    SQLAlchemy → SQLite (day7/agents.db)
                                    таблицы: agents (конфигурация)
                                             messages (диалог, FK → agents)
```

Поток одного сообщения: **пользователь → интерфейс → агент → история → БД →
API → ответ → история → БД** (детали — [docs/architecture.md](docs/architecture.md)).

## Структура

```
day7/
├── app.py               # Streamlit-чат (сообщения, ввод снизу, кнопки)
├── backend/
│   ├── __init__.py
│   ├── config.py        # URL/дефолты + чтение DEEPSEEK_API_KEY + путь к БД
│   ├── database.py      # SQLAlchemy: engine, сессии, ORM agents/messages
│   ├── agent.py         # класс Agent: self.messages + SQLite (память диалога)
│   ├── agent_manager.py # AgentManager: пул агентов, restore, история
│   ├── models.py        # Pydantic-схемы API
│   └── main.py          # FastAPI: 7 эндпоинтов
├── docs/
│   ├── architecture.md  # архитектура, схемы БД, потоки данных
│   ├── api.md           # документация эндпоинтов с примерами
│   └── usage.md         # установка, запуск, сценарии, демо, FAQ
├── requirements.txt     # fastapi, uvicorn, streamlit, openai, requests, sqlalchemy
└── .env.example         # шаблон ключа DEEPSEEK_API_KEY
```

## Быстрый старт

```bash
cd day7
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt
copy .env.example .env   # затем впишите DEEPSEEK_API_KEY=sk-...
```

Терминал 1 (бэкенд):

```bash
.venv/Scripts/python -m uvicorn backend.main:app --port 8000
```

Терминал 2 (фронтенд): откройте <http://localhost:8501>.

```bash
.venv/Scripts/python -m streamlit run app.py
```

Полная инструкция (ключ, сценарии, демо «память после рестарта», FAQ) — в
[docs/usage.md](docs/usage.md); описание эндпоинтов с примерами curl — в
[docs/api.md](docs/api.md); Swagger — на `http://127.0.0.1:8000/docs`.

## Возможности

- **Контекстная память**: агент хранит полный диалог
  `[{"role": "user"/"assistant", "content": ...}, ...]` в SQLite (таблица
  `messages`, связь один-ко-многим с агентами по `agent_id`).
- **Диалог переживает рестарт**: при старте бэкенд создаёт таблицы и
  восстанавливает агентов из `agents` вместе с историей — чат продолжается с
  того же места.
- **Полный контекст в DeepSeek**: на каждый запрос уходит вся история +
  системный промпт агента (первым сообщением, если задан).
- **Полноценный чат**: основная область показывает все сообщения выбранного
  агента (роль + текст), внизу — поле ввода и кнопки «🚀 Отправить» /
  «🧹 Очистить историю»; в боковой панели список агентов с числом сообщений.
- **Новый эндпоинт** `DELETE /agents/{agent_id}/history` — очистка диалога
  агента без удаления самого агента.
- Ответы API содержат не только текст и метрики (время, токены,
  `finish_reason`), но и **обновлённую историю**.
- Структурированные ошибки без traceback: нет ключа / недоступен DeepSeek /
  неизвестный агент; при сбое генерации история не портится.

## Демо для видео (память между рестартами)

1. Запустите бэкенд и фронтенд (см. «Быстрый старт»), создайте агента.
2. Напишите 3–4 сообщения подряд — агент отвечает, учитывая предыдущие.
3. Покажите историю в интерфейсе и в базе:
   ```bash
   python -c "import sqlite3; con=sqlite3.connect('agents.db'); [print(r) for r in con.execute('select id, agent_id, role, content from messages order by id')]"
   ```
4. Остановите бэкенд (Ctrl+C) и запустите снова (`uvicorn ...`).
5. Продолжите диалог: агент помнит всё, что было до рестарта.

## Ограничения

- Один процесс бэкенда и один файл `day7/agents.db`: база создаётся при старте,
  файл в git не попадает (правило `*.db` в корневом `.gitignore`).
- В `messages` хранятся только реплики диалога; системный промпт — конфигурация
  агента и в историю не пишется.
- Очень длинный диалог может упереться в контекст DeepSeek (~64K токенов) —
  кнопка «Очистить историю» или новый агент.
- Модель `deepseek-reasoner` может игнорировать `temperature` — это поведение
  провайдера, а не баг.

