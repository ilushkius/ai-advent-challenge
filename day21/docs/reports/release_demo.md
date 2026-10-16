# Отчёт демо подготовки релиза (день 35)

Прогон: 2026-10-16 23:14, скрипт `scripts/demo_release.py`, режим dry_run (файлы не менялись), провайдер 🌐 DeepSeek (облако), диапазон `day1..HEAD` (day1 (нет тега → корень истории) → HEAD), длительность 67.6 с.
Коммиты читает MCP-сервер `file_server` (`uv run python mcp_servers/file_server/server.py --file-root ..`), версию и раздел CHANGELOG предлагает модель, проверки готовности выполнены.

## Сводка прогона

| from_tag | to_tag | suggested_version | reason | breaking_changes_count | changelog_preview | checks_passed | files_to_modify | вердикт |
|---|---|---|---|---|---|---|---|---|
| day1 | HEAD | 1.1.0 | Добавлены новые ассистенты и режимы (файловый, пользователь… | 0 | Правила проекта переведены с Cline, OpenSpec, Superpowers и Caveman на omp.sh; Управление проектом переведено с Memory … | да | CHANGELOG.md (apply_patch); day21/docs/RELEASE_NOTES.md (write_file); README.md (apply_patch) | 🧪 dry_run: показан план, файлы не изменены |

## Метрики проекта

| метрика | значение |
|---|---|
| tags | 14 |
| commits | 70 |
| py_files | 579 |
| tests | 1797 |
| mcp_servers | 7 |
| assistants | 5 |

Строкой: 14 тегов, 70 коммитов, 579 файлов .py, 1797 тестов, 7 MCP-серверов, 5 ассистентов

## Проверки готовности

| проверка | значение | итог | команда |
|---|---|---|---|
| тесты | — | ✅ | uv run pytest -m not slow -q (код 0) |
| покрытие | 94.0% | ✅ | uv run pytest --cov=backend --cov-report=term -q (код 0) |
| README.md | на месте | ✅ | — |
| day21/docs/architecture.md | на месте | ✅ | — |

## Notes

* заметок нет

## Diff (первые строки)

Файлы плана: CHANGELOG.md (apply_patch); day21/docs/RELEASE_NOTES.md (write_file); README.md (apply_patch)

```diff
--- a/CHANGELOG.md
+++ b/CHANGELOG.md
@@ -5,6 +5,43 @@
 структуры кода), `docs` (документация), `rules` (правила для агента и процесса),
 `chore` (прочее: инфраструктура, скиллы, служебные изменения).
 
+## [1.1.0] - 2026-10-16
+
+### Added
+- day34: файловый ассистент с MCP file_server, планированием по цели, dry_run и реальными файловыми операциями
+- day33: ассистент поддержки с RAG по FAQ и MCP для users и tickets
+- day32: пайплайн автоматического AI-ревью кода с GitHub Action, MCP diff и RAG
+- day32: режим ревью GitHub PR с автополучением diff и публикацией комментариев
+- day31: ассистент разработчика с RAG по документации проекта и MCP для git-контекста
+- day30: удалённая LLM (Ollama в Colab за туннелем Cloudflare) и демо одной кнопкой
+- day29: профили настройки локальной LLM и сравнение квантов на кейсе RAG
+- day28: подключение локальной LLM к RAG-пайплайну со сравнением в один клик в UI
+- day26: локальная LLM через Ollama с HTTP-интеграцией в приложение и мини-чат
+- day25: мини-чат с источниками RAG, памятью задач и отчётом по сценарию
+- day24: обязательные источники и цитаты RAG, режим «не знаю» и демо-запуск в UI
+- day22–day23: режим RAG-запроса с новым корпусом и оценкой на 10 вопросах, reranker, отсечение по релевантности и переформулировка запроса
+- skills: проектные навыки для omp.sh (FSM, структура дня, общие модули, TDD, документация дня)
+- Набор навыков Caveman в .agents/skills (cavecrew, caveman-commit, caveman-compress, caveman-discover, caveman-review, caveman-stats, caveman-learn и др.)
+- Результаты дня 20 по RAG и сохранению в базу (day20/output)
+- Результаты дня 21 по RAG и сохранению в базу (day21/output)
+- Тесты навыков Caveman (caveman-explore, caveman-learn)
+- Конфигурации пакетов навыков Caveman (package.json)
+
+### Changed
+- Нет изменений.
+
+### Fixed
+- Нет изменений.
+
+### Removed
+- Нет изменений.
+
+### Breaking
+- Правила проекта переведены с Cline, OpenSpec, Superpowers и Caveman на omp.sh
+- Управление проектом переведено с Memory Bank на OpenSpec + Superpowers + Caveman
```

