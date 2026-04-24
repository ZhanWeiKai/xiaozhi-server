# WebUI 喇叭按钮播放 AI 消息语音 - 实现计划

## Context

用户想在 WebUI 文本输入框区域添加喇叭按钮，点击后把 AI 最后一条回复的文本通过 WebSocket 发给后端做 TTS，音频实时传回前端播放。复用现有 WebSocket 通道和 TTS 流水线，改动最小。

---

## 调用逻辑流程

```
用户点击喇叭按钮
  │
  ▼
App.vue: 取最后一条 AI 消息文本
  │
  ▼
WebSocket 发送: {"type": "tts", "text": "AI的回复内容"}
  │
  ▼
后端 connection.py: _route_message() 收到文本消息
  │
  ▼
textHandle.py: handleTextMessage() → TextMessageProcessor.process_message()
  │
  ▼
解析 JSON，type="tts" → 匹配 TtsTextMessageHandler
  │
  ▼
TtsTextMessageHandler.handle():
  取出 text 字段
  在独立线程调用 conn.tts.to_tts(text)
  to_tts() 创建全新 WebSocket 连接到 DashScope，不经过 TTS 队列
  │
  ▼
音频数据放入 tts_audio_queue（FIRST + MIDDLE + LAST 三元组格式）
  │
  ▼
audio_play_priority_thread 消费队列 → 通过 WebSocket 回传前端
  │
  ▼
前端 AudioManager.ts: 接收音频 → 入队 → 播放
```

---

## 改动清单

### 前端（`xiaozhi-webui-4-9/xiaozhi-webui/`）

#### 1. `src/components/InputField.vue` — 改动

**改动**：在发送按钮和电话按钮之间新增喇叭按钮

```html
<!-- 现有 -->
<button id="send-message" @click="handleSendButtonClick">...</button>
<button id="phone-call" @click="emit('phoneCallButtonClicked')">...</button>

<!-- 新增 -->
<button id="play-tts" @click="emit('playTtsButtonClicked')">
  <svg>喇叭图标</svg>
</button>
```

- 新增 emit: `(e: "playTtsButtonClicked"): void`
- 新增 prop: `disabled: boolean`（默认 false），AI 说话时 `disabled=true`，按钮置灰不可点击
- 样式：橙色 `#f59e0b`，和现有按钮 `3rem x 3rem` 一致

#### 2. `src/App.vue` — 改动

**改动**：监听喇叭按钮事件，发送 TTS 请求

- import ChatContainer 的 messages ref（需要从 ChatContainer expose）
- 新增 `playLastAiMessage` 方法：
  - 过滤 messages 取最后一条 `type === 'ai'` 的消息
  - 通过 `wsService.sendTextMessage()` 发送 `{"type":"tts","text":"..."}`
- InputField 组件绑定 `@play-tts-button-clicked="playLastAiMessage"`，`:disabled="isAiSpeaking"`
- 新增 `isAiSpeaking` 计算属性，基于 `chatStateManager.currentState` 判断是否为 `AI_SPEAKING`

#### 3. `src/components/ChatContainer.vue` — 改动

**改动**：expose messages 数组给父组件

```typescript
defineExpose({
  appendMessage,
  messages,  // 新增 expose
});
```

---

### 后端（`server-code/`，挂载到容器）

#### 4. `core/handle/textMessageType.py` — 改动

**改动**：枚举新增 TTS 类型

```python
class TextMessageType(Enum):
    HELLO = "hello"
    ABORT = "abort"
    LISTEN = "listen"
    IOT = "iot"
    MCP = "mcp"
    SERVER = "server"
    PING = "ping"
    TTS = "tts"          # 新增
```

#### 5. `core/handle/textHandler/ttsTextMessageHandler.py` — 新增

**新建**文件，处理 TTS-only 请求（最终版本）：

```python
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
                    from core.providers.tts.dto.dto import SentenceType
                    conn.tts.tts_audio_queue.put((SentenceType.FIRST, None, text))
                    for chunk in audio_data:
                        conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, chunk, None))
                    conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))
            except Exception as e:
                conn.logger.bind(tag=TAG).error(f"TTS生成失败: {e}")

        thread = threading.Thread(target=_run_tts, daemon=True)
        thread.start()
```

**关键设计**：
- 使用 `to_tts()` 而非 `tts_one_sentence()` 或手动操作 `tts_text_queue`，因为 `to_tts()` 创建全新 WebSocket 连接到 DashScope，完全独立于 TTS 队列和 session 管理，不存在连接复用问题
- 音频数据放入 `tts_audio_queue` 时必须使用 `(SentenceType, audio_data, text)` 三元组格式，因为 `audio_play_priority_thread` 消费时会解包为 3 个值

#### 6. `core/handle/textMessageHandlerRegistry.py` — 改动

**改动**：注册新 handler

```python
from core.handle.textHandler.ttsTextMessageHandler import TtsTextMessageHandler

# _register_default_handlers() 中 handlers 列表新增:
TtsTextMessageHandler(),
```

#### 7. `docker-compose.yml` — 改动

**改动**：新增 3 个文件挂载

```yaml
volumes:
  # ... 现有挂载 ...
  - ./core/handle/textHandler/ttsTextMessageHandler.py:/opt/xiaozhi-esp32-server/core/handle/textHandler/ttsTextMessageHandler.py
  - ./core/handle/textMessageType.py:/opt/xiaozhi-esp32-server/core/handle/textMessageType.py
  - ./core/handle/textMessageHandlerRegistry.py:/opt/xiaozhi-esp32-server/core/handle/textMessageHandlerRegistry.py
```

---

## 遇到的问题与解决

### 问题1：tts_audio_queue 格式不匹配

**现象**：TTS 生成成功（日志显示 73 bytes），但报错 `not enough values to unpack (expected 3, got 1)`

**原因**：`audio_play_priority_thread` 消费 `tts_audio_queue` 时期望解包 3 个值：

```python
sentence_type, audio_datas, text = self.tts_audio_queue.get()
```

但代码中放入的是 `(chunk,)` 只有 1 个元素。

**解决**：改为按正确格式放入三元组：

```python
conn.tts.tts_audio_queue.put((SentenceType.FIRST, None, text))   # 开始
for chunk in audio_data:
    conn.tts.tts_audio_queue.put((SentenceType.MIDDLE, chunk, None))  # 音频数据
conn.tts.tts_audio_queue.put((SentenceType.LAST, [], None))       # 结束
```

### 问题2：logger 导入路径错误

**现象**：`ImportError: cannot import name 'logger' from 'core.handle'`

**原因**：`core.handle` 模块没有导出 `logger`。其他 handler 统一使用 `conn.logger` 访问 logger。

**解决**：移除 `from core.handle import logger`，改用 `conn.logger.bind(tag=TAG)`。

### 问题3：Python 注释中文逗号

**现象**：`SyntaxError: invalid character '，' (U+FF0C)`

**原因**：代码注释中混入了中文全角逗号 `，`。

**解决**：替换为英文逗号 `,`。

---

## 验证方式

1. 后端部署后：`docker logs xiaozhi-esp32-server --tail 50 | grep 'TTS'` 确认收到 tts 消息且生成完成
2. 前端启动后：发送消息 → 点击喇叭 → 确认有声音播放
3. AI 说话时喇叭按钮 disabled，避免并发冲突
4. 回退验证：删除 docker-compose 新增挂载 → `--force-recreate` → 确认原有功能正常
