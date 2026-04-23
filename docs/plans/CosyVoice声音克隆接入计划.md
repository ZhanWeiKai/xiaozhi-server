# CosyVoice 声音克隆接入指南

> 录制音频 → 上传到公网URL → 调用 DashScope 声音克隆 API → 获取 voice_id → 在智控台"默认音色"填入 voice_id

## 整体流程

```
录制 10-20s WAV 音频
        │
        ▼
上传到公网可访问的 URL（OSS/临时文件服务器）
        │
        ▼
调用 DashScope 声音克隆 API（voice-enrollment）
        │
        ▼
获取 voice_id（如 cosyvoice-v2-myvoice-xxxxxxxx）
        │
        ▼
在智控台 TTS 配置的"默认音色"字段填入 voice_id
        │
        ▼
发送测试消息验证语音效果
```

## 前置条件

| 条件 | 说明 |
|------|------|
| 阿里云账号 | 已开通智能语音交互（NLS）服务 |
| DashScope API Key | 在 [DashScope 控制台](https://dashscope.console.aliyun.com/) 获取，格式 `sk-xxxxxxxx` |
| 录音文件 | 已准备好 WAV 格式音频（见下方录音要求） |
| 公网 URL | 克隆 API 需要通过 URL 下载音频文件 |

---

## 步骤 1：准备音频文件

### 录音要求

| 项目 | 要求 |
|------|------|
| 格式 | WAV（PCM 16bit, 单声道） |
| 时长 | 10-20 秒 |
| 采样率 | 16kHz（推荐）或 22.05kHz |
| 内容 | 自然说话，语速适中，读一段文章或自我介绍 |
| 质量 | 安静环境，无明显背景噪声，不要有混响 |
| 文件大小 | 不超过 10MB |

### 录音建议

1. 在安静的房间里录音
2. 保持正常说话的语速和语调
3. 用手机录音 app 即可，导出为 WAV 格式
4. 如果是 mp3/m4a 格式，用 ffmpeg 转换：
   ```bash
   ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 output.wav
   ```

---

## 步骤 2：上传音频到公网 URL

声音克隆 API 需要通过 URL 下载音频，所以音频必须放在公网可访问的地方。

### 推荐方式

使用任何可以生成公网 HTTPS URL 的方式：

| 方式 | 说明 |
|------|------|
| 阿里云 OSS | 最稳定，控制台直接上传，设置公开读权限即可 |
| 腾讯云 COS | 类似 OSS |
| 七牛云 | 免费额度，适合临时使用 |
| 其他文件分享 | 任何能生成公开 HTTPS 直链的方式 |

**要求**：URL 必须是 HTTPS，且不需要登录即可直接下载。

---

## 步骤 3：调用声音克隆 API

### API 信息

| 项目 | 值 |
|------|-----|
| 接口 | `https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization` |
| 方法 | POST |
| 认证 | Bearer Token（DashScope API Key） |
| 模型 | `cosyvoice-v2` |

### 3.1 创建声音

```bash
curl -X POST 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization' \
  -H 'Authorization: Bearer sk-你的DashScope-API-Key' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "cosyvoice-v2",
    "input": {
      "voice_id": "cosyvoice-v2-james",
      "audio_url": "https://你的音频公网URL/voice_sample.wav"
    }
  }'
```

**参数说明**：

| 参数 | 说明 |
|------|------|
| `model` | 固定值 `cosyvoice-v2` |
| `input.voice_id` | 自定义声音 ID，需全局唯一，建议 `cosyvoice-v2-` 前缀 |
| `input.audio_url` | 音频文件的公网 HTTPS URL |

### 3.2 成功响应

```json
{
  "request_id": "xxx-xxx-xxx",
  "output": {
    "voice_id": "cosyvoice-v2-james",
    "status": "succeeded"
  }
}
```

`status` 为 `succeeded` 表示克隆成功，`voice_id` 就是后续要用的 ID。

### 3.3 查询声音状态

如果创建后状态不是 `succeeded`，可以轮询查询：

```bash
curl 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization?voice_id=cosyvoice-v2-james' \
  -H 'Authorization: Bearer sk-你的DashScope-API-Key'
```

通常 10-30 秒完成。

### 3.4 其他管理 API

```bash
# 更新声音（换音频）
curl -X PUT 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization' \
  -H 'Authorization: Bearer sk-你的DashScope-API-Key' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "cosyvoice-v2",
    "input": {
      "voice_id": "cosyvoice-v2-james",
      "audio_url": "https://你的音频公网URL/new_voice_sample.wav"
    }
  }'

# 删除声音
curl -X DELETE 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization?voice_id=cosyvoice-v2-james' \
  -H 'Authorization: Bearer sk-你的DashScope-API-Key'
```

### 声音限制

| 项目 | 限制 |
|------|------|
| 每个账号最多 | 1000 个自定义声音 |
| 费用 | 创建/查询/更新/删除均免费 |
| 有效期 | 创建后 1 年内无使用自动删除 |
| 处理时间 | 通常 10-30 秒完成 |

---

## 步骤 4：在智控台配置 voice_id

### 重要说明：private_voice 字段不存在于智控台 UI

代码中 `aliyun_stream.py` 有两个 voice 相关字段（第 110-113 行）：

```python
if config.get("private_voice"):
    self.voice = config.get("private_voice")
else:
    self.voice = config.get("voice", "longxiaochun")
```

- `private_voice`：优先级高，**但智控台 UI 中没有这个字段**
- `voice`：对应智控台中的**"默认音色"**字段

因为 `private_voice` 在 UI 中不存在，`config.get("private_voice")` 永远为空，代码会走 `else` 分支使用 `voice` 字段的值。

### 操作方法

在智控台的 **阿里云语音合成(流式)** TTS 配置页面中：

1. 找到 **"默认音色"** 字段（当前值为 `longxiaochun`）
2. 将值改为你的克隆 `voice_id`（例如 `cosyvoice-v2-james`）
3. 其他字段（AppKey、AccessKey、Token 等）保持不变
4. 保存配置

### 智控台 TTS 配置字段对照表

| 智控台字段名 | 代码 config key | 说明 |
|-------------|----------------|------|
| 应用AppKey | `appkey` | NLS 应用的 AppKey |
| 临时Token | `token` | NLS 临时 Token |
| AccessKey ID | `access_key_id` | 阿里云 AccessKey ID |
| AccessKey Secret | `access_key_secret` | 阿里云 AccessKey Secret |
| 服务地址 | — | NLS 网关地址 |
| **默认音色** | **`voice`** | **填入克隆的 voice_id** |
| 音频格式 | `format` | pcm |
| 音量 | `volume` | 0-100 |
| 语速 | `speech_rate` | -500~500 |
| 音调 | `pitch_rate` | -500~500 |
| 输出目录 | — | 临时文件目录 |

---

## 步骤 5：验证语音效果

1. 保存配置后，发送一条测试消息（文字或语音都行）
2. 听 TTS 回复的语音是否使用了克隆的声音
3. 如果报错（如 voice not found），参考下方**故障排查**

### 可能的问题

| 问题 | 原因 | 解决 |
|------|------|------|
| 语音没有变化，还是默认音色 | voice_id 未生效 | 检查智控台"默认音色"是否保存成功，重启 TTS 会话 |
| 报错 voice not found | NLS 网关不识别 DashScope 克隆的 voice_id | 见下方兼容性说明 |
| 语音质量差 | 录音质量不好 | 重新录制高质量音频，调用更新 API 替换 |

### 兼容性说明

声音克隆 API 在 **DashScope 平台**（`dashscope.aliyuncs.com`），而 aliyun_stream.py 使用的是 **NLS 智能语音交互网关**（`nls-gateway-cn-beijing.aliyuncs.com`），这是两套不同的接口体系。

- **大概率兼容**：两者底层都是 CosyVoice 模型，代码中 `private_voice` 字段的存在说明开发者已预留克隆声音的支持
- **如果不兼容**：可以切换到智控台的 **"阿里百炼流式语音合成"** Provider（`alibl_stream.py`），它直接使用 DashScope API，与声音克隆是同一平台，兼容性有保障

---

## 完整操作清单

- [ ] 1. 准备 10-20s WAV 音频（16kHz, 单声道, PCM 16bit）
- [ ] 2. 上传音频到公网 HTTPS URL
- [ ] 3. 调用 DashScope 声音克隆 API，拿到 voice_id
- [ ] 4. 在智控台"默认音色"字段填入 voice_id，保存
- [ ] 5. 发送测试消息验证语音效果
- [ ] 6. 效果不满意则调整音频样本，调用更新 API 重新克隆

## 注意事项

1. **voice_id 命名**：建议使用 `cosyvoice-v2-` 前缀 + 自定义名称
2. **音频质量决定克隆效果**：噪声小、发音清晰、语速自然的音频效果最好
3. **1 年无使用自动删除**：需要定期使用，否则克隆的声音会被自动清理
4. **免费但有上限**：每个账号最多 1000 个自定义声音
5. **克隆复制的是音色**：会复制音色和语调，但不会复制说话内容和语气词
