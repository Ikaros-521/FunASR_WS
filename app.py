import gradio as gr
import requests
import os
import json

def to_srt(sentences):
    def format_time(ms):
        total_ms = int(round(ms))
        ms = total_ms % 1000
        total_sec = total_ms // 1000
        h = total_sec // 3600
        m = (total_sec % 3600) // 60
        s = total_sec % 60
        return f"{h:02}:{m:02}:{s:02},{ms:03}"
    srt = ""
    for idx, seg in enumerate(sentences, 1):
        srt += f"{idx}\n{format_time(seg['start'])} --> {format_time(seg['end'])}\n{seg['text']}\n\n"
    return srt.strip()

def parse_asr_result(data):
    audio_info = {
        "Size": 670663,
        "Duration": 10394,
        "SampleRate": 48000,
        "Language": "cn"
    }
    paragraphs = [
        {
            "ParagraphId": "16987422100275*******",
            "SpeakerId": "1",
            "Words": [
                {
                    "Id": idx+1,
                    "SentenceId": idx+1,
                    "Start": seg["start"],
                    "End": seg["end"],
                    "Text": seg["text"]
                } for idx, seg in enumerate(data.get("sentences", []))
            ]
        }
    ]
    audio_segments = []
    for seg in data.get("sentences", []):
        audio_segments.append([seg["start"], seg["end"]])
    result = {
        "AudioInfo": audio_info,
        "Paragraphs": paragraphs,
        "AudioSegments": audio_segments
    }
    return json.dumps(result, ensure_ascii=False, indent=2)

def clean_text_result(data):
    # 生成【编号】发言人1：内容 的格式
    lines = []
    for idx, seg in enumerate(data.get("sentences", []), 1):
        lines.append(f"【{idx}】发言人1：{seg['text']}")
    return " ".join(lines)

def asr_recognize(audio_path, use_ssl):
    host = "127.0.0.1"
    url = f"https://{host}:8200/recognition" if use_ssl else f"http://{host}:8200/recognition"
    files = {'audio': open(audio_path, 'rb')}
    try:
        resp = requests.post(url, files=files, verify=False)
        data = resp.json()
        if data.get("code", 1) != 0:
            return f"识别失败: {data.get('msg', '未知错误')}", "", "", "", ""
        text = data["text"]
        srt = to_srt(data.get("sentences", []))
        parsed = parse_asr_result(data)
        cleaned = clean_text_result(data)
        return data, text, srt, parsed, cleaned
    except Exception as e:
        return f"请求失败: {e}", "", "", "", ""

with gr.Blocks() as demo:
    gr.Markdown("# 语音识别演示")
    with gr.Tab("单文件识别"):
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
        parsed_out = gr.Textbox(label="解析JSON", lines=20)
        cleaned_out = gr.Textbox(label="清洗文本", lines=10)
        btn.click(asr_recognize, inputs=[audio_file, use_ssl], outputs=[ori_data, text_out, srt_out, parsed_out, cleaned_out])

    with gr.Tab("批量识别"):
        folder_path = gr.Textbox(label="输入音频文件夹路径", placeholder="如 C:/audio_folder")
        batch_use_ssl = gr.Checkbox(label="使用SSL(HTTPS)", value=False)
        batch_btn = gr.Button("开始批量识别")
        batch_progress = gr.Textbox(label="批量识别进度", lines=10)

        def batch_asr(folder_path, use_ssl):
            import glob
            import time
            import os
            audio_exts = [".wav", ".mp3", ".flac", ".m4a", ".aac", ".ogg"]
            if not os.path.isdir(folder_path):
                return f"路径不存在: {folder_path}"
            files = [f for f in glob.glob(os.path.join(folder_path, "*")) if os.path.splitext(f)[1].lower() in audio_exts]
            if not files:
                return "未找到音频文件。"
            progress_lines = []
            for idx, audio_path in enumerate(files, 1):
                try:
                    data, text, _, _, _ = asr_recognize(audio_path, use_ssl)
                    txt_path = os.path.splitext(audio_path)[0] + ".txt"
                    with open(txt_path, "w", encoding="utf-8") as f:
                        f.write(str(text))
                    progress_lines.append(f"[{idx}/{len(files)}] {os.path.basename(audio_path)} 识别完成，结果写入 {os.path.basename(txt_path)}")
                except Exception as e:
                    progress_lines.append(f"[{idx}/{len(files)}] {os.path.basename(audio_path)} 识别失败: {e}")
            return "\n".join(progress_lines)

        batch_btn.click(batch_asr, inputs=[folder_path, batch_use_ssl], outputs=batch_progress)

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