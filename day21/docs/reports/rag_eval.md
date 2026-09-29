# День 22 — RAG: сравнение ответов с корпусом и без него

Отчёт собран прогоном `scripts/run_rag_eval.py`: топ-K = 5, стратегия = rag_corpus_structural,
корпус — 36 документов / 314669 символов (~174 страниц), индекс — 680 чанков, время прогона 44 с.

## Как считался вердикт
Ключевые факты вопроса ищутся в тексте ответа (вхождение без учёта регистра); доля найденных
фактов сравнивается у ответа с RAG и без RAG: «лучше» — доля выше, «хуже» — ниже, «равно» —
доли совпали. Вопросы намеренно про значения из файлов корпуса: их нельзя воспроизвести по памяти.

## Таблица сравнения

| Вопрос | Ожидание (ключевые факты) | Источники (файл · раздел · score) | Ответ без RAG | Ответ с RAG | Вердикт |
|---|---|---|---|---|---|
| Чему равно EXCERPT_CHARS в day21/backend/domain/indexing_prompt.py и какой заголовок печатает render_index_block? | EXCERPT_CHARS = 300; INDEX_BLOCK_HEADER = «## Контекст из индекса документов» Факты: EXCERPT_CHARS, 300, Контекст из индекса документов | day21-structure.md · Раскладка · 0.4105<br>day21-backend-domain-indexing_prompt.py · module · 0.3929<br>day21-backend-domain-indexing_prompt.py · render_index_block · 0.2995<br>day21-backend-domain-indexing_prompt.py · _excerpt · 0.1964<br>day21-readme.md · Индексация и поиск · 0.1378 | В контексте нет данных для ответа. | В `day21/backend/domain/indexing_prompt.py` значение `EXCERPT_CHARS` равно 300. `render_index_block` печатает заголовок `## Контекст из индекса документов`. | лучше |
| Сколько символов в одной «странице» при подсчёте объёма документов: чему равен CHARS_PER_PAGE в day21/backend/services/document_loader.py? | CHARS_PER_PAGE = 1800 Факты: CHARS_PER_PAGE, 1800 | day21-backend-services-document_loader.py · module · 0.6406<br>day21-scripts-prepare_documents.py · module · 0.4823<br>day21-backend-services-document_loader.py · DocumentLoader · 0.1725<br>day21-docs-architecture.md · Документы и их источники · 0.1581<br>day21-readme.md · Индексация и поиск · 0.1443 | В контексте нет данных для ответа. | В контексте указано, что `CHARS_PER_PAGE = 1800`. | лучше |
| Чему равен PREVIEW_CHARS в day21/backend/services/index_service.py и какое сообщение бросается, если индекс стратегии пуст? | PREVIEW_CHARS = 300; IndexNotBuiltError(f«Индекс стратегии {strategy!r} пуст: сначала выполните индексацию») Факты: PREVIEW_CHARS, 300, Индекс стратегии, пуст | day21-backend-services-index_service.py · module · 0.5003<br>day21-backend-services-index_service.py · _preview · 0.5003<br>day21-structure.md · Почему сделано так (решения дня 21) · 0.2161<br>day21-backend-core-prompt_builder.py · module · 0.2001<br>day21-backend-core-prompt_builder.py · PromptBuilder · 0.2001 | В предоставленном контексте нет данных для ответа. | В контексте указано, что `PREVIEW_CHARS = 300`, а `_preview` показывает начало текста чанка. Сообщение об ошибке при пустом индексе стратегии в предоставленном контексте не приведено. | лучше |
| С какой долей кириллицы текст считается русским (CYRILLIC_RATIO) и сколько записей в таблице DOCUMENT_SOURCES (day21/backend/domain/document_sources.py)? | CYRILLIC_RATIO = 0.15; в таблице DOCUMENT_SOURCES 25 записей Факты: CYRILLIC_RATIO, 0.15, DOCUMENT_SOURCES, 25 | day21-backend-domain-document_sources.py · detect_language · 0.605<br>day21-backend-domain-document_sources.py · module · 0.4029<br>day21-backend-domain-document_sources.py · module · 0.3686<br>day21-readme.md · Индексация и поиск · 0.3196<br>day21-backend-domain-document_sources.py · _code · 0.2907 | В контексте нет данных для ответа. | CYRILLIC_RATIO = 0.15, а в таблице DOCUMENT_SOURCES — 25 записей. | лучше |
| Какой поток прогрева модели эмбеддингов создаёт при старте day21/backend/api/lifespan.py (threading.Thread, daemon=True, name=) и что запускается до этого потока? | database.init_db() → get_manager().restore_from_db() → get_scheduler().start() → get_mcp_registry().connect_all() → get_index_service().load_all(); поток name=«embedding-warmup» Факты: init_db, restore_from_db, embedding-warmup | day21-backend-api-lifespan.py · lifespan · 0.4494<br>day21-backend-api-lifespan.py · module · 0.3092<br>day21-backend-services-indexing_service.py · IndexingService · 0.3036<br>day21-backend-core-dependencies.py · get_embedding_service · 0.2889<br>day21-structure.md · Почему сделано так (решения дня 21) · 0.2513 | В контексте нет данных для ответа. | При старте создаётся демон-поток с `name="embedding-warmup"`, который вызывает `get_embedding_service().warmup()`. До этого выполняются: `database.init_db()`, `get_manager().restore_from_db()`, `get_scheduler().start()`, `get_mcp_registry().connect_all()` и `get_index_service().load_all()`. | лучше |
| Как ChunkStore.add_chunks проставляет embedding_id и какие id пропускает rows_by_ids (day21/backend/storage/chunk_store.py)? | вставка идёт пачкой с flush(), затем строкам проставляется orm.embedding_id = orm.id; rows_by_ids пропускает id, которых нет в БД (например, -1 — «пустая ячейка» FAISS), порядок результата = порядок ids Факты: embedding_id, flush, -1, пропускаются | day21-backend-storage-chunk_store.py · module · 0.6236<br>day21-tests-fixtures_indexing.py · module · 0.2082<br>day21-tests-fixtures_indexing.py · chunk_store · 0.1989<br>day21-backend-services-index_service.py · module · 0.1839<br>day21-backend-services-index_comparison.py · module · 0.1824 | В контексте нет данных для ответа. | В контексте нет данных для ответа. | равно |
| Какие значения у INDEX_AGENT_TOP_K и INDEX_AGENT_STRATEGY и чему равен INDEX_MAX_TOP_K (day21/backend/core/config.py)? | INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = «structural», INDEX_MAX_TOP_K = 20 Факты: INDEX_AGENT_TOP_K, INDEX_AGENT_STRATEGY, structural, INDEX_MAX_TOP_K, 20 | day21-backend-core-config.py · module · 0.6579<br>day21-backend-api-indexing.py · indexing_search · 0.346<br>day21-backend-services-indexing_service.py · IndexingService · 0.2373<br>day21-backend-services-index_comparison.py · module · 0.223<br>day21-scripts-indexing_scenarios.py · print_summary · 0.2145 | В предоставленном контексте нет данных для ответа: значения `INDEX_AGENT_TOP_K`, `INDEX_AGENT_STRATEGY` и `INDEX_MAX_TOP_K` не приведены. | В контексте указано: `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`, `INDEX_MAX_TOP_K = 20`. | лучше |
| Какое исключение и с каким текстом бросает LLMClient, если не передан client_factory (day21/backend/services/llm_client.py)? | RuntimeError(«LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)») Факты: RuntimeError, client_factory, Agent._make_client | day21-readme.md · Таблицы `document_chunks` и `index_runs` · 0.3838<br>day21-backend-services-llm_client.py · LLMClient · 0.2642<br>day21-backend-core-dependencies.py · get_llm_client · 0.2574<br>day21-backend-services-llm_client.py · module · 0.1887<br>day21-backend-core-dependencies.py · module · 0.1547 | В контексте нет данных для ответа. | В контексте нет данных для ответа. | равно |
| Какие хосты пропускает тестовый гвард no_real_network и как строится временная SQLite-база в тестах (day21/tests/conftest.py)? | разрешены префиксы («127.», «localhost», «::1», «0.0.0.0»), иначе AssertionError; фикстура schema_template (session) создаёт файл схемы, а session_factory копирует его в tmp_path/«test.db» Факты: no_real_network, 127., localhost, schema_template | day21-tests-conftest.py · no_real_network · 0.3524<br>day21-tests-conftest.py · schema_template · 0.3387<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.2667<br>day21-tests-conftest.py · stub_api_base · 0.2181<br>day21-structure.md · Раскладка · 0.2163 | В контексте нет данных для ответа. | Гвард `no_real_network` пускает только локальные адреса: пустой хост, `127.*`, `localhost`, `::1`, `0.0.0.0`; остальные вызывают `AssertionError` с текстом «тест попытался выйти в сеть». Временная SQLite-база строится через session-scoped фикстуру `schema_template`: `init_db` (create_all по ~25 таблицам) выполняется один раз за прогон в `tmp_path_factory`, а тесты получают копию файла схемы. | лучше |
| Какие поля у TestQuery и что делает validate_queries (day21/backend/domain/index_scenarios.py)? | @dataclass(frozen=True) TestQuery(query, expected_sources, note) и DEMO_QUERIES из пяти записей; validate_queries() возвращает список проблем (пустой список = всё валидно) Факты: TestQuery, query, expected_sources, validate_queries | day21-backend-domain-index_scenarios.py · module · 0.5571<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.4486<br>day21-backend-services-index_comparison.py · module · 0.4421<br>day21-docs-architecture.md · Метрики сравнения · 0.3813<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.3468 | В контексте нет данных для ответа. | У `TestQuery` три поля: `query: str`, `expected_sources: tuple[str, ...]` и `note: str` [5]. `validate_queries` проверяет непустой текст и ожидаемые источники, которые есть среди `DOCUMENT_SOURCES`, до создания строки запуска [4]. | лучше |

## Итог

- Лучше с RAG: 8; хуже: 0; равно: 2 (из 10).
- Поиск нашёл ожидаемый источник во всех 10 вопросах.
- Откатов на ответ без RAG не было: модель ответила на каждый запрос.

## Приложение: полные ответы

### 1. Чему равно EXCERPT_CHARS в day21/backend/domain/indexing_prompt.py и какой заголовок печатает render_index_block?

- **Ожидание:** EXCERPT_CHARS = 300; INDEX_BLOCK_HEADER = «## Контекст из индекса документов»
- **Ключевые факты:** EXCERPT_CHARS, 300, Контекст из индекса документов
- **Ожидаемые источники:** day21/backend/domain/indexing_prompt.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** В `day21/backend/domain/indexing_prompt.py` значение `EXCERPT_CHARS` равно 300. `render_index_block` печатает заголовок `## Контекст из индекса документов`.
- **Использованные чанки:**
  - `day21-structure.md · Структура дня 21 · Раскладка · structural:day21-structure.md:0007 · 0.4105`
  - `day21-backend-domain-indexing_prompt.py · Блок найденных фрагментов индекса в системном промпте (день 21). · module · structural:day21-backend-domain-indexing_prompt.py:0000 · 0.3929`
  - `day21-backend-domain-indexing_prompt.py · Блок найденных фрагментов индекса в системном промпте (день 21). · render_index_block · structural:day21-backend-domain-indexing_prompt.py:0001 · 0.2995`
  - `day21-backend-domain-indexing_prompt.py · Блок найденных фрагментов индекса в системном промпте (день 21). · _excerpt · structural:day21-backend-domain-indexing_prompt.py:0003 · 0.1964`
  - `day21-readme.md · День 21 — индексация документов и оптимизация затрат на LLM · Индексация и поиск · structural:day21-readme.md:0006 · 0.1378`
- **Метрики:** без RAG — 2986 мс, 152 токенов; с RAG — 21009 мс, 1644 токенов, 5 чанков, контекст 1635 токенов, кэш 24.1 %

### 2. Сколько символов в одной «странице» при подсчёте объёма документов: чему равен CHARS_PER_PAGE в day21/backend/services/document_loader.py?

- **Ожидание:** CHARS_PER_PAGE = 1800
- **Ключевые факты:** CHARS_PER_PAGE, 1800
- **Ожидаемые источники:** day21/backend/services/document_loader.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** В контексте указано, что `CHARS_PER_PAGE = 1800`.
- **Использованные чанки:**
  - `day21-backend-services-document_loader.py · Сборка набора документов дня 21 в папку ``documents/`` (день 21). · module · structural:day21-backend-services-document_loader.py:0000 · 0.6406`
  - `day21-scripts-prepare_documents.py · Сборка набора документов дня 21: `documents/` плюс манифест. · module · structural:day21-scripts-prepare_documents.py:0000 · 0.4823`
  - `day21-backend-services-document_loader.py · Сборка набора документов дня 21 в папку ``documents/`` (день 21). · DocumentLoader · structural:day21-backend-services-document_loader.py:0002 · 0.1725`
  - `day21-docs-architecture.md · Архитектура приложения — индексация документов и оптимизация затрат (день 21) · Документы и их источники · structural:day21-docs-architecture.md:0002 · 0.1581`
  - `day21-readme.md · День 21 — индексация документов и оптимизация затрат на LLM · Индексация и поиск · structural:day21-readme.md:0005 · 0.1443`
- **Метрики:** без RAG — 976 мс, 159 токенов; с RAG — 931 мс, 2700 токенов, 5 чанков, контекст 2811 токенов, кэш 14.3 %

### 3. Чему равен PREVIEW_CHARS в day21/backend/services/index_service.py и какое сообщение бросается, если индекс стратегии пуст?

- **Ожидание:** PREVIEW_CHARS = 300; IndexNotBuiltError(f«Индекс стратегии {strategy!r} пуст: сначала выполните индексацию»)
- **Ключевые факты:** PREVIEW_CHARS, 300, Индекс стратегии, пуст
- **Ожидаемые источники:** day21/backend/services/index_service.py
- **Ответ без RAG:** В предоставленном контексте нет данных для ответа.
- **Ответ с RAG:** В контексте указано, что `PREVIEW_CHARS = 300`, а `_preview` показывает начало текста чанка. Сообщение об ошибке при пустом индексе стратегии в предоставленном контексте не приведено.
- **Использованные чанки:**
  - `day21-backend-services-index_service.py · Векторный индекс на FAISS плюс метаданные чанков в SQLite (день 21). · module · structural:day21-backend-services-index_service.py:0001 · 0.5003`
  - `day21-backend-services-index_service.py · Векторный индекс на FAISS плюс метаданные чанков в SQLite (день 21). · _preview · structural:day21-backend-services-index_service.py:0010 · 0.5003`
  - `day21-structure.md · Структура дня 21 · Почему сделано так (решения дня 21) · structural:day21-structure.md:0002 · 0.2161`
  - `day21-backend-core-prompt_builder.py · Строитель промптов с кэшируемым стабильным префиксом (день 21). · module · structural:day21-backend-core-prompt_builder.py:0000 · 0.2001`
  - `day21-backend-core-prompt_builder.py · Строитель промптов с кэшируемым стабильным префиксом (день 21). · PromptBuilder · structural:day21-backend-core-prompt_builder.py:0010 · 0.2001`
- **Метрики:** без RAG — 1114 мс, 155 токенов; с RAG — 1147 мс, 2146 токенов, 5 чанков, контекст 2204 токенов, кэш 36.8 %

### 4. С какой долей кириллицы текст считается русским (CYRILLIC_RATIO) и сколько записей в таблице DOCUMENT_SOURCES (day21/backend/domain/document_sources.py)?

- **Ожидание:** CYRILLIC_RATIO = 0.15; в таблице DOCUMENT_SOURCES 25 записей
- **Ключевые факты:** CYRILLIC_RATIO, 0.15, DOCUMENT_SOURCES, 25
- **Ожидаемые источники:** day21/backend/domain/document_sources.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** CYRILLIC_RATIO = 0.15, а в таблице DOCUMENT_SOURCES — 25 записей.
- **Использованные чанки:**
  - `day21-backend-domain-document_sources.py · Источники документов дня 21: что именно индексируется и как это описано данными. · detect_language · structural:day21-backend-domain-document_sources.py:0009 · 0.605`
  - `day21-backend-domain-document_sources.py · Источники документов дня 21: что именно индексируется и как это описано данными. · module · structural:day21-backend-domain-document_sources.py:0001 · 0.4029`
  - `day21-backend-domain-document_sources.py · Источники документов дня 21: что именно индексируется и как это описано данными. · module · structural:day21-backend-domain-document_sources.py:0000 · 0.3686`
  - `day21-readme.md · День 21 — индексация документов и оптимизация затрат на LLM · Индексация и поиск · structural:day21-readme.md:0006 · 0.3196`
  - `day21-backend-domain-document_sources.py · Источники документов дня 21: что именно индексируется и как это описано данными. · _code · structural:day21-backend-domain-document_sources.py:0006 · 0.2907`
- **Метрики:** без RAG — 765 мс, 164 токенов; с RAG — 1363 мс, 1772 токенов, 5 чанков, контекст 1787 токенов, кэш 44.0 %

### 5. Какой поток прогрева модели эмбеддингов создаёт при старте day21/backend/api/lifespan.py (threading.Thread, daemon=True, name=) и что запускается до этого потока?

- **Ожидание:** database.init_db() → get_manager().restore_from_db() → get_scheduler().start() → get_mcp_registry().connect_all() → get_index_service().load_all(); поток name=«embedding-warmup»
- **Ключевые факты:** init_db, restore_from_db, embedding-warmup
- **Ожидаемые источники:** day21/backend/api/lifespan.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** При старте создаётся демон-поток с `name="embedding-warmup"`, который вызывает `get_embedding_service().warmup()`. До этого выполняются: `database.init_db()`, `get_manager().restore_from_db()`, `get_scheduler().start()`, `get_mcp_registry().connect_all()` и `get_index_service().load_all()`.
- **Использованные чанки:**
  - `day21-backend-api-lifespan.py · Жизненный цикл приложения дня 20: старт и остановка фоновых служб. · lifespan · structural:day21-backend-api-lifespan.py:0002 · 0.4494`
  - `day21-backend-api-lifespan.py · Жизненный цикл приложения дня 20: старт и остановка фоновых служб. · module · structural:day21-backend-api-lifespan.py:0001 · 0.3092`
  - `day21-backend-services-indexing_service.py · Служба индексации: запуск прогонов, прогресс, поиск, статистика, очистка. · IndexingService · structural:day21-backend-services-indexing_service.py:0004 · 0.3036`
  - `day21-backend-core-dependencies.py · Зависимости API-слоя дня 18: доступ к фоновым службам и помощники роутов. · get_embedding_service · structural:day21-backend-core-dependencies.py:0009 · 0.2889`
  - `day21-structure.md · Структура дня 21 · Почему сделано так (решения дня 21) · structural:day21-structure.md:0003 · 0.2513`
- **Метрики:** без RAG — 865 мс, 168 токенов; с RAG — 1216 мс, 2299 токенов, 5 чанков, контекст 2320 токенов, кэш 34.7 %

### 6. Как ChunkStore.add_chunks проставляет embedding_id и какие id пропускает rows_by_ids (day21/backend/storage/chunk_store.py)?

- **Ожидание:** вставка идёт пачкой с flush(), затем строкам проставляется orm.embedding_id = orm.id; rows_by_ids пропускает id, которых нет в БД (например, -1 — «пустая ячейка» FAISS), порядок результата = порядок ids
- **Ключевые факты:** embedding_id, flush, -1, пропускаются
- **Ожидаемые источники:** day21/backend/storage/chunk_store.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** В контексте нет данных для ответа.
- **Использованные чанки:**
  - `day21-backend-storage-chunk_store.py · Хранилище чанков документов в SQLite (день 21): ``ChunkStore``. · module · structural:day21-backend-storage-chunk_store.py:0000 · 0.6236`
  - `day21-tests-fixtures_indexing.py · Фикстуры индексации документов (день 21). · module · structural:day21-tests-fixtures_indexing.py:0000 · 0.2082`
  - `day21-tests-fixtures_indexing.py · Фикстуры индексации документов (день 21). · chunk_store · structural:day21-tests-fixtures_indexing.py:0007 · 0.1989`
  - `day21-backend-services-index_service.py · Векторный индекс на FAISS плюс метаданные чанков в SQLite (день 21). · module · structural:day21-backend-services-index_service.py:0000 · 0.1839`
  - `day21-backend-services-index_comparison.py · Сборка метрик сравнения стратегий (день 21). · module · structural:day21-backend-services-index_comparison.py:0000 · 0.1824`
- **Метрики:** без RAG — 1237 мс, 151 токенов; с RAG — 1012 мс, 1797 токенов, 5 чанков, контекст 1859 токенов, кэш 64.5 %

### 7. Какие значения у INDEX_AGENT_TOP_K и INDEX_AGENT_STRATEGY и чему равен INDEX_MAX_TOP_K (day21/backend/core/config.py)?

- **Ожидание:** INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = «structural», INDEX_MAX_TOP_K = 20
- **Ключевые факты:** INDEX_AGENT_TOP_K, INDEX_AGENT_STRATEGY, structural, INDEX_MAX_TOP_K, 20
- **Ожидаемые источники:** day21/backend/core/config.py
- **Ответ без RAG:** В предоставленном контексте нет данных для ответа: значения `INDEX_AGENT_TOP_K`, `INDEX_AGENT_STRATEGY` и `INDEX_MAX_TOP_K` не приведены.
- **Ответ с RAG:** В контексте указано: `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`, `INDEX_MAX_TOP_K = 20`.
- **Использованные чанки:**
  - `day21-backend-core-config.py · Конфигурация бэкенда дня 17: DeepSeek, дефолты агентов, стратегии, память, профиль. · module · structural:day21-backend-core-config.py:0008 · 0.6579`
  - `day21-backend-api-indexing.py · Роутер API дня 21: индексация документов и поиск по индексу. · indexing_search · structural:day21-backend-api-indexing.py:0007 · 0.346`
  - `day21-backend-services-indexing_service.py · Служба индексации: запуск прогонов, прогресс, поиск, статистика, очистка. · IndexingService · structural:day21-backend-services-indexing_service.py:0006 · 0.2373`
  - `day21-backend-services-index_comparison.py · Сборка метрик сравнения стратегий (день 21). · module · structural:day21-backend-services-index_comparison.py:0000 · 0.223`
  - `day21-scripts-indexing_scenarios.py · Пять сценариев проверки индексации документов (день 21). · print_summary · structural:day21-scripts-indexing_scenarios.py:0015 · 0.2145`
- **Метрики:** без RAG — 1324 мс, 193 токенов; с RAG — 1755 мс, 2411 токенов, 5 чанков, контекст 2328 токенов, кэш 16.2 %

### 8. Какое исключение и с каким текстом бросает LLMClient, если не передан client_factory (day21/backend/services/llm_client.py)?

- **Ожидание:** RuntimeError(«LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)»)
- **Ключевые факты:** RuntimeError, client_factory, Agent._make_client
- **Ожидаемые источники:** day21/backend/services/llm_client.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** В контексте нет данных для ответа.
- **Использованные чанки:**
  - `day21-readme.md · День 21 — индексация документов и оптимизация затрат на LLM · Таблицы `document_chunks` и `index_runs` · structural:day21-readme.md:0010 · 0.3838`
  - `day21-backend-services-llm_client.py · Единственная точка вызова DeepSeek: модель по задаче, метрики кэша, журнал (день 21). · LLMClient · structural:day21-backend-services-llm_client.py:0005 · 0.2642`
  - `day21-backend-core-dependencies.py · Зависимости API-слоя дня 18: доступ к фоновым службам и помощники роутов. · get_llm_client · structural:day21-backend-core-dependencies.py:0010 · 0.2574`
  - `day21-backend-services-llm_client.py · Единственная точка вызова DeepSeek: модель по задаче, метрики кэша, журнал (день 21). · module · structural:day21-backend-services-llm_client.py:0000 · 0.1887`
  - `day21-backend-core-dependencies.py · Зависимости API-слоя дня 18: доступ к фоновым службам и помощники роутов. · module · structural:day21-backend-core-dependencies.py:0000 · 0.1547`
- **Метрики:** без RAG — 869 мс, 155 токенов; с RAG — 1018 мс, 2461 токенов, 5 чанков, контекст 2585 токенов, кэш 15.7 %

### 9. Какие хосты пропускает тестовый гвард no_real_network и как строится временная SQLite-база в тестах (day21/tests/conftest.py)?

- **Ожидание:** разрешены префиксы («127.», «localhost», «::1», «0.0.0.0»), иначе AssertionError; фикстура schema_template (session) создаёт файл схемы, а session_factory копирует его в tmp_path/«test.db»
- **Ключевые факты:** no_real_network, 127., localhost, schema_template
- **Ожидаемые источники:** day21/tests/conftest.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** Гвард `no_real_network` пускает только локальные адреса: пустой хост, `127.*`, `localhost`, `::1`, `0.0.0.0`; остальные вызывают `AssertionError` с текстом «тест попытался выйти в сеть». Временная SQLite-база строится через session-scoped фикстуру `schema_template`: `init_db` (create_all по ~25 таблицам) выполняется один раз за прогон в `tmp_path_factory`, а тесты получают копию файла схемы.
- **Использованные чанки:**
  - `day21-tests-conftest.py · Фикстуры pytest дня 21: временная БД (копия общей схемы), агент с подменённым · no_real_network · structural:day21-tests-conftest.py:0004 · 0.3524`
  - `day21-tests-conftest.py · Фикстуры pytest дня 21: временная БД (копия общей схемы), агент с подменённым · schema_template · structural:day21-tests-conftest.py:0006 · 0.3387`
  - `day21-backend-domain-index_scenarios.py · Тестовые запросы демонстрации индексации и их проверка (день 21). · TestQuery · structural:day21-backend-domain-index_scenarios.py:0001 · 0.2667`
  - `day21-tests-conftest.py · Фикстуры pytest дня 21: временная БД (копия общей схемы), агент с подменённым · stub_api_base · structural:day21-tests-conftest.py:0005 · 0.2181`
  - `day21-structure.md · Структура дня 21 · Раскладка · structural:day21-structure.md:0008 · 0.2163`
- **Метрики:** без RAG — 756 мс, 161 токенов; с RAG — 1663 мс, 2244 токенов, 5 чанков, контекст 2147 токенов, кэш 18.2 %

### 10. Какие поля у TestQuery и что делает validate_queries (day21/backend/domain/index_scenarios.py)?

- **Ожидание:** @dataclass(frozen=True) TestQuery(query, expected_sources, note) и DEMO_QUERIES из пяти записей; validate_queries() возвращает список проблем (пустой список = всё валидно)
- **Ключевые факты:** TestQuery, query, expected_sources, validate_queries
- **Ожидаемые источники:** day21/backend/domain/index_scenarios.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Ответ с RAG:** У `TestQuery` три поля: `query: str`, `expected_sources: tuple[str, ...]` и `note: str` [5]. `validate_queries` проверяет непустой текст и ожидаемые источники, которые есть среди `DOCUMENT_SOURCES`, до создания строки запуска [4].
- **Использованные чанки:**
  - `day21-backend-domain-index_scenarios.py · Тестовые запросы демонстрации индексации и их проверка (день 21). · module · structural:day21-backend-domain-index_scenarios.py:0000 · 0.5571`
  - `day21-backend-domain-index_scenarios.py · Тестовые запросы демонстрации индексации и их проверка (день 21). · TestQuery · structural:day21-backend-domain-index_scenarios.py:0002 · 0.4486`
  - `day21-backend-services-index_comparison.py · Сборка метрик сравнения стратегий (день 21). · module · structural:day21-backend-services-index_comparison.py:0000 · 0.4421`
  - `day21-docs-architecture.md · Архитектура приложения — индексация документов и оптимизация затрат (день 21) · Метрики сравнения · structural:day21-docs-architecture.md:0013 · 0.3813`
  - `day21-backend-domain-index_scenarios.py · Тестовые запросы демонстрации индексации и их проверка (день 21). · TestQuery · structural:day21-backend-domain-index_scenarios.py:0001 · 0.3468`
- **Метрики:** без RAG — 832 мс, 144 токенов; с RAG — 1116 мс, 1916 токенов, 5 чанков, контекст 1898 токенов, кэш 48.6 %

