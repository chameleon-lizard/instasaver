import logging
from pathlib import Path

from instagrapi import Client
from instagrapi.exceptions import LoginRequired

logger = logging.getLogger(__name__)

SESSION_PATH = Path("data/session.json")


class InstagramClient:
    def __init__(self, username: str, password: str, totp_seed: str | None = None):
        self.username = username
        self.password = password
        self.totp_seed = totp_seed
        self.client = Client()
        self.client.delay_range = [1, 3]

    def login(self) -> bool:
        """Login to Instagram, using cached session if available"""
        SESSION_PATH.parent.mkdir(exist_ok=True)

        # Try to load existing session
        if SESSION_PATH.exists():
            logger.info("Loading existing session...")
            try:
                self.client.load_settings(SESSION_PATH)
                self.client.login(self.username, self.password)
                self._verify_session()
                logger.info("Session loaded successfully")
                return True
            except LoginRequired:
                logger.warning("Session expired, re-logging in...")
            except Exception as e:
                logger.warning("Failed to load session: %s", e)

        # Fresh login
        logger.info("Performing fresh login...")
        try:
            if self.totp_seed:
                self.client.totp_seed = self.totp_seed
            self.client.login(self.username, self.password)
            self.client.dump_settings(SESSION_PATH)
            logger.info("Logged in successfully")
            return True
        except Exception as e:
            logger.error("Login failed: %s", e)
            raise

    def _verify_session(self):
        """Verify the session is still valid"""
        try:
            self.client.get_timeline_feed()
        except LoginRequired:
            raise
        except Exception:
            pass

    def relogin(self):
        """Force re-login"""
        logger.info("Re-logging in...")
        if SESSION_PATH.exists():
            SESSION_PATH.unlink()
        self.client = Client()
        self.client.delay_range = [1, 3]
        self.login()
