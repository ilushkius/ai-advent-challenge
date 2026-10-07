# Локальный RAG: сравнение локальной и облачной модели (день 28)

* дата прогона: 2026-10-07 22:55
* локальная модель: qwen2.5-coder:14b (http://localhost:11434, предел ожидания 120.0 с)
* провайдер по умолчанию: deepseek
* стратегия поиска: rag_corpus_structural, top_k: 5 фрагментов в контексте каждой стороне
* корпус: документов 36, страниц 175, символов 316075
* чанки по стратегиям: rag_corpus_fixed: 295 · rag_corpus_structural: 387 (всего 682)
* порог релевантности: 0.6 — ниже него строки приходят в режиме «не знаю» без вызова модели
* вопросов: 10, время прогона: 45.8 с

Воспроизведение (нужны запущенный бэкенд, Ollama и `DEEPSEEK_API_KEY` в `day21/.env`):

```
uv run python scripts/run_local_rag_comparison.py
```

## Как считался вердикт

Строка считается так (`backend/domain/rag_compare.py`):

1. ответил ли провайдер по корпусу — режим `rag` и не `fallback` (режимы `dont_know` и `error` проигрывают любому ответу по корпусу);
2. среди ответивших — подтверждённые цитаты (`quotes_verified`), затем уверенность (`confidence`), затем число источников.

Источники в обеих колонках получены **одним и тем же локальным отбором** (FAISS-индекс дня 22 и sentence-transformers), поэтому колонка «Источники» сравнивает не retrieval, а то, воспользовалась ли модель контекстом: числа источников совпадают, различается ответ.

## Таблица сравнения

| № | Вопрос | Ответ local | Ответ cloud | Источники (local / cloud) | Время local, с | Время cloud, с | Режим (local / cloud) | Вердикт |
|---|---|---|---|---|---|---|---|---|
| 1 | Чему равен CHARS_PER_PAGE в document_loader? | CHARS_PER_PAGE равно 1800. | «Сколько символов в "странице" — для отчёта о размере набора документов. CHARS_PER_PAGE = 1800». | 5 / 5 | 3.31 | 1.20 | rag / rag | облако лучше |
| 2 | Чему равен PREVIEW_CHARS в выдаче поиска? | Согласно контексту, PREVIEW_CHARS равен 300. ``` #: Сколько символов попадания показываются в ``preview`` (полный текст — в ``content``). PREVIEW_CHARS = 300 ``` | «Сколько символов попадания показываются в ``preview`` (полный текст — в ``content``). PREVIEW_CHARS = 300». Также в `_preview` «compact[:PREVIEW_CHARS]» с добавлением «…», если текст длиннее. | 5 / 5 | 4.23 | 1.12 | rag / rag | облако лучше |
| 3 | Зачем нужен CYRILLIC_RATIO в document_sources? | CYRILLIC_RATIO используется для определения языка текста. Если доля кириллических символов в тексте больше 0.15, то текст считается русским ("ru"), иначе — английским ("en"). | Порог `CYRILLIC_RATIO = 0.15` используется функцией `detect_language`, которая определяет язык текста по доле кириллицы: `"ru"` или `"en"`. Если доля кириллических букв больше этого порога, возвращается `"ru"`, иначе `"en"`. | 5 / 5 | 4.12 | 1.17 | rag / rag | облако лучше |
| 4 | Как работает ChunkStore.add_chunks? | Чанки пишутся одной стратегии; возвращаются их id в порядке входа. Детали в коде: ```python def add_chunks(self, chunks: Iterable[Any], strategy: str) -> List[int]: rows = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in chunks] if not rows: return [] with self.session() as session: orm_r… | По контексту: «``add_chunks`` заводит строки и сразу проставляет ``embedding_id = id``», а вставка идёт пачкой с ``flush()``, потому что «id известны до ``commit()``». Метод принимает либо объекты чанкера, либо словари: «``chunks`` — либо объекты чанкера (``Chunk`` с ``to_dict()``), либо готовые сло… | 5 / 5 | 8.55 | 1.40 | rag / rag | локально лучше |
| 5 | Чему равен EXCERPT_CHARS в блоке индекса? | EXCERPT_CHARS равно 300. | В контексте указано: «Длина выдержки из чанка в блоке промпта (полный текст чанка в промпт не идёт). EXCERPT_CHARS = 300». То есть `EXCERPT_CHARS` равен 300. | 5 / 5 | 3.14 | 1.23 | rag / rag | равно |
| 6 | Что делает функция load_documents в document_loader? | Функция load_documents читает папку документов, метаданные берёт из манифеста. Если в манифесте нет файла, получает метаданные эвристиками и попадает в манифест: так ручная копия документа в папку не выпадает из статистики и из отчёта. | Функция `load_documents` «Читает папку документов, метаданные берёт из манифеста». Файл, «которого в манифесте нет, получает метаданные эвристиками и попадает в манифест: так ручная копия документа в папку не выпадает из статистики и из отчёта». | 5 / 5 | 4.76 | 1.12 | rag / rag | равно |
| 7 | Какая модель эмбеддингов по умолчанию в embedding_service? | Модель эмбеддингов по умолчанию в `embedding_service` — `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`. | По контексту: «модель по умолчанию `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (понимает русский; переопределяется `DAY21_EMBEDDING_MODEL`)». Это указано в разделе «Эмбеддинги» файла `backend/services/embedding_service.py`. | 5 / 5 | 3.60 | 0.82 | rag / rag | равно |
| 8 | Что проверяет TestQuery в indexing_scenarios? | TestQuery проверяет **данные**, а не код. Запросы — это данные, которые читаются прогоном (indexing_service), отчёт, интерфейс и тесты. Список запросов живёт в одном месте и проверяется validate_queries. | Согласно контексту, `TestQuery` — это «Тестовый запрос: текст, ожидаемые документы и пояснение для отчёта», с полями `query`, `expected_sources` и `note`. Контекст не описывает отдельной проверки, которую выполняет сам `TestQuery`, но указывает, что список запросов «проверяется `validate_queries`».… | 5 / 5 | 4.27 | 1.57 | rag / rag | облако лучше |
| 9 | Какая погода будет в Москве в выходные? | — | — | 0 / 0 | 0.05 | 0.05 | dont_know / dont_know | равно |
| 10 | Как приготовить борщ на ужин? | — | — | 0 / 0 | 0.06 | 0.03 | dont_know / dont_know | равно |

## Приложение: полные ответы

### 1. Чему равен CHARS_PER_PAGE в document_loader?

**Локальная модель (Ollama · local)** — режим `rag` · 3.31 с · провайдер `local`

> CHARS_PER_PAGE равно 1800.

источники: day21-scripts-prepare_documents.py · module · 0.7143; day21-backend-services-document_loader.py · module · 0.5714; day21-backend-services-document_loader.py · DocumentLoader · 0.5714; day21-backend-services-index_service.py · module · 0.3721; day21-backend-models-indexing.py · module · 0.2857

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.20 с · провайдер `deepseek`

> «Сколько символов в "странице" — для отчёта о размере набора документов. CHARS_PER_PAGE = 1800».

источники: day21-scripts-prepare_documents.py · module · 0.7143; day21-backend-services-document_loader.py · module · 0.5714; day21-backend-services-document_loader.py · DocumentLoader · 0.5714; day21-backend-services-index_service.py · module · 0.3721; day21-backend-models-indexing.py · module · 0.2857

### 2. Чему равен PREVIEW_CHARS в выдаче поиска?

**Локальная модель (Ollama · local)** — режим `rag` · 4.23 с · провайдер `local`

> Согласно контексту, PREVIEW_CHARS равен 300.
> 
> ```
> #: Сколько символов попадания показываются в ``preview`` (полный текст — в ``content``).
> PREVIEW_CHARS = 300
> ```

источники: day21-backend-services-index_service.py · _preview · 0.8152; day21-backend-services-index_service.py · module · 0.7105; day21-backend-models-indexing.py · module · 0.2368; day21-backend-models-indexing.py · DocumentChunk · 0.2368; day21-backend-schemas-indexing.py · IndexChunkOut · 0.2368

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.12 с · провайдер `deepseek`

> «Сколько символов попадания показываются в ``preview`` (полный текст — в ``content``). PREVIEW_CHARS = 300». Также в `_preview` «compact[:PREVIEW_CHARS]» с добавлением «…», если текст длиннее.

источники: day21-backend-services-index_service.py · _preview · 0.8152; day21-backend-services-index_service.py · module · 0.7105; day21-backend-models-indexing.py · module · 0.2368; day21-backend-models-indexing.py · DocumentChunk · 0.2368; day21-backend-schemas-indexing.py · IndexChunkOut · 0.2368

### 3. Зачем нужен CYRILLIC_RATIO в document_sources?

**Локальная модель (Ollama · local)** — режим `rag` · 4.12 с · провайдер `local`

> CYRILLIC_RATIO используется для определения языка текста. Если доля кириллических символов в тексте больше 0.15, то текст считается русским ("ru"), иначе — английским ("en").

источники: day21-backend-domain-document_sources.py · module · 0.8256; day21-backend-domain-document_sources.py · detect_language · 0.6788; day21-docs-architecture.md · Документы и их источники · 0.2718; day21-readme.md · Индексация и поиск · 0.2546; day21-backend-domain-index_scenarios.py · module · 0.2541

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.17 с · провайдер `deepseek`

> Порог `CYRILLIC_RATIO = 0.15` используется функцией `detect_language`, которая определяет язык текста по доле кириллицы: `"ru"` или `"en"`. Если доля кириллических букв больше этого порога, возвращается `"ru"`, иначе `"en"`.

источники: day21-backend-domain-document_sources.py · module · 0.8256; day21-backend-domain-document_sources.py · detect_language · 0.6788; day21-docs-architecture.md · Документы и их источники · 0.2718; day21-readme.md · Индексация и поиск · 0.2546; day21-backend-domain-index_scenarios.py · module · 0.2541

### 4. Как работает ChunkStore.add_chunks?

**Локальная модель (Ollama · local)** — режим `rag` · 8.55 с · провайдер `local`

> Чанки пишутся одной стратегии; возвращаются их id в порядке входа. Детали в коде:
> 
> ```python
> def add_chunks(self, chunks: Iterable[Any], strategy: str) -> List[int]:
>     rows = [c.to_dict() if hasattr(c, "to_dict") else dict(c) for c in chunks]
>     if not rows:
>         return []
>     with self.session() as session:
>         orm_rows = []
>         for row in rows:
>             orm = DocumentChunk(
>                 source=row["source"],
>                 title=row["title"],
>                 section=row.get("section") or "",
>                 chunk_id=row["chunk_id"],
>                 strategy=strategy,
>                 content=row["content"],
>                 token_count=int(row.get("token_count") or 0),
>                 embedding_id=0,
>                 start_char=int(row.get("start_char") or 0),
>                 end_char=int(row.get("end_char") or 0),
>                 section_level=int(row.get("section_level") or 0)
>             )
>             session.add(orm)
>             orm_rows.append(orm)
>         session.flush()
>         return [row.id for row in orm_rows]
> ```

источники: day21-backend-storage-chunk_store.py · module · 0.9354; day21-backend-services-chunker.py · Chunk · 0.9345; day21-backend-storage-chunk_store.py · ChunkStore · 0.8654; day21-backend-services-index_service.py · IndexService · 0.6731; day21-backend-services-index_service.py · module · 0.3269

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.40 с · провайдер `deepseek`

> По контексту: «``add_chunks`` заводит строки и сразу проставляет ``embedding_id = id``», а вставка идёт пачкой с ``flush()``, потому что «id известны до ``commit()``». Метод принимает либо объекты чанкера, либо словари: «``chunks`` — либо объекты чанкера (``Chunk`` с ``to_dict()``), либо готовые словари». Он «Пишет чанки одной стратегии; возвращает их id в порядке входа». id возвращаются, потому что «вектора FAISS кладутся под этими же id».

источники: day21-backend-storage-chunk_store.py · module · 0.9354; day21-backend-services-chunker.py · Chunk · 0.9345; day21-backend-storage-chunk_store.py · ChunkStore · 0.8654; day21-backend-services-index_service.py · IndexService · 0.6731; day21-backend-services-index_service.py · module · 0.3269

### 5. Чему равен EXCERPT_CHARS в блоке индекса?

**Локальная модель (Ollama · local)** — режим `rag` · 3.14 с · провайдер `local`

> EXCERPT_CHARS равно 300.

источники: day21-backend-domain-indexing_prompt.py · module · 0.9007; day21-backend-domain-indexing_prompt.py · _excerpt · 0.298; day21-backend-services-index_service.py · module · 0.2186; day21-docs-usage.md · 4.3 Как убедиться, что кэш работает · 0.2145; day21-backend-api-indexing.py · indexing_stats · 0.1312

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.23 с · провайдер `deepseek`

> В контексте указано: «Длина выдержки из чанка в блоке промпта (полный текст чанка в промпт не идёт). EXCERPT_CHARS = 300». То есть `EXCERPT_CHARS` равен 300.

источники: day21-backend-domain-indexing_prompt.py · module · 0.9007; day21-backend-domain-indexing_prompt.py · _excerpt · 0.298; day21-backend-services-index_service.py · module · 0.2186; day21-docs-usage.md · 4.3 Как убедиться, что кэш работает · 0.2145; day21-backend-api-indexing.py · indexing_stats · 0.1312

### 6. Что делает функция load_documents в document_loader?

**Локальная модель (Ollama · local)** — режим `rag` · 4.76 с · провайдер `local`

> Функция load_documents читает папку документов, метаданные берёт из манифеста. Если в манифесте нет файла, получает метаданные эвристиками и попадает в манифест: так ручная копия документа в папку не выпадает из статистики и из отчёта.

источники: day21-backend-services-document_loader.py · DocumentLoader · 0.6; day21-backend-services-document_loader.py · DocumentLoader · 0.48; day21-backend-api-lifespan.py · _warmup_models · 0.32; day21-backend-core-dependencies.py · get_embedding_service · 0.32; day21-tests-fixtures_indexing.py · @pytest.fixture · 0.1985

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.12 с · провайдер `deepseek`

> Функция `load_documents` «Читает папку документов, метаданные берёт из манифеста». Файл, «которого в манифесте нет, получает метаданные эвристиками и попадает в манифест: так ручная копия документа в папку не выпадает из статистики и из отчёта».

источники: day21-backend-services-document_loader.py · DocumentLoader · 0.6; day21-backend-services-document_loader.py · DocumentLoader · 0.48; day21-backend-api-lifespan.py · _warmup_models · 0.32; day21-backend-core-dependencies.py · get_embedding_service · 0.32; day21-tests-fixtures_indexing.py · @pytest.fixture · 0.1985

### 7. Какая модель эмбеддингов по умолчанию в embedding_service?

**Локальная модель (Ollama · local)** — режим `rag` · 3.60 с · провайдер `local`

> Модель эмбеддингов по умолчанию в `embedding_service` — `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`.

источники: day21-docs-usage.md · какая модель и какой предел ответа выбраны для какого типа задачи · 0.8491; day21-docs-architecture.md · Эмбеддинги · 0.2322; day21-tests-fixtures_indexing.py · @pytest.fixture · 0.22; day21-backend-services-embedding_service.py · get_embedding_service · 0.1804; day21-backend-core-dependencies.py · get_embedding_service · 0.1661

**Облако (DeepSeek · deepseek)** — режим `rag` · 0.82 с · провайдер `deepseek`

> По контексту: «модель по умолчанию `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` (понимает русский; переопределяется `DAY21_EMBEDDING_MODEL`)». Это указано в разделе «Эмбеддинги» файла `backend/services/embedding_service.py`.

источники: day21-docs-usage.md · какая модель и какой предел ответа выбраны для какого типа задачи · 0.8491; day21-docs-architecture.md · Эмбеддинги · 0.2322; day21-tests-fixtures_indexing.py · @pytest.fixture · 0.22; day21-backend-services-embedding_service.py · get_embedding_service · 0.1804; day21-backend-core-dependencies.py · get_embedding_service · 0.1661

### 8. Что проверяет TestQuery в indexing_scenarios?

**Локальная модель (Ollama · local)** — режим `rag` · 4.27 с · провайдер `local`

> TestQuery проверяет **данные**, а не код. Запросы — это данные, которые читаются прогоном (indexing_service), отчёт, интерфейс и тесты. Список запросов живёт в одном месте и проверяется validate_queries.

источники: day21-docs-architecture.md · Поток данных демо-сценария · 0.6; day21-backend-domain-index_scenarios.py · module · 0.3; day21-backend-domain-index_scenarios.py · TestQuery · 0.3; day21-scripts-indexing_scenarios.py · module · 0.2089; day21-backend-core-dependencies.py · get_indexing_service · 0.124

**Облако (DeepSeek · deepseek)** — режим `rag` · 1.57 с · провайдер `deepseek`

> Согласно контексту, `TestQuery` — это «Тестовый запрос: текст, ожидаемые документы и пояснение для отчёта», с полями `query`, `expected_sources` и `note`. Контекст не описывает отдельной проверки, которую выполняет сам `TestQuery`, но указывает, что список запросов «проверяется `validate_queries`». Для точного ответа уточните, что именно имеется в виду под «проверкой» — валидацию данных `TestQuery` или оценку поиска по ним.

источники: day21-docs-architecture.md · Поток данных демо-сценария · 0.6; day21-backend-domain-index_scenarios.py · module · 0.3; day21-backend-domain-index_scenarios.py · TestQuery · 0.3; day21-scripts-indexing_scenarios.py · module · 0.2089; day21-backend-core-dependencies.py · get_indexing_service · 0.124

### 9. Какая погода будет в Москве в выходные?

**Локальная модель (Ollama · local)** — режим `dont_know` · 0.05 с · провайдер `local`

> Не знаю. Уточните вопрос или дайте больше контекста

источники: —

предупреждение: Недостаточно контекста: максимальный балл 0.172 ниже порога 0.6

**Облако (DeepSeek · deepseek)** — режим `dont_know` · 0.05 с · провайдер `deepseek`

> Не знаю. Уточните вопрос или дайте больше контекста

источники: —

предупреждение: Недостаточно контекста: максимальный балл 0.172 ниже порога 0.6

### 10. Как приготовить борщ на ужин?

**Локальная модель (Ollama · local)** — режим `dont_know` · 0.06 с · провайдер `local`

> Не знаю. Уточните вопрос или дайте больше контекста

источники: —

предупреждение: Недостаточно контекста: максимальный балл 0.215 ниже порога 0.6

**Облако (DeepSeek · deepseek)** — режим `dont_know` · 0.03 с · провайдер `deepseek`

> Не знаю. Уточните вопрос или дайте больше контекста

источники: —

предупреждение: Недостаточно контекста: максимальный балл 0.215 ниже порога 0.6


## Итог

* всего вопросов: 10
* среднее время: локальная 3.61 с, облачная 0.97 с — облако быстрее в 3.7 раза
* ответов с источниками: local 8, cloud 8 (источники приходят из одного и того же локального отбора)
* режим `rag`: local 8, cloud 8
* `dont_know`: local 2, cloud 2
* подтверждённых цитат: local 2, cloud 5
* вердикты строк: локально лучше 1, облако лучше 4, равно 5
* общий вердикт прогона: облако лучше
* строк с режимом `error`: 0

## Выводы

Наблюдения по этому прогону (числа — из таблицы и `## Итог`; субъективные оценки
опираются на конкретные строки приложения):

* **Качество по корпусу.** Обе модели ответили по корпусу на 8 из 10 вопросов
  (`rag` у local 8 и у cloud 8), на двух вопросах вне корпуса обе ушли в «не знаю» с
  одинаковыми предупреждениями о пороге (0.172 и 0.215 против 0.6). Откатов и ошибок
  нет ни у одной стороны: 0 строк с `fallback`, 0 с `error`. Локальная 14B-модель
  прошла полный RAG-цикл без облака — retrieval, контекст и генерация целиком на
  своей машине.
* **Факты совпали, различалась форма.** На вопросах 1, 2, 5, 6, 7 оба ответа дают одно
  и то же: 1800, 300, 300, «читает папку, метаданные из манифеста»,
  `paraphrase-multilingual-MiniLM-L12-v2`. Ни на одной строке модели не разошлись в
  факте; облако цитирует фрагменты дословно, локальная формулирует своими словами.
* **Где локальная уступает.** На вопросах 1–3 машинный вердикт «облако лучше»
  выставлен за подтверждённые цитаты (`quotes_verified`): у локальной подтверждено 2
  цитаты против 5 у облака — механизм дня 24 сверяет ответ с началом чанка, а
  локальная чаще пересказывает. На вопросе 8 (что проверяет `TestQuery`) локальная
  достроила интерпретацию («TestQuery проверяет данные, а не код» и не назвала поля),
  тогда как облако осталось в границах корпуса: назвало поля и прямо сказало, что
  отдельной проверки корпус не описывает.
* **Где локальная не хуже.** Вопрос 4 (`ChunkStore.add_chunks`) — единственная строка
  с вердиктом «локально лучше»: локальная привела фрагмент кода с сигнатурой,
  `flush()` и порядком id до `commit()`, облако пересказало то же прозой.
* **Скорость.** Среднее время: локальная 3.61 с, облачная 0.97 с — облако быстрее в
  3.7 раза. Разброс локальной — от 3.1 с (вопрос 5) до 8.5 с (вопрос 4, самый длинный
  ответ: 14B-модель считает на локальном железе, веса уже в памяти). Стоимость облачных
  токенов в этом прогоне оплачена, локальные — нулевые.
* **Retrieval в сравнении не участвовал.** Источники обеих колонок совпадают до
  последнего фрагмента (5 / 5 на всех восьми строках с ответом): отбор один и тот же и
  всегда локальный (FAISS-индекс дня 22 и sentence-transformers). Отличается только
  генерация — ровно то, что и должно было сравниваться.
* **Итог по заданию.** Локальный контур RAG работает полностью офлайн и на этих
  вопросах по фактам не уступает облаку, но проигрывает в скорости (3.7 раза) и в
  дословной опоре на цитаты (2 против 5), а там, где корпус молчит о причине, склонна
  достраивать интерпретацию. Общий машинный вердикт прогона — «облако лучше» (4 строки
  против 1), при 5 «равно».

## Ручная оценка

Колонки «Локальная модель» и «Облако» — оценка человеком после чтения приложения;
вердикт в таблице сравнения машинный (`backend/domain/rag_compare.py`: режим → цитаты →
уверенность → источники). Где он расходится с ручной оценкой, сказано в комментарии.

| № | Вопрос | Локальная модель | Облако | Комментарий |
|---|---|---|---|---|
| 1 | Чему равен CHARS_PER_PAGE? | верно (1800) | верно (1800, дословно) | факт совпал; «облако лучше» — за подтверждённую цитату, а не за факт |
| 2 | Чему равен PREVIEW_CHARS? | верно (300) | верно (300, дословно) | то же расхождение машинного вердикта с ручной оценкой |
| 3 | Зачем нужен CYRILLIC_RATIO? | верно (порог 0.15 в `detect_language`) | верно (то же, с цитатой) | локальная короче, содержание то же |
| 4 | Как работает ChunkStore.add_chunks? | верно, с фрагментом кода | верно, пересказ | единственная строка «локально лучше» — за детализацию |
| 5 | Чему равен EXCERPT_CHARS? | верно (300) | верно (300) | совпало, вердикт «равно» |
| 6 | Что делает load_documents? | верно (папка + манифест) | верно (то же, полнее) | локальная пропустила фильтр расширений, но ответ верен |
| 7 | Модель эмбеддингов по умолчанию? | верно (MiniLM-L12-v2) | верно (то же + `DAY21_EMBEDDING_MODEL`) | совпало |
| 8 | Что проверяет TestQuery? | частично: ушла в интерпретацию, поля не назвала | верно: назвало поля и границу корпуса | «облако лучше» здесь совпадает с ручной оценкой |
| 9 | Погода в Москве? | «не знаю» — верно | «не знаю» — верно | вопроса нет в корпусе, режим `dont_know` корректен у обеих |
| 10 | Как приготовить борщ? | «не знаю» — верно | «не знаю» — верно | то же: ответа в корпусе нет |

