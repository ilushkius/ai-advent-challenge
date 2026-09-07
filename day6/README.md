# День 6 — Менеджер агентов DeepSeek (FastAPI + Streamlit)

Веб-приложение для управления **пулом LLM-агентов**: каждый агент — отдельная
сущность со своей конфигурацией (модель, температура, системный промпт,
`max_tokens`), историей запросов и инкапсулированным вызовом DeepSeek через
официальный OpenAI-совместимый endpoint `https://api.deepseek.com`.

Все агенты хранит **один менеджер-синглтон** (`AgentManager`) в памяти бэкенда:
создание десятков и сотен агентов с разными параметрами — это просто добавление
экземпляров (в UI — кнопка «Заспавнить N» до 100).

## Архитектура

```
Streamlit (порт 8501) ── HTTP (requests) ──► FastAPI (порт 8000) ──► DeepSeek API
                                              └─ AgentManager (синглтон)
                                                 └─ Agent × N (конфиг + история)
```

Фронтенд управляет агентами через HTTP-API и **не знает про ключ**: его читает
бэкенд. Детали — в [docs/architecture.md](docs/architecture.md).

## Структура

```
day6/
├── app.py               # Streamlit-фронтенд
├── backend/
│   ├── __init__.py
│   ├── main.py          # FastAPI: 6 эндпоинтов управления агентами
│   ├── agent.py         # класс Agent (вызов DeepSeek + история)
│   ├── agent_manager.py # класс AgentManager (синглтон)
│   ├── config.py        # URL/дефолты + чтение DEEPSEEK_API_KEY
│   └── models.py        # Pydantic-схемы API
├── docs/
│   ├── architecture.md  # архитектура и диаграммы
│   ├── api.md           # документация эндпоинтов с примерами
│   └── usage.md         # установка, запуск, сценарии, FAQ
├── requirements.txt
└── .env.example         # шаблон ключа DEEPSEEK_API_KEY
```

## Быстрый старт

```bash
cd day6
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

Полная инструкция (включая настройку ключа, сценарии и FAQ) — в
[docs/usage.md](docs/usage.md); описание всех эндпоинтов с примерами curl — в
[docs/api.md](docs/api.md); Swagger — на `http://127.0.0.1:8000/docs`.

## Возможности

- Создание/выбор/удаление агентов и отправка запросов из интерфейса.
- Ответ с метриками: время, токены (`prompt/completion/total`), `finish_reason`.
- История попыток каждого агента (успех и ошибки) — в UI и через API.
- Массовое создание (10–100 агентов с разными параметрами) — демонстрация
  масштабируемости менеджера.
- Структурированные ошибки без traceback: нет ключа / недоступен DeepSeek /
  неизвестный агент.

## Ограничения

- Агенты и история живут **в памяти бэкенда**: перезапуск uvicorn очищает их.
- Ключ `DEEPSEEK_API_KEY` читает бэкенд из `day6/.env` или переменной окружения
  (файл `.env` в git не коммитится; в репозитории — только `.env.example`).
- Модель `deepseek-reasoner` может игнорировать `temperature` — это поведение
  провайдера, а не баг.
