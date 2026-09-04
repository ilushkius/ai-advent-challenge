# Процесс разработки

Проект `ai-challenge` ведётся по **spec-driven** процессу **OpenSpec** с
навыками **Superpowers** (методология: TDD, планы, ревью) и **Caveman**
(экономия токенов ответов).

## Содержание

1. [Общая картина](#общая-картина)
2. [OpenSpec-воркфлоу (ритуал дня)](#openspec-воркфлоу-ритуал-дня)
3. [Команды и где они лежат](#команды-и-где-они-лежат)
4. [Навыки Superpowers](#навыки-superpowers)
5. [Caveman: экономия токенов](#caveman-экономия-токенов)
6. [Контекст проекта](#контекст-проекта)
7. [Проверка качества](#проверка-качества)
8. [Известные ограничения и советы](#известные-ограничения-и-советы)

## Общая картина

- **Источник правды о поведении** — эталонные спецификации
  `openspec/specs/<capability>/spec.md`. Сейчас: `project`, `architecture`,
  `tech-stack`, `day1-console-chat`, `day2-response-format`,
  `day3-reasoning-methods`, `day4-temperature-experiment`,
  `day5-model-comparison`.
- **Изменения** — папки в `openspec/changes/<change-name>/` (активные) и
  `openspec/changes/archive/` (завершённые). Каждый change содержит артефакты
  схемы `spec-driven`: `proposal.md`, `specs/` (дельты), `design.md`,
  `tasks.md`, метаданные `.openspec.yaml`.
- **Контекст и правила** — `openspec/config.yaml` (`context`, `rules`,
  `operations`); CLI впрыскивает их в промпты при генерации артефактов.
- Изменение считается завершённым, когда архивировано: дельты сливаются в
  основные спецификации, папка переезжает в
  `openspec/changes/archive/YYYY-MM-DD-<name>/`.

## OpenSpec-воркфлоу (ритуал дня)

Каждый день/задача челленджа проходит три шага в чате с Cline:

| Шаг | Команда | Что делает |
|---|---|---|
| 1. План | `/opsx:propose <описание>` | Создаёт change: `proposal.md` (зачем/что), `specs/<cap>/spec.md` (дельты ADDED/MODIFIED/REMOVED), `design.md` (как), `tasks.md` (чек-лист). Код не пишется |
| 2. Исполнение | `/opsx:apply` | Реализует задачи по одной, по TDD; после каждой задачи отмечает `- [x]` и показывает прогресс |
| 3. Завершение | `/opsx:archive` | Проверяет артефакты, синхронизирует дельты в основные спецификации и переносит change в `archive/` |

Дополнительные команды ядра OpenSpec:

- `/opsx:explore` — исследование кодовой базы/идеи до планирования;
- `/opsx:update` — обновить артефакты существующего change;
- `/opsx:sync` — синхронизировать дельты с основными спецификациями вручную.

Пример начала нового дня:

```
/opsx:propose day6: RAG по собственным заметкам (embeddings + поиск по тексту)
```

Cline предложит план; вы ревьюите `proposal.md`/`specs/`/`design.md`/`tasks.md`,
затем запускаете `/opsx:apply`, а после реализации — `/opsx:archive`.

Дни могут быть и документными — без кода приложения, как день 4 (эксперимент с
`temperature`): результатом такого дня становится документ `dayN/results.md`,
а вместо `py_compile`/AppTest он проверяется наличием файла.

> **Форма команды в Cline.** OpenSpec пишет команды файлами
> `.clinerules/workflows/opsx-<id>.md`, поэтому в Cline они срабатывают и в
> дефисной форме — `/opsx-propose`, `/opsx-apply`, `/opsx-archive` (это
> «родное» написание для инструментов без `:`-неймспейса). Каноническое имя из
> документации OpenSpec — `/opsx:propose` и т.д.; обе формы понимаются.

> Планирование (`propose`) и исполнение (`apply`) — раздельные шаги: propose
> только планирует и останавливается до вашей новой команды.

## Команды и где они лежат

Интеграция OpenSpec с Cline создаёт:

- **Workflow-команды** — `.clinerules/workflows/opsx-*.md` (полные пошаговые
  инструкции для Cline: propose/explore/apply/update/sync/archive);
- **Навыки OpenSpec** — `.cline/skills/openspec-*/SKILL.md` (короткие версии
  тех же воркфлоу, вызываются как `/openspec-<skill>`).

Terminal CLI (для ручных проверок и CI):

```bash
openspec schemas                    # список схем (spec-driven)
openspec list                       # активные changes
openspec validate --all             # валидация всех спека и changes
openspec show <change>              # просмотр change
openspec status --change <name>     # статус артефактов change
openspec instructions apply --change <name>   # инструкции для apply
openspec update                     # перегенерировать навыки/воркфлоу после обновления CLI
```

## Навыки Superpowers

Superpowers-ZH установлен в `.cline/skills/` (20 навыков). Индекс —
`.clinerules/superpowers-zh.md` — всегда в контексте; тела навыков читаются по
требованию, чтобы не раздувать контекст.

Наиболее частые навыки в этом проекте:

| Навык | Когда применять |
|---|---|
| `brainstorming` | любая новая фича/день: сначала уточнить замысел |
| `writing-plans` / `executing-plans` | составление и исполнение планов |
| `test-driven-development` | писать тест до кода (здесь — py_compile/AppTest) |
| `systematic-debugging` | любой баг: сначала найти корневую причину |
| `requesting-code-review` / `receiving-code-review` | ревью до merge |
| `verification-before-completion` | перед «готово» — запустить проверки |
| `subagent-driven-development` | длинные автономные реализации |

Навыки OpenSpec и Superpowers дополняют друг друга: OpenSpec задаёт «что и
почему» (specs), Superpowers — «как делать» (TDD, ревью).

## Caveman: экономия токенов

**Caveman** сжимает прозу ответов ИИ (убирает артикли/воду), сохраняя код,
команды и технические термины без изменений. Это экономит токены на длинных
сессиях.

- **Автоактивация**: правило `.clinerules/caveman.md` включает режим `full` в
  каждой сессии автоматически.
- **Переключение режима**: `/caveman lite|full|ultra|off` (есть и
  `wenyan-*` варианты для классического китайского — не нужны).
- **Безопасность**: при security-предупреждениях, необратимых действиях и
  непонятном вопросе Caveman автоматически переключается на обычный язык.
- **Границы**: код, комментарии, коммиты, issue/PR и эта документация пишутся
  обычным языком, даже когда режим включён.

Навыки Caveman лежат в `.agents/skills/caveman*/` (20 навыков: caveman,
caveman-commit, caveman-review, investigate-first, safe-refactor и др.).

## Контекст проекта

Где искать ответы на «что это и как устроено»:

1. `openspec/config.yaml` → `context` — стек, структура, конвенции, грабли
   DeepSeek (впрыскивается в каждый артефакт).
2. `openspec/specs/project/spec.md` — цель и сквозные требования челленджа.
3. `openspec/specs/architecture/spec.md` — моно-репозиторий, паттерны
   приложений (params-dict, session_state, мета-промпт, безопасный вывод).
4. `openspec/specs/tech-stack/spec.md` — DeepSeek/OpenAI SDK (base_url), секреты,
   запуск; клиент Hugging Face (`huggingface_hub`) дня 5 — в его capability-спеке.
5. Capability-спеки дней: `day1-console-chat`, `day2-response-format`,
   `day3-reasoning-methods`, `day4-temperature-experiment`,
   `day5-model-comparison` — что именно сделано в каждом дне.

## Проверка качества

Автотестов, линтеров и CI в проекте нет, поэтому перед «готово» выполняется
ручная проверка:

```bash
# 1. Синтаксис всех Python-файлов
python -m py_compile day1/deepseek_chat.py day2/app.py day3/app.py day5/app.py shared/deepseek_utils.py

# 2. Smoke-запуск Streamlit-приложений без реальных запросов к API
python -c "from streamlit.testing.v1 import AppTest; AppTest.from_file('day2/app.py').run(); AppTest.from_file('day3/app.py').run(); print('AppTest OK')"

# День 5 проверяется своим venv (там установлены streamlit и huggingface_hub):
day5/.venv/Scripts/python -c "from streamlit.testing.v1 import AppTest; AppTest.from_file('day5/app.py').run(); print('AppTest day5 OK')"

# 3. Валидация OpenSpec
openspec validate --all
```

Для проверки в venv дня 2 используйте `day2/.venv/Scripts/python`; для дня 5 —
`day5/.venv/Scripts/python`.

Команды 1–2 применяются к прикладным дням, содержащим `.py`-файлы
(day1–day3, day5). Документные дни без кода (например, day4) компиляции и
AppTest не требуют — для них проверяется наличие документа результатов
`day4/results.md`.

## Известные ограничения и советы

- **`.env` ищется в CWD** — все `streamlit run` выполняются из папки дня.
- **`openspec update` перезапишет** файлы workflow-команд и навыков OpenSpec —
  не редактируйте их вручную.
- **Схема `superpowers-driven` в OpenSpec CLI 1.11 отсутствует** (есть только
  `spec-driven`). Интеграция с Superpowers достигается навыками; при желании
  можно подключить community-схему `superpowers-bridge` из
  `JiangWay/openspec-schemas` — для этого потребуется отдельное решение.
- **Конфиг**: ключи `project.test_commands`/`e2e_command` (legacy) в OpenSpec
  1.11 не поддерживаются — команды проверки задаются в задачах `tasks.md` и в
  `operations.apply.guidance` конфига.
- **После установки/обновления инструментов** перезапустите VS Code/Cline,
  чтобы подхватились новые навыки и команды.
- **Caveman активируется в новой сессии** автоматически через
  `.clinerules/caveman.md`; если ответы снова длинные — проверьте, что правило
  на месте (`.clinerules/`) и сессия действительно новая.


