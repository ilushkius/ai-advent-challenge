# Отчёт дня 32: автоматическое AI-ревью кода

Отчёт собирает скрипт `scripts/run_local_pr_review.py`: каждая секция — одно
ревью (пара ref-ов или файл diff-а). Повторный прогон с тем же заголовком секции
заменяет её, новый заголовок добавляет ещё одну; границы секции отмечены
невидимым в просмотре маркером `<!-- section: … -->`.

```bash
uv run python scripts/run_local_pr_review.py --base day30 --head day31
uv run python scripts/run_local_pr_review.py --diff-file docs/reports/synthetic_pr.diff \
  --pr-label "synthetic PR: прямой SQL из слоя служб" \
  --section-title "Синтетический PR: прямой SQL из службы вместо хранилища"
```

<!-- section: Ревью diff day30..day31 -->

## Ревью diff day30..day31

## 🤖 AI-ревью: Ревью diff day30..day31

_Провайдер: deepseek · 19929 мс · файлов: 35 · источников RAG: 3_

### Изменённые файлы

- `CHANGELOG.md`
- `day21/README.md`
- `day21/STRUCTURE.md`
- `day21/app.py`
- `day21/backend/api/__init__.py`
- `day21/backend/api/agents.py`
- `day21/backend/api/dev_assistant.py`
- `day21/backend/api/lifespan.py`
- `day21/backend/api/main.py`
- `day21/backend/core/dependencies.py`
- `day21/backend/domain/dev_assistant.py`
- `day21/backend/domain/rag_corpus_spec.py`
- `day21/backend/schemas/dev_assistant.py`
- `day21/backend/services/__init__.py`
- `day21/backend/services/dev_assistant_service.py`
- `day21/docs/api.md`
- `day21/docs/architecture.md`
- `day21/docs/reports/dev_assistant_demo.md`
- `day21/docs/usage.md`
- `day21/frontend/chat_section.py`
- `day21/frontend/dev_assistant_api.py`
- `day21/frontend/dev_assistant_section.py`
- `day21/mcp_servers/dev_server/__init__.py`
- `day21/mcp_servers/dev_server/config.py`
- `day21/mcp_servers/dev_server/schemas.py`
- `day21/mcp_servers/dev_server/server.py`
- `day21/mcp_servers/dev_server/tools.py`
- `day21/scripts/demo_dev_assistant.py`
- `day21/scripts/dev_mcp_probe.py`
- `day21/scripts/reindex_with_docs.py`
- `day21/tests/dev_assistant_fakes.py`
- `day21/tests/integration/test_dev_assistant_flow.py`
- `day21/tests/integration/test_rag_flow.py`
- `day21/tests/unit/test_dev_assistant_panels.py`
- `day21/tests/unit/test_dev_assistant_service.py`

### Потенциальные баги

| Файл | Строка | Приоритет | Проблема |
| --- | --- | --- | --- |
| day21/backend/services/dev_assistant_service.py | 195 | P1 (важно) | При обрыве связи (MCPError) на шаге N в used добавляются записи для plan[position:], но предыдущие успешные записи уже добавлены — ветка return [] теряет блоки, собранные до обрыва, хотя ответ по документации мог бы строиться; кроме того, при TypeError/Didисключениях от call_tool (не MCPError) ошибка уходит наружу как 500 |
| day21/backend/services/dev_assistant_service.py | 145 | P2 (средне) | self.server инициализируется под RLock, но конкурирующий close() во время _connect() может оставить уже подключённый клиент потерянным и не закрытым (server присваивается только после успешного _connect, но close между list_tools и присваиванием не защищён) |
| day21/backend/domain/dev_assistant.py | 234 | P3 (минорно) | verdict() завязан на префиксы текста ответа ('Провайдер «', 'Ollama не запущена') — при смене формулировок в LLM_UNAVAILABLE_ANSWER/OLLAMA_UNAVAILABLE_ANSWER проверка тихо перестанет срабатывать, а шаблоны уже вынесены как константы и не переиспользуются |

### Архитектурные проблемы

| Файл | Приоритет | Проблема | Рекомендация |
| --- | --- | --- | --- |
| day21/backend/api/dev_assistant.py | P2 (средне) | Роутер импортирует RAGUpstreamError из services.rag_errors и сам решает маппинг доменных исключений в HTTP через _http_error, дублируя знание о слое RAG внутри слоя ассистента | объявить DevAssistantError/DevAssistantUpstreamError в domain/dev_assistant.py и маппить только их, оставив rag_errors деталью службы |
| day21/backend/services/dev_assistant_service.py | P3 (минорно) | Служба держит свой MCP-клиент вне реестра mcp_registry, а lifespan закрывает его отдельным вызовом — при появлении второго такого сервера закрытие снова придётся дописывать вручную | зарегистрировать соединение в общем реестре/фабрике клиентов и закрывать в одном месте |
### Рекомендации

- В _call_tools при обрыве связи возвращать уже собранные blocks и фиксировать в used только оставшиеся шаги плана, чтобы не терять контекст по документации.
- В verdict() сравнивать ответ с константами шаблонов (LLM_UNAVAILABLE_ANSWER/OLLAMA_UNAVAILABLE_ANSWER), а не с префиксами строк.

### Риски (P0 — P3)

| Приоритет | Файл | Риск |
| --- | --- | --- |
| P1 (важно) | day21/backend/services/dev_assistant_service.py | Не-MCPError исключение из call_tool (таймаут subprocess, ValueError парсинга) приведёт к 500 на /dev-assistant/help вместо ответа по документации с предупреждением. |
| P2 (средне) | day21/mcp_servers/dev_server/server.py | DEV_SERVER_TARGET запускается через 'uv run' с cwd=config.MCP_FLEET_CWD: при отсутствии uv/venv в окружении сервер не поднимется, а это штатно поглощается предупреждением и маскирует ошибку конфигурации. |
| P3 (минорно) | day21/backend/domain/rag_corpus_spec.py | Расширение окон (README 12000→30000, lifespan 3800→5200) увеличит индекс и время прогрева, а изменение формулировки model-warmup снова может вытеснить факт из окна lifespan. |
### Источники RAG

- `agents.md` · AGENTS.md — правила проекта ai-challenge · 0.7801
- `readme.md` · Документация · 0.7691
- `day21-structure.md` · Структура дня 31 · 0.6537
### Предупреждения

- … diff обрезан: показаны первые 2000 строк из 4344 (пропущены файлы: day21/docs/usage.md, day21/frontend/chat_section.py, day21/frontend/dev_assistant_api.py, day21/frontend/dev_assistant_section.py, day21/mcp_servers/dev_server/__init__.py, day21/mcp_servers/dev_server/config.py, day21/mcp_servers/dev_server/schemas.py, day21/mcp_servers/dev_server/server.py, day21/mcp_servers/dev_server/tools.py, day21/scripts/demo_dev_assistant.py, day21/scripts/dev_mcp_probe.py, day21/scripts/reindex_with_docs.py, day21/tests/dev_assistant_fakes.py, day21/tests/integration/test_dev_assistant_flow.py, day21/tests/integration/test_rag_flow.py, day21/tests/unit/test_dev_assistant_panels.py, day21/tests/unit/test_dev_assistant_service.py)
- В контексте нет фрагментов файла CHANGELOG.md: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff
- В контексте нет фрагментов файла day21/README.md: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff
- В контексте нет фрагментов файла day21/app.py: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff
- В контексте нет фрагментов файла day21/backend/api/__init__.py: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff
- В контексте нет фрагментов файла day21/backend/api/agents.py: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff
- В контексте нет фрагментов файла day21/backend/api/dev_assistant.py: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff
- В контексте нет фрагментов файла day21/backend/api/lifespan.py: его нет среди источников корпуса или фрагменты не попали в выдачу поиска — по этому файлу виден только diff

<details><summary>Полный ответ модели</summary>

{"bugs": [{"file": "day21/backend/services/dev_assistant_service.py", "line": "195", "issue": "При обрыве связи (MCPError) на шаге N в used добавляются записи для plan[position:], но предыдущие успешные записи уже добавлены — ветка return [] теряет блоки, собранные до обрыва, хотя ответ по документации мог бы строиться; кроме того, при TypeError/Didисключениях от call_tool (не MCPError) ошибка уходит наружу как 500", "priority": "P1"}, {"file": "day21/backend/services/dev_assistant_service.py", "line": "145", "issue": "self.server инициализируется под RLock, но конкурирующий close() во время _connect() может оставить уже подключённый клиент потерянным и не закрытым (server присваивается только после успешного _connect, но close между list_tools и присваиванием не защищён)", "priority": "P2"}, {"file": "day21/backend/domain/dev_assistant.py", "line": "234", "issue": "verdict() завязан на префиксы текста ответа ('Провайдер «', 'Ollama не запущена') — при смене формулировок в LLM_UNAVAILABLE_ANSWER/OLLAMA_UNAVAILABLE_ANSWER проверка тихо перестанет срабатывать, а шаблоны уже вынесены как константы и не переиспользуются", "priority": "P3"}], "architecture_issues": [{"file": "day21/backend/api/dev_assistant.py", "issue": "Роутер импортирует RAGUpstreamError из services.rag_errors и сам решает маппинг доменных исключений в HTTP через _http_error, дублируя знание о слое RAG внутри слоя ассистента", "recommendation": "объявить DevAssistantError/DevAssistantUpstreamError в domain/dev_assistant.py и маппить только их, оставив rag_errors деталью службы", "priority": "P2"}, {"file": "day21/backend/services/dev_assistant_service.py", "issue": "Служба держит свой MCP-клиент вне реестра mcp_registry, а lifespan закрывает его отдельным вызовом — при появлении второго такого сервера закрытие снова придётся дописывать вручную", "recommendation": "зарегистрировать соединение в общем реестре/фабрике клиентов и закрывать в одном месте", "priority": "P3"}], "recommendations": ["В _call_tools при обрыве связи возвращать уже собранные blocks и фиксировать в used только оставшиеся шаги плана, чтобы не терять контекст по документации.", "В verdict() сравнивать ответ с константами шаблонов (LLM_UNAVAILABLE_ANSWER/OLLAMA_UNAVAILABLE_ANSWER), а не с префиксами строк."], "risks": [{"priority": "P1", "file": "day21/backend/services/dev_assistant_service.py", "risk": "Не-MCPError исключение из call_tool (таймаут subprocess, ValueError парсинга) приведёт к 500 на /dev-assistant/help вместо ответа по документации с предупреждением."}, {"priority": "P2", "file": "day21/mcp_servers/dev_server/server.py", "risk": "DEV_SERVER_TARGET запускается через 'uv run' с cwd=config.MCP_FLEET_CWD: при отсутствии uv/venv в окружении сервер не поднимется, а это штатно поглощается предупреждением и маскирует ошибку конфигурации."}, {"priority": "P3", "file": "day21/backend/domain/rag_corpus_spec.py", "risk": "Расширение окон (README 12000→30000, lifespan 3800→5200) увеличит индекс и время прогрева, а изменение формулировки model-warmup снова может вытеснить факт из окна lifespan."}]}

</details>

---

<!-- section: Синтетический PR: прямой SQL из службы вместо хранилища -->

## Синтетический PR: прямой SQL из службы вместо хранилища

## 🤖 AI-ревью: Синтетический PR: прямой SQL из службы вместо хранилища

_Провайдер: deepseek · 16744 мс · файлов: 1 · источников RAG: 2_

### Изменённые файлы

- `day21/backend/services/index_service.py`

### Потенциальные баги

| Файл | Строка | Приоритет | Проблема |
| --- | --- | --- | --- |
| day21/backend/services/index_service.py | 300 | P0 (критично) | SQL-запрос собирается f-строкой с подстановкой source — прямая SQL-инъекция через параметр запроса. |
| day21/backend/services/index_service.py | 299 | P1 (важно) | session из SessionLocal() не закрывается (нет try/finally или with) — утечка соединений. |
| day21/backend/services/index_service.py | 297 | P3 (минорно) | import sqlalchemy внутри метода импортируется, но не используется. |

### Архитектурные проблемы

| Файл | Приоритет | Проблема | Рекомендация |
| --- | --- | --- | --- |
| day21/backend/services/index_service.py | P1 (важно) | Слой служб напрямую обращается к БД сырым SQL, минуя репозиторий/ORM-модели. | Вынести выборку чанков в storage/repository-слой с параметризованными ORM-запросами. |
| day21/backend/services/index_service.py | P2 (средне) | chunks_preview глотает все исключения и возвращает пустой список, скрывая ошибки БД от вызывающего кода. | Логировать исключение и пробрасывать конкретные ошибки вместо тихого возврата []. |
### Рекомендации

- Использовать параметризованный запрос/ORM: .filter(DocumentChunk.source == source).limit(limit).
- Обернуть работу с сессией в контекстный менеджер (with SessionLocal() as session).

### Риски (P0 — P3)

| Приоритет | Файл | Риск |
| --- | --- | --- |
| P0 (критично) | day21/backend/services/index_service.py | Через source возможен произвольный SQL: утечка или удаление данных БД. |
| P1 (важно) | day21/backend/services/index_service.py | Нез акрытые сессии исчерпают пул соединений и положат бэкенд под нагрузкой. |
| P2 (средне) | day21/backend/services/index_service.py | Отсутствие индекса по source + LIMIT без ORDER BY даёт нестабильный и медленный результат. |
### Источники RAG

- `day21-readme.md` · День 30 — удалённая LLM: Ollama в Google Colab за туннелем Cloudflare, демо одной кнопкой · 0.698
- `day21-backend-services-index_service.py` · get_index_service · 0.591
### Предупреждения

— нет

<details><summary>Полный ответ модели</summary>

{"bugs": [{"file": "day21/backend/services/index_service.py", "line": "300", "issue": "SQL-запрос собирается f-строкой с подстановкой source — прямая SQL-инъекция через параметр запроса.", "priority": "P0"}, {"file": "day21/backend/services/index_service.py", "line": "299", "issue": "session из SessionLocal() не закрывается (нет try/finally или with) — утечка соединений.", "priority": "P1"}, {"file": "day21/backend/services/index_service.py", "line": "297", "issue": "import sqlalchemy внутри метода импортируется, но не используется.", "priority": "P3"}], "architecture_issues": [{"file": "day21/backend/services/index_service.py", "line": "296", "issue": "Слой служб напрямую обращается к БД сырым SQL, минуя репозиторий/ORM-модели.", "recommendation": "Вынести выборку чанков в storage/repository-слой с параметризованными ORM-запросами.", "priority": "P1"}, {"file": "day21/backend/services/index_service.py", "line": "304", "issue": "chunks_preview глотает все исключения и возвращает пустой список, скрывая ошибки БД от вызывающего кода.", "recommendation": "Логировать исключение и пробрасывать конкретные ошибки вместо тихого возврата [].", "priority": "P2"}], "recommendations": ["Использовать параметризованный запрос/ORM: .filter(DocumentChunk.source == source).limit(limit).", "Обернуть работу с сессией в контекстный менеджер (with SessionLocal() as session)."], "risks": [{"priority": "P0", "file": "day21/backend/services/index_service.py", "risk": "Через source возможен произвольный SQL: утечка или удаление данных БД."}, {"priority": "P1", "file": "day21/backend/services/index_service.py", "risk": "Нез акрытые сессии исчерпают пул соединений и положат бэкенд под нагрузкой."}, {"priority": "P2", "file": "day21/backend/services/index_service.py", "risk": "Отсутствие индекса по source + LIMIT без ORDER BY даёт нестабильный и медленный результат."}]}

</details>

