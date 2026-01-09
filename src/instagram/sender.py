import logging

from instagrapi import Client

logger = logging.getLogger(__name__)


class InstagramSender:
    def __init__(self, client: Client):
        self.client = client

    def send_text(self, thread_id: str, text: str) -> bool:
        """Send text message to thread"""
        try:
            self.client.direct_send(text, thread_ids=[thread_id])
            return True
        except Exception as e:
            logger.error("Failed to send text: %s", e)
            return False

    def react_to_message(self, thread_id: str, item_id: str, emoji: str = "❤️") -> bool:
        """React to a message with emoji"""
        try:
            self.client.direct_send_reaction(thread_id, item_id, emoji)
            return True
        except Exception as e:
            logger.error("Failed to react: %s", e)
            return False

    def like_message(self, thread_id: str, item_id: str) -> bool:
        """Like a message (heart reaction)"""
        return self.react_to_message(thread_id, item_id, "❤️")
