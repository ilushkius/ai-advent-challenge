"""
============================================================
 Первый запрос к DeepSeek API (модель deepseek-chat)
============================================================

ПЕРЕД ЗАПУСКОМ установите библиотеку (в терминале):

    pip install openai

КАК ПОЛУЧИТЬ API-КЛЮЧ:
    1. Зарегистрируйтесь на https://platform.deepseek.com
    2. Откройте раздел "API Keys" -> "Create new key"
    3. Скопируйте ключ (он начинается с "sk-")

ГДЕ ХРАНИТЬ КЛЮЧ (скрипт проверяет по порядку и берёт первый
ПОДХОДЯЩИЙ вариант):
    1. Файл .env рядом со скриптом:
           DEEPSEEK_API_KEY=sk-ваш-ключ
    2. Переменная окружения DEEPSEEK_API_KEY.
    3. Если подходящего ключа нигде нет — скрипт спросит его
       в консоли (ввод будет скрыт, чтобы его никто не увидел).

Заглушки и мусор (пустые значения, "sk-вставьте-сюда-ваш-ключ")
скрипт считает НЕподходящими и переходит к следующему варианту.
"""

import os                        # чтение переменных окружения
import sys                       # настройка вывода в консоль
import getpass                   # скрытый ввод пароля/ключа
from openai import OpenAI        # официальная библиотека OpenAI (её использует DeepSeek)

# Чтобы русский текст и эмодзи корректно печатались в любой консоли Windows
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass  # если консоль не поддерживает UTF-8 — просто работаем дальше

# ------------------------------------------------------------
# Вспомогательные функции для поиска и проверки API-ключа
# ------------------------------------------------------------

def read_key_from_file(filename):
    """Ищет в файле строку DEEPSEEK_API_KEY=... и возвращает её значение.

    Если файла нет, строка не найдена или файл не читается — вернём None.
    """
    try:
        with open(filename, "r", encoding="utf-8") as file:
            for line in file:
                line = line.strip()
                # Пропускаем пустые строки и комментарии (начинаются с "#")
                if not line or line.startswith("#"):
                    continue
                # Некоторые .env-файлы пишут "export DEEPSEEK_API_KEY=..." —
                # уберём лишнее слово "export"
                if line.startswith("export "):
                    line = line[len("export "):].strip()
                if "=" in line:
                    name, value = line.split("=", 1)
                    if name.strip() == "DEEPSEEK_API_KEY":
                        # Убираем лишние пробелы и кавычки вокруг значения
                        return value.strip().strip('"').strip("'")
    except OSError:
        return None  # файл не существует или не открывается
    return None


def is_real_key(key):
    """Проверяет, что ключ похож на настоящий, а не на заглушку из образца."""
    if not key:
        return False
    # Слова-заглушки, которые встречаются в файлах-примерах
    placeholders = ("вставьте", "your-key", "your_api_key", "example", "placeholder")
    if any(word in key.lower() for word in placeholders):
        return False
    # Ключ DeepSeek начинается с "sk-", дальше — латинские буквы и/или цифры
    if not key.startswith("sk-") or len(key) < 6:
        return False
    tail = key[3:]  # часть после "sk-"
    return all(c.isascii() and (c.isalnum() or c in "-_") for c in tail)


# ------------------------------------------------------------
# Шаг 1. Получаем API-ключ
# ------------------------------------------------------------

# Проверяем ключ по порядку: .env -> переменная окружения.
# Берём первый ПОДХОДЯЩИЙ ключ и запоминаем, откуда он взят.
key_sources = [
    (".env", read_key_from_file(".env")),
    ("переменная окружения DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY")),
]

api_key = None
key_source = None
for source, value in key_sources:
    if is_real_key(value):
        api_key = value
        key_source = source
        break

# Если подходящего ключа не нашлось — просим ввести его вручную.
# getpass.getpass() скрывает ввод: символы не отображаются на экране.
if api_key is None:
    api_key = getpass.getpass("Введите ваш API-ключ DeepSeek: ").strip()
    key_source = "ручной ввод"

# Если ключ так и не похож на настоящий — дальше работать не имеет смысла
if not is_real_key(api_key):
    print("API-ключ не найден или не похож на настоящий. Завершение работы.")
    sys.exit(1)

print(f"API-ключ взят из: {key_source}")

# ------------------------------------------------------------
# Шаг 2. Создаём клиент для общения с DeepSeek
# ------------------------------------------------------------

# API DeepSeek совместимо с API OpenAI, поэтому используем класс OpenAI,
# но указываем адрес серверов DeepSeek через параметр base_url.
client = OpenAI(
    api_key=api_key,
    base_url="https://api.deepseek.com",
)

# ------------------------------------------------------------
# Шаг 3. Бесконечный цикл чата в консоли
# ------------------------------------------------------------

print()
print("=" * 50)
print("  Чат с DeepSeek начат! Задавайте любые вопросы.")
print("  Для выхода введите: exit  или  выход")
print("=" * 50)
print()

# while True создаёт бесконечный цикл. Выход из него — через break.
while True:
    # input() ждёт строку от пользователя, strip() убирает лишние пробелы
    user_text = input("Вы: ").strip()

    # Если введено "exit" или "выход" — выходим из цикла
    if user_text.lower() in ("exit", "выход"):
        print()
        print("До свидания! 👋")
        break

    # Пропускаем пустой ввод, чтобы не отправлять пустые запросы
    if not user_text:
        continue

    print("DeepSeek: ", end="", flush=True)

    try:
        # Отправляем запрос в модель deepseek-chat.
        # messages — список сообщений; здесь одно сообщение от пользователя.
        # stream=True включает потоковый режим: ответ приходит кусочками,
        # и мы печатаем его постепенно, как в онлайн-чате.
        stream = client.chat.completions.create(
            model="deepseek-chat",
            messages=[
                {"role": "user", "content": user_text},
            ],
            stream=True,
        )

        # Проходим по всем кусочкам ответа
        for chunk in stream:
            # В каждом кусочке текст лежит в chunk.choices[0].delta.content
            # (последний кусочек бывает пустым — поэтому нужна проверка)
            if chunk.choices and chunk.choices[0].delta.content:
                # end="" — не переводим строку, печатаем текст подряд.
                # flush=True — сразу показываем текст, без буферизации.
                print(chunk.choices[0].delta.content, end="", flush=True)

        print()  # перевод строки после ответа модели
        print()

    except Exception as error:
        # Если нет сети, неверный ключ или другая ошибка —
        # показываем понятное сообщение и продолжаем диалог.
        print()
        print(f"Произошла ошибка: {error}")
        print()
