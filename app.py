import gradio as gr
import requests
import os

def to_srt(sentences):
    def format_time(sec):
        ms = int((sec - int(sec)) * 1000)
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    srt = ""
    for idx, seg in enumerate(sentences, 1):
        srt += f"{idx}\n{format_time(seg['start'])} --> {format_time(seg['end'])}\n{seg['text']}\n\n"
    return srt.strip()

def asr_recognize(audio_path, use_ssl):
    url = "https://127.0.0.1:8000/recognition" if use_ssl else "http://127.0.0.1:8000/recognition"
    files = {'audio': open(audio_path, 'rb')}
    try:
        resp = requests.post(url, files=files, verify=False)
        data = resp.json()
        if data.get("code", 1) != 0:
            return f"识别失败: {data.get('msg', '未知错误')}", ""
        text = data["text"]
        srt = to_srt(data.get("sentences", []))
        return data, text, srt
    except Exception as e:
        return f"请求失败: {e}", "", ""

with gr.Blocks() as demo:
    gr.Markdown("# 语音识别演示")
    with gr.Row():
        audio_file = gr.Audio(
            label="上传或录制音频（支持WAV上传或直接录音）",
            sources=["upload", "microphone"],
            type="filepath"
        )
        use_ssl = gr.Checkbox(label="使用SSL(HTTPS)", value=False)
    btn = gr.Button("识别")
    ori_data = gr.Textbox(label="原始数据")
    text_out = gr.Textbox(label="识别文本")
    srt_out = gr.Textbox(label="SRT字幕")
    btn.click(asr_recognize, inputs=[audio_file, use_ssl], outputs=[ori_data, text_out, srt_out])

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssl", action="store_true", help="以SSL方式启动Gradio")
    args = parser.parse_args()
    if args.ssl:
        demo.launch(
            server_name="0.0.0.0",
            ssl_certfile="cert.pem",
            ssl_keyfile="key.pem",
            ssl_verify=False
        )
    else:
        demo.launch(server_name="0.0.0.0")