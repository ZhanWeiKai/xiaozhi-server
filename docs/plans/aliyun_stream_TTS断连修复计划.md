# aliyun_stream TTS 断连修复计划

## 问题现象

```
17:16:54  发送第一段语音: None          ← TTS 会话已启动，但无文本
17:17:04  LLM 首段文本返回耗时: 10.93s  ← LLM 太慢，空等 11 秒
17:17:05  WebSocket连接已关闭           ← NLS 网关因空闲断开连接
```

LLM 返回文本慢（10+ 秒），TTS WebSocket 连接建立后空等太久被 NLS 网关断开，后续文本全部丢弃。

## 根因分析

### aliyun_stream.py 的连接机制

```
start_session()
  │
  ├─ _ensure_connection()  →  建立 WebSocket 长连接到 NLS 网关
  ├─ 启动 _start_monitor_tts_response() 监听任务
  └─ 发送 StartSynthesis 请求
      │
      ▼
  （等待 LLM 返回文本...）  ← 连接空等，没有数据发送
      │
      ▼
text_to_speak()
  ├─ if self.ws is None → 直接放弃，不重连  ← BUG
  └─ 发送 RunSynthesis 文本
```

### 对比其他 TTS Provider

| 特性 | aliyun_stream.py | 其他 TTS Provider |
|------|-----------------|-------------------|
| 连接时机 | `start_session` 先建连接，等文本 | 收到文本才建连接 |
| 空等风险 | 有（LLM 慢时连接空等超时） | 无 |
| 断线处理 | `text_to_speak` 直接放弃 | 自动重连或无长连接 |
| ping 保活 | `ping_interval=30`（30 秒一次） | 不适用 |

### 两个问题点

1. **ping_interval=30 太大**：连接空等 11 秒时 ping 还没发出去（30 秒才发第一次），NLS 网关就断了
2. **text_to_speak 不重连**：连接断了直接 return，后续所有文本全部丢失

## 修改方案

### 修改文件

容器内路径：`/opt/xiaozhi-esp32-server/core/providers/tts/aliyun_stream.py`
本地保存路径：`server-code/core/providers/tts/aliyun_stream.py`

### 改动 1：降低 ping_interval（防止空闲断连）

**位置**：`_ensure_connection()` 方法内，`websockets.connect()` 调用

**原代码**：
```python
self.ws = await websockets.connect(
    self.ws_url,
    additional_headers={"X-NLS-Token": self.token},
    ping_interval=30,
    ping_timeout=10,
    close_timeout=10,
)
```

**改为**：
```python
self.ws = await websockets.connect(
    self.ws_url,
    additional_headers={"X-NLS-Token": self.token},
    ping_interval=5,
    ping_timeout=10,
    close_timeout=10,
)
```

**改动量**：`ping_interval=30` → `ping_interval=5`，只改一个数字

**效果**：每 5 秒发送一次 WebSocket ping，连接空等期间不会被 NLS 网关判定为死连接。即使 LLM 要等 10+ 秒，连接也能保持活跃。

### 改动 2：text_to_speak 断线重连（兜底保护）

**位置**：`text_to_speak()` 方法开头，`if self.ws is None` 分支

**原代码**：
```python
async def text_to_speak(self, text, _):
    try:
        if self.ws is None:
            logger.bind(tag=TAG).warning(f"WebSocket连接不存在，终止发送文本")
            return
        filtered_text = MarkdownCleaner.clean_markdown(text)
```

**改为**：
```python
async def text_to_speak(self, text, _):
    try:
        if self.ws is None:
            logger.bind(tag=TAG).warning(f"WebSocket连接不存在，尝试重连...")
            try:
                # 重新建立连接
                await self._ensure_connection()
                # 重新启动监听任务
                self._monitor_task = asyncio.create_task(self._start_monitor_tts_response())
                # 重新发送 StartSynthesis
                start_request = {
                    "header": {
                        "message_id": uuid.uuid4().hex,
                        "task_id": self.task_id,
                        "namespace": "FlowingSpeechSynthesizer",
                        "name": "StartSynthesis",
                        "appkey": self.appkey,
                    },
                    "payload": {
                        "voice": self.voice,
                        "format": self.format,
                        "sample_rate": self.conn.sample_rate,
                        "volume": self.volume,
                        "speech_rate": self.speech_rate,
                        "pitch_rate": self.pitch_rate,
                        "enable_subtitle": True,
                    },
                }
                await self.ws.send(json.dumps(start_request))
                self.last_active_time = time.time()
                logger.bind(tag=TAG).info(f"WebSocket重连成功，已重新发送StartSynthesis")
            except Exception as e:
                logger.bind(tag=TAG).error(f"WebSocket重连失败: {str(e)}")
                return
        filtered_text = MarkdownCleaner.clean_markdown(text)
```

**逻辑说明**：
1. 连接不存在时，不再直接放弃，而是尝试重连
2. 调用 `_ensure_connection()` 建立新 WebSocket 连接
3. 重新启动 `_start_monitor_tts_response` 监听任务（因为旧任务随旧连接已退出）
4. 重新发送 `StartSynthesis` 请求（NLS 网关要求新连接必须先 StartSynthesis 才能发 RunSynthesis）
5. 重连失败时仍然 return，不会影响后续流程

## 部署步骤

按照 `docs/plans/服务器代码修改更新流程.md` 执行：

### 1. 从容器提取原始文件到本地

```bash
ssh axonex@100.69.157.38 "docker cp xiaozhi-esp32-server:/opt/xiaozhi-esp32-server/core/providers/tts/aliyun_stream.py /tmp/aliyun_stream_v092.py"
scp axonex@100.69.157.38:/tmp/aliyun_stream_v092.py "C:\claude-project\xiaozhi-webui\xiaozhi-esp32-server\server-code\core\providers\tts\aliyun_stream.py"
```

### 2. 在本地修改代码

在 `server-code/core/providers/tts/aliyun_stream.py` 中做上述两处改动。

### 3. 验证语法

```bash
python -c "import py_compile; py_compile.compile('server-code/core/providers/tts/aliyun_stream.py', doraise=True); print('OK')"
```

### 4. 上传到服务器挂载目录

```bash
scp "C:\...\server-code\core\providers\tts\aliyun_stream.py" axonex@100.69.157.38:/tmp/aliyun_stream.py

ssh axonex@100.69.157.38
  sudo mkdir -p ~/xiaozhi-dev-4-20/core/providers/tts
  sudo cp /tmp/aliyun_stream.py ~/xiaozhi-dev-4-20/core/providers/tts/aliyun_stream.py
  sudo chown axonex:axonex ~/xiaozhi-dev-4-20/core/providers/tts/aliyun_stream.py
```

### 5. 配置 docker-compose.yml 挂载

在 `volumes` 部分添加：

```yaml
- ./core/providers/tts/aliyun_stream.py:/opt/xiaozhi-esp32-server/core/providers/tts/aliyun_stream.py
```

### 6. 清除缓存并重启

```bash
echo 'Aimo123456' | sudo -S find ~/xiaozhi-dev-4-20/core -type d -name '__pycache__' -exec rm -rf {} + 2>/dev/null
cd ~/xiaozhi-dev-4-20
docker compose up -d xiaozhi-esp32-server
```

### 7. 验证

```bash
# 确认容器正常启动
docker logs xiaozhi-esp32-server --tail 5

# 确认挂载文件生效
docker exec xiaozhi-esp32-server grep -c 'ping_interval=5' /opt/xiaozhi-esp32-server/core/providers/tts/aliyun_stream.py
```

## 风险评估

| 改动 | 风险 | 说明 |
|------|------|------|
| ping_interval 30→5 | 极低 | 标准 WebSocket 保活参数，只增加 ping 频率 |
| text_to_speak 重连 | 低 | 只在 ws 为 None 时触发，重连失败仍 return，不影响正常流程 |
| 重新发送 StartSynthesis | 低 | NLS 网关要求新连接必须先 StartSynthesis，符合协议规范 |

## 回滚

去掉 docker-compose.yml 中 `aliyun_stream.py` 的挂载行，重启即可恢复容器原始代码。

## 注意事项

1. **改动 1 是主要修复**：ping_interval=5 基本能解决问题，防止连接空闲断开
2. **改动 2 是兜底保护**：即使改动 1 不够（比如网络抖动导致连接断了），也能自动恢复
3. 两个改动互不冲突，建议同时部署
