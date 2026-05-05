# WebUI 喇叭按钮播放 AI 消息语音 - 实现计划

## Context

用户想在 WebUI 每条 AI 消息文本下方添加喇叭按钮，点击后把该条 AI 消息的完整文本通过 WebSocket 发给后端做 TTS，音频实时传回前端播放。复用现有 WebSocket 通道和 TTS 流水线，改动最小。

---

## 当前方案：to_tts() + handler 自身缓存

### 方案演进

1. ~~`tts_text_queue` 复用 WebSocket 方案（不可用）~~：往现有 TTS 队列放 FIRST+MIDDLE+LAST，复用 TTS session 的 WebSocket 连接。因 `_ensure_connection` 的 60 秒连接复用逻辑会复用 DashScope 已关闭的过期连接，导致 1007 错误，不可靠。
2. ~~`base.py` 分段缓存方案（已废弃）~~：在 `base.py` 的 `_audio_play_priority_thread` 中按 FIRST→MIDDLE* 分段缓存音频，handler 查缓存秒播。问题：前端 `llm` 事件和 `tts sentence_start` 事件都会 appendMessage，用户点击的是 `llm` 完整文本的喇叭按钮，完整文本的 MD5 和分段缓存 key 对不上，缓存永远命中不了。
3. **当前方案：to_tts() + handler 自身缓存**：handler 内部维护 `_audio_cache` dict，key = MD5(完整文本)。首次点击调 `to_tts()` 生成并缓存，后续相同文本秒播。

### 为什么不能复用 WebSocket

`alibl_stream.py` 的 `_ensure_connection` 有 60 秒连接复用逻辑。正常对话建立过 WebSocket 后，DashScope 服务端可能已关闭该连接（客户端不知道），但 `_ensure_connection` 检查 `self.ws` 非空且时间 < 60s 就直接返回过期连接，导致 1007 错误。因此必须用 `to_tts()` 创建全新连接。

### 为什么去掉 base.py 分段缓存

前端喇叭按钮发送的是**完整 AI 回复文本**（`llm` 事件的完整文本），但 `base.py` 缓存是**按分段**存储的（key = MD5(分段文本)），完整文本 MD5 匹配不到分段缓存，永远走兜底。分段缓存增加 `base.py` 复杂度却无法命中，需要删除。

### 缓存机制

| 项目 | 说明 |
|------|------|
| 缓存位置 | `ttsTextMessageHandler` 实例的 `_audio_cache` dict |
| 缓存 key | `MD5(text)`，text 经 `get_string_no_punctuation_or_emoji()` 处理 |
| 缓存 value | `[chunk_bytes, ...]`，`to_tts()` 返回的音频 chunks |
| 写入时机 | 首次点击喇叭，`to_tts()` 生成完成后存入 |
| 读取时机 | 后续点击相同文本，直接从缓存取出放入 `tts_audio_queue`，秒播 |

---

## 调用逻辑流程

```
用户点击某条 AI 消息下方的喇叭按钮
  |
  v
ChatContainer.vue: playMessage(msg.content)
  |
  v
emit("playTts", text) -> App.vue: playTtsMessage(text)
  |
  v
WebSocket 发送: {"type": "tts", "text": "该条AI消息的完整文本"}
  |
  v
后端 TtsTextMessageHandler.handle():
  text = get_string_no_punctuation_or_emoji(msg_json["text"])
  cache_key = MD5(text)
  |
  +-- handler._audio_cache 有 cache_key？
  |   +-- 有 -> 从缓存取音频 -> 放入 tts_audio_queue -> 秒播
  |   +-- 无 -> 新线程调 to_tts(text) 生成
  |            生成完成后存入 _audio_cache
  |            放入 tts_audio_queue -> 播放
  |
  v
audio_play_priority_thread 消费队列 -> WebSocket 回传前端
  |
  v
前端 AudioManager: 接收音频 -> 入队 -> 播放
```

---

## 改动清单

### 前端（`xiaozhi-webui-4-9/xiaozhi-webui/`）

#### 1. `src/components/ChatContainer.vue` — 改动

**改动**：在每条 AI 消息气泡下方添加喇叭按钮

**模板**：在 `message-time` div 后添加喇叭按钮

```html
<button
  v-if="msg.type === 'ai'"
  class="play-tts-btn"
  :disabled="disabled"
  @click="playMessage(msg.content)"
>
  <svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="currentColor">
    <path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02z"/>
  </svg>
</button>
```

**脚本**：新增 `disabled` prop、`playTts` emit、`playMessage` 方法

```typescript
const props = defineProps<{ disabled?: boolean }>();
const emit = defineEmits<{ (e: "playTts", text: string): void }>();

const playMessage = (text: string) => {
  if (props.disabled) return;
  emit("playTts", text);
};
```

**样式**：relative 定位，紧跟在文本下方

```less
.play-tts-btn {
  margin-top: 0.15rem;
  width: 1.5rem;
  height: 1.5rem;
  padding: 0.15rem;
  background-color: #f59e0b;
  border: none;
  border-radius: 50%;
  color: white;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  opacity: 0.6;
  transition: opacity 0.2s;

  &:hover { opacity: 1; }
  &:disabled { opacity: 0.3; cursor: not-allowed; }
  svg { width: 0.8rem; height: 0.8rem; }
}
```

#### 2. `src/App.vue` — 改动

- 新增 `playTtsMessage` 方法，通过 WebSocket 发送 `{"type": "tts", "text}`
- ChatContainer 绑定 `@play-tts="playTtsMessage"` 和 `:disabled="isAiSpeaking"`

#### 3. `src/components/InputField.vue` — 无改动

---

### 后端（`server-code/`，挂载到容器）

#### 4. `core/handle/textMessageType.py` — 改动

枚举新增 `TTS = "tts"`

#### 5. `core/handle/textHandler/ttsTextMessageHandler.py` — 更新

**改动**：handler 自身加 `_audio_cache`，首次 `to_tts()` 生成后缓存，后续秒播

```python
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
```

**对比旧版本**：
- 新增 `__init__` 中的 `_audio_cache`
- 新增缓存查找逻辑（`Use cached TTS audio`）
- `to_tts()` 生成完成后写入缓存（`TTS audio cached`）
- `to_tts()` 兜底逻辑不变

#### 6. `core/providers/tts/base.py` — 删除分段缓存代码

**不改其他逻辑**，只删除之前添加的 3 处分段缓存代码：

**删除 1**：`__init__` 中的两行（约第 74-75 行）
```python
# 删除
self.audio_cache = {}
self._cache_current = {}
```

**删除 2**：`_audio_play_priority_thread` 中 `client_abort` 分支里的一行
```python
# 删除
self._cache_current = {}
```

**删除 3**：`_audio_play_priority_thread` 中整段缓存逻辑（约 20 行）
```python
# 删除从 "# ===== 按分段缓存逻辑 =====" 到 "# ===== 缓存逻辑结束 =====" 的整段
```

**不影响现有功能**：这些代码纯粹是附加的缓存写入，不影响音频播放、上报、打断等核心流程。

#### 7. `core/handle/textMessageHandlerRegistry.py` — 改动

注册 `TtsTextMessageHandler()`

#### 8. `docker-compose.yml` — 改动

新增 4 个文件挂载：

```yaml
volumes:
  - ./core/handle/textHandler/ttsTextMessageHandler.py:/opt/xiaozhi-esp32-server/core/handle/textHandler/ttsTextMessageHandler.py
  - ./core/handle/textMessageType.py:/opt/xiaozhi-esp32-server/core/handle/textMessageType.py
  - ./core/handle/textMessageHandlerRegistry.py:/opt/xiaozhi-esp32-server/core/handle/textMessageHandlerRegistry.py
  - ./core/providers/tts/base.py:/opt/xiaozhi-esp32-server/core/providers/tts/base.py
```

---

## 遇到的问题与解决

### 问题1：tts_audio_queue 格式不匹配

**现象**：`not enough values to unpack (expected 3, got 1)`
**原因**：队列期望三元组 `(SentenceType, audio, text)`，代码放入了单元素元组
**解决**：改为放入三元组 `(FIRST, None, text)` / `(MIDDLE, chunk, None)` / `(LAST, [], None)`

### 问题2：logger 导入路径错误

**现象**：`ImportError: cannot import name 'logger' from 'core.handle'`
**解决**：改用 `conn.logger.bind(tag=TAG)`

### 问题3：Python 注释中文逗号

**现象**：`SyntaxError: invalid character ',' (U+FF0C)`
**解决**：替换为英文逗号

### 问题4：base.py 分段缓存无法命中

**现象**：handler 永远走兜底，日志显示 "TTS生成完成（兜底）"
**原因**：前端发送完整文本 MD5 匹配不到 base.py 的分段缓存 key
**解决**：
1. 删除 base.py 的分段缓存代码
2. handler 自身维护 `_audio_cache`，key = MD5(完整文本)，首次生成后缓存

---

## 验证方式

1. `docker logs xiaozhi-esp32-server --tail 50 | grep 'TTS'` 确认收到 tts 消息
2. 首次点击喇叭：日志 "TTS generated" + "TTS audio cached"，有声音播放（等待 3-5 秒）
3. 再次点击同一文本：日志 "Use cached TTS audio"，秒播
4. AI 说话时喇叭按钮 disabled
5. 回退：删除 docker-compose 新增挂载 → `--force-recreate` → 原有功能正常
