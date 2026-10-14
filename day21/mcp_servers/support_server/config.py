"""Константы MCP-сервера поддержки (день 33): корень дня, путь к базе, тексты.

Модуль без зависимости от SDK: его импортируют ``tools.py``, ``server.py`` и тесты.
Корень дня нужен, потому что сервер запускается ОТДЕЛЬНЫМ процессом, где ни корень
дня, ни корень репозитория в ``sys.path`` не попадают: без него импорт
``mcp_servers.support_server.*`` и путь к базе поддержки не разрешились бы.

База — один JSON-файл ``backend/data/support_db.json`` (пользователи, тикеты и
разделы продукта). Файл читается на КАЖДЫЙ вызов инструмента (см. ``tools._load``):
он источник истины, и кэш в процессе дал бы расхождение после правки базы.
"""
import sys
from pathlib import Path

#: Корень дня (day21/mcp_servers/support_server/config.py → day21/).
DAY_ROOT = Path(__file__).resolve().parents[2]
if str(DAY_ROOT) not in sys.path:
    sys.path.insert(0, str(DAY_ROOT))

#: Имя и версия сервера: уходят клиенту в ответе ``initialize``.
SERVER_NAME = "day21-support"
SERVER_VERSION = "1.0.0"

#: Инструкция сервера: клиент показывает её модели рядом с каталогом инструментов.
SERVER_INSTRUCTIONS = (
    "Пять инструментов поддержки. get_user(user_id=\"user_003\") отдаёт "
    "профиль (id, name, email, plan, registered_at, last_seen). get_ticket(ticket_id=\"ticket_007\") "
    "отдаёт тикет целиком: тема, статус, приоритет, дата и история сообщений. "
    "list_user_tickets(user_id=\"user_003\") перечисляет тикеты пользователя. "
    "get_product_info(product_area=\"auth\") отдаёт раздел продукта: описание и короткий FAQ "
    "(области: auth, billing, api, integrations, notifications). list_users() перечисляет "
    "всех пользователей базы. Ненайденная запись приходит словарём с полем error=\"not found\"."
)

#: Путь к базе поддержки от корня дня: пользователи, тикеты и разделы продукта.
DB_PATH = DAY_ROOT / "backend" / "data" / "support_db.json"
#: Суффикс базы: проверяется при чтении, чтобы кривой путь падал понятным текстом.
FILE_SUFFIX = ".json"
#: Значение поля ``error`` у ненайденной записи: ответ-данные, а не исключение.
NOT_FOUND = "not found"
