---
name: python-fsm-agent
description: "State machine (FSM) rules for the ai-challenge project: states and events as enum.Enum, transitions via the State pattern, explicit failure on unknown events. Use this whenever implementing, changing or reviewing a finite state machine, adding a state or an event, defining a transition table, or deciding how an unknown event must behave. Triggers: FSM, state machine, states, events, transitions, enum.Enum states, State pattern, handle(event), UnknownContextEvent, context_fsm."
---

# Стейт-машина на Python (FSM): правила проекта

Целевая архитектура `ai-challenge`: логика новых приложений описывается как
конечный автомат. Никакой разбросанной логики в `if/elif` по всему коду —
переходы централизуются в одном месте.

## Правила

- **Переходы живут в одном модуле дня.** Состояния, события и таблица переходов —
  один файл (эталон: `day9/backend/context_fsm.py`, перенесён в
  `day12/backend/context_fsm.py`).
- **Состояние и событие — только через `enum.Enum`.** Никаких «сырых» строк и
  чисел в коде, сравнениях и ветвлениях.
- **`Enum` — это идентификатор, а не логика.** Поведение живёт в классах-состояниях;
  значения членов — строковые/читаемые, чтобы попадать в UI и в лог без
  дополнительного маппинга.
- **Переходы — паттерном State.** Каждое состояние — отдельный класс с общим
  интерфейсом (например, `handle(event)`), возвращающий следующее состояние.
  Стейт-машина хранит текущее состояние и делегирует ему обработку события.
- **Диаграмма переходов однозначна:** у каждого события в конкретном состоянии —
  ровно один результат.
- **Неизвестное событие в состоянии → явная ошибка** (например,
  `UnknownContextEvent`) либо осознанный безопасный `IGNORE`, но не «тихое»
  зависание.
- **Классы состояний маленькие, тестируемые, без побочных эффектов на импорте.**
- **Стейт-машина отделена от транспорта:** Streamlit/FastAPI лишь транслируют
  события и отображают состояние. Классы состояний зависят только от домена, не
  от UI (Streamlit/FastAPI).

## Эталоны в репозитории

- `day9/backend/context_fsm.py` — первая реализация: `ContextState` /
  `ContextEvent` (`Enum`), состояния — классы с `handle(event)`, неизвестное
  событие — `UnknownContextEvent`.
- `day9/backend/context_policy.py` — чистая арифметика «когда сжимать и что
  оставить»: вынесена из FSM и покрыта отдельными тестами (образец разделения
  «поведение состояний» и «чистая логика решения»).
- `day12/backend/context_fsm.py` — та же машина в активном дне.

## Тесты FSM

Переходы покрываются `pytest`-тестами: параметризованная таблица пар
(состояние, событие) → ожидаемое состояние **и хотя бы один негативный сценарий**
(недопустимое событие → исключение). Тест пишется **до** реализации (TDD).
Эталон — `day9/tests/`. Детали процесса — в скилле `tdd-pytest-workflow`.
