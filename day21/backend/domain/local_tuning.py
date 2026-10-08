"""Настройка локальной модели под кейс RAG (день 29): два профиля одного формата.

Задание дня — настроить параметры локальной модели (``temperature``, предел ответа,
окно контекста), сравнить кванты и переписать промпт под конкретный кейс. Кейс —
ответы локальной модели по корпусу проекта (русский язык), поэтому профиль — это
именованный набор ровно тех ручек, которые день называет:

* ``baseline`` — поведение дня 26: ``temperature`` = ``config.DEFAULT_TEMPERATURE``,
  ``num_ctx`` = 4096 (значение Ollama по умолчанию, задано явно), предела ответа и
  системного промпта у профиля нет — их берут вызывающий код и тип задачи;
* ``tuned`` — после оптимизации: ``temperature`` 0.2, ``num_ctx`` 8192, предел
  ответа 512 токенов и переписанный системный промпт ``LOCAL_TUNED_RAG_PROMPT``.

Почему домен, а не конфиг. Параметров четыре, и все они должны меняться вместе:
профиль — единственный источник правды и для клиента (``num_ctx``), и для вызова
(``temperature``, предел ответа), и для промпта — иначе ``.env`` задал бы половину
настроек, а вторая осталась бы зашитой в сервисе. Оценка прогона (строка вопроса,
сводка варианта и вердикт пары) живёт рядом, в ``local_tuning_eval``: правило
сравнения не должно повторяться ни в интерфейсе, ни в отчёте.

Разрешение окружения — та же схема, что у порога релевантности дня 24
(``rag_quotes.resolve_relevance_threshold``): значение процесса → строка файла
``day21/.env`` → значение по умолчанию; битая запись — предупреждение логгера и
значение по умолчанию, а не падение сервиса. Значения вычисляются на импорте, поэтому
правка ``.env`` требует перезапуска бэкенда.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Callable, Mapping, Optional

from shared.logging_utils import get_logger

from ..core import config
from . import llm_provider

logger = get_logger(__name__)

__all__ = ["BASELINE_NUM_CTX", "CHAT_MAX_TOKENS_DEFAULT", "CHAT_MAX_TOKENS_ENV",
           "LOCAL_LLM_CHAT_MAX_TOKENS", "LOCAL_LLM_NUM_CTX", "LOCAL_LLM_PROFILE",
           "LOCAL_LLM_TEMPERATURE", "LOCAL_TUNED_RAG_PROMPT", "NUM_CTX_DEFAULT",
           "NUM_CTX_ENV", "PROFILE_BASELINE", "PROFILE_DEFAULT", "PROFILE_ENV",
           "PROFILE_LABELS", "PROFILE_TUNED", "PROFILES", "TEMPERATURE_DEFAULT",
           "TEMPERATURE_ENV", "TuningProfile", "active", "baseline_profile",
           "create", "profile_for", "prompt_for", "resolve_number",
           "resolve_profile", "tuned_profile"]

# ---------- имена и значения по умолчанию ----------
PROFILE_BASELINE = "baseline"
PROFILE_TUNED = "tuned"
PROFILES = (PROFILE_BASELINE, PROFILE_TUNED)

#: Подписи профилей: их отдают ``GET /llm/provider`` и интерфейс, чтобы список имён
#: не дублировался литералами во фронтенде.
PROFILE_LABELS = {
    PROFILE_BASELINE: "🧊 До оптимизации (baseline)",
    PROFILE_TUNED: "⚡ После оптимизации (tuned)",
}

#: Имя переменной профиля и профиль по умолчанию: tuned — поведение дня 29.
PROFILE_ENV = "LOCAL_LLM_PROFILE"
PROFILE_DEFAULT = PROFILE_TUNED

TEMPERATURE_ENV, TEMPERATURE_DEFAULT = "LOCAL_LLM_TEMPERATURE", 0.2
NUM_CTX_ENV, NUM_CTX_DEFAULT = "LOCAL_LLM_NUM_CTX", 8192
CHAT_MAX_TOKENS_ENV, CHAT_MAX_TOKENS_DEFAULT = "LOCAL_LLM_CHAT_MAX_TOKENS", 512

#: Окно контекста дня 26: Ollama по умолчанию держит 4096, поэтому baseline задаёт
#: его явно, а не полагается на версию службы.
BASELINE_NUM_CTX = 4096

#: Системный промпт профиля ``tuned``: короче дня 26, с жёстким форматом ответа.
#: Требование «строка Ответ: не длиннее трёх предложений + Источники:» задаёт предел
#: длины на уровне промпта, а не только ``num_predict``: обрезанный на полуслове ответ
#: тоже портит вердикт.
LOCAL_TUNED_RAG_PROMPT = (
    "Ты отвечаешь на вопрос по фрагментам внутреннего корпуса проекта.\n"
    "Правила:\n"
    "1. Опирайся только на блок контекста ниже; общие знания и домыслы не используй.\n"
    "2. Каждый факт подкрепляй короткой цитатой из контекста в кавычках.\n"
    "3. Формат ответа: строка «Ответ:» с ответом не длиннее трёх предложений, затем "
    "строка «Источники:» с номерами использованных фрагментов, например [2], [5].\n"
    "4. Если в контексте нет ответа — ответь ровно «Не знаю» и не перечисляй источники.\n"
    "5. Пиши по-русски, без вступлений, извинений и пересказа вопроса."
)


# ---------- разрешение окружения ----------
def _env_file_value(name: str, path: Optional[Any]) -> Optional[str]:
    """Читает ``NAME=VALUE`` из файла окружения; ``None``, если ключа нет.

    Копия правила дня 24 (``rag_quotes._env_file_value``): значение по умолчанию
    остаётся в этом модуле, а файл лишь переопределяет его. Пустые строки и
    комментарии пропускаются, кавычки вокруг значения снимаются.
    """
    if not path:
        return None
    try:
        lines = Path(path).read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for raw in lines:
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != name:
            continue
        return value.strip().strip('"').strip("'")
    return None


def _raw_value(name: str, env: Optional[Mapping[str, str]], path=None) -> Optional[str]:
    """Значение настройки: процессное окружение → файл ``.env`` → ``None``."""
    source: Mapping[str, str] = os.environ if env is None else env
    raw = source.get(name)
    if not raw:
        raw = _env_file_value(name, config.ENV_FILE if path is None else path)
    return raw


def resolve_profile(env: Optional[Mapping[str, str]] = None, path=None) -> str:
    """Имя профиля: ``env`` → ``.env`` → ``tuned``.

    Незнакомое имя — предупреждение и профиль по умолчанию: опечатка в ``.env`` не
    должна ни ронять сервис, ни молча менять набор параметров на чужой.
    """
    raw = _raw_value(PROFILE_ENV, env, path)
    if not raw:
        return PROFILE_DEFAULT
    name = str(raw).strip().lower()
    if name not in PROFILES:
        logger.warning("%s=%r неизвестен, беру %s", PROFILE_ENV, raw, PROFILE_DEFAULT)
        return PROFILE_DEFAULT
    return name


def resolve_number(name: str, default: Any, cast: Callable[[str], Any],
                   env: Optional[Mapping[str, str]] = None, path=None) -> Any:
    """Число настройки: ``env`` → ``.env`` → значение по умолчанию.

    Не число — предупреждение и значение по умолчанию (та же терпимость, что у порога
    дня 24): правка ``.env`` не должна ронять запрос.
    """
    raw = _raw_value(name, env, path)
    if raw in (None, ""):
        return default
    try:
        return cast(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("%s=%r не число, беру %s", name, raw, default)
        return default


#: Действующие значения: вычисляются на импорте, поэтому правка ``day21/.env``
#: требует перезапуска бэкенда.
LOCAL_LLM_PROFILE = resolve_profile()
LOCAL_LLM_TEMPERATURE = resolve_number(TEMPERATURE_ENV, TEMPERATURE_DEFAULT, float)
LOCAL_LLM_NUM_CTX = resolve_number(NUM_CTX_ENV, NUM_CTX_DEFAULT, int)
LOCAL_LLM_CHAT_MAX_TOKENS = resolve_number(
    CHAT_MAX_TOKENS_ENV, CHAT_MAX_TOKENS_DEFAULT, int)


# ---------- профиль ----------
@dataclass(frozen=True)
class TuningProfile:
    """Набор ручек генерации одного варианта: клиент берёт ``model``/``num_ctx``,
    вызов — ``temperature``/``max_tokens``/``system_prompt``.

    ``max_tokens`` и ``system_prompt`` могут быть ``None``: это значит «как было» —
    предел по типу задачи и промпт вызывающего кода (поведение дня 26).
    """

    name: str
    label: str
    temperature: float
    num_ctx: int
    max_tokens: Optional[int] = None
    system_prompt: Optional[str] = None
    model: Optional[str] = None

    @property
    def key(self) -> str:
        """Ключ кэша клиентов: профиль плюс модель (без модели — звёздочка)."""
        return f"{self.name}|{self.model or '*'}"

    @property
    def title(self) -> str:
        """Подпись варианта для сводки и отчёта: профиль и модель."""
        return f"{self.name} ({self.model or 'модель конфига'})"

    def as_dict(self) -> dict:
        """Профиль для схемы API и отчёта: параметры плюс длина промпта."""
        return {
            "profile": self.name,
            "label": self.label,
            "model": self.model,
            "temperature": self.temperature,
            "num_ctx": self.num_ctx,
            "max_tokens": self.max_tokens,
            "system_prompt": self.system_prompt,
            "system_prompt_chars": len(self.system_prompt or ""),
        }


def baseline_profile() -> TuningProfile:
    """Профиль дня 26: промпт и предел ответа — вызывающего кода."""
    return TuningProfile(
        name=PROFILE_BASELINE,
        label=PROFILE_LABELS[PROFILE_BASELINE],
        temperature=config.DEFAULT_TEMPERATURE,
        num_ctx=BASELINE_NUM_CTX,
    )


def tuned_profile() -> TuningProfile:
    """Профиль после оптимизации: значения модульных констант и новый промпт."""
    return TuningProfile(
        name=PROFILE_TUNED,
        label=PROFILE_LABELS[PROFILE_TUNED],
        temperature=LOCAL_LLM_TEMPERATURE,
        num_ctx=LOCAL_LLM_NUM_CTX,
        max_tokens=LOCAL_LLM_CHAT_MAX_TOKENS,
        system_prompt=LOCAL_TUNED_RAG_PROMPT,
    )


def create(name: str, *, model: Optional[str] = None) -> TuningProfile:
    """Профиль по имени: ``baseline``/``tuned``, модель подставляется снаружи.

    Незнакомое имя — ``ValueError``: роутер переводит его в 400, а молчаливая подмена
    профиля показала бы в ответе не тот набор параметров, который запросили.
    """
    if name == PROFILE_BASELINE:
        return replace(baseline_profile(), model=(model or None))
    if name == PROFILE_TUNED:
        return replace(tuned_profile(), model=(model or None))
    raise ValueError(f"Неизвестный профиль настройки: {name!r}. Доступны: "
                     f"{', '.join(PROFILES)}")


def active(provider: Optional[str] = None) -> Optional[TuningProfile]:
    """Профиль запроса для локального провайдера; облако профиля не имеет.

    ``tuned`` включён по умолчанию (``LOCAL_LLM_PROFILE``), ``baseline`` возвращает
    ``None`` — поведение дня 26 без единого параметра сверх конфига. Незнакомое
    значение тоже даёт ``None`` с предупреждением: неверная строка в ``.env`` не
    должна менять поведение незаметно.
    """
    if llm_provider.resolve(provider) != llm_provider.PROVIDER_LOCAL:
        return None
    if LOCAL_LLM_PROFILE == PROFILE_TUNED:
        return tuned_profile()
    if LOCAL_LLM_PROFILE != PROFILE_BASELINE:
        logger.warning("%s=%r неизвестен, работаю как в день 26",
                       PROFILE_ENV, LOCAL_LLM_PROFILE)
    return None


def prompt_for(profile: Optional[TuningProfile], default: str) -> str:
    """Системный промпт вызова: у профиля свой, иначе — промпт вызывающего кода."""
    if profile is not None and profile.system_prompt:
        return profile.system_prompt
    return default


def profile_for(provider: Optional[str] = None,
                profile: Optional[TuningProfile] = None) -> Optional[TuningProfile]:
    """Профиль вызова: явный объект важнее профиля по умолчанию из окружения.

    Так работает прогон дня 29: при ``LOCAL_LLM_PROFILE=tuned`` он всё равно может
    запросить ``baseline``, не трогая ``.env`` и не перезапуская бэкенд.
    """
    return profile if profile is not None else active(provider)
