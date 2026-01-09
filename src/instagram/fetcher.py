import tempfile
import logging
from pathlib import Path
from dataclasses import dataclass, field

import httpx
from instagrapi import Client
from instagrapi.types import DirectMessage, Media

logger = logging.getLogger(__name__)


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
    def __init__(self, client: Client, temp_dir: Path, timeout: int = 60):
        self.client = client
        self.temp_dir = temp_dir
        self.timeout = timeout
        self.temp_dir.mkdir(exist_ok=True)

    def fetch_message_content(self, msg: DirectMessage) -> FetchedContent:
        """Download all media from a DM message"""
        content = FetchedContent()

        # Debug: log all message attributes
        logger.info("Message item_type: %s", getattr(msg, 'item_type', None))
        attrs = {k: v for k, v in msg.__dict__.items() if v is not None and v != [] and v != {}}
        logger.info("Message non-empty attrs: %s", list(attrs.keys()))

        # Text
        if getattr(msg, 'text', None):
            content.text = msg.text

        # Shared post/reel
        media_share = getattr(msg, 'media_share', None)
        if media_share:
            self._fetch_media(media_share, content)

        # Clip (reel shared separately) - clip itself is the media object
        clip = getattr(msg, 'clip', None)
        if clip:
            logger.info("Clip: media_type=%s, video_url=%s",
                        getattr(clip, 'media_type', None),
                        bool(getattr(clip, 'video_url', None)))
            self._fetch_media(clip, content)

        # Story
        story_share = getattr(msg, 'story_share', None)
        if story_share and getattr(story_share, 'media', None):
            self._fetch_story(story_share.media, content)

        # Voice message
        voice_media = getattr(msg, 'voice_media', None)
        if voice_media:
            self._fetch_voice_safe(voice_media, content)

        # Visual media (video message / disappearing)
        visual_media = getattr(msg, 'visual_media', None)
        if visual_media:
            self._fetch_visual_media_safe(visual_media, content)

        # Direct media in message
        media = getattr(msg, 'media', None)
        if media:
            self._fetch_direct_media(media, content)

        # Link
        link = getattr(msg, 'link', None)
        if link:
            link_url = getattr(link, 'link_url', None)
            if link_url:
                if not content.text:
                    content.text = ""
                content.text += f"\n{link_url}"

        # Reel share (xma_media_share)
        xma = getattr(msg, 'xma_share', None)
        if xma:
            self._fetch_xma(xma, content)

        return content

    def _fetch_media(self, media: Media, content: FetchedContent):
        """Fetch post/reel media"""
        content.source_url = f"https://instagram.com/p/{media.code}/"
        caption = media.caption_text[:200] if media.caption_text else None

        if media.media_type == 1:  # Photo
            url = str(media.thumbnail_url) if media.thumbnail_url else None
            if url:
                path = self._download(url, "jpg")
                if path:
                    content.media.append(MediaFile(path, "photo", caption))

        elif media.media_type == 2:  # Video
            url = str(media.video_url) if media.video_url else None
            if url:
                path = self._download(url, "mp4")
                if path:
                    content.media.append(MediaFile(path, "video", caption))

        elif media.media_type == 8:  # Carousel
            for i, item in enumerate(media.resources or []):
                item_caption = caption if i == 0 else None
                if item.media_type == 1:
                    url = str(item.thumbnail_url) if item.thumbnail_url else None
                    if url:
                        path = self._download(url, "jpg")
                        if path:
                            content.media.append(MediaFile(path, "photo", item_caption))
                elif item.media_type == 2:
                    url = str(item.video_url) if item.video_url else None
                    if url:
                        path = self._download(url, "mp4")
                        if path:
                            content.media.append(MediaFile(path, "video", item_caption))

    def _fetch_story(self, story, content: FetchedContent):
        """Fetch story media"""
        username = story.user.username if story.user else "unknown"
        caption = f"Story от @{username}"

        if story.media_type == 1:  # Photo
            url = str(story.thumbnail_url) if story.thumbnail_url else None
            if url:
                path = self._download(url, "jpg")
                if path:
                    content.media.append(MediaFile(path, "photo", caption))
        elif story.media_type == 2:  # Video
            url = str(story.video_url) if story.video_url else None
            if url:
                path = self._download(url, "mp4")
                if path:
                    content.media.append(MediaFile(path, "video", caption))

    def _fetch_voice_safe(self, voice, content: FetchedContent):
        """Fetch voice message"""
        try:
            media = getattr(voice, 'media', None)
            if media:
                audio = getattr(media, 'audio', None)
                if audio:
                    url = getattr(audio, 'audio_src', None)
                    if url:
                        path = self._download(str(url), "mp3")
                        if path:
                            content.media.append(MediaFile(path, "audio", "Голосовое"))
        except Exception as e:
            logger.warning("Failed to fetch voice: %s", e)

    def _fetch_visual_media_safe(self, vm, content: FetchedContent):
        """Fetch video message (circle)"""
        try:
            media = getattr(vm, 'media', None)
            if not media:
                return

            video_versions = getattr(media, 'video_versions', None)
            if video_versions and len(video_versions) > 0:
                url = getattr(video_versions[0], 'url', None)
                if url:
                    path = self._download(str(url), "mp4")
                    if path:
                        content.media.append(MediaFile(path, "video", "Видео-сообщение"))
                return

            image_versions2 = getattr(media, 'image_versions2', None)
            if image_versions2:
                candidates = getattr(image_versions2, 'candidates', None)
                if candidates and len(candidates) > 0:
                    url = getattr(candidates[0], 'url', None)
                    if url:
                        path = self._download(str(url), "jpg")
                        if path:
                            content.media.append(MediaFile(path, "photo"))
        except Exception as e:
            logger.warning("Failed to fetch visual media: %s", e)

    def _fetch_xma(self, xma, content: FetchedContent):
        """Fetch XMA shared content (reels, etc)"""
        try:
            # XMA can contain video/image preview
            video_url = getattr(xma, 'video_url', None)
            if video_url:
                path = self._download(str(video_url), "mp4")
                if path:
                    content.media.append(MediaFile(path, "video"))
                return

            preview_url = getattr(xma, 'preview_url', None)
            if preview_url:
                path = self._download(str(preview_url), "jpg")
                if path:
                    content.media.append(MediaFile(path, "photo"))
        except Exception as e:
            logger.warning("Failed to fetch xma: %s", e)

    def _fetch_direct_media(self, media, content: FetchedContent):
        """Fetch media sent directly in DM"""
        if hasattr(media, 'video_url') and media.video_url:
            path = self._download(str(media.video_url), "mp4")
            if path:
                content.media.append(MediaFile(path, "video"))
        elif hasattr(media, 'thumbnail_url') and media.thumbnail_url:
            path = self._download(str(media.thumbnail_url), "jpg")
            if path:
                content.media.append(MediaFile(path, "photo"))

    def _download(self, url: str, ext: str) -> Path | None:
        """Download file to temp directory"""
        try:
            path = Path(tempfile.mktemp(suffix=f".{ext}", dir=self.temp_dir))

            with httpx.Client(timeout=self.timeout) as client:
                response = client.get(url)
                response.raise_for_status()
                path.write_bytes(response.content)

            return path
        except Exception as e:
            logger.error("Failed to download %s: %s", url[:50], e)
            return None

    def cleanup(self, content: FetchedContent):
        """Remove temporary files"""
        for media in content.media:
            try:
                media.path.unlink(missing_ok=True)
            except Exception:
                pass
