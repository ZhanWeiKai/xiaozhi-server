#!/bin/bash
# 同时启动 Flask HTTP 服务和 WebSocket 流式服务

echo "=== 启动 start_all.sh ==="

# 启动 Flask 服务（原有HTTP接口，端口3000）
python flask_server.py --port 3000 --model_dir FunAudioLLM/Fun-CosyVoice3-0.5B-2512 &
FLASK_PID=$!
echo "Flask HTTP 服务已启动, PID=$FLASK_PID"

# 启动 WebSocket 流式服务（端口3001）
python ws_server.py --port 3001 --model_dir FunAudioLLM/Fun-CosyVoice3-0.5B-2512 --voice default &
WS_PID=$!
echo "WebSocket 流式服务已启动, PID=$WS_PID"

# 等待任一进程退出
wait -n $FLASK_PID $WS_PID
EXIT_CODE=$?

echo "=== 进程退出 (exit_code=$EXIT_CODE)，关闭所有服务 ==="
kill $FLASK_PID $WS_PID 2>/dev/null
wait $FLASK_PID $WS_PID 2>/dev/null

exit $EXIT_CODE
