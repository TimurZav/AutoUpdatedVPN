import os
import json
import telebot
import hashlib
import logging
import requests
from io import BytesIO
from datetime import datetime
from dotenv import load_dotenv
from telebot.types import BotCommand
from apscheduler.schedulers.background import BackgroundScheduler
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery


load_dotenv()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
GITHUB_URL = os.getenv("GITHUB_URL")

STATE_FILE = "state.json"
DOCUMENT_NAME = "github_document.txt"

if not all([BOT_TOKEN, CHAT_ID, GITHUB_URL]):
    raise SystemExit("Environment variables are not fully defined")


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)


class DocumentState:
    """
    Stores and persists document state between application restarts.

    Keeps track of:
    - last document check time
    - last successful send time
    - last document hash
    """

    def __init__(self, path: str):
        self.path = path
        self.last_check_at: str | None = None
        self.last_send_at: str | None = None
        self.last_hash: str | None = None
        self.load()

    def load(self) -> None:
        """Load state from JSON file if it exists."""
        if not os.path.exists(self.path):
            return

        with open(self.path, "r", encoding="utf-8") as f:
            data = json.load(f)

        self.last_check_at = data.get("last_check_at")
        self.last_send_at = data.get("last_send_at")
        self.last_hash = data.get("last_hash")

    def save(self) -> None:
        """Persist current state to JSON file."""
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump(
                {
                    "last_check_at": self.last_check_at,
                    "last_send_at": self.last_send_at,
                    "last_hash": self.last_hash,
                },
                f,
                ensure_ascii=False,
                indent=2,
            )


class GitHubDocumentWatcher:
    """
    Responsible for fetching a document from GitHub,
    detecting changes and sending updates to Telegram.
    """

    def __init__(
        self,
        url: str,
        bot: telebot.TeleBot,
        chat_id: str,
        state: DocumentState,
    ):
        self.url = url
        self.bot = bot
        self.chat_id = chat_id
        self.state = state

    @staticmethod
    def _now() -> str:
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @staticmethod
    def _hash(content: str) -> str:
        return hashlib.sha256(content.encode("utf-8")).hexdigest()

    def fetch(self) -> str:
        """Download document content from GitHub."""
        logger.info("Fetching document from GitHub")
        response = requests.get(self.url, timeout=30)
        response.raise_for_status()
        return response.text

    def send(self, content: str) -> None:
        """Send document to Telegram chat."""
        file = BytesIO(content.encode("utf-8"))
        file.name = DOCUMENT_NAME

        self.bot.send_document(
            chat_id=self.chat_id,
            document=file,
            caption="📄 Документ обновлен",
        )

    def check_and_send(self) -> None:
        """
        Check document for changes and send it to Telegram
        only if the content has changed.
        """
        logger.info("Checking document")

        self.state.last_check_at = self._now()

        content = self.fetch()
        current_hash = self._hash(content)

        if current_hash == self.state.last_hash:
            logger.info("Document has not changed")
            self.state.save()
            return

        self.send(content)

        self.state.last_hash = current_hash
        self.state.last_send_at = self._now()
        self.state.save()

        logger.info("Document sent")

    def force_send(self) -> None:
        """
        Force document sending without checking for changes.
        """
        logger.info("Force sending document")

        self.state.last_check_at = self._now()

        content = self.fetch()
        self.send(content)

        self.state.last_hash = self._hash(content)
        self.state.last_send_at = self._now()
        self.state.save()


class TelegramBotApp:
    """
    Application entrypoint that wires together:
    - Telegram bot
    - Scheduler
    - Document watcher
    """

    def __init__(self):
        self.bot = telebot.TeleBot(BOT_TOKEN)
        self.state = DocumentState(STATE_FILE)
        self.watcher = GitHubDocumentWatcher(
            GITHUB_URL,
            self.bot,
            CHAT_ID,
            self.state,
        )
        self.scheduler = BackgroundScheduler()

        self._register_commands()
        self._register_handlers()
        self._register_jobs()

    @staticmethod
    def _is_authorized(chat_id: int) -> bool:
        return str(chat_id) == str(CHAT_ID)

    @staticmethod
    def _build_start_keyboard() -> InlineKeyboardMarkup:
        keyboard = InlineKeyboardMarkup(row_width=2)

        keyboard.add(
            InlineKeyboardButton("⏳ Статус", callback_data="status"),
            InlineKeyboardButton("📤 Отправить", callback_data="send_now"),
            InlineKeyboardButton("🔄 Проверить", callback_data="check"),
        )

        return keyboard

    def _register_commands(self) -> None:
        """Register visible bot commands in Telegram UI."""
        commands = [
            BotCommand("start", "Запустить бота"),
            BotCommand("status", "Показать статус документа"),
            BotCommand("send_now", "Принудительно отправить документ"),
            BotCommand("check", "Проверка актуального документа"),
        ]
        self.bot.set_my_commands(commands)

    def _register_jobs(self) -> None:
        """Register scheduled jobs."""
        self.scheduler.add_job(
            self.watcher.check_and_send,
            trigger="cron",
            hour=18,
            minute=0,
        )

    def _register_handlers(self) -> None:
        """Register Telegram bot command handlers."""

        @self.bot.message_handler(commands=["start"])
        def start(message):
            text = (
                "👋 Привет!\n\n"
                "Я отслеживаю документ в GitHub и отправляю его, "
                "если он изменился.\n\n"
                "Выбери действие:"
            )

            self.bot.send_message(
                message.chat.id,
                text,
                reply_markup=self._build_start_keyboard(),
            )

        @self.bot.message_handler(commands=["status"])
        def status(message):
            text = (
                "📊 Статус документа\n\n"
                f"🕒 Последняя проверка: {self.state.last_check_at}\n"
                f"📤 Последняя отправка: {self.state.last_send_at}\n"
                f"🔐 Хэш: {self.state.last_hash}"
            )

            self.bot.reply_to(message, text)

        @self.bot.message_handler(commands=["send_now"])
        def send_now(message):
            if not self._is_authorized(message.chat.id):
                self.bot.answer_callback_query(message.id, "⛔ Нет доступа", show_alert=True)
                return

            try:
                self.watcher.force_send()
            except Exception as e:
                logger.exception("Force send failed")
                self.bot.reply_to(message, f"❌ Ошибка: {e}")

        @self.bot.message_handler(commands=["check"])
        def check(message):
            if not self._is_authorized(message.chat.id):
                self.bot.answer_callback_query(message.id, "⛔ Нет доступа", show_alert=True)
                return

            try:
                self.watcher.check_and_send()
                self.bot.reply_to(message, "✅ Проверка завершена")
            except Exception as e:
                logger.exception("Check failed")
                self.bot.reply_to(message, f"❌ Ошибка: {e}")

        @self.bot.callback_query_handler(func=lambda call: True)
        def callback_handler(call: CallbackQuery):
            data_actions: dict = {
                'status': status,
                'send_now': send_now,
                'check': check
            }
            if call.data in data_actions:
                data_actions[call.data](call.message)

    def run(self) -> None:
        """Start scheduler and run Telegram bot polling."""
        logger.info("Starting scheduler")
        self.scheduler.start()

        logger.info("Starting bot polling")
        self.bot.infinity_polling()


if __name__ == "__main__":
    TelegramBotApp().run()
