# День 23 — RAG: режимы отбора (реранкер, порог, rewrite)

Отчёт собран прогоном `scripts/run_rag_eval.py`: топ-K = 5, стратегия = rag_corpus_structural, режимы = baseline, rewrite, rerank, rerank_filter, порог отсечения = 0.05,
корпус — 36 документов / 314669 символов (~174 страниц), индекс — 680 чанков, время прогона 128 с.

## Как считался вердикт
Ключевые факты вопроса ищутся в тексте ответа (вхождение без учёта регистра); доля найденных фактов
сравнивается с ответом без корпуса: «лучше» — доля выше, «хуже» — ниже, «равно» — доли совпали.
Второй вердикт сравнивает каждый режим с базовым отбором дня 22: видно, что добавляют ступени дня 23
к тому, что уже работало. Вопросы намеренно про значения из файлов корпуса: их нельзя воспроизвести
по памяти, поэтому ответ без корпуса служит честным эталоном.

## Таблица сравнения

| Вопрос | Ожидание (ключевые факты) | Источники (файл · раздел · score) | Ответ без RAG | Ответ baseline | Ответ rewrite | Ответ rerank | Ответ rerank_filter | Вердикт vs без RAG | Вердикт vs baseline |
|---|---|---|---|---|---|---|---|---|---|
| Чему равно EXCERPT_CHARS в day21/backend/domain/indexing_prompt.py и какой заголовок печатает render_index_block? | EXCERPT_CHARS = 300; INDEX_BLOCK_HEADER = «## Контекст из индекса документов» Факты: EXCERPT_CHARS, 300, Контекст из индекса документов | **baseline** — day21-structure.md · Раскладка · 0.4105 · vector=0.0 · lexical=0.4105<br>day21-backend-domain-indexing_prompt.py · module · 0.3929 · vector=0.0 · lexical=0.3929<br>day21-backend-domain-indexing_prompt.py · render_index_block · 0.2995 · vector=0.5156 · lexical=0.1964<br>day21-backend-domain-indexing_prompt.py · _excerpt · 0.1964 · vector=0.0 · lexical=0.1964<br>day21-readme.md · Индексация и поиск · 0.1378 · vector=0.5319 · lexical=0.0314<br>**rewrite** — day21-structure.md · Раскладка · 0.4917 · vector=0.0 · lexical=0.4917<br>day21-backend-domain-indexing_prompt.py · module · 0.4707 · vector=0.0 · lexical=0.4707<br>day21-backend-domain-indexing_prompt.py · render_index_block… | В контексте нет данных для ответа. | В контексте нет данных для ответа. | EXCERPT_CHARS равен 300 — это длина выдержки из чанка в блоке промпта. render_index_block печатает заголовок INDEX_BLOCK_HEADER: «## Контекст из индекса документов». | В контексте указано, что EXCERPT_CHARS = 300, а render_index_block печатает заголовок `## Контекст из индекса документов` (INDEX_BLOCK_HEADER). Источник: day21-backend-domain-indexing_prompt.py. | ⚠ отсечено 20 из 30: В контексте указано, что `EXCERPT_CHARS = 300` в модуле day21/backend/domain/indexing_prompt.py. Заголовок блока — `INDEX_BLOCK_HEADER = "## Контекст из индекса документов"`. | baseline: равно<br>rewrite: лучше<br>rerank: лучше<br>rerank_filter: лучше | baseline: —<br>rewrite: лучше<br>rerank: лучше<br>rerank_filter: лучше |
| Сколько символов в одной «странице» при подсчёте объёма документов: чему равен CHARS_PER_PAGE в day21/backend/services/document_loader.py? | CHARS_PER_PAGE = 1800 Факты: CHARS_PER_PAGE, 1800 | **baseline** — day21-backend-services-document_loader.py · module · 0.6406 · vector=0.0 · lexical=0.6406<br>day21-scripts-prepare_documents.py · module · 0.4823 · vector=0.0 · lexical=0.4823<br>day21-backend-services-document_loader.py · DocumentLoader · 0.1725 · vector=0.0 · lexical=0.1725<br>day21-docs-architecture.md · Документы и их источники · 0.1581 · vector=0.6205 · lexical=0.034<br>day21-readme.md · Индексация и поиск · 0.1443 · vector=0.5516 · lexical=0.034<br>**rewrite** — day21-scripts-prepare_documents.py · module · 1.0928 · vector=0.4642 · lexical=1.0<br>day21-backend-services-document_loader.py · module · 0.6514 · vector=0.0 · lexical=0.6514<br>day21-backend-services-document_… | В контексте нет данных для ответа. | В контексте указано: `CHARS_PER_PAGE = 1800`. | В контексте указано, что CHARS_PER_PAGE равен 1800 символам. | В контексте нет данных для ответа. | ⚠ отсечено 20 из 30: В контексте нет данных для ответа: значение `CHARS_PER_PAGE` из `day21/backend/services/document_loader.py` не приведено. Из фрагмента [5] видно лишь, что «страница» — это 1800 символов (`PAGE = CHARS_PER_PAGE`), но самого равенства в контексте нет. | baseline: лучше<br>rewrite: лучше<br>rerank: равно<br>rerank_filter: лучше | baseline: —<br>rewrite: равно<br>rerank: хуже<br>rerank_filter: равно |
| Чему равен PREVIEW_CHARS в day21/backend/services/index_service.py и какое сообщение бросается, если индекс стратегии пуст? | PREVIEW_CHARS = 300; IndexNotBuiltError(f«Индекс стратегии {strategy!r} пуст: сначала выполните индексацию») Факты: PREVIEW_CHARS, 300, Индекс стратегии, пуст | **baseline** — day21-backend-services-index_service.py · module · 0.5003 · vector=0.0 · lexical=0.5003<br>day21-backend-services-index_service.py · _preview · 0.5003 · vector=0.0 · lexical=0.5003<br>day21-structure.md · Почему сделано так (решения дня 21) · 0.2161 · vector=0.0 · lexical=0.2161<br>day21-backend-core-prompt_builder.py · module · 0.2001 · vector=0.0 · lexical=0.2001<br>day21-backend-core-prompt_builder.py · PromptBuilder · 0.2001 · vector=0.0 · lexical=0.2001<br>**rewrite** — day21-backend-services-index_service.py · module · 0.5838 · vector=0.0 · lexical=0.5838<br>day21-backend-services-index_service.py · _preview · 0.5838 · vector=0.0 · lexical=0.5838<br>day21-tests-fixtures… | В контексте нет данных для ответа. | В контексте нет данных для ответа. | PREVIEW_CHARS равен 300. В предоставленном контексте нет данных о сообщении, которое бросается при пустом индексе стратегии. | В контексте нет данных для ответа. | ⚠ отсечено 12 из 30: В контексте нет данных для ответа. | baseline: равно<br>rewrite: лучше<br>rerank: равно<br>rerank_filter: равно | baseline: —<br>rewrite: лучше<br>rerank: равно<br>rerank_filter: равно |
| С какой долей кириллицы текст считается русским (CYRILLIC_RATIO) и сколько записей в таблице DOCUMENT_SOURCES (day21/backend/domain/document_sources.py)? | CYRILLIC_RATIO = 0.15; в таблице DOCUMENT_SOURCES 25 записей Факты: CYRILLIC_RATIO, 0.15, DOCUMENT_SOURCES, 25 | **baseline** — day21-backend-domain-document_sources.py · detect_language · 0.605 · vector=0.4963 · lexical=0.5057<br>day21-backend-domain-document_sources.py · module · 0.4029 · vector=0.4974 · lexical=0.3034<br>day21-backend-domain-document_sources.py · module · 0.3686 · vector=0.3877 · lexical=0.2911<br>day21-readme.md · Индексация и поиск · 0.3196 · vector=0.4821 · lexical=0.2232<br>day21-backend-domain-document_sources.py · _code · 0.2907 · vector=0.3805 · lexical=0.2146<br>**rewrite** — day21-backend-api-indexing.py · run_demo · 0.3898 · vector=0.0 · lexical=0.3898<br>day21-backend-domain-document_sources.py · detect_language · 0.3248 · vector=0.0 · lexical=0.3248<br>day21-backend-dom… | В контексте нет данных для ответа. | CYRILLIC_RATIO = 0.15. В таблице DOCUMENT_SOURCES 25 записей (шестнадцать README, три docs, четыре кода, два guide). | В контексте нет данных для ответа. | CYRILLIC_RATIO = 0.15, а таблица DOCUMENT_SOURCES содержит 25 записей. | ⚠ отсечено 29 из 30: В контексте нет данных для ответа. | baseline: лучше<br>rewrite: равно<br>rerank: лучше<br>rerank_filter: равно | baseline: —<br>rewrite: хуже<br>rerank: равно<br>rerank_filter: хуже |
| Какой поток прогрева моделей создаёт при старте day21/backend/api/lifespan.py (threading.Thread, daemon=True, name=) и что запускается до этого потока? | database.init_db() → get_manager().restore_from_db() → get_scheduler().start() → get_mcp_registry().connect_all() → get_index_service().load_all(); поток name=«model-warmup» прогревает эмбеддер и реранкер (день 23) Факты: init_db, restore_from_db, model-warmup | **baseline** — day21-backend-services-embedding_service.py · module · 0.3352 · vector=0.4826 · lexical=0.2387<br>day21-backend-api-lifespan.py · lifespan · 0.3028 · vector=0.0 · lexical=0.3028<br>day21-backend-services-indexing_service.py · IndexingService · 0.2668 · vector=0.0 · lexical=0.2668<br>day21-backend-api-lifespan.py · module · 0.2574 · vector=0.4033 · lexical=0.1767<br>day21-backend-core-dependencies.py · get_embedding_service · 0.2497 · vector=0.4923 · lexical=0.1512<br>**rewrite** — day21-backend-api-lifespan.py · lifespan · 0.4696 · vector=0.492 · lexical=0.3712<br>day21-backend-services-indexing_service.py · IndexingService · 0.3271 · vector=0.0 · lexical=0.3271<br>day21-back… | В контексте нет данных для ответа. | При старте создаётся `threading.Thread(target=dependencies.get_embedding_service().warmup, daemon=True, name="embedding-warmup")`. До этого потока выполняются: `database.init_db()`, `dependencies.get_manager().restore_from_db()`, `dependencies.get_scheduler().start()`, `dependencies.get_mcp_registry().connect_all()` и `dependencies.get_index_service().load_all()`. | В контексте нет данных для ответа. В приведённом фрагменте [1] видно, что поток прогрева создаётся как `threading.Thread(target=dependencies.get_embedding_service().warmup, daemon=True, name="embedding-warmup")`, но конкретное значение параметра `name=` в этом блоке отсутствует — там указано `name="embedding-warmup"`? Нет, в тексте блока [1] параметр `name` не показан полностью. До этого потока запускаются: `database.init_db()`, `dependencies.get_manager().restore_from_db()`, `dependencies.get_scheduler().start()`, `dependencies.get_mcp_registry().connect_all()`, `dependencies.get_index_service().load_all()`. | В контексте нет данных для ответа. | ⚠ отсечено 19 из 30: В контексте нет данных для ответа. | baseline: лучше<br>rewrite: лучше<br>rerank: равно<br>rerank_filter: равно | baseline: —<br>rewrite: равно<br>rerank: хуже<br>rerank_filter: хуже |
| Как ChunkStore.add_chunks проставляет embedding_id и какие id пропускает rows_by_ids (day21/backend/storage/chunk_store.py)? | вставка идёт пачкой с flush(), затем строкам проставляется orm.embedding_id = orm.id; rows_by_ids пропускает id, которых нет в БД (например, -1 — «пустая ячейка» FAISS), порядок результата = порядок ids Факты: embedding_id, flush, -1, пропускаются | **baseline** — day21-backend-storage-chunk_store.py · module · 0.6236 · vector=0.4479 · lexical=0.534<br>day21-tests-fixtures_indexing.py · module · 0.2082 · vector=0.4673 · lexical=0.1147<br>day21-tests-fixtures_indexing.py · chunk_store · 0.1989 · vector=0.6034 · lexical=0.0782<br>day21-backend-services-index_service.py · module · 0.1839 · vector=0.4853 · lexical=0.0868<br>day21-backend-services-index_comparison.py · module · 0.1824 · vector=0.0 · lexical=0.1824<br>**rewrite** — day21-backend-storage-chunk_store.py · module · 0.511 · vector=0.0 · lexical=0.511<br>day21-backend-storage-chunk_store.py · ChunkStore · 0.511 · vector=0.0 · lexical=0.511<br>day21-tests-fixtures_indexing.py · mo… | В контексте нет данных для ответа. | В контексте нет данных для ответа. | В контексте нет данных для ответа. | `add_chunks` после `flush()` проставляет `embedding_id = orm.id` каждому чанку. `rows_by_ids` отбрасывает id меньше нуля (например, `-1` — «пустая ячейка» FAISS) и пропускает отсутствующие в БД id. | Add_chunks заводит строки, делает flush(), затем проставляет `embedding_id = id` для каждой строки, после чего commit() и возвращает id. Rows_by_ids отбрасывает id меньше нуля (например, -1 — «пустая ячейка» FAISS), а отсутствующие в БД id пропускает. | baseline: равно<br>rewrite: равно<br>rerank: лучше<br>rerank_filter: лучше | baseline: —<br>rewrite: равно<br>rerank: лучше<br>rerank_filter: лучше |
| Какие значения у INDEX_AGENT_TOP_K и INDEX_AGENT_STRATEGY и чему равен INDEX_MAX_TOP_K (day21/backend/core/config.py)? | INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = «structural», INDEX_MAX_TOP_K = 20 Факты: INDEX_AGENT_TOP_K, INDEX_AGENT_STRATEGY, structural, INDEX_MAX_TOP_K, 20 | **baseline** — day21-backend-core-config.py · module · 0.6579 · vector=0.0 · lexical=0.6579<br>day21-backend-api-indexing.py · indexing_search · 0.346 · vector=0.5433 · lexical=0.2373<br>day21-backend-services-indexing_service.py · IndexingService · 0.2373 · vector=0.0 · lexical=0.2373<br>day21-backend-services-index_comparison.py · module · 0.223 · vector=0.0 · lexical=0.223<br>day21-scripts-indexing_scenarios.py · print_summary · 0.2145 · vector=0.0 · lexical=0.2145<br>**rewrite** — day21-backend-core-config.py · module · 0.9557 · vector=0.0 · lexical=0.9557<br>day21-backend-api-indexing.py · indexing_search · 0.4631 · vector=0.5926 · lexical=0.3446<br>day21-backend-services-indexing_serv… | В контексте нет данных для ответа. | В контексте указано: `INDEX_MAX_TOP_K = 20`, `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`. | В контексте указано: `INDEX_MAX_TOP_K = 20`, `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`. | INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = "structural", INDEX_MAX_TOP_K = 20. | ⚠ отсечено 13 из 30: В контексте указаны: `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`, `INDEX_MAX_TOP_K = 20` (day21/backend/core/config.py). | baseline: лучше<br>rewrite: лучше<br>rerank: лучше<br>rerank_filter: лучше | baseline: —<br>rewrite: равно<br>rerank: равно<br>rerank_filter: равно |
| Какое исключение и с каким текстом бросает LLMClient, если не передан client_factory (day21/backend/services/llm_client.py)? | RuntimeError(«LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)») Факты: RuntimeError, client_factory, Agent._make_client | **baseline** — day21-readme.md · Таблицы `document_chunks` и `index_runs` · 0.3838 · vector=0.0 · lexical=0.3838<br>day21-backend-services-llm_client.py · LLMClient · 0.2642 · vector=0.0 · lexical=0.2642<br>day21-backend-core-dependencies.py · get_llm_client · 0.2574 · vector=0.6398 · lexical=0.1294<br>day21-backend-services-llm_client.py · module · 0.1887 · vector=0.0 · lexical=0.1887<br>day21-backend-core-dependencies.py · module · 0.1547 · vector=0.0 · lexical=0.1547<br>**rewrite** — day21-backend-services-llm_client.py · LLMClient · 0.6061 · vector=0.0 · lexical=0.6061<br>day21-backend-services-llm_client.py · module · 0.4329 · vector=0.0 · lexical=0.4329<br>day21-backend-core-dependenc… | В контексте нет данных для ответа. | `LLMClient` бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)». | Если `client_factory` не передан, `LLMClient` бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)». | LLMClient бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)». | ⚠ отсечено 24 из 30: LLMClient бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)». | baseline: лучше<br>rewrite: лучше<br>rerank: лучше<br>rerank_filter: лучше | baseline: —<br>rewrite: равно<br>rerank: равно<br>rerank_filter: равно |
| Какие хосты пропускает тестовый гвард no_real_network и как строится временная SQLite-база в тестах (day21/tests/conftest.py)? | разрешены префиксы («127.», «localhost», «::1», «0.0.0.0»), иначе AssertionError; фикстура schema_template (session) создаёт файл схемы, а session_factory копирует его в tmp_path/«test.db» Факты: no_real_network, 127., localhost, schema_template | **baseline** — day21-tests-conftest.py · no_real_network · 0.3524 · vector=0.5023 · lexical=0.2519<br>day21-tests-conftest.py · schema_template · 0.3387 · vector=0.533 · lexical=0.2321<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.2667 · vector=0.0 · lexical=0.2667<br>day21-tests-conftest.py · stub_api_base · 0.2181 · vector=0.498 · lexical=0.1185<br>day21-structure.md · Раскладка · 0.2163 · vector=0.0 · lexical=0.2163<br>**rewrite** — day21-tests-conftest.py · no_real_network · 0.3974 · vector=0.5185 · lexical=0.2937<br>day21-backend-services-index_service.py · IndexService · 0.3225 · vector=0.0 · lexical=0.3225<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.3109 ·… | В контексте нет данных для ответа. | Гвард `no_real_network` пропускает только локальные адреса: пустой хост, а также хосты, начинающиеся с `127.`, `localhost`, `::1`, `0.0.0.0` — остальные вызовы падают с `AssertionError`. База строится через session-scoped фикстуру `schema_template`: `init_db` (create_all по ~25 таблицам) выполняется один раз за прогон, а тесты получают копию файла схемы. | Гвард `no_real_network` пропускает только локальные адреса: пустой host, а также хосты, начинающиеся с `127.`, `localhost`, `::1`, `0.0.0.0`; остальные вызывают `AssertionError` с текстом «тест попытался выйти в сеть». Про построение временной SQLite-базы в предоставленном контексте данных нет — упоминается лишь session-scoped фикстура `schema_template` для схемы БД. | Гвард `no_real_network` пропускает только локальные адреса: пустой хост, а также те, что начинаются на `127.`, `localhost`, `::1`, `0.0.0.0`. Остальные хосты вызывают `AssertionError` с текстом про попытку выхода в сеть. Про построение временной SQLite-базы: в предоставленном контексте есть только упоминание в заголовке чанка («временная БД (копия общей схемы)») и импорты `init_db`, `make_engine`, `make_session_factory` из `backend.storage.database`. Деталей самой фикстуры в контексте нет. | ⚠ отсечено 27 из 30: В контексте нет данных для ответа. | baseline: лучше<br>rewrite: лучше<br>rerank: лучше<br>rerank_filter: равно | baseline: —<br>rewrite: равно<br>rerank: хуже<br>rerank_filter: хуже |
| Какие поля у TestQuery и что делает validate_queries (day21/backend/domain/index_scenarios.py)? | @dataclass(frozen=True) TestQuery(query, expected_sources, note) и DEMO_QUERIES из пяти записей; validate_queries() возвращает список проблем (пустой список = всё валидно) Факты: TestQuery, query, expected_sources, validate_queries | **baseline** — day21-backend-domain-index_scenarios.py · module · 0.5571 · vector=0.5573 · lexical=0.4456<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.4486 · vector=0.5089 · lexical=0.3468<br>day21-backend-services-index_comparison.py · module · 0.4421 · vector=0.0 · lexical=0.4421<br>day21-docs-architecture.md · Метрики сравнения · 0.3813 · vector=0.5968 · lexical=0.2619<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.3468 · vector=0.0 · lexical=0.3468<br>**rewrite** — day21-backend-domain-index_scenarios.py · module · 0.8389 · vector=0.4938 · lexical=0.7401<br>day21-backend-domain-index_scenarios.py · TestQuery · 0.5759 · vector=0.0 · lexical=0.5759<br>day21-docs-… | В контексте нет данных для ответа. | У `TestQuery` три поля: `query`, `expected_sources` и `note` (dataclass frozen). `validate_queries` проверяет непустой текст и ожидаемые источники, которые есть среди `DOCUMENT_SOURCES`, до создания строки запуска. | TestQuery — это frozen dataclass с полями: query (текст), expected_sources (кортеж ожидаемых источников) и note (пояснение для отчёта). validate_queries проверяет тестовые запросы и возвращает список ошибок; пустой список означает, что всё в порядке. Ловятся пустой текст запроса, отсутствие ожидаемых источников и ожидаемый источник, которого нет среди DOCUMENT_SOURCES. | TestQuery — dataclass из `day21/backend/domain/index_scenarios.py`, содержит поля `query` и `expected_sources` (судя по коду `validate_queries`). `validate_queries` проверяет тестовые запросы и возвращает список ошибок (пустой — всё в порядке): пустой текст запроса, отсутствие ожидаемых источников и ожидаемый источник, которого нет среди `DOCUMENT_SOURCES`. | ⚠ отсечено 14 из 30: В контексте нет данных для ответа. | baseline: лучше<br>rewrite: лучше<br>rerank: лучше<br>rerank_filter: равно | baseline: —<br>rewrite: равно<br>rerank: равно<br>rerank_filter: хуже |

## Свип порога отсечения

Порог выбирается по измерению, а не на глаз: прогон повторяется с сеткой порогов, и берётся
наименьший положительный, при котором каждый вопрос сохраняет хотя бы один фрагмент, а ожидаемый источник
сохраняется минимум в 9 из них. Вопросов с баллами реранкера: 10. Ноль — это выключенное отсечение, а не порог:
при нуле режим `rerank_filter` повторяет `rerank` до последнего фрагмента. Баллы для свипа не
пересчитываются: кросс-энкодер прогоняется один раз, порог только отсекает по сохранённым баллам.

| Порог | Вопросов с фрагментами | Ожидаемый источник сохранён | Вывод |
|---|---|---|---|
| 0.00 | 10 из 10 | 10 из 10 | отсечение выключено |
| 0.05 | 10 из 10 | 9 из 10 | **выбран** |
| 0.10 | 10 из 10 | 9 из 10 | проходит, но выше выбранного |
| 0.15 | 10 из 10 | 9 из 10 | проходит, но выше выбранного |
| 0.20 | 10 из 10 | 9 из 10 | проходит, но выше выбранного |
| 0.25 | 10 из 10 | 9 из 10 | проходит, но выше выбранного |
| 0.30 | 10 из 10 | 9 из 10 | проходит, но выше выбранного |
| 0.35 | 9 из 10 | 8 из 10 | часть вопросов без фрагментов |
| 0.40 | 9 из 10 | 8 из 10 | часть вопросов без фрагментов |
| 0.45 | 9 из 10 | 8 из 10 | часть вопросов без фрагментов |
| 0.50 | 9 из 10 | 8 из 10 | часть вопросов без фрагментов |
| 0.55 | 9 из 10 | 8 из 10 | часть вопросов без фрагментов |
| 0.60 | 9 из 10 | 8 из 10 | часть вопросов без фрагментов |
| 0.65 | 9 из 10 | 6 из 10 | часть вопросов без фрагментов |
| 0.70 | 8 из 10 | 5 из 10 | часть вопросов без фрагментов |
| 0.75 | 8 из 10 | 5 из 10 | часть вопросов без фрагментов |
| 0.80 | 8 из 10 | 5 из 10 | часть вопросов без фрагментов |
| 0.85 | 8 из 10 | 4 из 10 | часть вопросов без фрагментов |
| 0.90 | 6 из 10 | 4 из 10 | часть вопросов без фрагментов |

Выбранный порог: **0.05**. В прогоне использован 0.05

## Итог

- `baseline`: лучше — 7, хуже — 0, равно — 3 (против «без RAG»); против `baseline` — лучше 0, хуже 0, равно 10.
- `baseline`: кандидатов до отсечения 30.0, после 5.0 (вопросов в среднем 10); промахов поиска нет — источник найден во всех вопросах.
- `rewrite`: лучше — 8, хуже — 0, равно — 2 (против «без RAG»); против `baseline` — лучше 2, хуже 1, равно 7.
- `rewrite`: кандидатов до отсечения 30.0, после 5.0 (вопросов в среднем 10); промахов поиска нет — источник найден во всех вопросах.
- `rerank`: лучше — 7, хуже — 0, равно — 3 (против «без RAG»); против `baseline` — лучше 2, хуже 3, равно 5.
- `rerank`: кандидатов до отсечения 30.0, после 5.0 (вопросов в среднем 10); промахов поиска 3 из 10 — там ответ опирался на соседние фрагменты корпуса.
- `rerank_filter`: лучше — 5, хуже — 0, равно — 5 (против «без RAG»); против `baseline` — лучше 2, хуже 4, равно 4.
- `rerank_filter`: кандидатов до отсечения 30.0, после 4.4 (вопросов в среднем 10); промахов поиска 3 из 10 — там ответ опирался на соседние фрагменты корпуса.
- Сбоев запросов не было: все режимы ответили на все вопросы.
- Откатов на ответ без RAG не было: модель ответила на каждый запрос.
- Вердикты считались по вопросам выше (вопросов в отчёте: 10); режим `baseline` повторяет отбор дня 22 и служит второй точкой сравнения.
- Сверка ступени отсечения: `rerank_filter` против `rerank` — лучше 1, хуже 3, равно 6 (вопросов 10).

## Приложение: полные ответы

### 1. Чему равно EXCERPT_CHARS в day21/backend/domain/indexing_prompt.py и какой заголовок печатает render_index_block?

- **Ожидание:** EXCERPT_CHARS = 300; INDEX_BLOCK_HEADER = «## Контекст из индекса документов»
- **Ключевые факты:** EXCERPT_CHARS, 300, Контекст из индекса документов
- **Ожидаемые источники:** day21/backend/domain/indexing_prompt.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** В контексте нет данных для ответа.
- **Метрики baseline:** 19439 мс, 1604 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1635 токенов, кэш 88.3 %
- **Отобранные фрагменты baseline:**
  - `day21-structure.md · Раскладка · 0.4105 · vector=0.0 · lexical=0.4105`
  - `day21-backend-domain-indexing_prompt.py · module · 0.3929 · vector=0.0 · lexical=0.3929`
  - `day21-backend-domain-indexing_prompt.py · render_index_block · 0.2995 · vector=0.5156 · lexical=0.1964`
  - `day21-backend-domain-indexing_prompt.py · _excerpt · 0.1964 · vector=0.0 · lexical=0.1964`
  - `day21-readme.md · Индексация и поиск · 0.1378 · vector=0.5319 · lexical=0.0314`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** EXCERPT_CHARS равен 300 — это длина выдержки из чанка в блоке промпта. render_index_block печатает заголовок INDEX_BLOCK_HEADER: «## Контекст из индекса документов».
- **Поисковый запрос rewrite:** EXCERPT_CHARS day21/backend/domain/indexing_prompt.py render_index_block заголовок
- **Метрики rewrite:** 1951 мс, 1648 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1635 токенов, кэш 88.3 %
- **Отобранные фрагменты rewrite:**
  - `day21-structure.md · Раскладка · 0.4917 · vector=0.0 · lexical=0.4917`
  - `day21-backend-domain-indexing_prompt.py · module · 0.4707 · vector=0.0 · lexical=0.4707`
  - `day21-backend-domain-indexing_prompt.py · render_index_block · 0.3332 · vector=0.4897 · lexical=0.2353`
  - `day21-backend-domain-indexing_prompt.py · _excerpt · 0.2353 · vector=0.0 · lexical=0.2353`
  - `day21-readme.md · Индексация и поиск · 0.1392 · vector=0.5079 · lexical=0.0376`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** В контексте указано, что EXCERPT_CHARS = 300, а render_index_block печатает заголовок `## Контекст из индекса документов` (INDEX_BLOCK_HEADER). Источник: day21-backend-domain-indexing_prompt.py.
- **Метрики rerank:** 11774 мс, 1756 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1774 токенов, кэш 90.7 %
- **Отобранные фрагменты rerank:**
  - `day21-backend-domain-indexing_prompt.py · module · 0.9539 · rerank=0.9539 · vector=0.0 · lexical=0.3929`
  - `day21-tests-fixtures_indexing.py · module · 0.8646 · rerank=0.8646 · vector=0.5397 · lexical=0.0067`
  - `day21-readme.md · Индексация и поиск · 0.5898 · rerank=0.5898 · vector=0.5319 · lexical=0.0314`
  - `day21-backend-core-config.py · module · 0.5074 · rerank=0.5074 · vector=0.5869 · lexical=0.0202`
  - `day21-docs-reports-indexing_demo.md · День 21 — индексация документов: две стратегии чанкинга и сравнение · 0.394 · rerank=0.394 · vector=0.5418 · lexical=0.0`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте указано, что `EXCERPT_CHARS = 300` в модуле day21/backend/domain/indexing_prompt.py. Заголовок блока — `INDEX_BLOCK_HEADER = "## Контекст из индекса документов"`.
- **Метрики rerank_filter:** 984 мс, 1755 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 1774 токенов, кэш 90.7 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-domain-indexing_prompt.py · module · 0.9539 · rerank=0.9539 · vector=0.0 · lexical=0.3929`
  - `day21-tests-fixtures_indexing.py · module · 0.8646 · rerank=0.8646 · vector=0.5397 · lexical=0.0067`
  - `day21-readme.md · Индексация и поиск · 0.5898 · rerank=0.5898 · vector=0.5319 · lexical=0.0314`
  - `day21-backend-core-config.py · module · 0.5074 · rerank=0.5074 · vector=0.5869 · lexical=0.0202`
  - `day21-docs-reports-indexing_demo.md · День 21 — индексация документов: две стратегии чанкинга и сравнение · 0.394 · rerank=0.394 · vector=0.5418 · lexical=0.0`

### 2. Сколько символов в одной «странице» при подсчёте объёма документов: чему равен CHARS_PER_PAGE в day21/backend/services/document_loader.py?

- **Ожидание:** CHARS_PER_PAGE = 1800
- **Ключевые факты:** CHARS_PER_PAGE, 1800
- **Ожидаемые источники:** day21/backend/services/document_loader.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** В контексте указано: `CHARS_PER_PAGE = 1800`.
- **Метрики baseline:** 909 мс, 2699 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2811 токенов, кэш 90.7 %
- **Отобранные фрагменты baseline:**
  - `day21-backend-services-document_loader.py · module · 0.6406 · vector=0.0 · lexical=0.6406`
  - `day21-scripts-prepare_documents.py · module · 0.4823 · vector=0.0 · lexical=0.4823`
  - `day21-backend-services-document_loader.py · DocumentLoader · 0.1725 · vector=0.0 · lexical=0.1725`
  - `day21-docs-architecture.md · Документы и их источники · 0.1581 · vector=0.6205 · lexical=0.034`
  - `day21-readme.md · Индексация и поиск · 0.1443 · vector=0.5516 · lexical=0.034`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** В контексте указано, что CHARS_PER_PAGE равен 1800 символам.
- **Поисковый запрос rewrite:** CHARS_PER_PAGE document_loader.py day21/backend/services/document_loader.py
- **Метрики rewrite:** 1504 мс, 2550 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2527 токенов
- **Отобранные фрагменты rewrite:**
  - `day21-scripts-prepare_documents.py · module · 1.0928 · vector=0.4642 · lexical=1.0`
  - `day21-backend-services-document_loader.py · module · 0.6514 · vector=0.0 · lexical=0.6514`
  - `day21-backend-services-document_loader.py · DocumentLoader · 0.6514 · vector=0.0 · lexical=0.6514`
  - `day21-tests-fixtures_indexing.py · module · 0.3844 · vector=0.5159 · lexical=0.2812`
  - `day21-scripts-indexing_scenarios.py · module · 0.3486 · vector=0.0 · lexical=0.3486`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** В контексте нет данных для ответа.
- **Метрики rerank:** 4971 мс, 2485 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2619 токенов, кэш 93.1 %
- **Отобранные фрагменты rerank:**
  - `day21-readme.md · Индексация и поиск · 0.8936 · rerank=0.8936 · vector=0.5516 · lexical=0.034`
  - `day21-backend-domain-index_metrics.py · coverage_ratio · 0.5983 · rerank=0.5983 · vector=0.4687 · lexical=0.0266`
  - `day21-backend-domain-document_sources.py · _code · 0.568 · rerank=0.568 · vector=0.4992 · lexical=0.034`
  - `day21-docs-architecture.md · Документы и их источники · 0.4719 · rerank=0.4719 · vector=0.6205 · lexical=0.034`
  - `day21-scripts-prepare_documents.py · module · 0.4607 · rerank=0.4607 · vector=0.0 · lexical=0.4823`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте нет данных для ответа: значение `CHARS_PER_PAGE` из `day21/backend/services/document_loader.py` не приведено. Из фрагмента [5] видно лишь, что «страница» — это 1800 символов (`PAGE = CHARS_PER_PAGE`), но самого равенства в контексте нет.
- **Метрики rerank_filter:** 927 мс, 2553 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 2619 токенов, кэш 93.1 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-readme.md · Индексация и поиск · 0.8936 · rerank=0.8936 · vector=0.5516 · lexical=0.034`
  - `day21-backend-domain-index_metrics.py · coverage_ratio · 0.5983 · rerank=0.5983 · vector=0.4687 · lexical=0.0266`
  - `day21-backend-domain-document_sources.py · _code · 0.568 · rerank=0.568 · vector=0.4992 · lexical=0.034`
  - `day21-docs-architecture.md · Документы и их источники · 0.4719 · rerank=0.4719 · vector=0.6205 · lexical=0.034`
  - `day21-scripts-prepare_documents.py · module · 0.4607 · rerank=0.4607 · vector=0.0 · lexical=0.4823`

### 3. Чему равен PREVIEW_CHARS в day21/backend/services/index_service.py и какое сообщение бросается, если индекс стратегии пуст?

- **Ожидание:** PREVIEW_CHARS = 300; IndexNotBuiltError(f«Индекс стратегии {strategy!r} пуст: сначала выполните индексацию»)
- **Ключевые факты:** PREVIEW_CHARS, 300, Индекс стратегии, пуст
- **Ожидаемые источники:** day21/backend/services/index_service.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** В контексте нет данных для ответа.
- **Метрики baseline:** 1000 мс, 2099 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2204 токенов, кэш 91.9 %
- **Отобранные фрагменты baseline:**
  - `day21-backend-services-index_service.py · module · 0.5003 · vector=0.0 · lexical=0.5003`
  - `day21-backend-services-index_service.py · _preview · 0.5003 · vector=0.0 · lexical=0.5003`
  - `day21-structure.md · Почему сделано так (решения дня 21) · 0.2161 · vector=0.0 · lexical=0.2161`
  - `day21-backend-core-prompt_builder.py · module · 0.2001 · vector=0.0 · lexical=0.2001`
  - `day21-backend-core-prompt_builder.py · PromptBuilder · 0.2001 · vector=0.0 · lexical=0.2001`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** PREVIEW_CHARS равен 300. В предоставленном контексте нет данных о сообщении, которое бросается при пустом индексе стратегии.
- **Поисковый запрос rewrite:** PREVIEW_CHARS day21/backend/services/index_service.py сообщение индекс стратегии пуст
- **Метрики rewrite:** 2280 мс, 1824 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1860 токенов, кэш 85.9 %
- **Отобранные фрагменты rewrite:**
  - `day21-backend-services-index_service.py · module · 0.5838 · vector=0.0 · lexical=0.5838`
  - `day21-backend-services-index_service.py · _preview · 0.5838 · vector=0.0 · lexical=0.5838`
  - `day21-tests-fixtures_indexing.py · isolated_indexing · 0.2715 · vector=0.5705 · lexical=0.1574`
  - `day21-tests-fixtures_indexing.py · module · 0.234 · vector=0.5847 · lexical=0.1171`
  - `day21-backend-core-prompt_builder.py · module · 0.2335 · vector=0.0 · lexical=0.2335`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** В контексте нет данных для ответа.
- **Метрики rerank:** 6282 мс, 2556 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2906 токенов, кэш 90.5 %
- **Отобранные фрагменты rerank:**
  - `day21-backend-api-indexing.py · module · 0.9676 · rerank=0.9676 · vector=0.6626 · lexical=0.0145`
  - `day21-structure.md · Почему сделано так (решения дня 21) · 0.9503 · rerank=0.9503 · vector=0.0 · lexical=0.2161`
  - `day21-backend-models-indexing.py · module · 0.9021 · rerank=0.9021 · vector=0.0 · lexical=0.1575`
  - `day21-scripts-indexing_scenarios.py · module · 0.8919 · rerank=0.8919 · vector=0.5835 · lexical=0.049`
  - `day21-tests-fixtures_indexing.py · isolated_indexing · 0.722 · rerank=0.722 · vector=0.0 · lexical=0.1349`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте нет данных для ответа.
- **Метрики rerank_filter:** 879 мс, 2556 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 2906 токенов, кэш 90.5 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-api-indexing.py · module · 0.9676 · rerank=0.9676 · vector=0.6626 · lexical=0.0145`
  - `day21-structure.md · Почему сделано так (решения дня 21) · 0.9503 · rerank=0.9503 · vector=0.0 · lexical=0.2161`
  - `day21-backend-models-indexing.py · module · 0.9021 · rerank=0.9021 · vector=0.0 · lexical=0.1575`
  - `day21-scripts-indexing_scenarios.py · module · 0.8919 · rerank=0.8919 · vector=0.5835 · lexical=0.049`
  - `day21-tests-fixtures_indexing.py · isolated_indexing · 0.722 · rerank=0.722 · vector=0.0 · lexical=0.1349`

### 4. С какой долей кириллицы текст считается русским (CYRILLIC_RATIO) и сколько записей в таблице DOCUMENT_SOURCES (day21/backend/domain/document_sources.py)?

- **Ожидание:** CYRILLIC_RATIO = 0.15; в таблице DOCUMENT_SOURCES 25 записей
- **Ключевые факты:** CYRILLIC_RATIO, 0.15, DOCUMENT_SOURCES, 25
- **Ожидаемые источники:** day21/backend/domain/document_sources.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** CYRILLIC_RATIO = 0.15. В таблице DOCUMENT_SOURCES 25 записей (шестнадцать README, три docs, четыре кода, два guide).
- **Метрики baseline:** 824 мс, 1787 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1787 токенов, кэш 88.1 %
- **Отобранные фрагменты baseline:**
  - `day21-backend-domain-document_sources.py · detect_language · 0.605 · vector=0.4963 · lexical=0.5057`
  - `day21-backend-domain-document_sources.py · module · 0.4029 · vector=0.4974 · lexical=0.3034`
  - `day21-backend-domain-document_sources.py · module · 0.3686 · vector=0.3877 · lexical=0.2911`
  - `day21-readme.md · Индексация и поиск · 0.3196 · vector=0.4821 · lexical=0.2232`
  - `day21-backend-domain-document_sources.py · _code · 0.2907 · vector=0.3805 · lexical=0.2146`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** В контексте нет данных для ответа.
- **Поисковый запрос rewrite:** CYRILLIC_RATIO доля кириллицы русский текст day21/backend/domain/document_sources.py DOCUMENT_SOURCES количество записей
- **Метрики rewrite:** 1828 мс, 1669 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1725 токенов, кэш 38.6 %
- **Отобранные фрагменты rewrite:**
  - `day21-backend-api-indexing.py · run_demo · 0.3898 · vector=0.0 · lexical=0.3898`
  - `day21-backend-domain-document_sources.py · detect_language · 0.3248 · vector=0.0 · lexical=0.3248`
  - `day21-backend-domain-document_sources.py · module · 0.3246 · vector=0.6483 · lexical=0.1949`
  - `day21-readme.md · Индексация и поиск · 0.252 · vector=0.5429 · lexical=0.1434`
  - `day21-backend-domain-document_sources.py · module · 0.2412 · vector=0.4209 · lexical=0.157`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** CYRILLIC_RATIO = 0.15, а таблица DOCUMENT_SOURCES содержит 25 записей.
- **Метрики rerank:** 5082 мс, 1785 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1794 токенов, кэш 87.4 %
- **Отобранные фрагменты rerank:**
  - `day21-backend-domain-document_sources.py · detect_language · 0.6876 · rerank=0.6876 · vector=0.4963 · lexical=0.5057`
  - `day21-backend-domain-document_sources.py · module · 0.0467 · rerank=0.0467 · vector=0.4974 · lexical=0.3034`
  - `day21-readme.md · Индексация и поиск · 0.0331 · rerank=0.0331 · vector=0.4821 · lexical=0.2232`
  - `day21-docs-architecture.md · Метрики сравнения · 0.0064 · rerank=0.0064 · vector=0.3627 · lexical=0.0738`
  - `day21-backend-domain-document_sources.py · _code · 0.0061 · rerank=0.0061 · vector=0.3805 · lexical=0.2146`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте нет данных для ответа.
- **Метрики rerank_filter:** 651 мс, 364 токенов, чанков 1, до отсечения 30, после 1, порог 0.05, контекст 205 токенов, кэш 36.2 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-domain-document_sources.py · detect_language · 0.6876 · rerank=0.6876 · vector=0.4963 · lexical=0.5057`

### 5. Какой поток прогрева моделей создаёт при старте day21/backend/api/lifespan.py (threading.Thread, daemon=True, name=) и что запускается до этого потока?

- **Ожидание:** database.init_db() → get_manager().restore_from_db() → get_scheduler().start() → get_mcp_registry().connect_all() → get_index_service().load_all(); поток name=«model-warmup» прогревает эмбеддер и реранкер (день 23)
- **Ключевые факты:** init_db, restore_from_db, model-warmup
- **Ожидаемые источники:** day21/backend/api/lifespan.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** При старте создаётся `threading.Thread(target=dependencies.get_embedding_service().warmup, daemon=True, name="embedding-warmup")`. До этого потока выполняются: `database.init_db()`, `dependencies.get_manager().restore_from_db()`, `dependencies.get_scheduler().start()`, `dependencies.get_mcp_registry().connect_all()` и `dependencies.get_index_service().load_all()`.
- **Метрики baseline:** 1507 мс, 2310 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2322 токенов
- **Отобранные фрагменты baseline:**
  - `day21-backend-services-embedding_service.py · module · 0.3352 · vector=0.4826 · lexical=0.2387`
  - `day21-backend-api-lifespan.py · lifespan · 0.3028 · vector=0.0 · lexical=0.3028`
  - `day21-backend-services-indexing_service.py · IndexingService · 0.2668 · vector=0.0 · lexical=0.2668`
  - `day21-backend-api-lifespan.py · module · 0.2574 · vector=0.4033 · lexical=0.1767`
  - `day21-backend-core-dependencies.py · get_embedding_service · 0.2497 · vector=0.4923 · lexical=0.1512`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** В контексте нет данных для ответа. В приведённом фрагменте [1] видно, что поток прогрева создаётся как `threading.Thread(target=dependencies.get_embedding_service().warmup, daemon=True, name="embedding-warmup")`, но конкретное значение параметра `name=` в этом блоке отсутствует — там указано `name="embedding-warmup"`? Нет, в тексте блока [1] параметр `name` не показан полностью. До этого потока запускаются: `database.init_db()`, `dependencies.get_manager().restore_from_db()`, `dependencies.get_scheduler().start()`, `dependencies.get_mcp_registry().connect_all()`, `dependencies.get_index_service().load_all()`.
- **Поисковый запрос rewrite:** day21/backend/api/lifespan.py поток прогрева моделей threading.Thread daemon=True name что запускается до потока
- **Метрики rewrite:** 2217 мс, 2359 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2294 токенов
- **Отобранные фрагменты rewrite:**
  - `day21-backend-api-lifespan.py · lifespan · 0.4696 · vector=0.492 · lexical=0.3712`
  - `day21-backend-services-indexing_service.py · IndexingService · 0.3271 · vector=0.0 · lexical=0.3271`
  - `day21-backend-api-lifespan.py · module · 0.306 · vector=0.447 · lexical=0.2166`
  - `day21-docs-usage.md · состояние рычагов: пик/непик, скидка, кэш префиксов, сжатие, таблица моделей · 0.2735 · vector=0.4852 · lexical=0.1765`
  - `day21-structure.md · Почему сделано так (решения дня 21) · 0.2575 · vector=0.0 · lexical=0.2575`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** В контексте нет данных для ответа.
- **Метрики rerank:** 5193 мс, 2246 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2492 токенов
- **Отобранные фрагменты rerank:**
  - `day21-backend-core-dependencies.py · get_embedding_service · 0.9992 · rerank=0.9992 · vector=0.4923 · lexical=0.1512`
  - `day21-backend-api-main.py · module · 0.998 · rerank=0.998 · vector=0.4071 · lexical=0.0942`
  - `day21-backend-services-embedding_service.py · module · 0.9943 · rerank=0.9943 · vector=0.4826 · lexical=0.2387`
  - `day21-docs-architecture.md · Эмбеддинги · 0.8398 · rerank=0.8398 · vector=0.3971 · lexical=0.0433`
  - `day21-structure.md · Почему сделано так (решения дня 21) · 0.8139 · rerank=0.8139 · vector=0.0 · lexical=0.21`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте нет данных для ответа.
- **Метрики rerank_filter:** 959 мс, 2246 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 2492 токенов, кэш 91.6 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-core-dependencies.py · get_embedding_service · 0.9992 · rerank=0.9992 · vector=0.4923 · lexical=0.1512`
  - `day21-backend-api-main.py · module · 0.998 · rerank=0.998 · vector=0.4071 · lexical=0.0942`
  - `day21-backend-services-embedding_service.py · module · 0.9943 · rerank=0.9943 · vector=0.4826 · lexical=0.2387`
  - `day21-docs-architecture.md · Эмбеддинги · 0.8398 · rerank=0.8398 · vector=0.3971 · lexical=0.0433`
  - `day21-structure.md · Почему сделано так (решения дня 21) · 0.8139 · rerank=0.8139 · vector=0.0 · lexical=0.21`

### 6. Как ChunkStore.add_chunks проставляет embedding_id и какие id пропускает rows_by_ids (day21/backend/storage/chunk_store.py)?

- **Ожидание:** вставка идёт пачкой с flush(), затем строкам проставляется orm.embedding_id = orm.id; rows_by_ids пропускает id, которых нет в БД (например, -1 — «пустая ячейка» FAISS), порядок результата = порядок ids
- **Ключевые факты:** embedding_id, flush, -1, пропускаются
- **Ожидаемые источники:** day21/backend/storage/chunk_store.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** В контексте нет данных для ответа.
- **Метрики baseline:** 983 мс, 1797 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1859 токенов, кэш 86.0 %
- **Отобранные фрагменты baseline:**
  - `day21-backend-storage-chunk_store.py · module · 0.6236 · vector=0.4479 · lexical=0.534`
  - `day21-tests-fixtures_indexing.py · module · 0.2082 · vector=0.4673 · lexical=0.1147`
  - `day21-tests-fixtures_indexing.py · chunk_store · 0.1989 · vector=0.6034 · lexical=0.0782`
  - `day21-backend-services-index_service.py · module · 0.1839 · vector=0.4853 · lexical=0.0868`
  - `day21-backend-services-index_comparison.py · module · 0.1824 · vector=0.0 · lexical=0.1824`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** В контексте нет данных для ответа.
- **Поисковый запрос rewrite:** ChunkStore.add_chunks embedding_id rows_by_ids day21/backend/storage/chunk_store.py
- **Метрики rewrite:** 1935 мс, 2000 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1955 токенов, кэш 90.1 %
- **Отобранные фрагменты rewrite:**
  - `day21-backend-storage-chunk_store.py · module · 0.511 · vector=0.0 · lexical=0.511`
  - `day21-backend-storage-chunk_store.py · ChunkStore · 0.511 · vector=0.0 · lexical=0.511`
  - `day21-tests-fixtures_indexing.py · module · 0.4476 · vector=0.507 · lexical=0.3462`
  - `day21-scripts-indexing_scenarios.py · module · 0.3842 · vector=0.0 · lexical=0.3842`
  - `day21-tests-fixtures_indexing.py · chunk_store · 0.3608 · vector=0.625 · lexical=0.2358`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** `add_chunks` после `flush()` проставляет `embedding_id = orm.id` каждому чанку. `rows_by_ids` отбрасывает id меньше нуля (например, `-1` — «пустая ячейка» FAISS) и пропускает отсутствующие в БД id.
- **Метрики rerank:** 5293 мс, 2834 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2770 токенов, кэш 92.6 %
- **Отобранные фрагменты rerank:**
  - `day21-backend-storage-chunk_store.py · module · 0.9999 · rerank=0.9999 · vector=0.4479 · lexical=0.534`
  - `day21-backend-storage-chunk_store.py · ChunkStore · 0.9993 · rerank=0.9993 · vector=0.0 · lexical=0.1129`
  - `day21-backend-services-index_service.py · IndexService · 0.9983 · rerank=0.9983 · vector=0.0 · lexical=0.0912`
  - `day21-backend-storage-chunk_store.py · ChunkStore · 0.9965 · rerank=0.9965 · vector=0.0 · lexical=0.1693`
  - `day21-docs-architecture.md · Векторный индекс и метаданные · 0.996 · rerank=0.996 · vector=0.0 · lexical=0.093`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** Add_chunks заводит строки, делает flush(), затем проставляет `embedding_id = id` для каждой строки, после чего commit() и возвращает id. Rows_by_ids отбрасывает id меньше нуля (например, -1 — «пустая ячейка» FAISS), а отсутствующие в БД id пропускает.
- **Метрики rerank_filter:** 1121 мс, 2841 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 2770 токенов, кэш 92.6 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-storage-chunk_store.py · module · 0.9999 · rerank=0.9999 · vector=0.4479 · lexical=0.534`
  - `day21-backend-storage-chunk_store.py · ChunkStore · 0.9993 · rerank=0.9993 · vector=0.0 · lexical=0.1129`
  - `day21-backend-services-index_service.py · IndexService · 0.9983 · rerank=0.9983 · vector=0.0 · lexical=0.0912`
  - `day21-backend-storage-chunk_store.py · ChunkStore · 0.9965 · rerank=0.9965 · vector=0.0 · lexical=0.1693`
  - `day21-docs-architecture.md · Векторный индекс и метаданные · 0.996 · rerank=0.996 · vector=0.0 · lexical=0.093`

### 7. Какие значения у INDEX_AGENT_TOP_K и INDEX_AGENT_STRATEGY и чему равен INDEX_MAX_TOP_K (day21/backend/core/config.py)?

- **Ожидание:** INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = «structural», INDEX_MAX_TOP_K = 20
- **Ключевые факты:** INDEX_AGENT_TOP_K, INDEX_AGENT_STRATEGY, structural, INDEX_MAX_TOP_K, 20
- **Ожидаемые источники:** day21/backend/core/config.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** В контексте указано: `INDEX_MAX_TOP_K = 20`, `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`.
- **Метрики baseline:** 721 мс, 2411 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2328 токенов, кэш 91.9 %
- **Отобранные фрагменты baseline:**
  - `day21-backend-core-config.py · module · 0.6579 · vector=0.0 · lexical=0.6579`
  - `day21-backend-api-indexing.py · indexing_search · 0.346 · vector=0.5433 · lexical=0.2373`
  - `day21-backend-services-indexing_service.py · IndexingService · 0.2373 · vector=0.0 · lexical=0.2373`
  - `day21-backend-services-index_comparison.py · module · 0.223 · vector=0.0 · lexical=0.223`
  - `day21-scripts-indexing_scenarios.py · print_summary · 0.2145 · vector=0.0 · lexical=0.2145`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** В контексте указано: `INDEX_MAX_TOP_K = 20`, `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`.
- **Поисковый запрос rewrite:** INDEX_AGENT_TOP_K INDEX_AGENT_STRATEGY INDEX_MAX_TOP_K day21/backend/core/config.py
- **Метрики rewrite:** 2192 мс, 2834 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2848 токенов, кэш 91.7 %
- **Отобранные фрагменты rewrite:**
  - `day21-backend-core-config.py · module · 0.9557 · vector=0.0 · lexical=0.9557`
  - `day21-backend-api-indexing.py · indexing_search · 0.4631 · vector=0.5926 · lexical=0.3446`
  - `day21-backend-services-indexing_service.py · IndexingService · 0.3446 · vector=0.0 · lexical=0.3446`
  - `day21-backend-core-config.py · module · 0.1536 · vector=0.5467 · lexical=0.0443`
  - `day21-backend-api-main.py · module · 0.1502 · vector=0.5903 · lexical=0.0321`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** INDEX_AGENT_TOP_K = 3, INDEX_AGENT_STRATEGY = "structural", INDEX_MAX_TOP_K = 20.
- **Метрики rerank:** 5514 мс, 2865 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2851 токенов, кэш 94.9 %
- **Отобранные фрагменты rerank:**
  - `day21-backend-core-config.py · module · 0.9867 · rerank=0.9867 · vector=0.0 · lexical=0.6579`
  - `day21-backend-api-indexing.py · indexing_search · 0.9521 · rerank=0.9521 · vector=0.5433 · lexical=0.2373`
  - `day21-docs-reports-indexing_demo.md · Сравнение стратегий · 0.5358 · rerank=0.5358 · vector=0.5538 · lexical=0.0`
  - `day21-backend-core-config.py · module · 0.4608 · rerank=0.4608 · vector=0.5552 · lexical=0.0221`
  - `day21-backend-services-indexing_service.py · IndexingService · 0.43 · rerank=0.43 · vector=0.0 · lexical=0.2373`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте указаны: `INDEX_AGENT_TOP_K = 3`, `INDEX_AGENT_STRATEGY = "structural"`, `INDEX_MAX_TOP_K = 20` (day21/backend/core/config.py).
- **Метрики rerank_filter:** 1278 мс, 2885 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 2851 токенов, кэш 94.9 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-core-config.py · module · 0.9867 · rerank=0.9867 · vector=0.0 · lexical=0.6579`
  - `day21-backend-api-indexing.py · indexing_search · 0.9521 · rerank=0.9521 · vector=0.5433 · lexical=0.2373`
  - `day21-docs-reports-indexing_demo.md · Сравнение стратегий · 0.5358 · rerank=0.5358 · vector=0.5538 · lexical=0.0`
  - `day21-backend-core-config.py · module · 0.4608 · rerank=0.4608 · vector=0.5552 · lexical=0.0221`
  - `day21-backend-services-indexing_service.py · IndexingService · 0.43 · rerank=0.43 · vector=0.0 · lexical=0.2373`

### 8. Какое исключение и с каким текстом бросает LLMClient, если не передан client_factory (day21/backend/services/llm_client.py)?

- **Ожидание:** RuntimeError(«LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)»)
- **Ключевые факты:** RuntimeError, client_factory, Agent._make_client
- **Ожидаемые источники:** day21/backend/services/llm_client.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** `LLMClient` бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)».
- **Метрики baseline:** 818 мс, 2495 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2585 токенов, кэш 94.0 %
- **Отобранные фрагменты baseline:**
  - `day21-readme.md · Таблицы `document_chunks` и `index_runs` · 0.3838 · vector=0.0 · lexical=0.3838`
  - `day21-backend-services-llm_client.py · LLMClient · 0.2642 · vector=0.0 · lexical=0.2642`
  - `day21-backend-core-dependencies.py · get_llm_client · 0.2574 · vector=0.6398 · lexical=0.1294`
  - `day21-backend-services-llm_client.py · module · 0.1887 · vector=0.0 · lexical=0.1887`
  - `day21-backend-core-dependencies.py · module · 0.1547 · vector=0.0 · lexical=0.1547`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** Если `client_factory` не передан, `LLMClient` бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)».
- **Поисковый запрос rewrite:** LLMClient client_factory исключение текст day21/backend/services/llm_client.py
- **Метрики rewrite:** 1718 мс, 2490 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2577 токенов, кэш 94.5 %
- **Отобранные фрагменты rewrite:**
  - `day21-backend-services-llm_client.py · LLMClient · 0.6061 · vector=0.0 · lexical=0.6061`
  - `day21-backend-services-llm_client.py · module · 0.4329 · vector=0.0 · lexical=0.4329`
  - `day21-backend-core-dependencies.py · get_llm_client · 0.429 · vector=0.6603 · lexical=0.2969`
  - `day21-backend-core-dependencies.py · module · 0.3548 · vector=0.0 · lexical=0.3548`
  - `day21-tests-fixtures_indexing.py · isolated_indexing · 0.3537 · vector=0.4633 · lexical=0.261`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** LLMClient бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)».
- **Метрики rerank:** 4806 мс, 2421 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2550 токенов, кэш 91.5 %
- **Отобранные фрагменты rerank:**
  - `day21-backend-core-dependencies.py · get_llm_client · 0.8883 · rerank=0.8883 · vector=0.6398 · lexical=0.1294`
  - `day21-backend-services-llm_client.py · LLMClient · 0.8361 · rerank=0.8361 · vector=0.0 · lexical=0.2642`
  - `day21-docs-architecture.md · Эмбеддинги · 0.6836 · rerank=0.6836 · vector=0.0 · lexical=0.1217`
  - `day21-tests-fixtures_indexing.py · isolated_indexing · 0.4178 · rerank=0.4178 · vector=0.0 · lexical=0.1138`
  - `day21-backend-services-llm_client.py · module · 0.2504 · rerank=0.2504 · vector=0.0 · lexical=0.1887`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** LLMClient бросает `RuntimeError` с текстом: «LLMClient без client_factory: передайте фабрику клиента (в приложении это Agent._make_client)».
- **Метрики rerank_filter:** 968 мс, 2421 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 2550 токенов, кэш 91.5 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-backend-core-dependencies.py · get_llm_client · 0.8883 · rerank=0.8883 · vector=0.6398 · lexical=0.1294`
  - `day21-backend-services-llm_client.py · LLMClient · 0.8361 · rerank=0.8361 · vector=0.0 · lexical=0.2642`
  - `day21-docs-architecture.md · Эмбеддинги · 0.6836 · rerank=0.6836 · vector=0.0 · lexical=0.1217`
  - `day21-tests-fixtures_indexing.py · isolated_indexing · 0.4178 · rerank=0.4178 · vector=0.0 · lexical=0.1138`
  - `day21-backend-services-llm_client.py · module · 0.2504 · rerank=0.2504 · vector=0.0 · lexical=0.1887`

### 9. Какие хосты пропускает тестовый гвард no_real_network и как строится временная SQLite-база в тестах (day21/tests/conftest.py)?

- **Ожидание:** разрешены префиксы («127.», «localhost», «::1», «0.0.0.0»), иначе AssertionError; фикстура schema_template (session) создаёт файл схемы, а session_factory копирует его в tmp_path/«test.db»
- **Ключевые факты:** no_real_network, 127., localhost, schema_template
- **Ожидаемые источники:** day21/tests/conftest.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** Гвард `no_real_network` пропускает только локальные адреса: пустой хост, а также хосты, начинающиеся с `127.`, `localhost`, `::1`, `0.0.0.0` — остальные вызовы падают с `AssertionError`. База строится через session-scoped фикстуру `schema_template`: `init_db` (create_all по ~25 таблицам) выполняется один раз за прогон, а тесты получают копию файла схемы.
- **Метрики baseline:** 1036 мс, 2229 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2147 токенов, кэш 91.0 %
- **Отобранные фрагменты baseline:**
  - `day21-tests-conftest.py · no_real_network · 0.3524 · vector=0.5023 · lexical=0.2519`
  - `day21-tests-conftest.py · schema_template · 0.3387 · vector=0.533 · lexical=0.2321`
  - `day21-backend-domain-index_scenarios.py · TestQuery · 0.2667 · vector=0.0 · lexical=0.2667`
  - `day21-tests-conftest.py · stub_api_base · 0.2181 · vector=0.498 · lexical=0.1185`
  - `day21-structure.md · Раскладка · 0.2163 · vector=0.0 · lexical=0.2163`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** Гвард `no_real_network` пропускает только локальные адреса: пустой host, а также хосты, начинающиеся с `127.`, `localhost`, `::1`, `0.0.0.0`; остальные вызывают `AssertionError` с текстом «тест попытался выйти в сеть». Про построение временной SQLite-базы в предоставленном контексте данных нет — упоминается лишь session-scoped фикстура `schema_template` для схемы БД.
- **Поисковый запрос rewrite:** no_real_network тестовый гвард пропускаемые хосты day21/tests/conftest.py временная SQLite-база построение
- **Метрики rewrite:** 2488 мс, 2522 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2451 токенов
- **Отобранные фрагменты rewrite:**
  - `day21-tests-conftest.py · no_real_network · 0.3974 · vector=0.5185 · lexical=0.2937`
  - `day21-backend-services-index_service.py · IndexService · 0.3225 · vector=0.0 · lexical=0.3225`
  - `day21-backend-domain-index_scenarios.py · TestQuery · 0.3109 · vector=0.0 · lexical=0.3109`
  - `day21-structure.md · Раскладка · 0.2522 · vector=0.0 · lexical=0.2522`
  - `day21-tests-conftest.py · stub_api_base · 0.2344 · vector=0.4811 · lexical=0.1382`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** Гвард `no_real_network` пропускает только локальные адреса: пустой хост, а также те, что начинаются на `127.`, `localhost`, `::1`, `0.0.0.0`. Остальные хосты вызывают `AssertionError` с текстом про попытку выхода в сеть.

Про построение временной SQLite-базы: в предоставленном контексте есть только упоминание в заголовке чанка («временная БД (копия общей схемы)») и импорты `init_db`, `make_engine`, `make_session_factory` из `backend.storage.database`. Деталей самой фикстуры в контексте нет.
- **Метрики rerank:** 5469 мс, 2710 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2651 токенов, кэш 90.5 %
- **Отобранные фрагменты rerank:**
  - `day21-tests-conftest.py · no_real_network · 0.3265 · rerank=0.3265 · vector=0.5023 · lexical=0.2519`
  - `day21-tests-conftest.py · module · 0.1302 · rerank=0.1302 · vector=0.0 · lexical=0.1719`
  - `day21-docs-usage.md · 3. Тесты · 0.0691 · rerank=0.0691 · vector=0.0 · lexical=0.1426`
  - `day21-backend-core-config.py · module · 0.0085 · rerank=0.0085 · vector=0.5123 · lexical=0.0191`
  - `day21-backend-api-main.py · module · 0.0066 · rerank=0.0066 · vector=0.4374 · lexical=0.0191`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте нет данных для ответа.
- **Метрики rerank_filter:** 883 мс, 1658 токенов, чанков 3, до отсечения 30, после 3, порог 0.05, контекст 1640 токенов, кэш 85.4 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-tests-conftest.py · no_real_network · 0.3265 · rerank=0.3265 · vector=0.5023 · lexical=0.2519`
  - `day21-tests-conftest.py · module · 0.1302 · rerank=0.1302 · vector=0.0 · lexical=0.1719`
  - `day21-docs-usage.md · 3. Тесты · 0.0691 · rerank=0.0691 · vector=0.0 · lexical=0.1426`

### 10. Какие поля у TestQuery и что делает validate_queries (day21/backend/domain/index_scenarios.py)?

- **Ожидание:** @dataclass(frozen=True) TestQuery(query, expected_sources, note) и DEMO_QUERIES из пяти записей; validate_queries() возвращает список проблем (пустой список = всё валидно)
- **Ключевые факты:** TestQuery, query, expected_sources, validate_queries
- **Ожидаемые источники:** day21/backend/domain/index_scenarios.py
- **Ответ без RAG:** В контексте нет данных для ответа.
- **Режим baseline:** как в дне 22: гибридный поиск без отсечения
- **Ответ baseline:** У `TestQuery` три поля: `query`, `expected_sources` и `note` (dataclass frozen). `validate_queries` проверяет непустой текст и ожидаемые источники, которые есть среди `DOCUMENT_SOURCES`, до создания строки запуска.
- **Метрики baseline:** 824 мс, 1907 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1898 токенов, кэш 90.2 %
- **Отобранные фрагменты baseline:**
  - `day21-backend-domain-index_scenarios.py · module · 0.5571 · vector=0.5573 · lexical=0.4456`
  - `day21-backend-domain-index_scenarios.py · TestQuery · 0.4486 · vector=0.5089 · lexical=0.3468`
  - `day21-backend-services-index_comparison.py · module · 0.4421 · vector=0.0 · lexical=0.4421`
  - `day21-docs-architecture.md · Метрики сравнения · 0.3813 · vector=0.5968 · lexical=0.2619`
  - `day21-backend-domain-index_scenarios.py · TestQuery · 0.3468 · vector=0.0 · lexical=0.3468`
- **Режим rewrite:** переформулировка запроса моделью
- **Ответ rewrite:** TestQuery — это frozen dataclass с полями: query (текст), expected_sources (кортеж ожидаемых источников) и note (пояснение для отчёта). validate_queries проверяет тестовые запросы и возвращает список ошибок; пустой список означает, что всё в порядке. Ловятся пустой текст запроса, отсутствие ожидаемых источников и ожидаемый источник, которого нет среди DOCUMENT_SOURCES.
- **Поисковый запрос rewrite:** TestQuery поля validate_queries day21/backend/domain/index_scenarios.py
- **Метрики rewrite:** 1865 мс, 2231 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 2248 токенов, кэш 90.1 %
- **Отобранные фрагменты rewrite:**
  - `day21-backend-domain-index_scenarios.py · module · 0.8389 · vector=0.4938 · lexical=0.7401`
  - `day21-backend-domain-index_scenarios.py · TestQuery · 0.5759 · vector=0.0 · lexical=0.5759`
  - `day21-docs-architecture.md · Метрики сравнения · 0.5433 · vector=0.5421 · lexical=0.4349`
  - `day21-backend-services-indexing_service.py · module · 0.417 · vector=0.0 · lexical=0.417`
  - `day21-backend-domain-index_scenarios.py · validate_queries · 0.3052 · vector=0.4689 · lexical=0.2114`
- **Режим rerank:** кросс-энкодер пересортировывает кандидатов
- **Ответ rerank:** TestQuery — dataclass из `day21/backend/domain/index_scenarios.py`, содержит поля `query` и `expected_sources` (судя по коду `validate_queries`). `validate_queries` проверяет тестовые запросы и возвращает список ошибок (пустой — всё в порядке): пустой текст запроса, отсутствие ожидаемых источников и ожидаемый источник, которого нет среди `DOCUMENT_SOURCES`.
- **Метрики rerank:** 4746 мс, 1868 токенов, чанков 5, до отсечения 30, после 5, порог нет, контекст 1801 токенов, кэш 86.9 %
- **Отобранные фрагменты rerank:**
  - `day21-tests-fixtures_indexing.py · module · 0.9769 · rerank=0.9769 · vector=0.5234 · lexical=0.0108`
  - `day21-backend-domain-index_scenarios.py · module · 0.975 · rerank=0.975 · vector=0.5573 · lexical=0.4456`
  - `day21-docs-architecture.md · Метрики сравнения · 0.732 · rerank=0.732 · vector=0.5968 · lexical=0.2619`
  - `day21-backend-domain-index_scenarios.py · validate_queries · 0.7289 · rerank=0.7289 · vector=0.5014 · lexical=0.1273`
  - `day21-backend-services-index_comparison.py · module · 0.7137 · rerank=0.7137 · vector=0.0 · lexical=0.4421`
- **Режим rerank_filter:** кросс-энкодер и порог отсечения
- **Ответ rerank_filter:** В контексте нет данных для ответа.
- **Метрики rerank_filter:** 781 мс, 1777 токенов, чанков 5, до отсечения 30, после 5, порог 0.05, контекст 1801 токенов, кэш 86.9 %
- **Отобранные фрагменты rerank_filter:**
  - `day21-tests-fixtures_indexing.py · module · 0.9769 · rerank=0.9769 · vector=0.5234 · lexical=0.0108`
  - `day21-backend-domain-index_scenarios.py · module · 0.975 · rerank=0.975 · vector=0.5573 · lexical=0.4456`
  - `day21-docs-architecture.md · Метрики сравнения · 0.732 · rerank=0.732 · vector=0.5968 · lexical=0.2619`
  - `day21-backend-domain-index_scenarios.py · validate_queries · 0.7289 · rerank=0.7289 · vector=0.5014 · lexical=0.1273`
  - `day21-backend-services-index_comparison.py · module · 0.7137 · rerank=0.7137 · vector=0.0 · lexical=0.4421`

