# 首次对话 LLM 响应延迟分析

> 问题：每次新 WebSocket 连接后，第一句话 LLM 首段文本返回耗时 10~60s 不等，TTS 因百炼 23 秒超时频繁失败。

## 已确认的解决方案

**换用更快的 LLM 模型**。实测对比（从香港服务器发起，glm-4-flash，简单对话"你好"）：

| API 端点 | Round 1 | Round 2 | Round 3 | Round 4 | 平均首 token |
|---------|---------|---------|---------|---------|-------------|
| `api.z.ai/api/coding/paas/v4` (代理) | 1.93s | 1.11s | 1.31s | 1.49s | **1.46s** |
| `open.bigmodel.cn/api/coding/paas/v4` (官方) | 0.61s | 0.64s | 0.95s | 0.43s | **0.66s** |

**结论**：`open.bigmodel.cn/api/coding/paas/v4` 比 `api.z.ai` 快一倍多。

对比不同模型（`open.bigmodel.cn/api/coding/paas/v4`，简单对话"你好"）：

| 模型 | 首 token 耗时 | 说明 |
|------|-------------|------|
| **glm-4-flash** | **0.4~1.0s** | 推荐使用，对话场景够用 |
| glm-4.6 | 22~31s | 太慢，不适合实时对话 |
| glm-4v-flash (VLLM) | ~1s | 视觉模型，首 token 也很快 |

**最终配置**：
- 模型：`glm-4-flash`
- base_url：`https://open.bigmodel.cn/api/coding/paas/v4`（官方直连，比代理快）

## 延迟来源实测分析（2026-04-23）

从服务器日志采集的真实数据：

| 时间 | 首字耗时 | 总耗时 | token 数 | 备注 |
|------|---------|--------|---------|------|
| 16:19:52 | 27.95s | 31.88s | 53 | 当时用的是 glm-4.6 |
| 16:20:01 | 9.65s | 22.93s | 79 | |
| 16:20:47 | 23.85s | 39.19s | 90 | |
| 16:21:30 | 15.02s | 17.68s | 78 | |
| 16:22:59 | **63.37s** | 63.37s | **0** | 返回 0 token，可能触发 function_call |
| 16:23:01 | 41.45s | 48.75s | 86 | |

网络延迟实测（从香港服务器）：
- DNS: 0.08s, Connect: 0.08s, TLS: 0.10s → 总计 0.31s
- **网络不是瓶颈，瓶颈在 LLM 模型推理速度**

### TTS 23 秒超时的连锁反应

百炼 DashScope WebSocket 协议要求 `run-task` 之后 **23 秒内必须收到第一条 `continue-task` 文本**，否则服务端主动断开。LLM 首字 10~60 秒导致 TTS 每次超时失效。

```
16:11:21  TTS会话启动成功 (run-task → task-started)
16:11:44  TTS任务失败: request timeout after 23 seconds  ← 百炼等了23秒
16:11:51  LLM首段文本返回耗时: 30.86s                      ← LLM太慢，TTS已死
```

## 原始分析（2024年，仅供参考）

```
WebSocket连接建立
    │
    ├──① _background_initialize() 【异步，不等待完成】
    │     ├── _initialize_private_config_async()  ← HTTP请求获取差异化配置
    │     └── executor.submit(_initialize_components)  ← 线程池中执行
    │           ├── initialize_tts()
    │           ├── initialize_asr()
    │           ├── _initialize_memory() → init_memory()
    │           ├── _initialize_intent() → UnifiedToolHandler._initialize()【异步】
    │           └── _init_prompt_enhancement()
    │
    └──② async for message ... _route_message(message)
          └── startToChat() → conn.executor.submit(conn.chat, text)
                ├── memory.query_memory(query)  ← 【阻塞等待】
                └── llm.response()              ← 【阻塞等待】
```

## 核心问题：没有等待初始化完成就开始处理消息

关键代码在 `core/connection.py:256`：

```python
# 在后台初始化配置和组件（完全不阻塞主循环）
asyncio.create_task(self._background_initialize())  # ← 不等待！
```

`_background_initialize` 是 `asyncio.create_task` 启动的，**完全不等待完成**。然后 `_initialize_components` 又是 `executor.submit` 提交到线程池的。

但消息处理 `_route_message` 只检查了 `bind_completed_event`（等待 API 配置返回），**没有等待 LLM、Memory、Intent 等组件初始化完成**。

## 23秒延迟的具体来源（按概率排序）

### 1. Memory 首次查询阻塞（最可能，~10-15s）

`core/connection.py:977-980`：

```python
future = asyncio.run_coroutine_threadsafe(
    self.memory.query_memory(query), self.loop
)
memory_str = future.result()  # 阻塞等待！
```

如果 `self.memory` 还是 `None`（初始化未完成），虽然前面有 `if self.memory is not None` 检查不会崩溃，但如果 **Memory 初始化刚完成但内部状态未就绪**（如 mem0ai 的连接池未预热、PowerMem 的数据库连接未建立），首次 `query_memory` 可能非常慢。

### 2. LLM 首次请求冷启动（~5-8s）

如果用的是 OpenAI 兼容 API（阿里云百炼、DeepSeek 等），首次请求需要：
- DNS 解析
- TCP 连接建立
- TLS 握手
- HTTP/2 连接预热

后续请求复用已建立的连接，只需 ~5s。

### 3. 工具处理器异步初始化竞争（~3-5s）

`core/connection.py:854`：

```python
asyncio.run_coroutine_threadsafe(self.func_handler._initialize(), self.loop)
```

`UnifiedToolHandler._initialize()` 包括：
- 插件自动导入 `auto_import_modules("plugins_func.functions")`
- MCP 服务器初始化和连接
- Home Assistant 初始化

这些也是异步不等待的，可能和 chat 执行产生资源竞争。

### 4. 线程池竞争（~2s）

`_initialize_components` 和 `chat()` 都用 `self.executor`（同一个线程池），如果线程池大小有限，初始化任务可能占用线程，导致 chat 任务排队等待。

## 为什么后续对话正常（5s）？

- 所有组件已初始化完毕
- 网络连接已建立并复用
- DNS 已缓存
- TLS 会话已恢复
- 线程池空闲

## 延迟来源汇总

| 延迟来源 | 首次 | 后续 | 原因 |
|---------|------|------|------|
| Memory 查询 | ~10s | <1s | 首次需要建立连接/加载数据 |
| LLM 首次请求 | ~8s | ~3s | DNS + TCP + TLS 握手 |
| 工具/MCP 初始化竞争 | ~3s | 0s | 首次需要加载插件和连接 |
| 线程池竞争 | ~2s | 0s | 初始化任务占用线程 |
| **总计** | **~23s** | **~5s** | |

## 优化建议

### 已完成

- [x] LLM 模型从 glm-4.6 切换为 glm-4-flash（首 token 从 20+ 秒降到 1 秒以内）
- [x] base_url 使用官方直连 `open.bigmodel.cn/api/coding/paas/v4`（比代理 api.z.ai 快一倍）

### 待评估

1. **关闭不需要的 function_call**：当前启用了 get_weather、get_news、play_music 等工具，模型需额外判断是否调用，可能增加首 token 延迟。如果不需要每次对话都查天气/新闻，可考虑关闭
2. **MCP 接入点优化**：日志显示 MCP 接入点初始化响应结果为空，可能影响 function_call 行为

## 相关代码文件

| 文件 | 作用 |
|------|------|
| `core/connection.py:212` | `handle_connection()` - 连接入口 |
| `core/connection.py:256` | `_background_initialize()` - 异步初始化（不等待） |
| `core/connection.py:502` | `_initialize_components()` - 组件初始化（线程池） |
| `core/connection.py:621` | `_background_initialize()` - 后台初始化入口 |
| `core/connection.py:765` | `_initialize_memory()` - 记忆模块初始化 |
| `core/connection.py:849` | `_initialize_intent()` - 意图+工具处理器初始化 |
| `core/connection.py:861` | `chat()` - 主对话逻辑 |
| `core/connection.py:977` | `memory.query_memory()` - 记忆查询（阻塞） |
| `core/utils/modules_initialize.py` | `initialize_modules()` - 模块工厂函数 |
| `core/handle/receiveAudioHandle.py:41` | `startToChat()` - 音频消息处理入口 |
| `core/handle/receiveAudioHandle.py:98` | `conn.executor.submit(conn.chat)` - 提交 chat 到线程池 |
