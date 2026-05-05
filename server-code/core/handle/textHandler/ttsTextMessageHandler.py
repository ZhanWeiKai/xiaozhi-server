import asyncio
import hashlib
import threading
from typing import TYPE_CHECKING, Dict, Any
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType
from core.providers.tts.dto.dto import SentenceType
from core.utils import textUtils

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__


class TtsTextMessageHandler(TextMessageHandler):
    """Handle frontend TTS request, skip LLM, use own cache"""

    def __init__(self):
        self._audio_cache = {}  # MD5(text) -> [chunk_bytes, ...]

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.TTS

    async def handle(self, conn: "ConnectionHandler", msg_json: Dict[str, Any]) -> None:
        text = msg_json.get("text", "")
        if not text:
            return

        text = textUtils.get_string_no_punctuation_or_emoji(text)
        if not text:
            return

        cache_key = hashlib.md5(text.encode()).hexdigest()

        # Cache hit: play from cache instantly
        cached_chunks = self._audio_cache.get(cache_key)
        if cached_chunks:
            conn.logger.bind(tag=TAG).info(f"Use cached TTS audio, {len(cached_chunks)} chunks")
            conn.tts.tts_audio_queue.put((SentenceType.FIRST, None, text))
            for chunk in cached_chunks:
                conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, chunk, None))
            conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
            return

        # Cache miss: call to_tts() in a separate thread, then cache result
        def _run_tts():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                audio_data = conn.tts.to_tts(text)
                conn.logger.bind(tag=TAG).info(f"TTS generated, audio: {len(audio_data) if audio_data else 0} bytes")
                if audio_data:
                    self._audio_cache[cache_key] = list(audio_data)
                    conn.logger.bind(tag=TAG).info(f"TTS audio cached, key: {cache_key}")
                    conn.tts.tts_audio_queue.put((SentenceType.FIRST, None, text))
                    for chunk in audio_data:
                        conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, chunk, None))
                    conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"TTS failed: {e}")

        thread = threading.Thread(target=_run_tts, daemon=True)
        thread.start()
