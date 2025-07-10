import av
import asyncio
import websockets
import json
import time

# 配置
RTMP_URL = "rtmp://127.0.0.1:1935/live/test"
WS_URL = "ws://127.0.0.1:10096"
CHUNK_SIZE = 16000  # 每次发送的采样点数
SAMPLE_RATE = 16000  # 采样率

async def asr_rtmp():
    async with websockets.connect(WS_URL) as ws:
        # 发送初始化参数
        request = {
            "chunk_size": [5, 10, 5],
            "wav_name": "rtmp",
            "is_speaking": True,
            "chunk_interval": 10,
            "itn": True,
            "mode": "online"
        }
        await ws.send(json.dumps(request))
        print("已发送初始化参数")

        # 启动接收ASR返回的协程
        async def recv_msg():
            try:
                async for message in ws:
                    print("ASR返回：", message[:100])
            except websockets.ConnectionClosed:
                print("WebSocket关闭")

        recv_task = asyncio.create_task(recv_msg())

        # 拉取RTMP音频流并发送
        container = av.open(RTMP_URL)
        pcm_buffer = b""
        for frame in container.decode(audio=0):
            pcm = frame.to_ndarray().tobytes()
            pcm_buffer += pcm
            while len(pcm_buffer) >= CHUNK_SIZE * 2:
                chunk = pcm_buffer[:CHUNK_SIZE * 2]
                pcm_buffer = pcm_buffer[CHUNK_SIZE * 2:]
                await ws.send(chunk)
                await asyncio.sleep(CHUNK_SIZE / SAMPLE_RATE)  # 控制发送速率

        await ws.close()
        await recv_task

if __name__ == "__main__":
    asyncio.run(asr_rtmp())