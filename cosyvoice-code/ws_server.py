"""
DashScope 协议兼容的 WebSocket TTS 服务器
让 cosyvoice_local_ws.py 可以通过 DashScope 协议连接本地 CosyVoice 模型

用法：python ws_server.py --port 3001 --model_dir FunAudioLLM/Fun-CosyVoice3-0.5B-2512 --voice default
"""

import os
import sys
import json
import uuid
import argparse
import asyncio
import struct
import numpy as np
import websockets
from concurrent.futures import ThreadPoolExecutor

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))

# CosyVoice imports（容器内已安装）
from cosyvoice.cli.cosyvoice import AutoModel
from cosyvoice.utils.file_utils import logging as cosyvoice_logger

# 配置日志
import logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(name)s - %(message)s'
)
logger = logging.getLogger("ws_server")

# 全局模型实例
cosyvoice = None
cosyvoice_sample_rate = 48000


def load_model(model_dir):
    """加载 CosyVoice 模型"""
    global cosyvoice, cosyvoice_sample_rate
    cosyvoice = AutoModel(model_dir=model_dir, fp16=True)
    cosyvoice_sample_rate = cosyvoice.sample_rate
    logger.info("CosyVoice 模型加载完成: %s, 采样率: %d", model_dir, cosyvoice_sample_rate)


def get_voice_config(voice_name):
    """获取音色配置，返回 (wav_path, prompt_text)"""
    voices_dir = os.path.join(ROOT_DIR, 'voices')
    wav_path = os.path.join(voices_dir, voice_name + '.wav')
    txt_path = os.path.join(voices_dir, voice_name + '.txt')

    if not os.path.exists(wav_path):
        return None, None

    prompt_text = ''
    if os.path.exists(txt_path):
        with open(txt_path, 'r', encoding='utf-8') as f:
            prompt_text = f.read().strip()

    return wav_path, prompt_text


def synthesize_stream(tts_text, prompt_text, prompt_wav_path, speed=1.0, voice_name=''):
    """
    流式合成语音，返回 PCM 音频块生成器
    每个 yield 返回 int16 numpy array
    """
    set_all_random_seed(42)
    cosyvoice_logger.info('WebSocket TTS: zero_shot STREAMING mode, text=%s...', tts_text[:50])

    # 预缓存音色
    if voice_name and prompt_wav_path and prompt_text:
        try:
            cosyvoice.add_zero_shot_spk(prompt_text, prompt_wav_path, voice_name)
        except Exception as e:
            logger.warning("预缓存音色失败: %s, 继续...", e)

    generator = cosyvoice.inference_zero_shot(
        tts_text, prompt_text, prompt_wav_path,
        zero_shot_spk_id=voice_name,
        stream=True, speed=speed, text_frontend=False
    )
    for item in generator:
        pcm_float = item['tts_speech'].numpy().flatten()
        int16 = (pcm_float * 32767).astype(np.int16)
        yield int16


def set_all_random_seed(seed):
    """设置所有随机种子以确保可复现性"""
    import random as _random
    import numpy as _np
    _random.seed(seed)
    _np.random.seed(seed)


def resample_pcm(pcm_data, from_rate, to_rate):
    """重采样 PCM 数据（numpy int16 array）"""
    if from_rate == to_rate:
        return pcm_data
    duration = len(pcm_data) / from_rate
    target_length = int(duration * to_rate)
    if target_length == 0:
        return pcm_data
    indices = np.linspace(0, len(pcm_data) - 1, target_length)
    resampled = np.interp(indices, np.arange(len(pcm_data)), pcm_data.astype(np.float64))
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def adjust_volume(pcm_data, volume):
    """调整音量 (0-100)，默认 50 为不调整"""
    if volume is None or volume == 50:
        return pcm_data
    factor = volume / 50.0
    adjusted = (pcm_data.astype(np.float64) * factor)
    return np.clip(adjusted, -32768, 32767).astype(np.int16)


async def handle_client(websocket, default_voice, default_prompt_text, default_prompt_wav):
    """处理单个 WebSocket 客户端连接"""
    session_params = {}
    task_id = None

    try:
        async for message in websocket:
            if isinstance(message, bytes):
                continue  # 客户端不发二进制数据

            data = json.loads(message)
            header = data.get("header", {})
            payload = data.get("payload", {})
            action = header.get("action")
            task_id = header.get("task_id", str(uuid.uuid4()))

            if action == "run-task":
                # 启动任务，解析参数
                params = payload.get("parameters", {})
                voice_name = params.get("voice", default_voice)
                model_dir = params.get("model_dir", "")
                target_sample_rate = params.get("sample_rate", 16000)
                volume = params.get("volume", 50)
                speed = params.get("rate", 1.0)

                # 解析参考音频
                # voice 参数可能是：音色名称（从 voices/ 目录查找）或直接文件路径
                if os.path.isabs(voice_name) and os.path.exists(voice_name):
                    prompt_wav = voice_name
                    prompt_text = params.get("prompt_text", default_prompt_text)
                else:
                    # 从 voices 目录查找
                    wav, txt = get_voice_config(voice_name)
                    if wav:
                        prompt_wav = wav
                        prompt_text = txt
                    else:
                        # 使用默认音色
                        prompt_wav = default_prompt_wav
                        prompt_text = default_prompt_text
                        logger.warning("音色 '%s' 未找到，使用默认音色", voice_name)

                session_params = {
                    "voice_name": voice_name,
                    "prompt_wav": prompt_wav,
                    "prompt_text": prompt_text,
                    "target_sample_rate": target_sample_rate,
                    "volume": volume,
                    "speed": speed,
                }
                logger.info("任务启动 task_id=%s, voice=%s, sample_rate=%d, volume=%d, speed=%.1f",
                           task_id, voice_name, target_sample_rate, volume, speed)

                # 回复 task-started
                response = {
                    "header": {
                        "event": "task-started",
                        "task_id": task_id,
                        "request_id": str(uuid.uuid4())
                    },
                    "payload": {
                        "output": {
                            "task_id": task_id,
                            "task_status": "SUCCEEDED"
                        }
                    }
                }
                await websocket.send(json.dumps(response))

            elif action == "continue-task":
                # 接收到待合成文本
                text = payload.get("input", {}).get("text", "")
                if not text:
                    continue

                # 处理可能的 <|endofprompt|> 分隔符
                if '<|endofprompt|>' in text:
                    text = text.split('<|endofprompt|>', 1)[1].strip()

                if not text:
                    continue

                logger.info("收到文本: %s", text[:50])

                # 在线程池中执行合成，避免阻塞事件循环
                voice_name = session_params.get("voice_name", default_voice)
                prompt_wav = session_params.get("prompt_wav", default_prompt_wav)
                prompt_text = session_params.get("prompt_text", default_prompt_text)
                speed = session_params.get("speed", 1.0)

                loop = asyncio.get_event_loop()
                audio_chunks = []

                def run_synthesis():
                    for chunk in synthesize_stream(
                        tts_text=text,
                        prompt_text=prompt_text,
                        prompt_wav_path=prompt_wav,
                        speed=speed,
                        voice_name=voice_name,
                    ):
                        audio_chunks.append(chunk)

                with ThreadPoolExecutor(max_workers=1) as executor:
                    future = executor.submit(run_synthesis)
                    while not future.done():
                        # 定期检查客户端是否断开（通过尝试 peek）
                        try:
                            await asyncio.wait_for(asyncio.sleep(0.1), timeout=0.2)
                        except asyncio.TimeoutError:
                            pass
                    future.result()  # 获取结果或异常

                # 发送音频数据
                target_rate = session_params.get("target_sample_rate", 16000)
                volume = session_params.get("volume", 50)

                for chunk in audio_chunks:
                    # 重采样（48000 → 目标采样率）
                    resampled = resample_pcm(chunk, cosyvoice_sample_rate, target_rate)
                    # 调整音量
                    adjusted = adjust_volume(resampled, volume)
                    # 发送二进制 PCM 数据
                    await websocket.send(adjusted.tobytes())

                # 发送 result-generated
                response = {
                    "header": {
                        "event": "result-generated",
                        "task_id": task_id
                    },
                    "payload": {
                        "output": {"audio_url": ""}
                    }
                }
                await websocket.send(json.dumps(response))
                logger.info("文本合成完成: %s", text[:50])

            elif action == "finish-task":
                # 结束任务
                response = {
                    "header": {
                        "event": "task-finished",
                        "task_id": task_id
                    },
                    "payload": {
                        "output": {
                            "task_id": task_id,
                            "task_status": "SUCCEEDED"
                        }
                    }
                }
                await websocket.send(json.dumps(response))
                logger.info("任务结束 task_id=%s", task_id)

    except websockets.ConnectionClosed:
        logger.info("客户端断开连接")
    except Exception as e:
        logger.error("处理客户端出错: %s", e, exc_info=True)


async def main():
    parser = argparse.ArgumentParser(description="CosyVoice DashScope WebSocket Server")
    parser.add_argument("--port", type=int, default=3001, help="WebSocket 监听端口")
    parser.add_argument("--host", type=str, default="0.0.0.0", help="监听地址")
    parser.add_argument("--model_dir", type=str, default="FunAudioLLM/Fun-CosyVoice3-0.5B-2512", help="模型目录")
    parser.add_argument("--voice", type=str, default="default", help="默认音色名称（对应 voices/ 目录下的 wav 文件名）")
    args = parser.parse_args()

    # 加载模型
    load_model(args.model_dir)

    # 加载默认音色
    default_prompt_wav, default_prompt_text = get_voice_config(args.voice)
    if default_prompt_wav is None:
        logger.warning("默认音色 '%s' 未找到，请确保 voices/ 目录下有对应的 wav 文件", args.voice)
        default_prompt_wav = ""
        default_prompt_text = ""
    else:
        logger.info("默认音色: %s, 参考音频: %s", args.voice, default_prompt_wav)
        # 预缓存
        try:
            cosyvoice.add_zero_shot_spk(default_prompt_text, default_prompt_wav, args.voice)
            logger.info("默认音色预缓存完成")
        except Exception as e:
            logger.warning("默认音色预缓存失败: %s", e)

    logger.info("WebSocket 服务器启动: ws://%s:%d", args.host, args.port)

    async def client_handler(websocket):
        await handle_client(websocket, args.voice, default_prompt_text, default_prompt_wav)

    async with websockets.serve(client_handler, args.host, args.port):
        await asyncio.Future()  # 永久运行


if __name__ == "__main__":
    asyncio.run(main())
