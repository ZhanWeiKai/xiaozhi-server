# NFC 触发 LLM 语音回复流程

> NFC 刷卡 → ESP32 读取 → WebSocket 发送文本 → xiaozhi-server 处理 → LLM 回复 → TTS 语音 → 音频返回播放

## 整体架构

```
NFC标签 ──刷卡──→ ESP32(PN532) ──WebSocket──→ xiaozhi-server(100.69.157.38)
                                                         │
                                                    ┌────┴────┐
                                                    │   LLM   │ 生成回复文本
                                                    └────┬────┘
                                                         │
                                                    ┌────┴────┐
                                                    │   TTS   │ 文本转语音
                                                    └────┬────┘
                                                         │
                                              音频二进制流──→ ESP32 播放
```

## 前提条件

1. **WebSocket 已连接**：设备开机后已完成 WebSocket 连接和 hello 握手，连接处于活跃状态
2. **NFC 硬件**：ESP32 + PN532 模块（或其他 NFC 读取模块）
3. **服务端无需任何修改**：xiaozhi-server 原生支持文本输入，不需要改服务器代码

## 服务端相关信息

| 项目 | 值 |
|------|-----|
| WebSocket 地址 | `wss://xiaozhi-wstest.jamesweb.org/xiaozhi/v1/` |
| 认证参数 | `?device-id=设备ID&authorization=Bearer token` |
| 服务器 SSH | `axonex@100.69.157.38` |

## WebSocket 消息交互顺序

### 第 1 步：建立连接（设备开机时完成，只需一次）

```
客户端 → 服务端:  {"type":"hello","device_id":"xxx","device_name":"xxx","device_mac":"xxx","token":"xxx","features":{"mcp":true}}
服务端 → 客户端:  {"type":"hello","session_id":"xxx",...}   ← 握手成功，拿到 session_id
```

握手成功后，WebSocket 连接保持长连接，不需要重复握手。

### 第 2 步：NFC 刷卡触发（每次刷卡时）

**情况 A：设备当前没有在说话**（最常见），直接发送：

```json
{"type":"listen","state":"detect","text":"你好，欢迎光临"}
```

**情况 B：设备正在说话**，需要先打断再发送：

```json
{"type":"abort","session_id":"当前session_id","reason":"wake_word_detected"}
```

然后立即发送：

```json
{"type":"listen","state":"detect","text":"你好，欢迎光临"}
```

### 服务端自动处理流程

收到 `{"type":"listen","state":"detect","text":"xxx"}` 后：

```
listenMessageHandler 接收消息
  │
  ├─ state == "detect" 且有 text 字段
  │
  ├─ 跳过 ASR（不需要语音识别，已经是文字）
  │
  ├─ 调用 startToChat(conn, original_text)
  │     │
  │     ├─ LLM 接收文本，生成回复
  │     │
  │     ├─ TTS 将回复转为语音
  │     │
  │     └─ 音频通过 WebSocket 二进制帧发回 ESP32
  │
  └─ ESP32 播放音频
```

## 完整时序图

```
  ESP32                           xiaozhi-server                     LLM                    TTS
    │                                   │                              │                     │
    │  (开机时) hello 握手               │                              │                     │
    │ ──────────────────────────────→   │                              │                     │
    │          hello 响应               │                              │                     │
    │   ←────────────────────────────   │                              │                     │
    │                                   │                              │                     │
    │  (NFC 刷卡)                       │                              │                     │
    │                                   │                              │                     │
    │  listen + text                    │                              │                     │
    │ ──────────────────────────────→   │                              │                     │
    │                                   │  发送文本给 LLM               │                     │
    │                                   │ ──────────────────────────→  │                     │
    │                                   │                              │                     │
    │                                   │  LLM 流式回复文本             │                     │
    │                                   │  ←─────────────────────────  │                     │
    │                                   │                              │                     │
    │                                   │  文本送 TTS                   │                     │
    │                                   │ ─────────────────────────────────────────────────→  │
    │                                   │                              │                     │
    │  二进制音频数据                    │  TTS 返回音频                 │                     │
    │  ←────────────────────────────   │  ←────────────────────────────────────────────────  │
    │                                   │                              │                     │
    │  播放语音                         │                              │                     │
    │                                   │                              │                     │
```

## NFC 标签内容设计

NFC 标签的 NDEF 记录里存储的是**触发文本**，即 `text` 字段的值。不同标签可以存不同内容：

| NFC 标签 | text 内容 | LLM 会回复 |
|-----------|----------|-----------|
| 门口标签 | "有客人来了" | 根据角色设定打招呼 |
| 会议室标签 | "现在进入会议室" | 提醒保持安静等 |
| 卧室标签 | "要睡觉了" | 晚安问候 |
| 玩具标签 | "给我讲个故事" | 讲一个短故事 |

LLM 的回复内容由服务端的**角色设定（prompt）**决定，同一个 text 不同的角色会回复不同的内容。

## 关键代码位置

| 文件 | 路径 | 说明 |
|------|------|------|
| listen 消息处理 | `core/handle/textHandler/listenMessageHandler.py` | 接收 `{"type":"listen","state":"detect","text":"xxx"}` |
| 聊天入口 | `core/connection.py` → `startToChat()` | LLM 调用和 TTS 转发 |
| TTS 音频发送 | `core/handle/sendAudioHandle.py` | 音频二进制帧发送 |
| WebSocket 服务端 | `core/websocket_server.py` | 连接管理和认证 |

## 注意事项

1. **text 内容尽量简短明确**，LLM 会基于这个输入生成回复，太长的文本反而会让 LLM 回复变慢
2. **每次 NFC 刷卡都会触发一次完整的 LLM → TTS 流程**，如果快速连续刷多张卡，前一张卡的回复会被打断
3. **session_id 在 hello 握手时获取**，之后所有消息（包括 abort）都需要带上这个 session_id
4. **不需要额外的认证或配置**，只要 WebSocket 已连接，直接发 listen 消息即可

## ESP32 伪代码示例

以下伪代码说明 NFC 刷卡后如何通过已有的 WebSocket 连接发送文本消息，基于 xiaozhi-esp32 固件的现有架构（`WebsocketProtocol` 类）。

```cpp
#include <PN532.h>        // NFC 模块驱动

// ========== 全局变量 ==========
WebsocketProtocol* websocket = nullptr;  // xiaozhi-esp32 固件已有的 WebSocket 协议实例
String current_session_id = "";          // hello 握手后保存的 session_id
bool is_speaking = false;               // 当前是否正在播放语音

// ========== NFC 刷卡回调 ==========
// 当 PN532 检测到 NFC 标签时触发
void onNfcTagDetected(uint8_t* uid, uint8_t uidLength) {
    // 1. 读取 NFC 标签内容（NDEF 记录中的文本）
    String nfc_text = readNdefText(uid, uidLength);
    if (nfc_text.length() == 0) return;  // 空标签，忽略

    // 2. 检查 WebSocket 是否已连接
    if (!websocket || !websocket->isConnected()) {
        Serial.println("[NFC] WebSocket 未连接，跳过");
        return;
    }

    // 3. 如果正在说话，先发打断消息
    if (is_speaking && current_session_id.length() > 0) {
        String abort_msg = "{\"type\":\"abort\",\"session_id\":\""
                         + current_session_id
                         + "\",\"reason\":\"wake_word_detected\"}";
        websocket->sendText(abort_msg);
        Serial.println("[NFC] 已发送打断消息");
        delay(50);  // 短暂等待，确保打断消息先发出
    }

    // 4. 发送文本消息，触发 LLM 回复
    String listen_msg = "{\"type\":\"listen\",\"state\":\"detect\",\"text\":\""
                      + nfc_text
                      + "\"}";
    websocket->sendText(listen_msg);
    Serial.println("[NFC] 已发送文本: " + nfc_text);
}

// ========== hello 握手回调 ==========
// xiaozhi-esp32 固件在 WebSocket 连接成功后自动发送 hello
// 收到服务端 hello 响应时，保存 session_id
void onHelloResponse(String session_id) {
    current_session_id = session_id;
    Serial.println("[WS] 握手成功, session_id: " + session_id);
}

// ========== 语音状态回调 ==========
// 当收到 TTS stop 消息时，标记说话结束
void onTtsStop() {
    is_speaking = false;
}
// 当收到 TTS start 消息时，标记开始说话
void onTtsStart() {
    is_speaking = true;
}

// ========== setup() 和 loop() ==========
void setup() {
    Serial.begin(115200);

    // 初始化 NFC（PN532 通过 SPI 或 I2C 连接）
    // PN532_SPI pn532(SPI, SS_PIN);
    // pn532.begin();
    // pn532.SAMConfig();

    // xiaozhi-esp32 固件的 WebSocket 连接会自动建立
    // hello 握手、session_id 保存等都在固件内部完成
    // 你只需要注册 NFC 回调即可
}

void loop() {
    // 轮询 NFC 标签（防重复：同一张卡只触发一次）
    uint8_t uid[7];
    uint8_t uidLength;

    if (pn532.readPassiveTargetID(PN532_MIFARE_ISO14443A, uid, &uidLength)) {
        static uint32_t last_uid = 0;
        uint32_t current_uid = uid[0] | (uid[1] << 8) | (uid[2] << 16);
        if (current_uid != last_uid) {       // 防止同一张卡重复触发
            last_uid = current_uid;
            onNfcTagDetected(uid, uidLength);
            delay(2000);                      // 冷却时间，避免连续触发
        }
    }
}
```

### 伪代码要点说明

| 要点 | 说明 |
|------|------|
| **WebSocket 实例** | 使用 xiaozhi-esp32 固件已有的 `WebsocketProtocol` 对象，不需要自己实现 WebSocket 连接 |
| **session_id** | hello 握手后从服务端响应中获取，打断消息需要用到 |
| **is_speaking 状态** | 通过 TTS 的 start/stop 消息跟踪，决定是否需要先打断 |
| **防重复触发** | 用 `last_uid` 记录上次刷的卡，同一张卡不重复触发 |
| **冷却时间** | `delay(2000)` 防止快速连续触发导致 LLM 响应混乱 |
| **sendText()** | xiaozhi-esp32 固件内部的方法，通过 WebSocket 发送 JSON 文本消息 |

### 实际集成时的注意事项

1. **NFC 初始化要在 WiFi 连接之后**，因为需要先建立 WebSocket 连接
2. **不要在 NFC 回调里阻塞太久**，发送完消息就返回，让 loop() 继续处理 WebSocket 收到的音频数据
3. **实际固件中 `sendText()` 可能叫别的名字**（如 `SendTextMessage`），需参考 xiaozhi-esp32 源码中 `WebsocketProtocol` 类的实际方法名
4. **`websocket` 和 `session_id` 的获取方式**需根据 xiaozhi-esp32 固件的实际代码结构调整，可能需要通过全局变量或事件回调获取
