import uuid
import asyncio
import threading
from typing import TYPE_CHECKING, Dict, Any
from core.handle.textMessageHandler import TextMessageHandler
from core.handle.textMessageType import TextMessageType

if TYPE_CHECKING:
    from core.connection import ConnectionHandler

TAG = __name__


class TtsTextMessageHandler(TextMessageHandler):
    """处理前端 TTS 请求，跳过 LLM，独立建立 TTS 会话"""

    @property
    def message_type(self) -> TextMessageType:
        return TextMessageType.TTS

    async def handle(self, conn: "ConnectionHandler", msg_json: Dict[str, Any]) -> None:
        text = msg_json.get("text", "")
        if not text:
            return

        # 在独立线程中调用 to_tts()，它创建全新 WebSocket 连接,
        # 不经过 TTS 队列和 session 管理，避免连接复用问题
        def _run_tts():
            try:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
                audio_data = conn.tts.to_tts(text)
                conn.logger.bind(tag=TAG).info(f"TTS生成完成，音频数据: {len(audio_data)} bytes")
                if audio_data:
                    # tts_audio_queue 期望 (SentenceType, audio_datas, text) 三元组
                    from core.providers.tts.dto.dto import SentenceType
                    conn.tts.tts_audio_queue.put((SentenceType.FIRST, None, text))
                    for chunk in audio_data:
                        conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, chunk, None))
                    conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"TTS生成失败: {e}")

        thread = threading.Thread(target=_run_tts, daemon=True)
        thread.start()
