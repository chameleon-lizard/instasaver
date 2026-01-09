import asyncio
import logging
from pathlib import Path

from ..config import Settings
from ..storage.database import Database
from ..instagram.client import InstagramClient
from ..instagram.fetcher import InstagramFetcher
from ..instagram.sender import InstagramSender
from ..telegram.bot import TelegramBridge

logger = logging.getLogger(__name__)


class Bridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database()
        self.temp_dir = Path("data/temp")
        self.temp_dir.mkdir(parents=True, exist_ok=True)

        # Instagram
        self.ig_client = InstagramClient(
            settings.ig_username,
            settings.ig_password,
            settings.ig_totp_seed
        )
        self.ig_fetcher: InstagramFetcher | None = None
        self.ig_sender: InstagramSender | None = None

        # Telegram
        self.tg = TelegramBridge(settings, self.db)

        # Whitelist (None = allow all, empty set after filtering = allow all)
        self.allowed_users: set[str] | None = None
        if settings.allowed_users:
            users = {u.strip() for u in settings.allowed_users.split(",") if u.strip()}
            if users:
                self.allowed_users = users

    async def start(self):
        """Start the bridge"""
        # Login to Instagram
        self.ig_client.login()
        logger.info("Instagram: logged in as @%s", self.settings.ig_username)

        # Initialize fetcher and sender after login
        self.ig_fetcher = InstagramFetcher(
            self.ig_client.client,
            self.temp_dir,
            self.settings.download_timeout
        )
        self.ig_sender = InstagramSender(self.ig_client.client)

        # Inject dependencies into handlers
        self.tg.dp["db"] = self.db
        self.tg.dp["ig_sender"] = self.ig_sender

        # Start tasks
        await asyncio.gather(
            self._poll_instagram(),
            self._run_telegram_bot()
        )

    async def _run_telegram_bot(self):
        """Run Telegram bot polling"""
        logger.info("Starting Telegram bot...")
        await self.tg.dp.start_polling(self.tg.bot)

    async def _poll_instagram(self):
        """Poll Instagram DMs"""
        logger.info("Starting Instagram polling every %d seconds", self.settings.poll_interval)

        while True:
            try:
                await self._check_dms()
            except Exception as e:
                logger.exception("Error checking DMs: %s", e)
                await self.tg.notify_error(f"DM check failed: {e}")

            await asyncio.sleep(self.settings.poll_interval)

    async def _check_dms(self):
        """Check for new DMs and forward to Telegram"""
        if not self.ig_fetcher:
            return

        threads = self.ig_client.client.direct_threads(amount=10)
        logger.info("Found %d threads", len(threads))

        my_user_id = self.ig_client.client.user_id
        logger.info("My user_id: %s", my_user_id)

        for thread in threads:
            # Get sender from thread
            sender = "Unknown"
            if thread.users:
                sender = thread.users[0].username

            logger.info("Thread with @%s, %d messages", sender, len(thread.messages) if thread.messages else 0)

            # Whitelist check
            if self.allowed_users and sender not in self.allowed_users:
                logger.info("Skipping @%s - not in whitelist %s", sender, self.allowed_users)
                continue

            # Process recent messages (oldest first for correct order)
            messages = list(reversed(thread.messages[:5])) if thread.messages else []

            for msg in messages:
                logger.info(
                    "Message id=%s, user_id=%s, item_type=%s, text=%s",
                    msg.id, msg.user_id, msg.item_type, msg.text[:50] if msg.text else None
                )

                # Skip own messages
                if str(msg.user_id) == str(my_user_id):
                    logger.info("Skipping own message")
                    continue

                if self.db.is_seen(msg.id):
                    logger.info("Already seen, skipping")
                    continue

                self.db.mark_seen(msg.id)
                logger.info("Processing new message from @%s", sender)

                # Fetch content
                content = self.ig_fetcher.fetch_message_content(msg)
                logger.info("Fetched content: text=%s, media=%d", bool(content.text), len(content.media))

                if content.text or content.media:
                    try:
                        await self.tg.send_content(
                            sender=sender,
                            content=content,
                            ig_thread_id=thread.id,
                            ig_item_id=msg.id
                        )
                        logger.info("Forwarded message from @%s", sender)
                    except Exception as e:
                        logger.exception("Failed to send to Telegram: %s", e)
                    finally:
                        # Cleanup temp files
                        self.ig_fetcher.cleanup(content)
                else:
                    logger.info("No content to send")
