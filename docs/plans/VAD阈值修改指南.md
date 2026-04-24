# VAD 阈值修改指南

## 配置存储位置

VAD 的实际配置**不在 config.yaml**，而是在**数据库 `ai_model_config` 表**中。

| 位置 | 作用 | 是否有效 |
|------|------|---------|
| `config.yaml` → `VAD.SileroVAD.threshold` | 镜像内的默认配置 | 无效（被 API 覆盖） |
| `ai_model_config.config_json` | 数据库中的实际配置 | **有效** |
| 智控台 Web 界面 | 操作数据库 | **有效** |

## 为什么改 config.yaml 不生效

服务器的配置加载链路（`config/config_loader.py`）：

```
启动
 └── load_config()
      └── 检查 data/.config.yaml 是否配置了 manager-api.url
           │
           ├── 有 → get_config_from_api_async() → 从 Java API 获取配置 ← 当前走这条
           │       └── API 从数据库 ai_model_config 表读取
           │
           └── 没有 → merge_configs(default_config, custom_config) → 读 config.yaml
```

当 `data/.config.yaml` 配置了 `manager-api.url`（智控台部署模式），**所有配置从 Java API 获取**，config.yaml 只作为不启用智控台时的本地配置。

## 修改方法

### 方法一：数据库直接修改（推荐）

```bash
# 查看当前 VAD 配置
docker exec xiaozhi-esp32-server-db mysql -uroot -p123456 -D xiaozhi_esp32_server \
  --default-character-set=utf8mb4 \
  -e "SELECT id, config_json FROM ai_model_config WHERE id='VAD_SileroVAD';"

# 修改阈值（例如改为 0.9）
docker exec xiaozhi-esp32-server-db mysql -uroot -p123456 -D xiaozhi_esp32_server \
  --default-character-set=utf8mb4 \
  -e "UPDATE ai_model_config SET config_json = JSON_SET(config_json, '$.threshold', '0.9') WHERE id='VAD_SileroVAD';"
```

### 方法二：智控台 Web 界面

在智控台的模型配置页面直接修改 VAD 模型的参数。

## 修改后必须做的事

改完数据库后，**必须重启 web 容器和 server 容器**，否则不生效：

```bash
# 1. 重启 web 容器（清除 Java API 缓存）
docker restart xiaozhi-esp32-server-web

# 2. 等待 web 容器就绪（约 15 秒）
sleep 15

# 3. 重启 server 容器（清除 Python 端配置缓存）
docker restart xiaozhi-esp32-server
```

### 为什么需要重启两个容器

1. **web 容器**（Java API）：有内部缓存，数据库改了但 API 仍返回旧值，必须重启才能刷新
2. **server 容器**（Python）：`config_loader.py` 使用 `cache_manager` 缓存配置（`CacheType.CONFIG, "main_config"`），必须重启才能重新从 API 拉取

## VAD 参数说明

| 参数 | 数据库字段 | 默认值 | 说明 |
|------|-----------|--------|------|
| threshold | `$.threshold` | 0.5 | 语音判定阈值，高于此值判定为有声音 |
| threshold_low | `$.threshold_low` | 0.2 | 低阈值，低于此值判定为无声音（双阈值防抖） |
| min_silence_duration_ms | `$.min_silence_duration_ms` | 700 | 静音多久后认为一句话说完（毫秒） |

### 阈值调节建议

| threshold 值 | 效果 |
|-------------|------|
| 0.5（默认） | 灵敏，容易误触发环境噪音 |
| 0.7 | 适中，过滤部分噪音 |
| 0.9 | 不灵敏，需要较大音量才触发，适合嘈杂环境 |

## 验证方法

```bash
# 查看 VAD 实时概率值（需在 silero.py 中已添加 print 调试行）
docker logs xiaozhi-esp32-server --tail 100 2>&1 | grep 'VAD'

# 输出示例：
# [VAD] prob=0.741 voice=□   ← 0.741 < 0.9，未触发
# [VAD] prob=0.952 voice=■   ← 0.952 >= 0.9，触发

# 验证 API 返回的配置值
docker exec xiaozhi-esp32-server python3 -c "
import asyncio, yaml
async def test():
    from config.manage_api_client import init_service, get_server_config
    with open('/opt/xiaozhi-esp32-server/data/.config.yaml', 'r') as f:
        cfg = yaml.safe_load(f)
    init_service(cfg)
    config = await get_server_config()
    print('VAD:', config.get('VAD', {}))
asyncio.run(test())
"
```

## 相关代码文件

| 文件 | 作用 |
|------|------|
| `config/config_loader.py` | 配置加载入口，决定读 config.yaml 还是 API |
| `config/manage_api_client.py` | 从 Java API 获取配置 |
| `core/utils/modules_initialize.py:80-88` | VAD 模块初始化，将 config 传入构造函数 |
| `core/providers/vad/silero.py:27-32` | 读取 threshold 配置并设置 `self.vad_threshold` |
| 数据库 `ai_model_config` 表 | VAD 参数实际存储位置 |
