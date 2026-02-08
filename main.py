import os
import logging
import requests
import telebot
from io import BytesIO
from dotenv import load_dotenv
from apscheduler.schedulers.blocking import BlockingScheduler

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Получаем переменные окружения
TELEGRAM_BOT_TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
TELEGRAM_CHAT_ID = os.getenv('TELEGRAM_CHAT_ID')
GITHUB_URL = os.getenv('GITHUB_URL')

# Проверяем наличие всех необходимых переменных
if not all([TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, GITHUB_URL]):
    logger.error("Не все переменные окружения установлены!")
    logger.error(f"TELEGRAM_BOT_TOKEN: {'установлен' if TELEGRAM_BOT_TOKEN else 'отсутствует'}")
    logger.error(f"TELEGRAM_CHAT_ID: {'установлен' if TELEGRAM_CHAT_ID else 'отсутствует'}")
    logger.error(f"GITHUB_URL: {'установлен' if GITHUB_URL else 'отсутствует'}")
    raise SystemExit("Ошибка: отсутствуют необходимые переменные окружения")


def fetch_github_document():
    """Получает содержимое документа из GitHub"""
    try:
        logger.info(f"Получаю документ из GitHub: {GITHUB_URL}")
        response = requests.get(GITHUB_URL, timeout=30)
        response.raise_for_status()
        logger.info("Документ успешно получен из GitHub")
        return response.text
    except requests.exceptions.RequestException as err:
        logger.error(f"Ошибка при получении документа из GitHub: {err}")
        raise


def send_to_telegram(content):
    """Отправляет содержимое в Telegram"""
    try:
        bot = telebot.TeleBot(TELEGRAM_BOT_TOKEN)

        # Если содержимое слишком большое, отправляем файлом
        max_message_length = 4096
        if len(content) <= max_message_length:
            bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=content
            )
            logger.info("Сообщение успешно отправлено в Telegram")
        else:
            # Отправляем как файл, если текст слишком длинный
            logger.info("Содержимое слишком большое, отправляю как файл")
            file = BytesIO(content.encode('utf-8'))
            file.name = 'github_document.txt'
            bot.send_document(
                chat_id=TELEGRAM_CHAT_ID,
                document=file,
                caption='Документ из GitHub'
            )
            logger.info("Файл успешно отправлен в Telegram")

    except Exception as err:
        logger.error(f"Ошибка при отправке в Telegram: {err}")
        raise


def scheduled_job():
    """Задача, которая выполняется по расписанию"""
    logger.info("Запуск запланированной задачи")
    try:
        content = fetch_github_document()
        send_to_telegram(content)
        logger.info("Задача выполнена успешно")
    except Exception as e:
        logger.error(f"Ошибка при выполнении задачи: {e}")


def main():
    """Главная функция"""
    logger.info("Запуск приложения")
    logger.info(f"Документ будет отправляться каждый день в 18:00 по местному времени")

    # Создаем планировщик
    scheduler = BlockingScheduler()

    # Добавляем задачу на выполнение каждый день в 18:00
    scheduler.add_job(scheduled_job, 'cron', hour=18, minute=0)

    logger.info("Планировщик настроен. Ожидаю выполнения задач...")

    try:
        # Запускаем планировщик
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Приложение остановлено")


if __name__ == "__main__":
    main()
