# xiaozhi-server 升级指南

> 从自建 ARM64 镜像升级到官方预构建镜像（支持 ARM64）
> 生成日期: 2026-04-20

---

## 升级内容

| 项目 | 旧版本 | 新版本 |
|------|--------|--------|
| Python 服务 | `xiaozhi-esp32-server:arm64-latest`（自建） | `ghcr.nju.edu.cn/.../server_latest`（官方） |
| Java API | `xiaozhi-manager-api:arm64-latest`（自建） | 合并到 `web_latest` |
| Vue 前端 | `manager-web:arm64-latest`（自建） | 合并到 `web_latest` |
| MySQL | 不变 | 不变 |
| Redis | 不变 | 不变 |

**主要变化**: 旧版本把 Java API 和 Vue 前端拆成 2 个容器，新版本官方镜像合并为 1 个容器（`web_latest`）。外部端口 8000、8002、8003 保持不变，不影响 ESP32 设备和 WebUI 的连接。

---

## 目录规划

升级使用全新的独立目录，**旧目录 `~/xiaozhi-dev/` 完全不动**。

| 目录 | 用途 | 状态 |
|------|------|------|
| `~/xiaozhi-dev/` | 旧版本（当前运行） | 不修改，稳定后删除 |
| `~/xiaozhi-dev-4-20/` | 新版本（官方镜像） | 新建，数据独立 |

新目录需要的文件（仅复制必要的，不复制旧 tar 包、构建脚本等历史遗留）：

```
~/xiaozhi-dev-4-20/
├── docker-compose-final.yml    # 新的 compose 文件（上传）
├── data/
│   └── .config.yaml            # 从旧目录复制（12KB）
├── models/SenseVoiceSmall/
│   └── model.pt                # 从旧目录复制（893MB）
├── core/                       # 从旧目录复制（1.8MB，自定义代码）
├── mysql/
│   └── data/                   # 停旧服务后用 sudo 复制（104MB）
└── uploadfile/                 # 从旧目录复制（12KB）
```

**不需要复制的文件**（旧目录历史遗留，约 1.7GB）：

| 文件 | 大小 | 原因 |
|------|------|------|
| `app.py` | 5KB | 旧构建遗留 |
| `build_xiaozhi.log` | 170KB | 旧构建日志 |
| `deploy-*.sh` (3个) | - | 旧部署脚本 |
| `docker-compose-*.yml` (4个) | - | 旧 compose 文件 |
| `Dockerfile.arm64*` (2个) | - | 旧构建文件 |
| `.dockerignore` | - | 旧构建文件 |
| `manager-web-arm64-latest.tar` | 58MB | 旧镜像包 |
| `xiaozhi-server-arm64-latest.tar` | 1.6GB | 旧镜像包 |
| `mysql_backup_*` (2个) | - | 旧备份 |
| `nginx-manager-web.conf` | - | 旧 nginx 配置 |
| `requirements.txt` | - | 旧依赖文件 |

---

## 风险分析

| 风险 | 影响 | 缓解措施 |
|------|------|----------|
| 官方镜像与自定义 core/ 代码不兼容 | 服务启动报错 | 回滚：切回旧目录，旧 core/ 天然兼容 |
| 拉取镜像占用大量磁盘空间 | 磁盘满导致拉取失败 | 升级前检查磁盘空间，预留 10GB |
| 新版本 Docker 网络导致 FunASR 断连 | ASR 功能不可用 | 升级/回滚后重新连接网络 |

**核心保障**: 旧目录 `~/xiaozhi-dev/` 从头到尾不被修改。回滚 = 停新服务 + 启旧服务，和升级前的状态完全一致。

---

## 升级前检查

### 检查 1：磁盘空间

```bash
df -h /home/axonex
```

确保可用空间 ≥ 10GB（新镜像 server 约 7GB + web 约 350MB + MySQL 数据复制）。如果空间不足，先清理：

```bash
docker image prune -f
```

### 检查 2：当前服务状态正常

```bash
cd ~/xiaozhi-dev && docker compose ps
```

确认所有容器状态为 healthy 或 running。**不要在服务异常时升级**，先修复再升级。

### 检查 3：记录当前版本信息（用于对比）

```bash
docker images --format '{{.Repository}}:{{.Tag}}  {{.ID}}  {{.Size}}' | grep -E 'xiaozhi-esp32-server:arm64|xiaozhi-manager-api:arm64|manager-web:arm64'
```

把输出保存下来，回滚后可对比确认。

---

## 升级步骤

### 第 1 步：创建新目录

```bash
ssh axonex@100.69.157.38
mkdir -p ~/xiaozhi-dev-4-20
```

### 第 2 步：复制必要的文件到新目录

```bash
# 复制配置（12KB）
cp -r ~/xiaozhi-dev/data ~/xiaozhi-dev-4-20/

# 复制模型（893MB）
mkdir -p ~/xiaozhi-dev-4-20/models/SenseVoiceSmall
cp ~/xiaozhi-dev/models/SenseVoiceSmall/model.pt ~/xiaozhi-dev-4-20/models/SenseVoiceSmall/

# 复制 core 自定义代码（1.8MB）
cp -r ~/xiaozhi-dev/core ~/xiaozhi-dev-4-20/

# 复制 uploadfile（12KB）
cp -r ~/xiaozhi-dev/uploadfile ~/xiaozhi-dev-4-20/ 2>/dev/null
```

验证文件完整：

```bash
ls -la ~/xiaozhi-dev-4-20/
ls -la ~/xiaozhi-dev-4-20/data/
ls -la ~/xiaozhi-dev-4-20/models/SenseVoiceSmall/
ls -la ~/xiaozhi-dev-4-20/core/
```

> **注意**: MySQL 数据暂时不复制，需要在第 4 步停服务后操作。

### 第 3 步：上传新的 compose 文件

在本地 Windows 执行：

```bash
scp docker-compose-final-new.yml axonex@100.69.157.38:~/xiaozhi-dev-4-20/docker-compose-final.yml
```

在服务器上验证文件已更新：

```bash
grep ghcr.nju.edu.cn ~/xiaozhi-dev-4-20/docker-compose-final.yml
```

应该看到 2 行匹配（server_latest 和 web_latest）。

### 第 4 步：停止旧服务

```bash
cd ~/xiaozhi-dev && docker compose down
```

验证容器已停止：

```bash
docker ps | grep xiaozhi
```

应该没有任何输出。

> **注意**: `docker compose down` 会删除 `xiaozhi-dev_default` 网络。FunASR 容器会断连，在第 8 步重新连接。

### 第 5 步：复制 MySQL 数据

旧服务已停止，MySQL 文件现在可以读取。需要 sudo 因为文件属于 mysql 用户。

```bash
mkdir -p ~/xiaozhi-dev-4-20/mysql
sudo cp -r ~/xiaozhi-dev/mysql/data ~/xiaozhi-dev-4-20/mysql/data
sudo chown -R axonex:axonex ~/xiaozhi-dev-4-20/mysql/data
```

验证 MySQL 数据复制完整：

```bash
ls ~/xiaozhi-dev-4-20/mysql/data/ | head -5
```

### 第 6 步：拉取最新官方镜像

```bash
cd ~/xiaozhi-dev-4-20
docker compose pull
```

等待下载完成。镜像较大（server 约 7GB，web 约 350MB），取决于网速可能需要几分钟。

> **如果拉取失败**（网络超时、磁盘满等），直接跳到回滚步骤。旧目录完好无损，随时可以恢复。

### 第 7 步：启动新服务

```bash
cd ~/xiaozhi-dev-4-20 && docker compose up -d
```

### 第 8 步：重新连接 FunASR 网络

```bash
docker network connect xiaozhi-dev-4-20_default funasr-gpu 2>/dev/null
docker network connect xiaozhi-dev-4-20_default cosyvoice-tts 2>/dev/null
```

> 注意网络名称：新目录的网络名为 `xiaozhi-dev-4-20_default`（由目录名决定）。

### 第 9 步：验证

```bash
# 检查所有容器状态（等 30 秒让服务完全启动）
sleep 30
cd ~/xiaozhi-dev-4-20 && docker compose ps

# 检查主服务日志
docker logs xiaozhi-esp32-server --tail 30
docker logs xiaozhi-esp32-server-web --tail 30

# 验证 FunASR 网络连通性
docker exec funasr-gpu python3 -c "
import socket
s = socket.socket()
r = s.connect_ex(('xiaozhi-esp32-server', 8003))
print('OK' if r == 0 else 'FAIL')
s.close()
"
```

验证清单：

- [ ] `xiaozhi-esp32-server` 容器状态为 healthy 或 running
- [ ] `xiaozhi-esp32-server-web` 容器状态为 healthy 或 running
- [ ] `xiaozhi-esp32-server-db` 容器状态为 healthy
- [ ] `xiaozhi-esp32-server-redis` 容器状态为 healthy
- [ ] 端口 8000 可访问（WebSocket）
- [ ] 端口 8002 可访问（智控台 http://100.69.157.38:8002/）
- [ ] FunASR 网络连通（测试返回 OK）
- [ ] ESP32 设备能正常连接和对话

**全部通过 → 升级成功。**
**任何一项失败 → 执行下面的回滚步骤。**

---

## 回滚步骤（如果出问题）

### 快速回滚（一键执行）

```bash
cd ~/xiaozhi-dev-4-20 && docker compose down && \
cd ~/xiaozhi-dev && docker compose up -d && \
sleep 10 && \
docker network connect xiaozhi-dev_default funasr-gpu 2>/dev/null && \
docker network connect xiaozhi-dev_default cosyvoice-tts 2>/dev/null && \
echo "回滚完成"
```

### 分步回滚（便于排查）

#### 第 1 步：停止新服务

```bash
cd ~/xiaozhi-dev-4-20 && docker compose down
```

#### 第 2 步：启动旧服务

```bash
cd ~/xiaozhi-dev && docker compose up -d
```

旧目录的 compose 文件、镜像、配置全部没有被修改过，启动后就是升级前的状态。

#### 第 3 步：重新连接 FunASR 网络

```bash
docker network connect xiaozhi-dev_default funasr-gpu 2>/dev/null
docker network connect xiaozhi-dev_default cosyvoice-tts 2>/dev/null
```

> 注意：这里用旧网络名 `xiaozhi-dev_default`。

#### 第 4 步：验证回滚

```bash
# 确认容器数量（旧版本应该有 5 个容器）
cd ~/xiaozhi-dev && docker compose ps

# 检查服务日志
docker logs xiaozhi-esp32-server --tail 10
```

回滚验证清单：

- [ ] 容器数量为 5 个（server + web + api + db + redis）
- [ ] 所有容器状态为 healthy 或 running
- [ ] 端口 8000、8002、8003 正常访问
- [ ] FunASR 连通性正常
- [ ] ESP32 设备能正常连接和对话

---

## 回滚为什么能完全还原

| 还原项 | 机制 | 说明 |
|--------|------|------|
| Docker 镜像 | 旧目录未修改 | `xiaozhi-esp32-server:arm64-latest` 等镜像标签指向旧镜像 |
| Compose 文件 | 旧目录未修改 | `~/xiaozhi-dev/docker-compose-final.yml` 内容完全不变 |
| MySQL 数据 | 旧目录未修改 | `~/xiaozhi-dev/mysql/data/` 不被触碰，回滚后继续使用 |
| core/ 自定义代码 | 旧目录未修改 | `~/xiaozhi-dev/core/` 完全不被触碰 |
| 配置文件 | 旧目录未修改 | `~/xiaozhi-dev/data/.config.yaml` 不被触碰 |
| 模型文件 | 旧目录未修改 | `~/xiaozhi-dev/models/` 不被触碰 |

**旧目录 `~/xiaozhi-dev/` 从头到尾没有被修改过任何文件，回滚 = 停新启动旧。**

---

## 升级后清理（确认稳定后再执行）

确认新版本稳定运行 1-2 天后，可以删除旧目录释放磁盘空间：

```bash
# 停掉旧服务（如果还在运行的话）
cd ~/xiaozhi-dev && docker compose down 2>/dev/null

# 删除旧目录
rm -rf ~/xiaozhi-dev

# 清理旧的自建镜像
docker rmi xiaozhi-esp32-server:arm64-latest xiaozhi-manager-api:arm64-latest manager-web:arm64-latest

# 清理无标签的悬空镜像
docker image prune -f
```

> **注意**: 删除旧目录和旧镜像后无法再回滚。建议至少运行 1-2 天稳定后再清理。

---

## 注意事项

1. **core/ 目录挂载保留**: 新 compose 仍然挂载 `./core:/opt/xiaozhi-esp32-server/core`，之前对 VAD 等模块的修改仍然生效。但如果新版本的代码结构有变化（模块重命名、函数签名改变等），core/ 里的旧代码可能导致冲突。此时需要更新 core/ 代码以匹配新版本。

2. **两个目录不能同时运行**: 端口 8000、8002、8003 相同，同时启动会冲突。回滚时必须先停新服务再启旧服务。

3. **FunASR 网络重连**: 每次切换版本，Docker 网络会被重建，FunASR 容器需要重新连接。注意网络名不同：旧版本是 `xiaozhi-dev_default`，新版本是 `xiaozhi-dev-4-20_default`。

4. **端口不变**: 外部访问端口（8000、8002、8003、3307、6380）完全不变。ESP32 设备和 WebUI 无需做任何修改。

5. **智控台结构变化**: 旧版本有 5 个容器（server + api + manager-web + db + redis），新版本有 4 个容器（server + web + db + redis）。`manager-web` 容器不再存在，智控台功能合并到 `xiaozhi-esp32-server-web` 容器中。

6. **web_latest 镜像的 Java API 端口为 8003**: 旧版本 manager-api 使用内部端口 8080，新版本 `web_latest` 镜像的 Java API 监听端口 8003。复制 `.config.yaml` 后必须修改 `manager-api.url` 从 `http://xiaozhi-esp32-server-web:8080/xiaozhi` 改为 `http://xiaozhi-esp32-server-web:8003/xiaozhi`，否则 server 容器启动后无法连接 manager-api。

7. **官方镜像不含 curl**: `web_latest` 和 `server_latest` 容器内没有 `curl` 命令，docker-compose 中的 healthcheck 使用 curl 会持续失败（显示 unhealthy），但不影响服务正常运行。如需健康检查，server 容器可用 `python3`，web 容器可用 `wget`。

---

## 升级实际记录（2026-04-20）

**升级结果**: ✅ 成功

**实际版本**: v0.9.2 (官方 `server_latest` + `web_latest`)

**遇到的问题及解决**:

| 问题 | 原因 | 解决方案 |
|------|------|----------|
| server 容器启动后报 `POST /config/server-base` 连接错误 | `.config.yaml` 中 `manager-api.url` 端口为 8080，但 `web_latest` 的 Java API 监听 8003 | `sed -i 's/:8080/:8003/' ~/xiaozhi-dev-4-20/data/.config.yaml` |
| docker compose 使用错误的文件 | 目录中有多个 compose 文件，`docker compose` 默认使用 `docker-compose.yml` | 将上传的文件重命名为 `docker-compose.yml` |
| web 容器 healthcheck 失败（unhealthy） | 官方镜像不含 curl | 不影响实际运行，忽略健康检查状态 |

**验证通过项**:

- [x] server 容器 v0.9.2 启动成功
- [x] web 容器正常运行（Java API + 前端）
- [x] MySQL、Redis 正常
- [x] 端口 8000、8002 可访问
- [x] FunASR 网络连通
- [x] CosyVoice 网络连通
- [x] WebUI WebSocket 连接正常，配置获取成功
- [x] ASR_FunASRServer 初始化成功
- [x] MCP 接入点连接成功

---

## 文件对照

| 文件 / 目录 | 位置 | 用途 |
|-------------|------|------|
| `docker-compose-final-new.yml` | 本地仓库 | 新的 compose 文件模板 |
| `docker-compose-final.yml` | `~/xiaozhi-dev/` | 旧 compose 文件（不修改） |
| `docker-compose-final.yml` | `~/xiaozhi-dev-4-20/` | 新 compose 文件（上传后） |
| `xiaozhi-server升级指南.md` | 本地仓库 | 本文档 |

---

## 后续服务更新

> 当前已迁移到官方预构建镜像，后续更新只需拉取最新镜像并重启即可。

### 更新步骤

```bash
ssh axonex@100.69.157.38

# 1. 拉取最新镜像
cd ~/xiaozhi-dev-4-20 && docker compose pull

# 2. 重启服务（会自动使用新镜像）
docker compose down && docker compose up -d

# 3. 重新连接 FunASR / CosyVoice 网络
docker network connect xiaozhi-dev-4-20_default funasr-gpu 2>/dev/null
docker network connect xiaozhi-dev-4-20_default cosyvoice-tts 2>/dev/null

# 4. 验证
sleep 30
docker compose ps
docker logs xiaozhi-esp32-server --tail 20
```

### 验证清单

- [ ] `xiaozhi-esp32-server` 容器正常运行
- [ ] `xiaozhi-esp32-server-web` 容器正常运行
- [ ] 端口 8000、8002 可访问
- [ ] FunASR / CosyVoice 连通
- [ ] WebUI 能正常连接对话

### 注意事项

1. **更新前确认服务正常**，不要在异常状态下更新
2. **core/ 挂载的代码不会随镜像更新**，如果新版本修改了 core/ 中的模块结构，需要手动同步代码
3. **config.yaml 不会自动更新**，新版本如有新增配置项需要手动添加
4. **如果更新后出问题**，旧镜像标签仍存在（`server_latest`、`web_latest` 会指向最新版），Docker 会保留之前的镜像层，可用 `docker images` 查看历史镜像并手动回退
5. **磁盘清理**：多次更新后旧镜像层会占用空间，定期执行 `docker image prune -f` 清理
