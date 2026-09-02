# Tech Stack Specification

## Purpose

Технологический контракт окружения и зависимостей: Python-стек на Windows,
доступ к DeepSeek через OpenAI SDK, секреты и команды запуска.

## Requirements

### Requirement: Доступ к DeepSeek через OpenAI SDK
Все обращения к DeepSeek SHALL выполняться официальным OpenAI SDK с
`base_url = https://api.deepseek.com` (строго с поддоменом `api.`, без `www`);
адрес без `api.` запросы не принимает.

#### Scenario: Корректный base_url
- GIVEN клиент `OpenAI(api_key=..., base_url="https://api.deepseek.com")`
- WHEN выполняется `chat.completions.create(...)`
- THEN запрос уходит на `POST https://api.deepseek.com/chat/completions` и
  обрабатывается корректно

### Requirement: Поиск API-ключа
Ключ `DEEPSEEK_API_KEY` SHALL искаться в порядке: файл `.env` рядом с
приложением → переменная окружения → ручной ввод (в консоли скрытым `getpass`,
в UI — полем-паролем). Заглушки и пустые значения SHALL считаться неподходящими.

#### Scenario: Ключ из .env
- GIVEN файл `.env` в рабочей папке с реальным ключом
- WHEN приложение запускается
- THEN ключ берётся из `.env` без запроса ручного ввода

#### Scenario: Заглушка считается неподходящей
- GIVEN в `.env` значение-заглушка вида `sk-вставьте-сюда-ваш-ключ`
- WHEN приложение ищет ключ
- THEN заглушка отвергается и запрашивается следующий источник ключа

### Requirement: Строгий JSON-режим
JSON-режим DeepSeek SHALL включаться только при наличии system-промпта,
требующего JSON, и параметра `response_format={"type":"json_object"}`.

#### Scenario: Автодобавление system-промпта
- GIVEN приложение дня 2/3 и выбранный режим «Строгий JSON»
- WHEN пользователь запускает запрос
- THEN в messages автоматически добавляется system-промпт о JSON и передаётся
  `response_format`, а лог показывает оба факта

### Requirement: Ограничения deepseek-reasoner
Модель `deepseek-reasoner` SHALL использоваться с учётом того, что API может
игнорировать `temperature` и `response_format`; интерфейс SHALL предупреждать об
этом пользователя.

#### Scenario: Предупреждение об игнорировании параметров
- GIVEN приложение дня 2 и выбранная модель `deepseek-reasoner`
- WHEN пользователь меняет temperature или включает JSON-режим
- THEN интерфейс показывает предупреждение, что reasoner может проигнорировать
  эти параметры

### Requirement: Диапазоны и семантика параметров UI
UI-виджеты дней 2–3 SHALL ограничивать значения параметров: `max_tokens`
10–3000, `temperature` 0.0–2.0, `seed` — целое ≥ 0 и передаваться только при
включённом чекбоксе, stop-строки — список, разделённый запятыми.

#### Scenario: Seed не передаётся без чекбокса
- GIVEN приложение дня 2/3 с выключенным чекбоксом seed
- WHEN пользователь запускает запрос
- THEN параметр `seed` отсутствует в запросе и в техническом логе

### Requirement: Запуск из папки дня
Приложения SHALL искать `.env` в текущей рабочей директории; запуск
`streamlit run app.py` SHALL выполняться из папки соответствующего дня.

#### Scenario: Запуск не из той папки
- GIVEN запуск `streamlit run day2/app.py` из корня репозитория
- WHEN приложение ищет ключ
- THEN ключ из `day2/.env` не находится (файл ищется в CWD) и приложение
  переходит к переменной окружения или ручному вводу

### Requirement: Среда и проверка регрессии
Проект SHALL поддерживать Windows/PowerShell, Python 3.14 и виртуальное
окружение `day2/.venv` (streamlit 1.62.0, openai 3.6.0). Автотестов, линтеров,
CI и `pyproject.toml` в проекте нет; регрессия SHALL проверяться синтаксической
компиляцией (`python -m py_compile`) и запуском приложений через
`streamlit.testing.AppTest` без реальных запросов к API.

#### Scenario: Проверка после рефакторинга
- GIVEN изменённые `day2/app.py`, `day3/app.py` или `shared/deepseek_utils.py`
- WHEN выполняется `python -m py_compile` для всех файлов и AppTest-запуск
- THEN ошибки отсутствуют, что считается базовой проверкой регрессии

### Requirement: Корректный вывод русской консоли
Консольный скрипт дня 1 SHALL настраивать stdout на UTF-8
(`sys.stdout.reconfigure(encoding="utf-8", errors="replace")`), чтобы русский
текст и эмодзи печатались корректно в консоли Windows.

#### Scenario: Печать эмодзи и кириллицы
- GIVEN Windows-консоль с кодировкой по умолчанию
- WHEN запускается day1/deepseek_chat.py
- THEN приветствие и ответы модели отображаются без кракозябр
