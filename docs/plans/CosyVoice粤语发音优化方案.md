# CosyVoice 粤语发音优化方案

> 问题：使用 `cosyvoice-v3.5-plus` 模型时，粤语口语发音不够标准，部分字词发音不准确，声音生硬不够自然。

## 当前配置

| 项目 | 值 |
|------|-----|
| TTS Provider | 阿里百炼流式语音合成 (`alibl_stream.py`) |
| 模型 | `cosyvoice-v3.5-plus` |
| 接口 | DashScope WebSocket API |

## GPT 原始建议及问题分析

GPT 建议使用 `hot_fix.pronunciation` + `jyutping` 拼音注音方案，但该方案**不适用于当前配置**：

| 问题 | 说明 |
|------|------|
| `hot_fix` 不支持 v3.5-plus | `hot_fix.pronunciation` 仅支持 `cosyvoice-v3-flash` 克隆音色，v3.5-plus 不支持 |
| Jyutping 拼音不兼容 | API 的 `pronunciation` 字段期望的是**普通话拼音**格式（如 `tian1 qi4`），不是粤拼（Jyutping） |
| SSML `<phoneme>` 的拼音也是普通话拼音 | 即使启用 SSML，`<phoneme>` 标签的拼音同样基于普通话 |

## CosyVoice API 不支持的参数

CosyVoice TTS API **没有** `temperature`、`top_p`、`top_k` 参数，这些是 LLM 的推理参数，不适用于语音合成。

## CosyVoice API 完整参数列表（`alibl_stream.py` 当前缺失的参数）

以下参数在 API 文档中存在，但当前代码未传递：

| 参数 | 类型 | 说明 | 对自然度的影响 | 建议优先级 |
|------|------|------|--------------|-----------|
| `instruction` | string | 自然语言指令，控制情感/方言/风格 | **最大** | 高 |
| `seed` | int (0-65535) | 随机种子，不同 seed 产生不同合成变化 | 中等 | 高 |
| `language_hints` | string[] | 指定目标语言（zh/en/ja/ko 等） | 低（主要影响数字/符号朗读） | 低 |
| `enable_ssml` | boolean | 开启 SSML 精确注音 | 低 | 低 |
| `word_timestamp_enabled` | boolean | 字级别时间戳 | 无 | 无 |
| `enable_aigc_tag` | boolean | AIGC 隐性水印 | 无 | 无 |
| `hot_fix` | object | 文本热修复（仅 v3-flash 复刻音色） | 中等 | 无（不支持 v3.5） |
| `enable_markdown_filter` | boolean | Markdown 过滤（仅 v3-flash 复刻音色） | 无 | 无 |

---

## 方案 1：`instruction` 参数（推荐首选）

### 原理

`cosyvoice-v3.5-plus` 支持 `instruction` 参数，可以传入自然语言指令来控制方言、情感、语速、语气等。对**自然度**影响最大。

### 参数说明

| 项目 | 说明 |
|------|------|
| 参数名 | `instruction` |
| 类型 | string |
| 长度限制 | 最多 100 字符（汉字按 2 字符计算，其他按 1 字符） |
| 支持模型 | `cosyvoice-v3.5-flash`、`cosyvoice-v3.5-plus`（仅复刻/设计音色，无系统音色） |
| 用途 | 控制方言、情感、说话风格、自然度等 |
| 限制 | v3.5 系列无系统音色，必须使用声音复刻/设计音色 |

### 指令示例（来自官方文档）

控制**自然度**的指令：
```
用自然亲切的闲聊风格叙述
语气轻松自然，像和朋友聊天一样
用广播剧博主的语气讲话
我想体验一下自然的语气
```

控制**粤语**的指令（仅 v3-flash 复刻音色支持方言列表）：
```
请用广东话表达
```

控制**情感**的指令：
```
请用非常激昂且高亢的语气说话
语气要充满哀伤与怀念，带有轻微的鼻音
请尝试用气声说话，音量极轻，营造出在耳边亲密低语的神秘感
语气要像专业的新闻播音员一样，冷静、客观且字正腔圆
语气要显得活泼俏皮，带着明显的笑意，让声音听起来充满朝气与阳光
```

控制**语速/音量**的指令：
```
请尽可能非常大声地说一句话
请用尽可能慢地语速说一句话
你可以慢一点说吗
```

### 使用示例

```json
"parameters": {
    "text_type": "PlainText",
    "voice": "cosyvoice-v3.5-plus-xxx",
    "instruction": "用自然亲切的闲聊风格叙述",
    "seed": 12345,
    "format": "pcm",
    "sample_rate": 16000,
    "volume": 50,
    "rate": 1.0,
    "pitch": 1.0
}
```

### 代码修改详细方案

**仅修改一个文件**：`core/providers/tts/alibl_stream.py`

共 **3 处修改 + 1 处新增 import**，不需要改其他文件。

#### 改动 1：新增 `import random`（第 1 行区域）

现有 import 里没有 `random`，`seed="random"` 时需要用到。

```python
# 第 1 行区域，在现有 import 之后新增
import random
```

#### 改动 2：`__init__()` 读取新配置（第 62 行之后，`_apply_percentage_params` 之前）

新增读取 `instruction`、`seed`、`language_hints` 三个配置：

```python
# 在 self.pitch = float(pitch) if pitch else 1.0 之后
# self._apply_percentage_params(config) 之前

# 指令参数（控制情感/方言/风格/自然度）
self.instruction = config.get("instruction", "")

# 随机种子（0=默认行为，random=每次随机生成，其他数字=固定值可复现）
seed_config = config.get("seed", "0")
self.seed = int(seed_config) if seed_config != "random" else random.randint(1, 65535)

# 目标语言提示（如 "zh", "en" 等），影响数字/符号朗读方式
self.language_hints = config.get("language_hints", None)
```

**智控台配置方式**：

| 智控台新增字段 | config key | 示例值 | 说明 |
|--------------|------------|--------|------|
| 指令 | `instruction` | `用自然亲切的闲聊风格叙述` | 控制情感/方言/风格，留空不生效 |
| 随机种子 | `seed` | `random` 或 `12345` 或 `0` | `random`=每次随机，数字=固定值，`0`=默认 |
| 语言提示 | `language_hints` | `zh` 或 `en` | 留空不生效 |

#### 改动 3：`start_session()` 的 `parameters`（第 253-261 行）

在现有参数后添加新字段，用条件判断避免传空值：

```python
# 修改前
"parameters": {
    "text_type": "PlainText",
    "voice": self.voice,
    "format": self.format,
    "sample_rate": self.conn.sample_rate,
    "volume": self.volume,
    "rate": self.rate,
    "pitch": self.pitch,
},

# 修改后
"parameters": {
    "text_type": "PlainText",
    "voice": self.voice,
    "format": self.format,
    "sample_rate": self.conn.sample_rate,
    "volume": self.volume,
    "rate": self.rate,
    "pitch": self.pitch,
    # --- 新增 ---
    "seed": self.seed,
    "language_hints": [self.language_hints] if self.language_hints else None,
    **({"instruction": self.instruction} if self.instruction else {}),
},
```

#### 改动 4：`to_tts()` 的 `parameters`（第 450-458 行）

和改动 3 完全一样，`to_tts()` 是非流式生成方法，里面有一份独立的 parameters，需要同步添加：

```python
# 修改前（同上）
"parameters": {
    "text_type": "PlainText",
    "voice": self.voice,
    "format": self.format,
    "sample_rate": self.conn.sample_rate,
    "volume": self.volume,
    "rate": self.rate,
    "pitch": self.pitch,
},

# 修改后（同改动 3）
"parameters": {
    "text_type": "PlainText",
    "voice": self.voice,
    "format": self.format,
    "sample_rate": self.conn.sample_rate,
    "volume": self.volume,
    "rate": self.rate,
    "pitch": self.pitch,
    # --- 新增 ---
    "seed": self.seed,
    "language_hints": [self.language_hints] if self.language_hints else None,
    **({"instruction": self.instruction} if self.instruction else {}),
},
```

#### 不需要修改的方法

| 方法 | 原因 |
|------|------|
| `text_to_speak()` | 只发 `continue-task`，不含 parameters |
| `finish_session()` | 只发 `finish-task`，不含 parameters |
| `_start_monitor_tts_response()` | 只接收响应，不发送参数 |
| `_ensure_connection()` | 只建立 WebSocket 连接，不涉及合成参数 |

### 优缺点

| 优点 | 缺点 |
|------|------|
| 实现最简单，改动最小 | 对特定生僻字可能效果有限 |
| 不需要额外依赖 | 100 字符限制 |
| 模型原生支持 | 无法精确控制单个字的发音 |
| 对自然度改善效果最显著 | v3.5 系列必须用复刻/设计音色 |

---

## 方案 2：`seed` 参数（解决声音机械重复感）

### 原理

CosyVoice API 支持 `seed` 参数控制合成随机性。默认 seed=0 时，相同文本+相同参数每次合成结果完全一样，听起来很机械。设置不同 seed 可引入变化。

### 参数说明

| 项目 | 说明 |
|------|------|
| 参数名 | `seed` |
| 类型 | int |
| 取值范围 | 0-65535 |
| 默认值 | 0 |
| 不支持 | `cosyvoice-v1` |

### 行为

- **seed=0**（默认）：相同输入每次合成结果完全相同 → 听起来机械
- **seed=固定值**：可复现同一合成结果 → 适合测试
- **seed=随机值**（1-65535）：每次合成有微小变化 → 更自然

### 使用方式

建议每次 TTS 会话（`start_session`）时生成一个随机 seed：

```python
import random

# 在 start_session 中
"seed": random.randint(1, 65535),
```

或在配置中设置 `"seed": "random"` 表示每次随机。

### 优缺点

| 优点 | 缺点 |
|------|------|
| 参数简单，改动极小 | 效果有限，只是微小变化 |
| 避免同一句话每次完全一样 | 无法根本改变语气/情感 |
| 可和 instruction 组合使用 | |

---

## 方案 3：文本预处理（普通话→粤语口语）

### 原理

普通话和粤语书面语存在大量差异，将 LLM 返回的普通话文本预处理为粤语口语表达，再送入 TTS。

### 常见普通话→粤语用词替换表

| 普通话 | 粤语 | 普通话 | 粤语 |
|--------|------|--------|------|
| 什么 | 咩 | 怎么 | 點解 |
| 非常 | 好多 | 很 | 好 |
| 他们 | 佢哋 | 我们 | 我哋 |
| 这个 | 呢个 | 那个 | 嗰个 |
| 这里 | 呢度 | 那里 | 嗰度 |
| 时候 | 陣時 | 已经 | 已經 |
| 但是 | 不過 | 所以 | 所以 |
| 可以 | 可以/得 | 谢谢 | 唔該 |
| 对不起 | 唔好意思 | 没关系 | 唔緊要 |
| 是的 | 係嘅 | 不是 | 唔係 |
| 吃饭 | 食飯 | 喝水 | 飲水 |
| 睡觉 | 瞓覺 | 走路 | 行路 |
| 看书 | 睇書 | 听说 | 聽講 |
| 知道 | 知 | 理解 | 明白 |
| 漂亮 | 靚 | 厉害 | 厲害/叻 |
| 玩耍 | 玩 | 小孩 | 細路 |
| 老婆 | 老婆/太太 | 老公 | 老公/先生 |
| 帮忙 | 幫手 | 快点 | 快啲 |
| 一下 | 一陣/一下 | 等 | 等陣 |
| 喜欢 | 鍾意 | 讨厌 | 唔鍾意 |
| 便宜 | 平 | 贵 | 貴 |
| 很多 | 好多 | 一点 | 少少 |
| 今天 | 今日 | 昨天 | 尋日 |
| 明天 | 聽日 | 现在 | 而家 |
| 早上 | 朝早 | 晚上 | 晚黑 |
| 中午 | 晝飯 | 下午 | 下晝 |

### 实现方式

在 `alibl_stream.py` 的 `text_to_speak()` 方法中，发送文本前增加预处理步骤：

```python
def _preprocess_cantonese(self, text: str) -> str:
    """将普通话文本预处理为更口语化的粤语表达"""
    replacements = {
        "什么": "咩", "怎么": "點解", "非常": "好多",
        "他们": "佢哋", "我们": "我哋", "这个": "呢个",
        "那个": "嗰个", "这里": "呢度", "那里": "嗰度",
        "睡觉": "瞓覺", "吃饭": "食飯", "喝水": "飲水",
        "看书": "睇書", "漂亮": "靚", "喜欢": "鍾意",
        "知道": "知", "今天": "今日", "明天": "聽日",
        "现在": "而家", "小孩": "細路", "帮忙": "幫手",
        # ... 更多替换规则
    }
    for mandarin, cantonese in replacements.items():
        text = text.replace(mandarin, cantonese)
    return text
```

### 更好的实现：让 LLM 直接输出粤语

在 system prompt 中加入指令，让 LLM 直接生成粤语口语文本，避免后处理：

```
你是一个粤语助手。请用广东话口语回复用户，使用粤语常用表达方式。
例如：用"咩"代替"什么"，用"點解"代替"怎么"，用"呢个"代替"这个"。
```

### 优缺点

| 优点 | 缺点 |
|------|------|
| 文本更贴近粤语表达习惯 | 简单替换容易误替换（如"什么"在"什么都不"中） |
| LLM 直接输出效果最好 | 依赖 LLM 粤语能力 |
| 词语层面的根本优化 | 需要维护替换表 |

---

## 方案 4：SSML `<phoneme>` 精确注音

### 原理

`cosyvoice-v3.5-plus` 支持 SSML（语音合成标记语言），可以通过 `<phoneme>` 标签为特定字词指定发音。

### 启用方式

在请求参数中添加 `"enable_ssml": true`：

```json
"parameters": {
    "text_type": "PlainText",
    "voice": "longxiaochun_v2",
    "enable_ssml": true,
    "format": "pcm",
    "sample_rate": 16000
}
```

### SSML 示例

```xml
<speak>
你好，欢迎来到广州。
<phoneme alphabet="pinyin" ph="hou2 sai1 nei5">好世界</phoneme>！
</speak>
```

### 注意事项

| 项目 | 说明 |
|------|------|
| 拼音格式 | **普通话拼音**，不是粤拼（Jyutping） |
| 适用场景 | 只对特定容易读错的字词生效 |
| 局限性 | 无法通过普通话拼音精确指定粤语发音 |

### 结论

SSML 方案对粤语发音优化**效果有限**，因为 `<phoneme>` 标签只能指定普通话拼音，无法直接控制粤语发音。仅适用于部分普通话和粤语发音相同的字词微调。

---

## 方案 5：组合方案（推荐）

### 最佳实践：`instruction` + `seed` + 文本预处理

```
LLM 输出文本（粤语口语）
    │
    ▼
文本预处理（普通话→粤语用词替换，可选）
    │
    ▼
TTS 合成（instruction="用自然亲切的闲聊风格叙述" + seed=随机）
    │
    ▼
语音输出（更自然、更有变化）
```

### 实现优先级

1. **第一步**（改动最小，立即见效）：在 `alibl_stream.py` 中添加 `instruction` 和 `seed` 参数支持
2. **第二步**（文本层优化）：在 LLM system prompt 中要求粤语口语输出
3. **第三步**（可选）：添加文本后处理模块，做普通话→粤语用词替换
4. **SSML**：不推荐用于粤语优化，效果有限

---

## 修改文件清单

| 文件 | 改动 | 内容 |
|------|------|------|
| `core/providers/tts/alibl_stream.py` | 新增 import | `import random` |
| `core/providers/tts/alibl_stream.py` | `__init__()` 第 62 行后 | 新增 3 行：读取 `instruction`、`seed`、`language_hints` |
| `core/providers/tts/alibl_stream.py` | `start_session()` 第 253-261 行 | parameters 字典加 3 个字段 |
| `core/providers/tts/alibl_stream.py` | `to_tts()` 第 450-458 行 | parameters 字典加 3 个字段（同步改动 3） |

## 参考文档

- [CosyVoice WebSocket API 文档](https://help.aliyun.com/zh/model-studio/cosyvoice-websocket-api)
- [DashScope 控制台](https://dashscope.console.aliyun.com/)
