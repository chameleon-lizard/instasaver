import logging
from typing import TYPE_CHECKING

from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.filters import Command
from aiogram.enums import ParseMode

from ..config import Settings
from ..storage.database import Database, MessageMapping
from ..instagram.fetcher import FetchedContent

if TYPE_CHECKING:
    from ..instagram.sender import InstagramSender

logger = logging.getLogger(__name__)
router = Router()


class TelegramBridge:
    def __init__(self, settings: Settings, db: Database):
        self.bot = Bot(token=settings.tg_bot_token)
        self.dp = Dispatcher()
        self.dp.include_router(router)
        self.owner_id = settings.tg_owner_id
        self.db = db

    async def send_content(
        self,
        sender: str,
        content: FetchedContent,
        ig_thread_id: str,
        ig_item_id: str
    ) -> int | None:
        """Send fetched content to Telegram, return message_id"""

        header = f"<b>@{sender}</b>"
        if content.source_url:
            header += f"\n<a href='{content.source_url}'>Источник</a>"

        sent_message = None

        # Multiple media -> media group
        if len(content.media) > 1:
            media_group = []
            for i, m in enumerate(content.media):
                file = FSInputFile(m.path)
                caption = header if i == 0 else None

                if m.media_type == "photo":
                    media_group.append(InputMediaPhoto(
                        media=file,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    ))
                else:
                    media_group.append(InputMediaVideo(
                        media=file,
                        caption=caption,
                        parse_mode=ParseMode.HTML
                    ))

            messages = await self.bot.send_media_group(self.owner_id, media_group)
            sent_message = messages[0]

        # Single media
        elif content.media:
            m = content.media[0]
            file = FSInputFile(m.path)
            caption = header
            if m.caption:
                caption += f"\n\n{m.caption}"

            if m.media_type == "photo":
                sent_message = await self.bot.send_photo(
                    self.owner_id, file, caption=caption, parse_mode=ParseMode.HTML
                )
            elif m.media_type == "video":
                sent_message = await self.bot.send_video(
                    self.owner_id, file, caption=caption, parse_mode=ParseMode.HTML
                )
            elif m.media_type == "audio":
                sent_message = await self.bot.send_voice(
                    self.owner_id, file, caption=caption, parse_mode=ParseMode.HTML
                )

        # Text only
        elif content.text:
            text = f"{header}\n\n{content.text}"
            sent_message = await self.bot.send_message(
                self.owner_id, text, parse_mode=ParseMode.HTML
            )

        # Save mapping
        if sent_message:
            mapping = MessageMapping(
                tg_message_id=sent_message.message_id,
                tg_chat_id=self.owner_id,
                ig_thread_id=ig_thread_id,
                ig_item_id=ig_item_id,
                ig_sender=sender
            )
            self.db.save_mapping(mapping)
            return sent_message.message_id

        return None

    async def notify_error(self, error: str):
        """Send error notification"""
        await self.bot.send_message(self.owner_id, f"Error: {error}")


# === Handlers ===

@router.message(F.reply_to_message, ~Command("like"), ~Command("react"))
async def handle_reply(message: Message, db: Database, ig_sender: "InstagramSender"):
    """Handle reply to forwarded message -> send to Instagram"""
    if not message.reply_to_message:
        return

    reply_to = message.reply_to_message
    mapping = db.get_mapping_by_tg(reply_to.message_id, message.chat.id)

    if not mapping:
        await message.reply("Не могу найти оригинальное сообщение")
        return

    # Text reply
    if message.text:
        success = ig_sender.send_text(mapping.ig_thread_id, message.text)
        if success:
            await message.reply("Отправлено")
        else:
            await message.reply("Ошибка отправки")


@router.message(Command("like"))
async def handle_like_command(message: Message, db: Database, ig_sender: "InstagramSender"):
    """Handle /like command as reply -> like on Instagram"""
    if not message.reply_to_message:
        await message.reply("Используй /like как ответ на сообщение")
        return

    mapping = db.get_mapping_by_tg(
        message.reply_to_message.message_id,
        message.chat.id
    )

    if not mapping:
        await message.reply("Не могу найти оригинальное сообщение")
        return

    success = ig_sender.like_message(mapping.ig_thread_id, mapping.ig_item_id)
    if success:
        await message.reply("❤️")
    else:
        await message.reply("Ошибка")


@router.message(Command("react"))
async def handle_react_command(message: Message, db: Database, ig_sender: "InstagramSender"):
    """Handle /react emoji as reply -> reaction on Instagram"""
    if not message.reply_to_message:
        await message.reply("Используй /react emoji как ответ на сообщение")
        return

    # Parse emoji from command
    parts = (message.text or "").split(maxsplit=1)
    emoji = parts[1] if len(parts) > 1 else "❤️"

    mapping = db.get_mapping_by_tg(
        message.reply_to_message.message_id,
        message.chat.id
    )

    if not mapping:
        await message.reply("Не могу найти оригинальное сообщение")
        return

    success = ig_sender.react_to_message(mapping.ig_thread_id, mapping.ig_item_id, emoji)
    if success:
        await message.reply(emoji)
    else:
        await message.reply("Ошибка")


@router.message(Command("status"))
async def handle_status(message: Message):
    """Bot status"""
    await message.reply("Бот работает")
