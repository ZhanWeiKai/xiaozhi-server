# 本地 CosyVoice 接入百炼流式 TTS 方案

> 目标：让小智服务器使用本地部署的 CosyVoice 模型进行语音合成，通过 WebSocket 流式传输音频，体验与百炼 API 一致。

## 为什么需要这个方案

### 当前两种方式的对比

| 对比项 | 百炼 API (`alibl_stream.py`) | 本地 CosyVoice (`cosyvoice_local.py`) |
|--------|------------------------------|---------------------------------------|
| 协议 | WebSocket 双工流式 | HTTP 单次请求-响应 |
| 音频传输 | 边合成边发送，连续流畅 | 一句一句合成，中间有 3-4s 空白 |
| 网络延迟 | 需要公网，首次 ~5s | 局域网，几乎无延迟 |
| 费用 | 按字符计费 | 免费，仅消耗 GPU |
| 粤语效果 | v3.5-plus + instruction 参数 | 取决于模型和参考音频 |
| 音色 | 需要先克隆到 DashScope | 本地直接 zero-shot 克隆 |

### 本地 CosyVoice 为什么"一卡一卡"

通过分析日志发现，本地 CosyVoice 的 `cosyvoice_local.py` 是这样工作的：

```
LLM 返回完整文本（8.37s等待）
    │
    ├── 第1句: HTTP请求 → 等待合成完成 → 发送音频（3-4s）
    ├── 第2句: HTTP请求 → 等待合成完成 → 发送音频（3-4s）
    └── 第3句: HTTP请求 → 等待合成完成 → 发送音频（3-4s）
```

每句话之间有 3-4 秒的空白等待，用户体验很差。

### 方案思路：新建独立 TTS Provider

**不改 `alibl_stream.py`，不改智控台前后端代码**。创建一个全新的 TTS Provider `cosyvoice_local_ws.py`，注册到智控台数据库后自动出现在供应器下拉列表。

```
智控台选择「本地CosyVoice(流式)」供应器
    │
    ▼
cosyvoice_local_ws.py（新建，DUAL_STREAM）
    │  ─── WebSocket（DashScope协议）───→  ws_server.py（CosyVoice容器内）
    │                                          │
    │                                    CosyVoice 模型推理
    │                                          │
    │  ←── PCM音频流（边合成边返回）────────    │
    ▼
opus_encoder → 发送到设备 → 连续流畅播放
```

两个供应器独立存在，智控台切换就行，互不影响：

```
智控台 TTS 供应器下拉列表：
  ├── 阿里百炼(流式)          ← alibl_stream.py（不动）
  ├── 火山引擎(流式)          ← huoshan_stream.py（不动）
  ├── 本地CosyVoice(流式)     ← cosyvoice_local_ws.py（新增）
  └── ...
```

---

## 智控台供应器注册机制

### 供应器是怎么出现在下拉列表的

智控台的供应器列表是**数据库驱动**的，不是硬编码在前端代码里。整个流程：

```
ai_model_provider 表（数据库）
    │
    ▼
GET /models/{modelType}/provideTypes  （Java后端API）
    │
    ▼
AddModelDialog.vue → loadProviders()  （前端调用API）
    │
    ▼
下拉列表渲染（根据 fields JSON 自动生成配置表单）
```

### 关键数据库表：`ai_model_provider`

| 字段 | 类型 | 说明 | 示例（阿里百炼流式） |
|------|------|------|---------------------|
| `id` | varchar | 主键 | `SYSTEM_TTS_AliBLStreamTTS` |
| `model_type` | varchar | 模型类型 | `TTS` |
| `provider_code` | varchar | 供应器代码（对应Python文件名） | `alibl_stream` |
| `name` | varchar | 供应器显示名称 | `阿里百炼流式语音合成` |
| `fields` | json | 配置字段定义（自动生成表单） | `[{"key":"api_key","label":"API密钥","type":"string"},...]` |
| `sort` | int | 排序号 | 19 |

### `fields` JSON 格式说明

`fields` 数组中的每个对象定义一个配置字段，智控台会自动渲染为输入框：

```json
[
  {"key": "api_key", "label": "API密钥", "type": "string"},
  {"key": "volume", "label": "音量", "type": "number"}
]
```

- `key`：对应 Python 代码中 `config.get("key")` 的 key
- `label`：智控台表单中显示的中文标签
- `type`：`string` 或 `number`（对应普通输入框和数字输入框）

### Provider 加载机制

小智服务器根据 `provider_code` 动态加载对应的 Python 文件：

```
provider_code = "alibl_stream"
    │
    ▼
加载文件: core/providers/tts/{provider_code}.py
    │
    ▼
实例化类: TTSProvider(TTSProviderBase)
    │
    ▼
传入 configJson（来自数据库 ai_model_config.config_json）
```

所以 `provider_code` 必须和文件名一致。

### 参考已有注册（阿里百炼流式）

来源：`main/manager-api/src/main/resources/db/changelog/202509161701.sql`

```sql
-- 1. 注册供应器（定义下拉列表项 + 配置字段）
INSERT INTO `ai_model_provider` (...) VALUES
('SYSTEM_TTS_AliBLStreamTTS', 'TTS', 'alibl_stream', '阿里百炼流式语音合成',
 '[{"key":"api_key","label":"API密钥","type":"string"},{"key":"output_dir","label":"输出目录","type":"string"},{"key":"model","label":"模型","type":"string"},{"key":"voice","label":"音色","type":"string"},{"key":"format","label":"音频格式","type":"string"},{"key":"sample_rate","label":"采样率","type":"number"},{"key":"volume","label":"音量","type":"number"},{"key":"rate","label":"语速","type":"number"},{"key":"pitch","label":"音调","type":"number"}]',
 19, 1, NOW(), 1, NOW());

-- 2. 添加默认模型配置（用户在智控台配置的具体参数值）
INSERT INTO `ai_model_config` VALUES
('TTS_AliBLStreamTTS', 'TTS', 'AliBLStreamTTS', '阿里百炼流式语音合成', 0, 1,
 '{"type": "alibl_stream", "appkey": "", "output_dir": "tmp/", "model": "cosyvoice-v2", "voice": "longcheng_v2", "format": "pcm", "sample_rate": 24000, "volume": 50, "rate": 1, "pitch": 1}', ...);

-- 3. 添加音色列表（可选，供用户在音色管理中选择）
INSERT INTO `ai_tts_voice` VALUES
('TTS_AliBLStreamTTS_0001', 'TTS_AliBLStreamTTS', '龙小淳-知性积极女', 'longxiaochun_v2', '中文及中英文混合', ...);
```

---

## DashScope WebSocket 协议详解

通过逆向分析 `alibl_stream.py`，百炼的 WebSocket 协议包含 3 种请求消息和 4 种响应消息。
`cosyvoice_local_ws.py` 作为客户端会发送这 3 种消息，`ws_server.py` 作为服务端需要处理并回复。

### 客户端发送的消息（`cosyvoice_local_ws.py` 发出，`ws_server.py` 接收）

#### 1. `run-task` — 启动任务

```json
{
    "header": {
        "action": "run-task",
        "task_id": "会话ID",
        "streaming": "duplex"
    },
    "payload": {
        "task_group": "audio",
        "task": "tts",
        "function": "SpeechSynthesizer",
        "model": "cosyvoice-v2",
        "parameters": {
            "text_type": "PlainText",
            "voice": "longxiaochun_v2",
            "format": "pcm",
            "sample_rate": 16000,
            "volume": 50,
            "rate": 1.0,
            "pitch": 1.0
        },
        "input": {}
    }
}
```

`parameters` 中的关键字段：
- `sample_rate`：目标采样率（通常是 16000）
- `volume`：音量 0-100
- `format`：音频格式（pcm）

#### 2. `continue-task` — 发送待合成文本

```json
{
    "header": {
        "action": "continue-task",
        "task_id": "会话ID",
        "streaming": "duplex"
    },
    "payload": {
        "input": {
            "text": "你好，今天天气真好"
        }
    }
}
```

#### 3. `finish-task` — 结束任务

```json
{
    "header": {
        "action": "finish-task",
        "task_id": "会话ID",
        "streaming": "duplex"
    },
    "payload": {
        "input": {}
    }
}
```

### 服务端需要发送的响应（`ws_server.py` 发出，`cosyvoice_local_ws.py` 接收）

#### 1. `task-started` — 任务启动成功

```json
{
    "header": {
        "event": "task-started",
        "task_id": "会话ID",
        "request_id": "xxx"
    },
    "payload": {
        "output": {
            "task_id": "会话ID",
            "task_status": "SUCCEEDED"
        }
    }
}
```

#### 2. 二进制 PCM 音频数据

直接发送 `bytes`，不包装成 JSON。`cosyvoice_local_ws.py` 通过 `isinstance(msg, (bytes, bytearray))` 判断。

#### 3. `result-generated` — 一段文本合成完成

```json
{
    "header": {
        "event": "result-generated",
        "task_id": "会话ID"
    },
    "payload": {
        "output": {
            "audio_url": ""
        }
    }
}
```

`cosyvoice_local_ws.py` 收到此消息后，会将 `conn.tts_MessageText`（当前文本）放入音频队列。

#### 4. `task-finished` — 任务完成

```json
{
    "header": {
        "event": "task-finished",
        "task_id": "会话ID"
    },
    "payload": {
        "output": {
            "task_id": "会话ID",
            "task_status": "SUCCEEDED"
        }
    }
}
```

---

## 实现方案（共 3 步）

### 改动总览

| 步骤 | 类型 | 文件/位置 | 说明 |
|------|------|----------|------|
| **第1步** | **新增** | 数据库 SQL（1条INSERT） | 注册新供应器到 `ai_model_provider` 表 |
| **第2步** | **新增** | `server-code/core/providers/tts/cosyvoice_local_ws.py` | 新建 TTS Provider 实现文件 |
| **第3步** | **新增** | CosyVoice 容器内 `ws_server.py` | 本地 CosyVoice WebSocket 服务 |

**不需要改的东西：**

| 不需要改 | 原因 |
|---------|------|
| 智控台前端 Vue 代码 | 下拉列表从数据库读取，fields JSON 自动渲染表单 |
| 智控台后端 Java 代码 | 通用 API 接口，支持任意 provider |
| `alibl_stream.py` | 完全不动 |
| `config.yaml` | 不需要 |
| 数据库迁移文件（changelog） | 直接执行 SQL 即可 |

---

### 第1步：数据库注册新供应器 [新增 SQL]

在服务器上执行以下 SQL，往 `ai_model_provider` 表插入一条新供应器记录：

```sql
INSERT INTO `ai_model_provider`
  (`id`, `model_type`, `provider_code`, `name`, `fields`, `sort`, `creator`, `create_date`, `updater`, `update_date`)
VALUES
  ('SYSTEM_TTS_CosyVoiceLocalWS', 'TTS', 'cosyvoice_local_ws', '本地CosyVoice(流式)',
   '[{"key":"ws_url","label":"WebSocket地址","type":"string"},{"key":"voice_prompt","label":"参考音频路径","type":"string"},{"key":"model_dir","label":"模型目录","type":"string"},{"key":"sample_rate","label":"采样率","type":"number"},{"key":"volume","label":"音量","type":"number"},{"key":"rate","label":"语速","type":"number"},{"key":"pitch","label":"音调","type":"number"}]',
   24, 1, NOW(), 1, NOW());
```

**执行后效果**：智控台 → 模型配置 → TTS → 添加，供应器下拉列表自动出现「本地CosyVoice(流式)」，并自动渲染 7 个配置字段。

#### 各字段说明

| config key | 智控台显示名 | 示例值 | 说明 |
|-----------|------------|--------|------|
| `ws_url` | WebSocket地址 | `ws://cosyvoice-tts:3001` | ws_server.py 的地址 |
| `voice_prompt` | 参考音频路径 | `/workspace/CosyVoice/ref_audio.wav` | zero-shot 克隆的参考音频 |
| `model_dir` | 模型目录 | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | CosyVoice 模型路径 |
| `sample_rate` | 采样率 | `16000` | 目标采样率 |
| `volume` | 音量 | `50` | 0-100 |
| `rate` | 语速 | `1.0` | 0.5-2.0 |
| `pitch` | 音调 | `1.0` | 0.5-2.0 |

#### 执行方式

```bash
# SSH 到服务器
ssh axonex@100.69.157.38

# 进入 manager-api 的数据库容器执行 SQL
docker exec -it xiaozhi-manager-db mysql -u root -p
# 输入数据库密码后，选择数据库并执行上面的 INSERT
```

---

### 第2步：创建 `cosyvoice_local_ws.py` [新增文件]

#### 文件位置

```
server-code/core/providers/tts/cosyvoice_local_ws.py    ← 新建
```

#### 设计说明

这个文件是一个独立的 TTS Provider，和 `alibl_stream.py` 同级，但不修改 `alibl_stream.py`。

关键点：
- 继承 `TTSProviderBase`，设置 `interface_type = InterfaceType.DUAL_STREAM`
- `ws_url` 从配置读取（智控台有这个字段）
- 实现完整的 DashScope 协议：`start_session`、`text_to_speak`、`finish_session`、`_start_monitor_tts_response`
- 代码结构和 `alibl_stream.py` 几乎一致，区别在于：
  - 不需要 `api_key` 验证
  - `ws_url` 可配置（不是硬编码百炼地址）
  - parameters 简化（不需要 instruction/seed/language_hints）

#### 核心代码结构（基于 `alibl_stream.py` 简化）

```python
import os, uuid, json, time, queue, asyncio, traceback, websockets
from asyncio import Task
from typing import Callable, Any
from config.logger import setup_logging
from core.utils.tts import MarkdownCleaner
from core.providers.tts.base import TTSProviderBase
from core.providers.tts.dto.dto import SentenceType, ContentType, InterfaceType

TAG = __name__
logger = setup_logging()

class TTSProvider(TTSProviderBase):
    TTS_PARAM_CONFIG = [
        ("ttsVolume", "volume", 0, 100, 50, int),
        ("ttsRate", "rate", 0.5, 2.0, 1.0, lambda v: round(v, 1)),
        ("ttsPitch", "pitch", 0.5, 2.0, 1.0, lambda v: round(v, 1)),
    ]

    def __init__(self, config, delete_audio_file):
        super().__init__(config, delete_audio_file)
        self.interface_type = InterfaceType.DUAL_STREAM
        self.report_on_last = True

        # WebSocket配置（从智控台读取，不硬编码）
        self.ws_url = config.get("ws_url", "ws://localhost:3001")
        self.ws = None
        self._monitor_task = None
        self.last_active_time = None

        # CosyVoice 配置
        self.voice_prompt = config.get("voice_prompt", "")
        self.model_dir = config.get("model_dir", "FunAudioLLM/Fun-CosyVoice3-0.5B-2512")
        self.format = config.get("format", "pcm")

        volume = config.get("volume", "50")
        self.volume = int(volume) if volume else 50
        rate = config.get("rate", "1.0")
        self.rate = float(rate) if rate else 1.0
        pitch = config.get("pitch", "1.0")
        self.pitch = float(pitch) if pitch else 1.0

        # 无 api_key 验证（本地服务不需要）

        self._apply_percentage_params(config)

    async def _ensure_connection(self):
        """确保WebSocket连接可用，支持60秒内连接复用"""
        # 与 alibl_stream.py 完全一致的连接复用逻辑
        ...

    def tts_text_priority_thread(self):
        """流式TTS文本处理线程"""
        # 与 alibl_stream.py 完全一致
        ...

    async def text_to_speak(self, text, _):
        """发送文本到本地TTS服务"""
        # 与 alibl_stream.py 一致，发送 continue-task 消息
        ...

    async def start_session(self, session_id):
        """启动TTS会话，发送 run-task"""
        # 与 alibl_stream.py 一致，但 parameters 中：
        # - 不包含 api_key 相关 header
        # - 包含 voice_prompt 和 model_dir 信息
        ...

    async def finish_session(self, session_id):
        """结束TTS会话，发送 finish-task"""
        # 与 alibl_stream.py 完全一致
        ...

    async def _start_monitor_tts_response(self):
        """监听TTS响应，接收二进制PCM音频"""
        # 与 alibl_stream.py 完全一致
        ...

    async def close(self):
        """清理资源"""
        # 与 alibl_stream.py 完全一致
        ...
```

> **注意**：实际实现时，`tts_text_priority_thread`、`_ensure_connection`、`_start_monitor_tts_response`、`close` 等方法可以直接从 `alibl_stream.py` 复制，因为 DashScope 协议的处理逻辑完全一样。主要区别在 `__init__`（配置来源不同）和 `start_session`（parameters 不同）。

#### 与 `alibl_stream.py` 的区别对比

| 对比项 | `alibl_stream.py` | `cosyvoice_local_ws.py` |
|--------|-------------------|------------------------|
| WebSocket地址 | 硬编码百炼 `wss://dashscope.aliyuncs.com/...` | 从配置读取 `config.get("ws_url")` |
| API Key | 必填，有校验 `if not self.api_key: raise` | 无需，不校验 |
| Authorization header | `Bearer {api_key}` | 无（本地服务不需要认证） |
| parameters 中的 voice | 百炼音色 ID | 参考音频路径 |
| instruction/seed/language_hints | 支持 | 不需要（本地模型直接控制） |
| 其余协议逻辑 | — | 完全一致 |

---

### 第3步：创建 `ws_server.py` [新增文件]

#### 文件位置

```
CosyVoice Docker 容器内：/workspace/CosyVoice/ws_server.py    ← 新建
```

#### 完整设计

```python
"""
DashScope 协议兼容的 WebSocket TTS 服务器
让 cosyvoice_local_ws.py 可以通过 DashScope 协议连接本地 CosyVoice 模型
"""

import json
import uuid
import asyncio
import websockets
import numpy as np
from concurrent.futures import ThreadPoolExecutor
import logging

# CosyVoice 相关 import（需要根据容器内实际API调整）
from cosyvoice.cli.cosyvoice import CosyVoice2

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 配置
COSYVOICE_HOST = "0.0.0.0"
COSYVOICE_PORT = 3001
MODEL_DIR = "FunAudioLLM/Fun-CosyVoice3-0.5B-2512"
COSYVOICE_SAMPLE_RATE = 48000  # 模型输出采样率

# 全局模型实例
cosyvoice_model = None

def load_model():
    """加载 CosyVoice 模型"""
    global cosyvoice_model
    cosyvoice_model = CosyVoice2(MODEL_DIR)
    logger.info(f"CosyVoice 模型加载完成: {MODEL_DIR}")

def synthesize_stream(text, voice_prompt_wav, instruction="", speed=1.0):
    """
    流式合成语音，返回 PCM 音频生成器
    """
    for chunk in cosyvoice_model.inference_zero_shot(
        text=text,
        prompt_wav=voice_prompt_wav,
        prompt_text="",
        stream=True,
        speed=speed,
    ):
        yield chunk

def resample_pcm(pcm_data, from_rate, to_rate):
    """重采样 PCM 数据"""
    if from_rate == to_rate:
        return pcm_data
    duration = len(pcm_data) / from_rate
    target_length = int(duration * to_rate)
    indices = np.linspace(0, len(pcm_data) - 1, target_length)
    return np.interp(indices, np.arange(len(pcm_data)), pcm_data).astype(np.int16)

def adjust_volume(pcm_data, volume):
    """调整音量 (0-100)"""
    if volume == 50:
        return pcm_data
    factor = volume / 50.0
    adjusted = (pcm_data * factor).astype(np.int16)
    return np.clip(adjusted, -32768, 32767).astype(np.int16)

async def handle_client(websocket):
    """处理单个 WebSocket 客户端连接"""
    session_params = {}
    task_id = None

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                continue

            data = json.loads(message)
            header = data.get("header", {})
            payload = data.get("payload", {})
            action = header.get("action")
            task_id = header.get("task_id", str(uuid.uuid4()))

            if action == "run-task":
                params = payload.get("parameters", {})
                session_params = {
                    "sample_rate": params.get("sample_rate", 16000),
                    "volume": params.get("volume", 50),
                    "voice_prompt": params.get("voice", ""),
                    "model_dir": params.get("model_dir", MODEL_DIR),
                    "speed": params.get("rate", 1.0),
                }
                logger.info(f"任务启动 task_id={task_id}")

                response = {
                    "header": {"event": "task-started", "task_id": task_id,
                               "request_id": str(uuid.uuid4())},
                    "payload": {"output": {"task_id": task_id, "task_status": "SUCCEEDED"}}
                }
                await websocket.send(json.dumps(response))

            elif action == "continue-task":
                text = payload.get("input", {}).get("text", "")
                if not text:
                    continue
                logger.info(f"收到文本: {text}")

                # 在线程池中执行合成，避免阻塞事件循环
                loop = asyncio.get_event_loop()
                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(
                        list,
                        synthesize_stream(
                            text=text,
                            voice_prompt_wav=session_params.get("voice_prompt", ""),
                            speed=session_params.get("speed", 1.0),
                        )
                    )
                    while not future.done():
                        await asyncio.sleep(0.1)
                    audio_chunks = future.result()

                # 发送音频数据
                target_rate = session_params.get("sample_rate", 16000)
                volume = session_params.get("volume", 50)

                for chunk in audio_chunks:
                    pcm_array = np.frombuffer(chunk.tobytes(), dtype=np.int16)
                    resampled = resample_pcm(pcm_array, COSYVOICE_SAMPLE_RATE, target_rate)
                    resampled = adjust_volume(resampled, volume)
                    await websocket.send(resampled.tobytes())

                # 发送 result-generated
                response = {
                    "header": {"event": "result-generated", "task_id": task_id},
                    "payload": {"output": {"audio_url": ""}}
                }
                await websocket.send(json.dumps(response))
                logger.info(f"文本合成完成: {text}")

            elif action == "finish-task":
                response = {
                    "header": {"event": "task-finished", "task_id": task_id},
                    "payload": {"output": {"task_id": task_id, "task_status": "SUCCEEDED"}}
                }
                await websocket.send(json.dumps(response))
                logger.info(f"任务结束 task_id={task_id}")

    except websockets.ConnectionClosed:
        logger.info("客户端断开连接")
    except Exception as e:
        logger.error(f"处理客户端出错: {e}")

async def main():
    load_model()
    logger.info(f"WebSocket 服务器启动: ws://{COSYVOICE_HOST}:{COSYVOICE_PORT}")
    async with websockets.serve(handle_client, COSYVOICE_HOST, COSYVOICE_PORT):
        await asyncio.Future()

if __name__ == "__main__":
    asyncio.run(main())
```

> **注意**：上面的代码是设计草案，实际部署时需要根据容器内的 CosyVoice API 版本调整 import 和调用方式。

---

## 部署到服务器（实际操作记录）

### 服务器信息

| 项目 | 值 |
|------|-----|
| SSH | `axonex@100.69.157.38` |
| 数据库容器 | `xiaozhi-esp32-server-db`（MySQL，root密码 `123456`） |
| 数据库名 | `xiaozhi_esp32_server` |
| CosyVoice 镜像 | `cosyvoice-tts:latest`（30.9GB，CUDA 12.4） |
| CosyVoice 挂载卷 | `/home/axonex/cosyvoice/CosyVoice` |
| 容器内代码路径 | `/workspace/CosyVoice/` |
| Docker 网络 | `xiaozhi-dev_default`（两个容器已在此网络中） |
| 模型 | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` |
| 模型实际采样率 | **24000Hz**（不是文档常见的 48000Hz） |

### CosyVoice 容器现状

CosyVoice 容器**不是用 docker-compose 管理的**，是通过 `docker run` 启动的。容器挂载了本地目录：

```
/home/axonex/cosyvoice/CosyVoice  →  /workspace/CosyVoice
```

所以修改容器内文件（如 `ws_server.py`、`start_all.sh`）只需要修改宿主机上的文件，然后重建容器即可生效。

### 已确认的 CosyVoice API 详情

通过读取容器内的 `flask_server.py`，确认了以下信息：

| 项目 | 实际值 |
|------|--------|
| 模型加载方式 | `AutoModel(model_dir=model_dir)`（不是 `CosyVoice2`） |
| 流式推理 | `cosyvoice.inference_zero_shot(tts_text, prompt_text, prompt_wav_path, zero_shot_spk_id=voice_name, stream=True, speed=speed, text_frontend=False)` |
| 音频格式 | 返回 `item['tts_speech'].numpy().flatten()`，是 float32，需乘以 32767 转为 int16 |
| 音色管理 | `voices/` 目录下放 `{name}.wav` + `{name}.txt`，txt 是参考音频对应的文字 |
| 音色预缓存 | `cosyvoice.add_zero_shot_spk(prompt_text, wav_path, voice_name)` |

### 部署步骤（已完成）

#### 步骤 1：上传 `cosyvoice_local_ws.py` 到服务器并配置挂载 [新增文件 + 修改]

```bash
# 1. 上传到服务器 /tmp
scp cosyvoice_local_ws.py axonex@100.69.157.38:/tmp/cosyvoice_local_ws.py

# 2. 复制到挂载目录（需要 sudo）
ssh axonex@100.69.157.38
  echo 'Aimo123456' | sudo -S cp /tmp/cosyvoice_local_ws.py ~/xiaozhi-dev-4-20/core/providers/tts/cosyvoice_local_ws.py
  echo 'Aimo123456' | sudo -S chown axonex:axonex ~/xiaozhi-dev-4-20/core/providers/tts/cosyvoice_local_ws.py

# 3. 在 docker-compose.yml 中添加单文件挂载（在 alibl_stream.py 挂载行后面）
# 用 sed 在第 34 行后插入：
#   - ./core/providers/tts/cosyvoice_local_ws.py:/opt/xiaozhi-esp32-server/core/providers/tts/cosyvoice_local_ws.py
```

验证挂载（`docker-compose up -d` 后容器内应能看到该文件）：
```bash
docker exec xiaozhi-esp32-server ls -la /opt/xiaozhi-esp32-server/core/providers/tts/cosyvoice_local_ws.py
docker exec xiaozhi-esp32-server python -c "import py_compile; py_compile.compile('/opt/xiaozhi-esp32-server/core/providers/tts/cosyvoice_local_ws.py', doraise=True); print('OK')"
```

#### 步骤 2：注册供应器到数据库 [新增 SQL]

数据库容器是 `xiaozhi-esp32-server-db`，数据库名是 `xiaozhi_esp32_server`（不是 `xiaozhi`）：

```bash
ssh axonex@100.69.157.38
docker exec xiaozhi-esp32-server-db mysql -u root -p123456 xiaozhi_esp32_server
```

执行 SQL（注意转义）：

```sql
INSERT INTO ai_model_provider (id, model_type, provider_code, name, fields, sort, creator, create_date, updater, update_date)
VALUES ('SYSTEM_TTS_CosyVoiceLocalWS', 'TTS', 'cosyvoice_local_ws', '本地CosyVoice(流式)',
'[{"key":"ws_url","label":"WebSocket地址","type":"string"},{"key":"voice_prompt","label":"参考音频路径","type":"string"},{"key":"model_dir","label":"模型目录","type":"string"},{"key":"sample_rate","label":"采样率","type":"number"},{"key":"volume","label":"音量","type":"number"},{"key":"rate","label":"语速","type":"number"},{"key":"pitch","label":"音调","type":"number"}]',
24, 1, NOW(), 1, NOW());
```

验证：
```bash
docker exec xiaozhi-esp32-server-db mysql -u root -p123456 xiaozhi_esp32_server \
  -e "SELECT id, provider_code, name, sort FROM ai_model_provider WHERE provider_code='cosyvoice_local_ws';"
```

#### 步骤 3：上传 `ws_server.py` 和 `start_all.sh` 到 CosyVoice 容器 [新增文件]

CosyVoice 容器是 `docker run` 启动的（非 compose），文件需要通过挂载卷写入宿主机目录：

```bash
# 1. 上传到服务器 /tmp
scp ws_server.py axonex@100.69.157.38:/tmp/ws_server.py
scp start_all.sh axonex@100.69.157.38:/tmp/start_all.sh

# 2. 复制到宿主机挂载目录（容器会自动看到）
cp /tmp/ws_server.py /home/axonex/cosyvoice/CosyVoice/ws_server.py
cp /tmp/start_all.sh /home/axonex/cosyvoice/CosyVoice/start_all.sh

# 3. 修复 Windows 换行符问题（重要！）
sed -i 's/\r$//' /home/axonex/cosyvoice/CosyVoice/start_all.sh
```

`start_all.sh` 的内容：

```bash
#!/bin/bash
# 同时启动 Flask HTTP 服务和 WebSocket 流式服务

echo "=== 启动 start_all.sh ==="

# 启动 Flask 服务（原有HTTP接口，端口3000）
python flask_server.py --port 3000 --model_dir FunAudioLLM/Fun-CosyVoice3-0.5B-2512 &
FLASK_PID=$!
echo "Flask HTTP 服务已启动, PID=$FLASK_PID"

# 启动 WebSocket 流式服务（端口3001）
python ws_server.py --port 3001 --model_dir FunAudioLLM/Fun-CosyVoice3-0.5B-2512 --voice default &
WS_PID=$!
echo "WebSocket 流式服务已启动, PID=$WS_PID"

# 等待任一进程退出
wait -n $FLASK_PID $WS_PID
EXIT_CODE=$?

echo "=== 进程退出 (exit_code=$EXIT_CODE)，关闭所有服务 ==="
kill $FLASK_PID $WS_PID 2>/dev/null
wait $FLASK_PID $WS_PID 2>/dev/null

exit $EXIT_CODE
```

#### 步骤 4：重建 CosyVoice 容器（同时运行 Flask + WebSocket）

原容器需要停掉删除后重建，因为要改启动命令和端口映射：

```bash
# 停止并删除原容器
docker stop cosyvoice-tts
docker rm cosyvoice-tts

# 用新启动命令和端口映射重建（--gpus all 分配 GPU，--network 加入同一 Docker 网络）
docker run -d --name cosyvoice-tts --gpus all \
  --network xiaozhi-dev_default \
  -v /home/axonex/cosyvoice/CosyVoice:/workspace/CosyVoice \
  -p 3000:3000 \
  -p 3001:3001 \
  -e API_KEY='sk-cosyvoice3' \
  cosyvoice-tts:latest \
  bash /workspace/CosyVoice/start_all.sh
```

关键参数说明：
- `--gpus all`：分配所有 GPU（模型需要 GPU 推理）
- `--network xiaozhi-dev_default`：加入小智服务的 Docker 网络（这样 `xiaozhi-esp32-server` 可以通过 `cosyvoice-tts:3001` 访问）
- `-v .../CosyVoice:/workspace/CosyVoice`：挂载本地目录（包含代码和模型）
- `-p 3000:3000 -p 3001:3001`：映射两个端口
- `bash /workspace/CosyVoice/start_all.sh`：启动脚本同时运行两个服务

等待约 60 秒让模型加载完成，验证日志：

```bash
# 等待并检查日志
sleep 60 && docker logs cosyvoice-tts --tail 10

# 期望看到：
# Flask HTTP 服务已启动, PID=xxx
# WebSocket 流式服务已启动, PID=xxx
# Model loaded: FunAudioLLM/Fun-CosyVoice3-0.5B-2512, sample_rate=24000
# WebSocket 服务器启动: ws://0.0.0.0:3001
```

#### 步骤 5：清理 pycache 并重启小智服务器

```bash
# 清理 pycache
echo 'Aimo123456' | sudo -S find ~/xiaozhi-dev-4-20/core -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null

# 用 up -d 重建容器（读取新的挂载配置）
cd ~/xiaozhi-dev-4-20
docker compose up -d xiaozhi-esp32-server

# 验证
docker logs xiaozhi-esp32-server --tail 5
```

#### 步骤 6：验证网络互通

在小智服务器容器内测试能否访问 CosyVoice 的 WebSocket：

```bash
docker exec xiaozhi-esp32-server python -c "
import asyncio, websockets
async def test():
    try:
        async with websockets.connect('ws://cosyvoice-tts:3001', timeout=5) as ws:
            print('网络互通正常！')
    except Exception as e:
        print(f'网络不通: {e}')
asyncio.run(test())
"
```

### 回滚方式

**回滚小智服务器**：去掉 docker-compose.yml 中 cosyvoice_local_ws.py 的挂载行，`docker compose up -d` 重建。

**回滚 CosyVoice 容器**：用原始启动命令重建容器（只启动 flask_server.py）：
```bash
docker stop cosyvoice-tts && docker rm cosyvoice-tts
docker run -d --name cosyvoice-tts --gpus all \
  --network xiaozhi-dev_default \
  -v /home/axonex/cosyvoice/CosyVoice:/workspace/CosyVoice \
  -p 3000:3000 \
  -e API_KEY='sk-cosyvoice3' \
  cosyvoice-tts:latest \
  python flask_server.py --port 3000 --model_dir FunAudioLLM/Fun-CosyVoice3-0.5B-2512
```

**删除数据库注册**：
```bash
docker exec xiaozhi-esp32-server-db mysql -u root -p123456 xiaozhi_esp32_server \
  -e "DELETE FROM ai_model_provider WHERE id='SYSTEM_TTS_CosyVoiceLocalWS';"
```

---

## 智控台配置

注册成功后，在智控台操作：

1. 进入 模型配置 → TTS → 点击「添加」
2. 供应器下拉选择「本地CosyVoice(流式)」
3. 填写配置：

| 字段 | 填写内容 | 说明 |
|------|---------|------|
| WebSocket地址 | `ws://cosyvoice-tts:3001` | ws_server.py 的地址 |
| 参考音频路径 | `/workspace/CosyVoice/ref_audio.wav` | zero-shot 克隆的参考音频 |
| 模型目录 | `FunAudioLLM/Fun-CosyVoice3-0.5B-2512` | CosyVoice 模型路径 |
| 采样率 | `16000` | 目标采样率 |
| 音量 | `50` | 0-100 |
| 语速 | `1.0` | 0.5-2.0 |
| 音调 | `1.0` | 0.5-2.0 |

4. 设为默认，保存
5. 发送测试消息验证

### 切换回百炼 API

1. 将百炼的 TTS 模型设为默认
2. 禁用本地 CosyVoice 模型
3. 不需要重启服务，切换即时生效

---

## 架构总览

```
┌──────────────────────────────────────────────────────────────┐
│                     服务器 (100.69.157.38)                     │
│                                                                │
│  ┌─────────────────────────┐   ┌────────────────────────────┐ │
│  │   xiaozhi-esp32-server  │   │      cosyvoice-tts          │ │
│  │   Docker 容器            │   │      Docker 容器             │ │
│  │                          │   │                              │ │
│  │  core/providers/tts/     │   │  /workspace/CosyVoice/      │ │
│  │  ├── alibl_stream.py     │   │  ├── flask_server.py :3000  │ │
│  │  │   (百炼API, 不动)     │   │  │   (原有HTTP接口)          │ │
│  │  │                      │   │  │                           │ │
│  │  └── cosyvoice_local_ws  │   │  └── ws_server.py :3001     │ │
│  │      .py (新增)          │   │      (新增，DashScope协议)   │ │
│  │         │                │   │         │                    │ │
│  │         │ WebSocket      │   │  CosyVoice 模型             │ │
│  │         │ (DashScope     │──→│  48000Hz PCM               │ │
│  │         │  协议)         │←──│  重采样 → 16000Hz          │ │
│  │         │                │   │  音量调整                   │ │
│  └─────────────────────────┘   └────────────────────────────┘ │
│                                                                │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │   xiaozhi-manager (智控台后端)                            │ │
│  │                                                          │ │
│  │   ai_model_provider 表                                   │ │
│  │   ├── SYSTEM_TTS_AliBLStreamTTS (已有，不动)             │ │
│  │   └── SYSTEM_TTS_CosyVoiceLocalWS (新增 INSERT)          │ │
│  └──────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────┘
```

---

## 修改文件清单（最终版）

| 序号 | 类型 | 文件 | 位置 | 说明 |
|------|------|------|------|------|
| 1 | **新增** | `cosyvoice_local_ws.py` | `server-code/core/providers/tts/` | 新 TTS Provider 实现 |
| 2 | **新增** | `ws_server.py` | CosyVoice 容器内 `/workspace/CosyVoice/` | 本地 CosyVoice WebSocket 服务 |
| 3 | **新增** | SQL INSERT | 数据库 `ai_model_provider` 表 | 注册供应器到智控台 |
| 4 | **修改** | `docker-compose.yml` | CosyVoice 服务器 | 新增 3001 端口映射 |
| 5 | **修改** | `docker-compose.yml` | 小智服务器 | 新增 cosyvoice_local_ws.py 挂载 |
| — | **不动** | `alibl_stream.py` | — | 完全不修改 |
| — | **不动** | 智控台前端 Vue 代码 | — | 不需要改 |
| — | **不动** | 智控台后端 Java 代码 | — | 不需要改 |

---

## 待确认事项

在真正开发前，需要确认以下几点：

### 1. CosyVoice 模型的流式推理 API

当前 `flask_server.py` 中的合成调用方式需要查看，确认：
- `CosyVoice2` 还是 `CosyVoice` 类
- `inference_zero_shot` 是否支持 `stream=True`
- 流式输出每个 chunk 的格式（numpy array? bytes?）
- 参考音频路径和加载方式

### 2. 参考音频管理

本地 CosyVoice 使用 zero-shot 克隆需要参考音频。需要决定：
- 参考音频是固定路径还是可配置
- 是否支持运行时切换参考音频（通过 voice 参数传入路径）

### 3. 音频格式兼容

- 模型输出是 48000Hz，目标通常是 16000Hz，需要确认重采样质量
- `cosyvoice_local_ws.py` 的 `opus_encoder` 是否支持 48000Hz 输入（可能不需要重采样）
- PCM 是 int16 还是 float32

### 4. 并发处理

- 多个 WebSocket 客户端同时连接时怎么处理（多线程/排队）
- 模型推理是 GPU 密集型，同时只应处理一个合成请求

---

## 参考文档

- `CosyVoice粤语发音优化方案.md` — 百炼 API 的 instruction/seed/language_hints 参数分析
- `CosyVoice声音克隆接入计划.md` — 百炼平台声音克隆流程
- `服务器代码修改更新流程.md` — 服务器代码修改部署流程
