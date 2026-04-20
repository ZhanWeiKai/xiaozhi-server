# xiaozhi-server 部署指南

> 最后更新: 2026-04-20

---

## 一、服务器上的目录结构

```
~/xiaozhi-dev/                          # 主部署目录
├── docker-compose-final.yml            # Docker Compose 配置（唯一入口）
├── data/
│   └── .config.yaml                    # xiaozhi-server 核心配置
├── models/
│   └── SenseVoiceSmall/
│       └── model.pt                    # ASR 语音识别模型（893MB）
├── core/                               # Python 核心代码（挂载到容器）
├── mysql/data/                         # MySQL 数据持久化
└── uploadfile/                         # 上传文件目录

~/xiaozhi-webui/                        # WebUI 部署目录
├── backend/
│   ├── app/                            # FastAPI 后端代码
│   ├── libs/                           # opus 编解码库
│   ├── main.py                         # 后端入口
│   ├── venv/                           # Python 虚拟环境
│   └── config/
│       └── config.json                 # WebUI 连接配置
└── backend.log                         # 后端日志

/var/www/xiaozhi-webui/                 # WebUI 前端静态文件（nginx 托管）

~/funasr-gpu/                           # FunASR GPU ASR 服务
├── workspace/
│   └── funasr_debug.py                 # FunASR WebSocket 服务脚本
└── Dockerfile                          # FunASR 构建文件

~/xiaozhi-mcp-server/                   # MCP Endpoint Server
├── docker-compose.yml
└── data/
    └── .mcp-endpoint-server.cfg        # MCP 配置
```

---

## 二、部署步骤

### 第 1 步：创建服务器目录

```bash
ssh axonex@100.69.157.38 "mkdir -p ~/xiaozhi-dev/{data,models/SenseVoiceSmall,uploadfile,mysql/data,core}"
```

### 第 2 步：上传 docker-compose-final.yml

```bash
scp docker-compose-final.yml axonex@100.69.157.38:~/xiaozhi-dev/
```

**docker-compose-final.yml 内容：**

```yaml
services:
  xiaozhi-esp32-server:
    image: xiaozhi-esp32-server:arm64-latest
    container_name: xiaozhi-esp32-server
    depends_on:
      xiaozhi-esp32-server-db:
        condition: service_healthy
      xiaozhi-esp32-server-redis:
        condition: service_healthy
    restart: always
    ports:
      - "8000:8000"
      - "8003:8003"
    environment:
      - TZ=Asia/Shanghai
      - PYTHONUNBUFFERED=1
      - LOG_LEVEL=INFO
    volumes:
      - ./data:/opt/xiaozhi-esp32-server/data
      - ./models/SenseVoiceSmall/model.pt:/opt/xiaozhi-esp32-server/models/SenseVoiceSmall/model.pt
      - ./uploadfile:/opt/xiaozhi-esp32-server/uploadfile
      - ./core:/opt/xiaozhi-esp32-server/core
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 60s

  xiaozhi-esp32-server-web:
    image: xiaozhi-manager-api:arm64-latest
    container_name: xiaozhi-esp32-server-web
    depends_on:
      xiaozhi-esp32-server-db:
        condition: service_healthy
      xiaozhi-esp32-server-redis:
        condition: service_healthy
    restart: always
    expose:
      - "8080"
    environment:
      - TZ=Asia/Shanghai
      - SERVER_PORT=8080
      - SPRING_DATASOURCE_DRUID_URL=jdbc:mysql://xiaozhi-esp32-server-db:3306/xiaozhi_esp32_server
      - SPRING_DATASOURCE_DRUID_USERNAME=root
      - SPRING_DATASOURCE_DRUID_PASSWORD=123456
      - SPRING_DATA_REDIS_HOST=xiaozhi-esp32-server-redis
      - SPRING_DATA_REDIS_PORT=6379
    volumes:
      - ./uploadfile:/uploadfile

  manager-web:
    image: manager-web:arm64-latest
    container_name: manager-web
    restart: always
    ports:
      - "8002:8001"

  xiaozhi-esp32-server-db:
    image: mysql:latest
    container_name: xiaozhi-esp32-server-db
    restart: always
    ports:
      - "3307:3306"
    environment:
      - MYSQL_ROOT_PASSWORD=123456
      - TZ=Asia/Shanghai
    volumes:
      - ./mysql/data:/var/lib/mysql
    healthcheck:
      test: ["CMD", "mysqladmin", "ping", "-h", "localhost", "-u", "root", "-p123456"]
      interval: 10s
      timeout: 5s
      retries: 5

  xiaozhi-esp32-server-redis:
    image: arm64v8/redis:8.0
    container_name: xiaozhi-esp32-server-redis
    restart: always
    ports:
      - "6380:6379"
    command: --appendonly yes --requirepass ""
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 5
```

### 第 3 步：上传配置文件和模型

```bash
# 服务器配置
scp data/.config.yaml axonex@100.69.157.38:~/xiaozhi-dev/data/

# ASR 模型（893MB，必须有，否则语音识别不可用）
scp models/SenseVoiceSmall/model.pt axonex@100.69.157.38:~/xiaozhi-dev/models/SenseVoiceSmall/

# Python 核心代码（挂载到容器，修改后无需重新构建镜像）
scp -r core/ axonex@100.69.157.38:~/xiaozhi-dev/
```

### 第 4 步：启动主服务

```bash
ssh axonex@100.69.157.38 "cd ~/xiaozhi-dev && docker compose -f docker-compose-final.yml up -d"
```

启动后会运行 5 个容器：

| 容器 | 端口 | 作用 |
|------|------|------|
| xiaozhi-esp32-server | 8000, 8003 | 主服务（WebSocket + HTTP） |
| xiaozhi-esp32-server-web | 8080（内部） | 智控台 API（Spring Boot） |
| manager-web | 8002 | 智控台前端（nginx 反向代理） |
| xiaozhi-esp32-server-db | 3307 | MySQL 数据库 |
| xiaozhi-esp32-server-redis | 6380 | Redis 缓存 |

### 第 5 步：验证主服务

```bash
# 查看容器状态
ssh axonex@100.69.157.38 "cd ~/xiaozhi-dev && docker compose -f docker-compose-final.yml ps"

# 查看主服务日志
ssh axonex@100.69.157.38 "docker logs xiaozhi-esp32-server --tail 30"

# 访问智控台
# http://100.69.157.38:8002/
```

---

## 三、配置文件说明

### data/.config.yaml（xiaozhi-server 核心配置）

关键字段：

```yaml
manager-api:
  url: http://xiaozhi-esp32-server-web:8002/xiaozhi
  secret: <从数据库获取的密钥>

# ASR 语音识别（使用 FunASR GPU 远程服务）
asr:
  FunASRServer:
    type: fun_server
    host: funasr-gpu
    port: 10095
    is_ssl: false
    api_key: none
    output_dir: tmp/
```

> **注意**: `secret` 值必须与数据库中 `sys_params` 表的 `server.secret` 一致，否则会报"无效的服务器密钥"。

### WebUI config.json（WebUI 连接配置）

```json
{
  "WS_URL": "ws://127.0.0.1:8000/xiaozhi/v1",
  "WS_PROXY_URL": "ws://0.0.0.0:5000",
  "TOKEN_ENABLE": true,
  "TOKEN": "<用 HMAC-SHA256 生成的 TOKEN>",
  "CLIENT_ID": "<客户端ID>",
  "DEVICE_ID": "<设备ID>"
}
```

> **注意**: `WS_URL` 必须用 `127.0.0.1` 本地地址，不能用外网域名，否则 Cloudflare Tunnel 会形成循环引用。

---

## 四、常用管理命令

### 主服务管理

```bash
# 启动
ssh axonex@100.69.157.38 "cd ~/xiaozhi-dev && docker compose -f docker-compose-final.yml up -d"

# 停止
ssh axonex@100.69.157.38 "cd ~/xiaozhi-dev && docker compose -f docker-compose-final.yml down"

# 重启
ssh axonex@100.69.157.38 "cd ~/xiaozhi-dev && docker compose -f docker-compose-final.yml restart"

# 查看日志
ssh axonex@100.69.157.38 "docker logs -f xiaozhi-esp32-server"

# 只重启 xiaozhi-server（改代码后）
ssh axonex@100.69.157.38 "docker restart xiaozhi-esp32-server"
```

### 更新代码到容器

```bash
# 修改本地 core/ 代码后
scp -r core/ axonex@100.69.157.38:~/xiaozhi-dev/
ssh axonex@100.69.157.38 "docker restart xiaozhi-esp32-server"
```

### 更新配置

```bash
# 修改 .config.yaml 后
scp data/.config.yaml axonex@100.69.157.38:~/xiaozhi-dev/data/
ssh axonex@100.69.157.38 "docker restart xiaozhi-esp32-server"
```

---

## 五、端口分配

| 端口 | 服务 | 访问地址 |
|------|------|----------|
| 8000 | xiaozhi-server WebSocket | `ws://100.69.157.38:8000/xiaozhi/v1/` |
| 8002 | 智控台 | `http://100.69.157.38:8002/` |
| 8003 | xiaozhi-server HTTP | `http://100.69.157.38:8003/` |
| 8004 | MCP Endpoint | `http://100.69.157.38:8004/` |
| 10095 | FunASR GPU ASR | `ws://100.69.157.38:10095/` |
| 3000 | CosyVoice TTS | `http://100.69.157.38:3000/` |

---

## 六、性能优化记录

### 6.1 VAD 语音活动检测：启用 force_onnx_cpu

**改动时间**: 2026-04-20

**改动文件**: `core/providers/vad/silero.py`

**改动内容**: 在 `torch.hub.load()` 调用中添加 `force_onnx_cpu=True` 参数。

```python
# 改动前
self.model, _ = torch.hub.load(
    repo_or_dir=config["model_dir"],
    source="local",
    onnx=True,
    model="silero_vad",
    force_reload=False,
)

# 改动后
self.model, _ = torch.hub.load(
    repo_or_dir=config["model_dir"],
    source="local",
    onnx=True,
    force_onnx_cpu=True,    # ← 新增
    model="silero_vad",
    force_reload=False,
)
```

**背景与原因**:

服务器硬件为 ARM64 架构（NVIDIA Grace Blackwell GB10），虽然配有 GPU，但容器内未配置 GPU 直通：
- `torch.cuda.is_available()` = False
- onnxruntime 仅有 `CPUExecutionProvider`，没有 `CUDAExecutionProvider`

`silero_vad()` 函数中 `force_onnx_cpu` 参数控制 `OnnxWrapper` 的行为：

```python
# hubconf.py / utils_vad.py 中的逻辑
if force_onnx_cpu and 'CPUExecutionProvider' in onnxruntime.get_available_providers():
    self.session = onnxruntime.InferenceSession(path, providers=['CPUExecutionProvider'])
else:
    self.session = onnxruntime.InferenceSession(path)  # 自动搜索可用 provider
```

当 `force_onnx_cpu=False`（默认值）时，onnxruntime 启动时会枚举所有可用的 Execution Provider，尝试初始化并选择最优的。在没有 GPU EP 的环境下，这个搜索过程是无效的开销。

**改动效果**:

1. **消除 provider 搜索开销** — 跳过 onnxruntime 的 provider 枚举和初始化尝试，直接使用 CPUExecutionProvider
2. **启动更快** — 每个新连接创建 VAD 实例时无需经历 provider 探测流程
3. **行为确定性** — 避免某些 onnxruntime 版本在自动选 provider 时的潜在问题或日志告警

**性能影响**: VAD 模型本身极小（~2MB），Cortex-X925 大核性能强劲（最高 4.0GHz），CPU 推理延迟已在亚毫秒级，此改动主要优化的是初始化开销和稳定性，推理速度不变。

> **注意**: 本地仓库的 `core/providers/vad/silero.py` 已进一步优化，绕过了 `torch.hub.load()` 包装层，直接使用 `onnxruntime.InferenceSession()` 并硬编码 `providers=["CPUExecutionProvider"]`，效果等价且更优。当本地代码同步到服务器后，此处的 `force_onnx_cpu` 改动将不再需要。
