"""Настройки логирования, общие для приложений дней (папка shared/).

Модуль — единственный источник настроек логирования: приложения и общие модули
берут отсюда логгер (``get_logger``), а вывод включает приложение
(``configure_logging``).

По умолчанию вывод ВЫКЛЮЧЕН: ``get_logger`` не добавляет ни хендлеров, ни
уровня, а root-логгер по умолчанию пропускает только WARNING и выше. Поэтому
модули могут писать ``logger.debug(...)`` сколько угодно — наблюдаемое
поведение приложения не меняется; вывод включает только явный вызов
``configure_logging()`` из приложения.
"""
import logging

#: Формат строки лога по умолчанию для приложений дней.
DEFAULT_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def get_logger(name: str) -> logging.Logger:
    """Логгер модуля (без хендлеров: вывод настраивает приложение)."""
    return logging.getLogger(name)


def configure_logging(level: int = logging.INFO, fmt: str = DEFAULT_FORMAT) -> None:
    """Включает вывод логов в консоль (``logging.basicConfig`` для root-логгера)."""
    logging.basicConfig(level=level, format=fmt)
