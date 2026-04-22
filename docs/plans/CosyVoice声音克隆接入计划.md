# CosyVoice 声音克隆接入计划

> 录制音频 → 上传到公网可访问URL → 调用 DashScope 声音克隆 API → 获取 voice_id → 配置到 xiaozhi-server TTS

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
在 xiaozhi-server 智控台配置 voice_id
        │
        ▼
验证语音播放效果
```

## 前置条件

| 条件 | 说明 |
|------|------|
| 阿里云账号 | 已开通智能语音交互（NLS）服务 |
| DashScope API Key | 在 [DashScope 控制台](https://dashscope.console.aliyun.com/) 获取 |
| AccessKey | RAM 访问控制台获取 access_key_id 和 access_key_secret |
| 录音设备 | 手机或电脑录音均可，需清晰无噪声 |
| 公网 URL | 克隆 API 需要通过 URL 读取音频文件 |

## 步骤 1：录制声音样本

### 录音要求

| 项目 | 要求 |
|------|------|
| 格式 | WAV（PCM 16bit, 单声道） |
| 时长 | 10-20 秒 |
| 内容 | 自然说话，语速适中，推荐读一段话（不要太短也不要太长） |
| 质量 | 安静环境，无明显背景噪声，不要有混响 |
| 采样率 | 16kHz 或 22.05kHz（推荐 16kHz） |
| 文件大小 | 不超过 10MB |

### 录音建议

1. 在安静的房间里录音
2. 保持正常说话的语速和语调
3. 录制内容建议：自我介绍或读一小段文章
4. 用手机录音 app 即可，导出为 WAV 格式
5. 如果是 mp3/m4a 格式，用 [ffmpeg](https://ffmpeg.org/) 转换：
   ```bash
   ffmpeg -i input.mp3 -ar 16000 -ac 1 -sample_fmt s16 output.wav
   ```

## 步骤 2：上传音频到公网

声音克隆 API 需要通过 URL 下载音频文件，所以音频必须放在公网可访问的地方。

### 方案 A：阿里云 OSS（推荐）

```bash
# 1. 创建 OSS bucket（如果还没有）
# 2. 上传文件
ossutil cp voice_sample.wav oss://your-bucket/voice_sample.wav
# 3. 设置公开读权限（或生成临时签名 URL）
```

### 方案 B：临时文件分享

使用任何可以生成公网 URL 的方式：
- 七牛云
- 腾讯云 COS
- GitHub Release（私有仓库附件不可用）
- 任何临时文件分享服务

**注意**：URL 必须是 HTTPS，且不需要登录即可访问。

## 步骤 3：调用声音克隆 API

### API 信息

| 项目 | 值 |
|------|-----|
| 接口 | `https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization` |
| 方法 | POST |
| 认证 | Bearer Token（DashScope API Key） |
| 模型 | `voice-enrollment` |

### 请求示例

```bash
curl -X POST 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization' \
  -H 'Authorization: Bearer sk-xxxxxxxxxxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "voice-enrollment",
    "input": {
      "voice_id": "my-voice-001",
      "audio_url": "https://your-oss.com/voice_sample.wav"
    }
  }'
```

### 参数说明

| 参数 | 类型 | 说明 |
|------|------|------|
| `model` | string | 固定值 `voice-enrollment` |
| `input.voice_id` | string | 自定义声音 ID，需全局唯一，格式建议 `cosyvoice-v2-xxx` |
| `input.audio_url` | string | 音频文件的公网 HTTPS URL |

### 成功响应

```json
{
  "request_id": "xxx",
  "output": {
    "voice_id": "my-voice-001",
    "status": "succeeded"
  }
}
```

### 其他管理 API

```bash
# 查询声音状态
curl 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization?voice_id=my-voice-001' \
  -H 'Authorization: Bearer sk-xxxxxxxx'

# 更新声音（换音频）
curl -X PUT 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization' \
  -H 'Authorization: Bearer sk-xxxxxxxx' \
  -H 'Content-Type: application/json' \
  -d '{
    "model": "voice-enrollment",
    "input": {
      "voice_id": "my-voice-001",
      "audio_url": "https://your-oss.com/new_voice_sample.wav"
    }
  }'

# 删除声音
curl -X DELETE 'https://dashscope.aliyuncs.com/api/v1/services/audio/tts/customization?voice_id=my-voice-001' \
  -H 'Authorization: Bearer sk-xxxxxxxx'
```

### 声音限制

| 项目 | 限制 |
|------|------|
| 每个账号最多 | 1000 个自定义声音 |
| 费用 | 创建/查询/更新/删除均免费 |
| 有效期 | 创建后 1 年内无使用自动删除 |
| 处理时间 | 通常 10-30 秒完成 |

## 步骤 4：配置到 xiaozhi-server

获取到 `voice_id` 后，在智控台的 TTS 配置中使用。

### 关键问题：选择哪个 TTS Provider？

xiaozhi-server 中有**两个**阿里云 CosyVoice 相关的 TTS Provider：

| Provider | 文件 | 接口 | 认证方式 |
|----------|------|------|----------|
| 阿里云语音合成(流式) | `aliyun_stream.py` | NLS 网关 WebSocket | AccessKey + appkey |
| 阿里百炼流式语音合成 | `alibl_stream.py` | DashScope API | Bearer API Key |

**声音克隆是通过 DashScope API 创建的**，所以需要确认 cloned voice_id 能否在两个 Provider 上使用。

## 可行性评估

### 核心问题

声音克隆 API 在 DashScope 平台（`dashscope.aliyuncs.com`），而 aliyun_stream.py 使用的是 NLS 智能语音交互网关（`nls-gateway-cn-beijing.aliyuncs.com`），这是**两套不同的接口体系**。

### 方案对比

#### 方案 A：使用 aliyun_stream.py（阿里云语音合成-流式）

**配置字段**：`access_key_id`, `access_key_secret`, `appkey`, `voice`

- appkey 从智能语音交互控制台获取
- voice 填入克隆的 voice_id
- 使用 NLS 网关的 FlowingSpeechSynthesizer 协议

**风险**：
- NLS 网关的 `FlowingSpeechSynthesizer` 是否支持 DashScope 克隆的 voice_id，**官方文档未明确说明**
- NLS 网关和 DashScope 是不同的服务入口，虽然底层都是 CosyVoice 模型，但 voice_id 的分发和路由可能不同
- 代码中 `private_voice` 字段优先于 `voice`，这暗示 private_voice 可能就是用于克隆声音的

**代码线索**（aliyun_stream.py 第 110-113 行）：
```python
if config.get("private_voice"):
    self.voice = config.get("private_voice")
else:
    self.voice = config.get("voice", "longxiaochun")
```

`private_voice` 字段的存在说明**原开发者已经考虑过私有/克隆声音的场景**，这增加了可行性。

**可行性：中高（需要实际测试）**

#### 方案 B：使用 alibl_stream.py（阿里百炼流式语音合成）

**配置字段**：API Key（DashScope）

- 直接使用 DashScope API，与声音克隆是同一平台
- voice_id 在 DashScope 平台创建，在 DashScope 平台使用，兼容性有保障

**优势**：
- 同一平台，兼容性确定无疑
- 配置更简单（只需一个 API Key）
- 不需要 appkey 和 AccessKey

**风险**：
- alibl_stream.py 的流式性能和稳定性可能与 aliyun_stream.py 有差异
- 需要确认 alibl_stream.py 是否支持克隆 voice_id 作为 voice 参数

**可行性：高**

#### 方案 C：NLS 控制台内置声音克隆

阿里云智能语音交互控制台本身可能也提供声音克隆功能，如果通过 NLS 控制台克隆，则可以直接在 aliyun_stream.py 中使用。

- 需要登录 [智能语音交互控制台](https://nls-portal.console.aliyun.com/) 检查是否有声音克隆功能
- 如果有，通过该渠道克隆的声音应该与 NLS 网关完全兼容

**可行性：需确认（可能不存在此功能）**

### 推荐方案

**首选：方案 A（aliyun_stream.py + private_voice 字段）**

理由：
1. 代码中已有 `private_voice` 字段，说明开发者已预留克隆声音的支持
2. aliyun_stream.py 是当前正在使用的 Provider，已验证稳定
3. NLS 网关和 DashScope 底层都是 CosyVoice 模型，voice_id 大概率通用

**回退：方案 B（alibl_stream.py）**

如果方案 A 的 voice_id 在 NLS 网关不识别，切换到 alibl_stream.py。

### 验证步骤

无论选择哪个方案，都需要以下验证：

1. **先用 DashScope API 克隆声音**，拿到 voice_id
2. **测试 voice_id 在 NLS 网关是否可用**：
   ```bash
   # 用 NLS 网关的 WebSocket 接口，voice 填入克隆的 voice_id
   # 如果返回正常音频，说明兼容
   # 如果返回错误（如 voice not found），则不可用
   ```
3. **如果 NLS 网关不支持，切换到 alibl_stream.py**，用 DashScope API Key + voice_id 测试

## 完整操作清单

- [ ] 1. 录制 10-20s WAV 音频样本（16kHz, 单声道, PCM 16bit）
- [ ] 2. 上传音频到公网 URL（OSS 或其他方式）
- [ ] 3. 调用 DashScope 声音克隆 API，获取 voice_id
- [ ] 4. 在智控台 TTS 配置中：
  - [ ] 方案 A：将 voice_id 填入 `private_voice` 字段（aliyun_stream.py）
  - [ ] 方案 B：将 voice_id 填入 `voice` 字段（alibl_stream.py）
- [ ] 5. 发送测试消息验证语音效果
- [ ] 6. 如果效果不满意，调整音频样本重新克隆（支持更新）

## 注意事项

1. **voice_id 命名规范**：建议使用 `cosyvoice-v2-` 前缀 + 自定义名称，如 `cosyvoice-v2-james`
2. **音频质量决定克隆效果**：噪声小、发音清晰、语速自然的音频效果最好
3. **1 年无使用自动删除**：需要定期使用，否则克隆的声音会被自动清理
4. **免费但有上限**：每个账号最多 1000 个自定义声音
5. **克隆声音的语气特征**：克隆会复制音色和语调，但不会复制说话内容和语气词
