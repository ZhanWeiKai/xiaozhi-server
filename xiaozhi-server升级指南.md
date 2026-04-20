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

## 升级步骤

### 第 1 步：备份现有镜像

在服务器上执行（SSH 连接后）：

```bash
ssh axonex@100.69.157.38
cd ~/xiaozhi-dev
```

```bash
docker tag xiaozhi-esp32-server:arm64-latest xiaozhi-esp32-server:arm64-backup-20260420
docker tag xiaozhi-manager-api:arm64-latest xiaozhi-manager-api:arm64-backup-20260420
docker tag manager-web:arm64-latest manager-web:arm64-backup-20260420
```

验证备份成功：

```bash
docker images | grep backup-20260420
```

应该看到 3 个带 `arm64-backup-20260420` 标签的镜像。

### 第 2 步：备份当前 compose 文件

```bash
cp docker-compose-final.yml docker-compose-final.yml.bak
```

### 第 3 步：停止现有容器

```bash
docker compose -f docker-compose-final.yml down
```

验证容器已停止：

```bash
docker ps | grep xiaozhi
```

应该没有任何输出（MySQL 和 Redis 数据不受影响，数据在 `./mysql/data/` 卷里）。

### 第 4 步：上传新的 compose 文件

在本地 Windows 执行：

```bash
scp docker-compose-final-new.yml axonex@100.69.157.38:~/xiaozhi-dev/docker-compose-final.yml
```

### 第 5 步：拉取最新官方镜像

```bash
cd ~/xiaozhi-dev
docker compose pull
```

等待下载完成。镜像较大（server 约 7GB，web 约 350MB），取决于网速可能需要几分钟。

### 第 6 步：启动服务

```bash
docker compose up -d
```

### 第 7 步：验证

```bash
# 检查所有容器状态
docker compose ps

# 检查主服务日志
docker logs xiaozhi-esp32-server --tail 30

# 检查智控台日志
docker logs xiaozhi-esp32-server-web --tail 30
```

验证清单：

- [ ] `xiaozhi-esp32-server` 容器状态为 healthy 或 running
- [ ] `xiaozhi-esp32-server-web` 容器状态为 healthy 或 running
- [ ] `xiaozhi-esp32-server-db` 容器状态为 healthy
- [ ] `xiaozhi-esp32-server-redis` 容器状态为 healthy
- [ ] 端口 8000 可访问（WebSocket）
- [ ] 端口 8002 可访问（智控台 http://100.69.157.38:8002/）
- [ ] ESP32 设备能正常连接和对话

---

## 回滚步骤（如果出问题）

### 第 1 步：停止新容器

```bash
cd ~/xiaozhi-dev
docker compose down
```

### 第 2 步：恢复旧 compose 文件

```bash
cp docker-compose-final.yml.bak docker-compose-final.yml
```

### 第 3 步：恢复旧镜像标签

```bash
docker tag xiaozhi-esp32-server:arm64-backup-20260420 xiaozhi-esp32-server:arm64-latest
docker tag xiaozhi-manager-api:arm64-backup-20260420 xiaozhi-manager-api:arm64-latest
docker tag manager-web:arm64-backup-20260420 manager-web:arm64-latest
```

### 第 4 步：启动旧服务

```bash
docker compose -f docker-compose-final.yml up -d
```

### 第 5 步：验证回滚

```bash
docker compose ps
docker logs xiaozhi-esp32-server --tail 10
```

确认一切恢复到升级前的状态。

---

## 注意事项

1. **core/ 目录挂载保留**: 新 compose 仍然挂载 `./core:/opt/xiaozhi-esp32-server/core`，之前对 VAD 等模块的修改仍然生效。官方镜像自带一份默认代码，core/ 挂载会覆盖其中的同名文件。

2. **MySQL 数据安全**: 数据存储在 `./mysql/data/` 目录，不受镜像更换影响。升级前后数据不会丢失。

3. **FunASR GPU 服务**: FunASR 容器连接到 `xiaozhi-dev_default` 网络，升级不影响它。但如果网络名称或配置有变化，需要确认 FunASR 容器的网络配置。

4. **端口不变**: 外部访问端口（8000、8002、8003、3307、6380）完全不变。ESP32 设备和 WebUI 无需做任何修改。

5. **智控台结构变化**: 旧版本有 3 个自定义容器（server + api + manager-web），新版本只有 4 个容器（server + web + db + redis）。`manager-web` 容器不再存在，智控台功能合并到 `xiaozhi-esp32-server-web` 容器中。

---

## 文件对照

| 文件 | 用途 |
|------|------|
| `docker-compose-final-new.yml` | 新的 compose 文件（官方镜像） |
| `docker-compose-final.yml.bak` | 旧 compose 文件备份 |
| `docker-compose-final.yml` | 当前使用的 compose 文件（升级后 = new） |
