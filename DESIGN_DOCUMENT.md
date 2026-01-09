# Instagram ↔ Telegram Bridge

## Цель проекта

Полноценный мост между Instagram DM и Telegram: получаю весь контент (видео, фото, не ссылки) в телегу, могу отвечать и ставить реакции прямо из телеги.

**Use case:** девушка кидает рилсы/посты/сторисы в директ → я получаю само видео/фото в телеге → могу ответить или лайкнуть не заходя в Instagram.

---

## Функциональные требования

### Core: Получение контента

| Тип контента | Что приходит в Telegram |
|--------------|-------------------------|
| Пост (фото) | Само фото + caption |
| Пост (карусель) | Все фото/видео как media group |
| Рилс | Само видео + caption |
| Сторис | Фото/видео сторис |
| Текст | Текст сообщения |
| Голосовое | Аудио файл |
| Видео-сообщение (кружок) | Видео файл |
| Ссылка | Текст с URL |

### Nice to have: Ответы из Telegram → Instagram

| Действие в Telegram | Что происходит в Instagram |
|---------------------|----------------------------|
| Reply текстом | Отправка текста в тот же тред |
| Реакция эмодзи на сообщение | Реакция на оригинальное сообщение |
| `/like` reply | Лайк ❤️ на сообщение |

---

## Архитектура

```
┌─────────────────┐                      ┌──────────────────┐
│   Instagram     │ ◄── poll DMs ─────── │                  │
│   Direct API    │ ─── download ──────► │   Bot Service    │
│                 │ ◄── send/react ───── │   (Python)       │
└─────────────────┘                      └────────┬─────────┘
                                                  │
                                    ┌─────────────┴─────────────┐
                                    │                           │
                              send media               receive commands
                                    │                           │
                                    ▼                           ▼
                           ┌──────────────────┐       ┌──────────────────┐
                           │  Telegram Bot    │       │  Telegram Bot    │
                           │  (send to me)    │       │  (listen to me)  │
                           └──────────────────┘       └──────────────────┘
```

### Ключевая идея для ответов

Каждое сообщение в телеге сохраняет маппинг:
```
telegram_message_id → (instagram_thread_id, instagram_message_id)
```

Когда я делаю reply в телеге, бот находит оригинальный тред и отправляет туда.

---

## Технологический стек

| Компонент | Технология |
|-----------|------------|
| Instagram API | `instagrapi` |
| Telegram | `aiogram 3.x` (лучше для handlers и FSM) |
| Хранение маппинга | SQLite (нужны индексы для поиска) |
| Временные файлы | `tempfile` + cleanup |
| Конфиг | `pydantic-settings` |
| Контейнер | Docker |

---

## Структура проекта

```
insta-tg-bridge/
├── src/
│   ├── __init__.py
│   ├── main.py
│   ├── config.py
│   ├── instagram/
│   │   ├── __init__.py
│   │   ├── client.py        # Auth, session management
│   │   ├── fetcher.py       # Download media content
│   │   └── sender.py        # Send messages, reactions
│   ├── telegram/
│   │   ├── __init__.py
│   │   ├── bot.py           # Bot setup, handlers
│   │   └── formatter.py     # Format messages for TG
│   ├── storage/
│   │   ├── __init__.py
│   │   ├── database.py      # SQLite operations
│   │   └── models.py        # Data models
│   └── bridge/
│       ├── __init__.py
│       └── core.py          # Main bridge logic
├── data/
│   ├── session.json         # Instagram session
│   ├── bridge.db            # SQLite database
│   └── temp/                # Temporary media files
├── .env.example
├── Dockerfile
├── docker-compose.yml
└── requirements.txt
```

---

## База данных (SQLite)

```sql
-- Маппинг сообщений TG ↔ IG
CREATE TABLE message_mapping (
    id INTEGER PRIMARY KEY,
    tg_message_id INTEGER NOT NULL,
    tg_chat_id INTEGER NOT NULL,
    ig_thread_id TEXT NOT NULL,
    ig_item_id TEXT NOT NULL,
    ig_sender TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(tg_message_id, tg_chat_id)
);

CREATE INDEX idx_tg_message ON message_mapping(tg_message_id, tg_chat_id);
CREATE INDEX idx_ig_item ON message_mapping(ig_item_id);

-- Обработанные сообщения (чтобы не дублировать)
CREATE TABLE seen_messages (
    ig_item_id TEXT PRIMARY KEY,
    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- Активные треды (для быстрого доступа)
CREATE TABLE active_threads (
    ig_thread_id TEXT PRIMARY KEY,
    ig_username TEXT,
    last_message_at TIMESTAMP,
    is_muted BOOLEAN DEFAULT FALSE
);
```

---

## Конфигурация (.env)

```bash
# Instagram
IG_USERNAME=bot_account
IG_PASSWORD=password
IG_TOTP_SEED=           # optional, for 2FA

# Telegram
TG_BOT_TOKEN=123456:ABC...
TG_OWNER_ID=123456789   # твой user id

# Settings
POLL_INTERVAL=30
DOWNLOAD_TIMEOUT=60
MAX_FILE_SIZE_MB=50     # Telegram limit

# Optional filters
ALLOWED_USERS=girlfriend,friend  # comma-separated, empty = all
```

---

## Реализация

### Database (`src/storage/database.py`)

```python
import sqlite3
from pathlib import Path
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime

DB_PATH = Path("data/bridge.db")

@dataclass
class MessageMapping:
    tg_message_id: int
    tg_chat_id: int
    ig_thread_id: str
    ig_item_id: str
    ig_sender: str | None = None

class Database:
    def __init__(self):
        DB_PATH.parent.mkdir(exist_ok=True)
        self._init_db()
    
    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(DB_PATH)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def _init_db(self):
        with self._conn() as conn:
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS message_mapping (
                    id INTEGER PRIMARY KEY,
                    tg_message_id INTEGER NOT NULL,
                    tg_chat_id INTEGER NOT NULL,
                    ig_thread_id TEXT NOT NULL,
                    ig_item_id TEXT NOT NULL,
                    ig_sender TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tg_message_id, tg_chat_id)
                );
                CREATE INDEX IF NOT EXISTS idx_tg_msg 
                    ON message_mapping(tg_message_id, tg_chat_id);
                
                CREATE TABLE IF NOT EXISTS seen_messages (
                    ig_item_id TEXT PRIMARY KEY,
                    processed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                );
            """)
    
    def is_seen(self, ig_item_id: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_messages WHERE ig_item_id = ?",
                (ig_item_id,)
            ).fetchone()
            return row is not None
    
    def mark_seen(self, ig_item_id: str):
        with self._conn() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO seen_messages (ig_item_id) VALUES (?)",
                (ig_item_id,)
            )
    
    def save_mapping(self, mapping: MessageMapping):
        with self._conn() as conn:
            conn.execute("""
                INSERT OR REPLACE INTO message_mapping 
                (tg_message_id, tg_chat_id, ig_thread_id, ig_item_id, ig_sender)
                VALUES (?, ?, ?, ?, ?)
            """, (
                mapping.tg_message_id, mapping.tg_chat_id,
                mapping.ig_thread_id, mapping.ig_item_id, mapping.ig_sender
            ))
    
    def get_mapping_by_tg(self, tg_message_id: int, tg_chat_id: int) -> MessageMapping | None:
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM message_mapping 
                WHERE tg_message_id = ? AND tg_chat_id = ?
            """, (tg_message_id, tg_chat_id)).fetchone()
            if row:
                return MessageMapping(
                    tg_message_id=row["tg_message_id"],
                    tg_chat_id=row["tg_chat_id"],
                    ig_thread_id=row["ig_thread_id"],
                    ig_item_id=row["ig_item_id"],
                    ig_sender=row["ig_sender"]
                )
            return None
```

### Instagram Fetcher (`src/instagram/fetcher.py`)

```python
import tempfile
from pathlib import Path
from dataclasses import dataclass, field
from instagrapi import Client
from instagrapi.types import DirectMessage, Media

@dataclass
class MediaFile:
    path: Path
    media_type: str  # "photo", "video", "audio", "animation"
    caption: str | None = None

@dataclass 
class FetchedContent:
    text: str | None = None
    media: list[MediaFile] = field(default_factory=list)
    source_url: str | None = None  # original IG link for reference

class InstagramFetcher:
    def __init__(self, client: Client, temp_dir: Path):
        self.client = client
        self.temp_dir = temp_dir
        self.temp_dir.mkdir(exist_ok=True)
    
    def fetch_message_content(self, msg: DirectMessage) -> FetchedContent:
        """Download all media from a DM message"""
        content = FetchedContent()
        
        # Text
        if msg.text:
            content.text = msg.text
        
        # Shared post/reel
        if msg.media_share:
            self._fetch_media(msg.media_share, content)
        
        # Clip (reel shared separately)
        if msg.clip:
            self._fetch_media(msg.clip, content)
        
        # Story
        if msg.story_share and msg.story_share.media:
            self._fetch_story(msg.story_share.media, content)
        
        # Voice message
        if msg.voice_media:
            self._fetch_voice(msg, content)
        
        # Visual media (video message / disappearing)
        if msg.visual_media:
            self._fetch_visual_media(msg, content)
        
        # Direct media in message
        if msg.media:
            self._fetch_direct_media(msg.media, content)
        
        # Link
        if msg.link:
            if not content.text:
                content.text = ""
            content.text += f"\n🔗 {msg.link.link_url}"
        
        return content
    
    def _fetch_media(self, media: Media, content: FetchedContent):
        """Fetch post/reel media"""
        content.source_url = f"https://instagram.com/p/{media.code}/"
        caption = media.caption_text[:200] if media.caption_text else None
        
        if media.media_type == 1:  # Photo
            path = self._download(media.thumbnail_url, "jpg")
            content.media.append(MediaFile(path, "photo", caption))
        
        elif media.media_type == 2:  # Video
            path = self._download(media.video_url, "mp4")
            content.media.append(MediaFile(path, "video", caption))
        
        elif media.media_type == 8:  # Carousel
            for item in media.resources:
                if item.media_type == 1:
                    path = self._download(item.thumbnail_url, "jpg")
                    content.media.append(MediaFile(path, "photo"))
                elif item.media_type == 2:
                    path = self._download(item.video_url, "mp4")
                    content.media.append(MediaFile(path, "video"))
            if caption:
                content.media[0].caption = caption
    
    def _fetch_story(self, story, content: FetchedContent):
        """Fetch story media"""
        username = story.user.username if story.user else "unknown"
        caption = f"📖 Story от @{username}"
        
        if story.media_type == 1:  # Photo
            path = self._download(story.thumbnail_url, "jpg")
            content.media.append(MediaFile(path, "photo", caption))
        elif story.media_type == 2:  # Video
            path = self._download(story.video_url, "mp4")
            content.media.append(MediaFile(path, "video", caption))
    
    def _fetch_voice(self, msg: DirectMessage, content: FetchedContent):
        """Fetch voice message"""
        voice = msg.voice_media
        if voice.media and voice.media.audio:
            url = voice.media.audio.audio_src
            path = self._download(url, "mp3")
            content.media.append(MediaFile(path, "audio", "🎤 Голосовое"))
    
    def _fetch_visual_media(self, msg: DirectMessage, content: FetchedContent):
        """Fetch video message (circle)"""
        vm = msg.visual_media
        if vm.media:
            if vm.media.video_versions:
                url = vm.media.video_versions[0].url
                path = self._download(url, "mp4")
                content.media.append(MediaFile(path, "video", "🔵 Видео-сообщение"))
            elif vm.media.image_versions2:
                url = vm.media.image_versions2.candidates[0].url
                path = self._download(url, "jpg")
                content.media.append(MediaFile(path, "photo"))
    
    def _fetch_direct_media(self, media, content: FetchedContent):
        """Fetch media sent directly in DM"""
        if hasattr(media, 'video_url') and media.video_url:
            path = self._download(media.video_url, "mp4")
            content.media.append(MediaFile(path, "video"))
        elif hasattr(media, 'thumbnail_url') and media.thumbnail_url:
            path = self._download(media.thumbnail_url, "jpg")
            content.media.append(MediaFile(path, "photo"))
    
    def _download(self, url: str, ext: str) -> Path:
        """Download file to temp directory"""
        import httpx
        
        path = Path(tempfile.mktemp(suffix=f".{ext}", dir=self.temp_dir))
        
        with httpx.Client(timeout=60) as client:
            response = client.get(url)
            response.raise_for_status()
            path.write_bytes(response.content)
        
        return path
    
    def cleanup(self, content: FetchedContent):
        """Remove temporary files"""
        for media in content.media:
            try:
                media.path.unlink(missing_ok=True)
            except:
                pass
```

### Instagram Sender (`src/instagram/sender.py`)

```python
from instagrapi import Client

class InstagramSender:
    def __init__(self, client: Client):
        self.client = client
    
    def send_text(self, thread_id: str, text: str) -> bool:
        """Send text message to thread"""
        try:
            self.client.direct_send(text, thread_ids=[thread_id])
            return True
        except Exception as e:
            print(f"Failed to send text: {e}")
            return False
    
    def react_to_message(self, thread_id: str, item_id: str, emoji: str = "❤️") -> bool:
        """React to a message with emoji"""
        try:
            # instagrapi method for reactions
            self.client.direct_message_react(thread_id, item_id, emoji)
            return True
        except Exception as e:
            print(f"Failed to react: {e}")
            return False
    
    def like_message(self, thread_id: str, item_id: str) -> bool:
        """Like a message (heart reaction)"""
        return self.react_to_message(thread_id, item_id, "❤️")
```

### Telegram Bot (`src/telegram/bot.py`)

```python
import logging
from pathlib import Path
from aiogram import Bot, Dispatcher, Router, F
from aiogram.types import Message, FSInputFile, InputMediaPhoto, InputMediaVideo
from aiogram.filters import Command
from aiogram.enums import ParseMode

from ..config import Settings
from ..storage.database import Database, MessageMapping
from ..instagram.fetcher import FetchedContent

logger = logging.getLogger(__name__)
router = Router()

class TelegramBridge:
    def __init__(self, settings: Settings, db: Database):
        self.bot = Bot(token=settings.tg_bot_token)
        self.dp = Dispatcher()
        self.dp.include_router(router)
        self.owner_id = settings.tg_owner_id
        self.db = db
        
        # Will be set by bridge core
        self.on_reply_callback = None
        self.on_reaction_callback = None
    
    async def send_content(
        self, 
        sender: str, 
        content: FetchedContent,
        ig_thread_id: str,
        ig_item_id: str
    ) -> int | None:
        """Send fetched content to Telegram, return message_id"""
        
        header = f"📩 <b>@{sender}</b>"
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
                sent_message = await self.bot.send_audio(
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
        await self.bot.send_message(self.owner_id, f"⚠️ {error}")


# === Handlers для ответов ===

@router.message(F.reply_to_message)
async def handle_reply(message: Message, db: Database, ig_sender: "InstagramSender"):
    """Handle reply to forwarded message -> send to Instagram"""
    reply_to = message.reply_to_message
    mapping = db.get_mapping_by_tg(reply_to.message_id, message.chat.id)
    
    if not mapping:
        await message.reply("❌ Не могу найти оригинальное сообщение")
        return
    
    # Text reply
    if message.text:
        success = ig_sender.send_text(mapping.ig_thread_id, message.text)
        if success:
            await message.reply("✅ Отправлено")
        else:
            await message.reply("❌ Ошибка отправки")


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
        await message.reply("❌ Не могу найти оригинальное сообщение")
        return
    
    success = ig_sender.like_message(mapping.ig_thread_id, mapping.ig_item_id)
    if success:
        await message.reply("❤️")
    else:
        await message.reply("❌ Ошибка")


@router.message(Command("react"))
async def handle_react_command(message: Message, db: Database, ig_sender: "InstagramSender"):
    """Handle /react 😂 as reply -> reaction on Instagram"""
    if not message.reply_to_message:
        await message.reply("Используй /react 😂 как ответ на сообщение")
        return
    
    # Parse emoji from command
    parts = message.text.split(maxsplit=1)
    emoji = parts[1] if len(parts) > 1 else "❤️"
    
    mapping = db.get_mapping_by_tg(
        message.reply_to_message.message_id,
        message.chat.id
    )
    
    if not mapping:
        await message.reply("❌ Не могу найти оригинальное сообщение")
        return
    
    success = ig_sender.react_to_message(mapping.ig_thread_id, mapping.ig_item_id, emoji)
    if success:
        await message.reply(emoji)
    else:
        await message.reply("❌ Ошибка")


@router.message(Command("status"))
async def handle_status(message: Message):
    """Bot status"""
    await message.reply("✅ Бот работает")
```

### Bridge Core (`src/bridge/core.py`)

```python
import asyncio
import logging
from pathlib import Path

from ..config import Settings
from ..storage.database import Database
from ..instagram.client import InstagramClient
from ..instagram.fetcher import InstagramFetcher, FetchedContent
from ..instagram.sender import InstagramSender
from ..telegram.bot import TelegramBridge

logger = logging.getLogger(__name__)

class Bridge:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.db = Database()
        self.temp_dir = Path("data/temp")
        
        # Instagram
        self.ig_client = InstagramClient(
            settings.ig_username,
            settings.ig_password,
            settings.ig_totp_seed
        )
        self.ig_fetcher = InstagramFetcher(self.ig_client.client, self.temp_dir)
        self.ig_sender = InstagramSender(self.ig_client.client)
        
        # Telegram
        self.tg = TelegramBridge(settings, self.db)
        
        # Whitelist
        self.allowed_users = None
        if settings.allowed_users:
            self.allowed_users = set(settings.allowed_users.split(","))
    
    async def start(self):
        """Start the bridge"""
        # Login to Instagram
        self.ig_client.login()
        logger.info("Instagram: logged in as @%s", self.settings.ig_username)
        
        # Start tasks
        await asyncio.gather(
            self._poll_instagram(),
            self._run_telegram_bot()
        )
    
    async def _run_telegram_bot(self):
        """Run Telegram bot polling"""
        # Inject dependencies into handlers
        self.tg.dp["db"] = self.db
        self.tg.dp["ig_sender"] = self.ig_sender
        
        await self.tg.dp.start_polling(self.tg.bot)
    
    async def _poll_instagram(self):
        """Poll Instagram DMs"""
        logger.info("Starting Instagram polling every %d seconds", self.settings.poll_interval)
        
        while True:
            try:
                await self._check_dms()
            except Exception as e:
                logger.error("Error checking DMs: %s", e)
                await self.tg.notify_error(f"DM check failed: {e}")
            
            await asyncio.sleep(self.settings.poll_interval)
    
    async def _check_dms(self):
        """Check for new DMs and forward to Telegram"""
        threads = self.ig_client.client.direct_threads(amount=10)
        
        for thread in threads:
            sender = thread.users[0].username if thread.users else "Unknown"
            
            # Whitelist check
            if self.allowed_users and sender not in self.allowed_users:
                continue
            
            for msg in thread.messages[:5]:
                if self.db.is_seen(msg.id):
                    continue
                
                self.db.mark_seen(msg.id)
                
                # Fetch content
                content = self.ig_fetcher.fetch_message_content(msg)
                
                if content.text or content.media:
                    try:
                        await self.tg.send_content(
                            sender=sender,
                            content=content,
                            ig_thread_id=thread.id,
                            ig_item_id=msg.id
                        )
                        logger.info("Forwarded message from @%s", sender)
                    finally:
                        # Cleanup temp files
                        self.ig_fetcher.cleanup(content)
```

### Main (`src/main.py`)

```python
import asyncio
import logging
from .config import Settings
from .bridge.core import Bridge

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

async def main():
    settings = Settings()
    bridge = Bridge(settings)
    await bridge.start()

if __name__ == "__main__":
    asyncio.run(main())
```

### Config (`src/config.py`)

```python
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Instagram
    ig_username: str
    ig_password: str
    ig_totp_seed: str | None = None
    
    # Telegram
    tg_bot_token: str
    tg_owner_id: int
    
    # Behavior
    poll_interval: int = 30
    download_timeout: int = 60
    max_file_size_mb: int = 50
    
    # Filters
    allowed_users: str | None = None  # comma-separated
    
    class Config:
        env_file = ".env"
```

---

## Docker

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

# Dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ src/
RUN mkdir -p data/temp

CMD ["python", "-m", "src.main"]
```

### docker-compose.yml

```yaml
version: "3.8"

services:
  bridge:
    build: .
    restart: unless-stopped
    env_file:
      - .env
    volumes:
      - ./data:/app/data
    logging:
      driver: "json-file"
      options:
        max-size: "10m"
        max-file: "3"
```

### requirements.txt

```
instagrapi>=2.0.0
aiogram>=3.0.0
pydantic-settings>=2.0.0
httpx>=0.25.0
aiosqlite>=0.19.0
```

---

## Использование

### Команды в Telegram

| Команда | Действие |
|---------|----------|
| (просто reply текстом) | Отправить текст в Instagram тред |
| `/like` (как reply) | Лайкнуть сообщение в Instagram |
| `/react 😂` (как reply) | Поставить реакцию на сообщение |
| `/status` | Проверить что бот работает |

### Пример взаимодействия

```
[Telegram]
📩 @girlfriend
[видео рилса]
Смотри какой котик 😍

> /like
❤️

> (reply) хахаха офигенный
✅ Отправлено
```

---

## Ограничения и нюансы

| Проблема | Решение/Workaround |
|----------|-------------------|
| Telegram лимит 50MB на файл | Пропускаем слишком большие файлы с уведомлением |
| Instagram rate limits | Задержки между запросами, не чаще 30 сек polling |
| Сторисы исчезают | Скачиваем сразу, но не можем достать старые |
| 2FA на Instagram | Использовать TOTP seed в конфиге |
| Бан аккаунта | Отдельный аккаунт, прогрев, не спамить |

---

## Checklist для Claude Code

### Core (must have)
- [ ] Структура проекта
- [ ] `src/config.py` — Settings
- [ ] `src/storage/database.py` — SQLite
- [ ] `src/instagram/client.py` — Auth + session
- [ ] `src/instagram/fetcher.py` — Download media
- [ ] `src/telegram/bot.py` — Send to Telegram
- [ ] `src/bridge/core.py` — Main loop
- [ ] `src/main.py` — Entry point
- [ ] Dockerfile + docker-compose.yml
- [ ] .env.example

### Nice to have (v2)
- [ ] `src/instagram/sender.py` — Send messages
- [ ] Reply handler в telegram/bot.py
- [ ] `/like` command
- [ ] `/react` command
- [ ] Message mapping в БД

### Polish
- [ ] Graceful shutdown
- [ ] Retry logic для Instagram
- [ ] `/mute @user` command
- [ ] Error notifications в телегу
- [ ] README.md
