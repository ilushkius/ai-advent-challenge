# Tech Context — технологии, окружение, запуск

## Окружение разработки
- **ОС:** Windows (PowerShell, VS Code). Путь: `C:\Users\ilushkius\ai-challenge`.
- **Python:** 3.14.7 (64-bit). Виртуальное окружение: `day2/.venv` (создано из
  `C:\Users\ilushkius\AppData\Local\Python\pythoncore-3.14-64`).
- **Git:** ветка `main`, remote `origin`. По одному коммиту на день; рефакторинг
  и документация закоммичены отдельно (`5aa6898` «Day 3 Refactoring»).
- Кодировка файлов UTF-8; комментарии и UI — на русском.

## Технологии и зависимости

| День | Стек | `requirements.txt` |
|---|---|---|
| day1 | Python-скрипт, OpenAI SDK | `openai>=1.40.0` |
| day2 | Streamlit + OpenAI SDK | `streamlit>=1.30.0`, `openai>=1.40.0` |
| day3 | Streamlit + OpenAI SDK | `streamlit>=1.30.0`, `openai>=1.40.0` |

Фактически установлено в `day2/.venv` (по dist-info в site-packages):
**streamlit 1.62.0**, **openai 3.6.0**, numpy 2.5.2, pandas 3.0.5, pyarrow 25.0.1,
pillow 12.3.0, altair 6.2.2, pydantic 2.13.5, httpx2 2.12.0, uvicorn 0.52.4,
websockets 16.1.1 и др. (python-dotenv НЕ используется — ключ читается вручную).

Примечание: код написан в синтаксисе, совместимом с OpenAI SDK 1.x/2.x
(`OpenAI(api_key=..., base_url=...)`), и работает на установленном openai 3.6.0.

## Внешний сервис — DeepSeek API (OpenAI-совместимый)
- `base_url`: `https://api.deepseek.com` — строго с `api.`, БЕЗ `www`;
  адрес `https://deepseek.com` API-запросы не принимает (помечено в коде как грабли).
- Метод: `POST /chat/completions`.
- Модели: `deepseek-chat` (основная) и `deepseek-reasoner`
  (может игнорировать `temperature` и `response_format` — ограничение API).

## Переменные окружения / секреты
- `DEEPSEEK_API_KEY` — ключ DeepSeek (начинается с `sk-`).
- Приоритет источников: `.env` рядом с приложением → переменная окружения →
  ручной ввод (Day 1: `getpass`; Day 2/3: поле-пароль в sidebar).
- `.env` не коммитится (корневой `.gitignore`), в git только шаблоны `.env.example`
  (есть во всех днях: day1, day2, day3).
- Локально: `day1/.env` существует; `day2/.env` нет (ключ вводится в UI/из env).

## Команды запуска (обязательно из папки дня!)
```
# День 1
pip install -r requirements.txt
python deepseek_chat.py

# День 2 или 3
pip install -r requirements.txt       # либо переиспользовать day2/.venv
streamlit run app.py
```
Важно: `read_key_from_env_file()` ищет `.env` в **текущей рабочей директории**,
поэтому `streamlit run` надо выполнять из самой папки дня.

День 2/3 импортируют общий пакет `shared/` из корня репозитория (папка корня
добавляется в sys.path по `__file__`); day1 полностью автономен. Общая
документация — в корневом `README.md`.

## Технические нюансы
- Day 1: `sys.stdout.reconfigure(encoding="utf-8", errors="replace")` — корректный
  вывод русского текста/эмодзи в консоли Windows.
- JSON-режим DeepSeek: обязательны system-промпт + `response_format={"type":"json_object"}`.
- `seed` — int; при выключенном чекбоксе параметр не отправляется вовсе.
- `usage` берётся из `response.usage`; может быть `None` → приводится к `{}`.
- Диапазоны UI: `max_tokens` 10–3000, `temperature` 0.0–2.0, `seed` ≥ 0,
  `stop` — строки через запятую.
- Для мета-промпта (Day 3): Шаг А с `META_MAX_TOKENS=600`.

## Чего нет в проекте
Тестов, линтеров, CI, `pyproject.toml`, корневого `requirements.txt` (зависимости
— в `requirements.txt` каждого дня). Общие утилиты вынесены в
`shared/deepseek_utils.py`, описание проекта — в корневом `README.md`.
