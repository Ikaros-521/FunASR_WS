import subprocess
import json
import os
import argparse
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
import uvicorn
from loguru import logger

logger.add("webui-log.txt", level="INFO", rotation="200 MB")

app = FastAPI()

# 允许跨域
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 设置静态文件路径
app.mount("/web", StaticFiles(directory="web"), name="web")

# 路由到静态的 index.html
@app.get("/")
async def get_index():
    return FileResponse("web/index.html")

# 在程序退出前执行stop_program()函数
@app.on_event("shutdown")
async def shutdown_event():
    os._exit(0)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run the FastAPI server with optional SSL.")
    parser.add_argument("--ssl", action="store_true", help="Enable SSL (HTTPS) mode")
    args = parser.parse_args()

    if args.ssl:
        # 启用 HTTPS
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8101,
            ssl_keyfile="key.pem",
            ssl_certfile="cert.pem"
        )
    else:
        # 仅 HTTP
        uvicorn.run(
            app,
            host="0.0.0.0",
            port=8101
        )