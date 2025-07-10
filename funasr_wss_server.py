import asyncio
import json
import websockets
import time
import logging
import tracemalloc
import numpy as np
import argparse
import ssl
import struct  # 添加struct模块用于解析二进制数据
from loguru import logger

# 添加重采样所需的库
try:
    import librosa
    HAS_LIBROSA = True
except ImportError:
    logger.warning("librosa库未安装，将使用简单的重采样方法")
    HAS_LIBROSA = False

parser = argparse.ArgumentParser()
parser.add_argument(
    "--host", type=str, default="0.0.0.0", required=False, help="host ip, localhost, 0.0.0.0"
)
parser.add_argument("--port", type=int, default=10095, required=False, help="grpc server port")
parser.add_argument(
    "--asr_model",
    type=str,
    default="iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch",
    help="model from modelscope",
)
parser.add_argument("--asr_model_revision", type=str, default="v2.0.4", help="")
parser.add_argument(
    "--asr_model_online",
    type=str,
    default="iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online",
    help="model from modelscope",
)
parser.add_argument("--asr_model_online_revision", type=str, default="v2.0.4", help="")
parser.add_argument(
    "--vad_model",
    type=str,
    default="iic/speech_fsmn_vad_zh-cn-16k-common-pytorch",
    help="model from modelscope",
)
parser.add_argument("--vad_model_revision", type=str, default="v2.0.4", help="")
parser.add_argument(
    "--punc_model",
    type=str,
    default="iic/punc_ct-transformer_zh-cn-common-vad_realtime-vocab272727",
    help="model from modelscope",
)
parser.add_argument("--punc_model_revision", type=str, default="v2.0.4", help="")
parser.add_argument("--ngpu", type=int, default=1, help="0 for cpu, 1 for gpu")
parser.add_argument("--device", type=str, default="cuda", help="cuda, cpu")
parser.add_argument("--ncpu", type=int, default=4, help="cpu cores")
parser.add_argument(
    "--certfile",
    type=str,
    default="cert.pem",
    required=False,
    help="certfile for ssl",
)

parser.add_argument(
    "--keyfile",
    type=str,
    default="key.pem",
    required=False,
    help="keyfile for ssl",
)
args = parser.parse_args()


websocket_users = set()

logger.info("模型加载中，请耐心等待...")
from funasr import AutoModel

# asr
model_asr = AutoModel(
    model=args.asr_model,
    model_revision=args.asr_model_revision,
    ngpu=args.ngpu,
    ncpu=args.ncpu,
    device=args.device,
    disable_pbar=True,
    disable_log=True,
    disable_update=True,
)
# asr
model_asr_streaming = AutoModel(
    model=args.asr_model_online,
    model_revision=args.asr_model_online_revision,
    ngpu=args.ngpu,
    ncpu=args.ncpu,
    device=args.device,
    disable_pbar=True,
    disable_log=True,
    disable_update=True,
)
# vad
model_vad = AutoModel(
    model=args.vad_model,
    model_revision=args.vad_model_revision,
    ngpu=args.ngpu,
    ncpu=args.ncpu,
    device=args.device,
    disable_pbar=True,
    disable_log=True,
    # chunk_size=60,
    disable_update=True,
)

if args.punc_model != "":
    model_punc = AutoModel(
        model=args.punc_model,
        model_revision=args.punc_model_revision,
        ngpu=args.ngpu,
        ncpu=args.ncpu,
        device=args.device,
        disable_pbar=True,
        disable_log=True,
        disable_update=True,
    )
else:
    model_punc = None


logger.info("模型已加载！现在只能同时支持一个客户端!!!!")


async def ws_reset(websocket):
    logger.info("WS已重置, 总连接数 ", len(websocket_users))

    websocket.status_dict_asr_online["cache"] = {}
    websocket.status_dict_asr_online["is_final"] = True
    websocket.status_dict_vad["cache"] = {}
    websocket.status_dict_vad["is_final"] = True
    websocket.status_dict_punc["cache"] = {}

    await websocket.close()


async def clear_websocket():
    for websocket in websocket_users:
        await ws_reset(websocket)
    websocket_users.clear()


async def ws_serve(websocket, path):
    frames = []
    frames_asr = []
    frames_asr_online = []
    global websocket_users
    # await clear_websocket()
    websocket_users.add(websocket)
    websocket.status_dict_asr = {}
    websocket.status_dict_asr_online = {"cache": {}, "is_final": False}
    websocket.status_dict_vad = {"cache": {}, "is_final": False}
    websocket.status_dict_punc = {"cache": {}}
    websocket.chunk_interval = 10
    websocket.vad_pre_idx = 0
    speech_start = False
    speech_end_i = -1
    websocket.wav_name = "microphone"
    websocket.mode = "2pass"
    websocket.is_file_mode = False  # 添加文件模式标志
    websocket.file_data = []  # 存储文件数据
    websocket.is_speaking = True  # 默认为说话状态
    websocket.wav_format = ""  # 文件格式
    websocket.audio_fs = 16000  # 默认采样率 - ASR模型期望16kHz
    logger.info("新用户已连接")

    try:
        async for message in websocket:
            if isinstance(message, str):
                messagejson = json.loads(message)

                if "is_speaking" in messagejson:
                    websocket.is_speaking = messagejson["is_speaking"]
                    websocket.status_dict_asr_online["is_final"] = not websocket.is_speaking
                    logger.info(f"说话状态更新: {websocket.is_speaking}")
                    
                                         # 如果是文件模式且停止说话，处理所有累积的数据
                    if websocket.is_file_mode and not websocket.is_speaking and len(websocket.file_data) > 0:
                        logger.info(f"文件模式: 处理累积的数据，大小: {len(websocket.file_data)} 块")
                        try:
                            # 合并所有数据
                            audio_in = b"".join(websocket.file_data)
                            total_bytes = len(audio_in)
                            logger.info(f"合并后的音频数据大小: {total_bytes} 字节")
                            
                            # 处理WAV文件头
                            if websocket.wav_name.lower() == "wav":
                                logger.info("检测到WAV文件，解析文件头")
                                # 使用WAV头解析函数
                                sample_rate, data_start = parse_wav_header(audio_in)
                                
                                if sample_rate is not None and data_start is not None:
                                    # 更新采样率信息
                                    websocket.audio_fs = sample_rate
                                    
                                    # 跳过文件头
                                    if total_bytes > data_start:
                                        logger.info(f"跳过WAV文件头 ({data_start} 字节)")
                                        audio_in = audio_in[data_start:]
                                        logger.info(f"去除WAV头后的数据大小: {len(audio_in)} 字节")
                                else:
                                    # 如果解析失败，使用默认值（44字节）
                                    logger.warning("WAV头解析失败，使用默认值（跳过44字节）")
                                    if total_bytes > 44:
                                        audio_in = audio_in[44:]
                                        logger.info(f"去除默认WAV头后的数据大小: {len(audio_in)} 字节")
                            
                            # 处理采样率 - ASR模型期望16kHz
                            if hasattr(websocket, 'audio_fs') and websocket.audio_fs != 16000:
                                logger.info(f"文件采样率 {websocket.audio_fs}Hz 与模型期望的16000Hz不匹配，进行重采样")
                                # 进行重采样处理
                                audio_in = resample_audio(audio_in, websocket.audio_fs, 16000)
                                logger.info(f"重采样后的数据大小: {len(audio_in)} 字节")
                            
                            # 发送到ASR引擎处理
                            logger.info(f"发送数据到ASR引擎处理，大小: {len(audio_in)} 字节")
                            await async_asr(websocket, audio_in)
                            websocket.file_data = []  # 处理后清空数据
                        except Exception as e:
                            logger.error(f"处理文件数据时出错: {str(e)}")
                            logger.exception(e)  # 打印完整堆栈跟踪
                            
                if "chunk_interval" in messagejson:
                    websocket.chunk_interval = messagejson["chunk_interval"]
                    
                if "wav_name" in messagejson:
                    websocket.wav_name = messagejson.get("wav_name")
                    # 检测是否为文件模式
                    if websocket.wav_name.lower() in ["wav", "mp3", "pcm"]:
                        websocket.is_file_mode = True
                        logger.info(f"检测到文件模式: {websocket.wav_name}")
                        
                if "wav_format" in messagejson:
                    # 检测文件格式
                    websocket.is_file_mode = True
                    websocket.wav_format = messagejson['wav_format']
                    logger.info(f"检测到文件格式: {websocket.wav_format}")
                    
                if "audio_fs" in messagejson:
                    # 文件采样率
                    websocket.audio_fs = messagejson['audio_fs']
                    logger.info(f"文件采样率: {websocket.audio_fs}")
                    
                if "chunk_size" in messagejson:
                    chunk_size = messagejson["chunk_size"]
                    if isinstance(chunk_size, str):
                        chunk_size = chunk_size.split(",")
                    websocket.status_dict_asr_online["chunk_size"] = [int(x) for x in chunk_size]
                    
                if "encoder_chunk_look_back" in messagejson:
                    websocket.status_dict_asr_online["encoder_chunk_look_back"] = messagejson[
                        "encoder_chunk_look_back"
                    ]
                    
                if "decoder_chunk_look_back" in messagejson:
                    websocket.status_dict_asr_online["decoder_chunk_look_back"] = messagejson[
                        "decoder_chunk_look_back"
                    ]
                    
                if "hotword" in messagejson:
                    websocket.status_dict_asr["hotword"] = messagejson["hotwords"]
                    
                if "mode" in messagejson:
                    websocket.mode = messagejson["mode"]
                    logger.info(f"识别模式: {websocket.mode}")
                    if websocket.mode == "offline":
                        websocket.is_file_mode = True

            websocket.status_dict_vad["chunk_size"] = int(
                websocket.status_dict_asr_online["chunk_size"][1] * 60 / websocket.chunk_interval
            )
            if len(frames_asr_online) > 0 or len(frames_asr) >= 0 or not isinstance(message, str):
                if not isinstance(message, str):
                    # 记录收到的二进制数据
                    data_size = len(message)
                    # logger.debug(f"收到二进制数据: {data_size} 字节")
                    
                    # 文件模式特殊处理
                    if websocket.is_file_mode:
                        # 累积文件数据
                        websocket.file_data.append(message)
                        # logger.debug(f"文件模式: 累积数据 {data_size} 字节，总计 {len(websocket.file_data)} 块")
                        continue
                    
                    # 以下是麦克风模式的处理
                    frames.append(message)
                    duration_ms = len(message) // 32
                    websocket.vad_pre_idx += duration_ms

                    # asr online
                    frames_asr_online.append(message)
                    websocket.status_dict_asr_online["is_final"] = speech_end_i != -1
                    if (
                        len(frames_asr_online) % websocket.chunk_interval == 0
                        or websocket.status_dict_asr_online["is_final"]
                    ):
                        if websocket.mode == "2pass" or websocket.mode == "online" or websocket.mode == "2pass-sentence":
                            audio_in = b"".join(frames_asr_online)
                            try:
                                # 2pass-final模式下不发送流式识别结果
                                if websocket.mode != "2pass-final":
                                    await async_asr_online(websocket, audio_in)
                            except Exception as e:
                                logger.error(f"在线ASR处理出错: {str(e)}")
                        frames_asr_online = []
                    if speech_start:
                        frames_asr.append(message)
                    # vad online
                    try:
                        speech_start_i, speech_end_i = await async_vad(websocket, message)
                    except Exception as e:
                        logger.error(f"VAD处理出错: {str(e)}")
                    if speech_start_i != -1:
                        speech_start = True
                        beg_bias = (websocket.vad_pre_idx - speech_start_i) // duration_ms
                        frames_pre = frames[-beg_bias:]
                        frames_asr = []
                        frames_asr.extend(frames_pre)
                # asr punc offline - 非文件模式下的处理
                if not websocket.is_file_mode and (speech_end_i != -1 or not websocket.is_speaking):
                    logger.info("检测到语音结束点或停止说话")
                    if websocket.mode == "2pass" or websocket.mode == "offline" or websocket.mode == "2pass-final" or websocket.mode == "2pass-sentence":
                        audio_in = b"".join(frames_asr)
                        logger.info(f"离线ASR处理，数据大小: {len(audio_in)} 字节")
                        try:
                            await async_asr(websocket, audio_in)
                        except Exception as e:
                            logger.error(f"离线ASR处理出错: {str(e)}")
                    frames_asr = []
                    speech_start = False
                    frames_asr_online = []
                    websocket.status_dict_asr_online["cache"] = {}
                    if not websocket.is_speaking:
                        websocket.vad_pre_idx = 0
                        frames = []
                        websocket.status_dict_vad["cache"] = {}
                    else:
                        frames = frames[-20:]

    except websockets.ConnectionClosed:
        logger.info("ConnectionClosed...", websocket_users, flush=True)
        await ws_reset(websocket)
        websocket_users.remove(websocket)
    except websockets.InvalidState:
        logger.info("InvalidState...")
    except Exception as e:
        logger.info("Exception:", e)


async def async_vad(websocket, audio_in):

    segments_result = model_vad.generate(input=audio_in, **websocket.status_dict_vad)[0]["value"]
    # logger.info(segments_result)

    speech_start = -1
    speech_end = -1

    if len(segments_result) == 0 or len(segments_result) > 1:
        return speech_start, speech_end
    if segments_result[0][0] != -1:
        speech_start = segments_result[0][0]
    if segments_result[0][1] != -1:
        speech_end = segments_result[0][1]
    return speech_start, speech_end


async def async_asr(websocket, audio_in):
    if len(audio_in) > 0:
        logger.info(f"处理音频数据，长度: {len(audio_in)} 字节")
        try:
            # 对于文件模式，添加特殊处理
            if websocket.is_file_mode:
                logger.info("使用文件模式处理ASR")
                
                # 检查数据是否合理
                if len(audio_in) < 1000:
                    logger.warning(f"音频数据可能太小 ({len(audio_in)} 字节)，可能影响识别质量")
                
                # 确保采样率正确设置 - ASR模型期望16kHz
                if hasattr(websocket, 'audio_fs') and websocket.audio_fs != 16000:
                    logger.info(f"注意：ASR模型期望16000Hz采样率，输入文件采样率为{websocket.audio_fs}Hz，进行重采样")
                    # 进行重采样
                    audio_in = resample_audio(audio_in, websocket.audio_fs, 16000)
                    logger.info(f"重采样后的数据大小: {len(audio_in)} 字节")
            
            # 调用ASR模型进行识别
            logger.info("调用ASR模型进行识别...")
            rec_result = model_asr.generate(input=audio_in, **websocket.status_dict_asr)[0]
            logger.info(f"ASR识别结果: {rec_result}")
            
            # 应用标点符号
            if model_punc is not None and len(rec_result["text"]) > 0:
                logger.info(f"应用标点符号前: {rec_result['text']}")
                rec_result = model_punc.generate(
                    input=rec_result["text"], **websocket.status_dict_punc
                )[0]
                logger.info(f"应用标点符号后: {rec_result['text']}")
            
            # 检查识别结果
            if not rec_result["text"] or len(rec_result["text"].strip()) <= 1:
                logger.warning("识别结果为空或只有一个字符，可能是音频数据有问题")
                
            # 无论是否有文本，都发送结果
            if "2pass" in websocket.mode:
                mode = "2pass-offline" if websocket.mode == "2pass" else websocket.mode
            else:
                mode = websocket.mode
                
            message = json.dumps(
                {
                    "mode": mode,
                    "text": rec_result["text"],
                    "wav_name": websocket.wav_name,
                    "is_final": True,  # 文件模式下总是设置为最终结果
                },
                ensure_ascii=False
            )
            logger.info(f"发送识别结果: {message}")
            await websocket.send(message)
            
        except Exception as e:
            logger.error(f"ASR处理出错: {str(e)}")
            logger.exception(e)  # 打印完整堆栈跟踪
            # 发送错误信息
            if "2pass" in websocket.mode:
                mode = "2pass-offline" if websocket.mode == "2pass" else websocket.mode
            else:
                mode = websocket.mode
                
            message = json.dumps(
                {
                    "mode": mode,
                    "text": f"识别处理出错，请重试。错误: {str(e)}",
                    "wav_name": websocket.wav_name,
                    "is_final": True,
                    "error": str(e)
                },
                ensure_ascii=False
            )
            await websocket.send(message)
    else:
        logger.info("收到空音频数据")
        if "2pass" in websocket.mode:
            mode = "2pass-offline" if websocket.mode == "2pass" else websocket.mode
        else:
            mode = websocket.mode
            
        message = json.dumps(
            {
                "mode": mode,
                "text": "",
                "wav_name": websocket.wav_name,
                "is_final": True,
            },
            ensure_ascii=False
        )
        await websocket.send(message)    

async def async_asr_online(websocket, audio_in):
    if len(audio_in) > 0:
        # logger.info(websocket.status_dict_asr_online.get("is_final", False))
        rec_result = model_asr_streaming.generate(
            input=audio_in, **websocket.status_dict_asr_online
        )[0]
        # logger.info(f"流式识别结果: {rec_result}")
        if websocket.mode == "2pass" and websocket.status_dict_asr_online.get("is_final", False):
            return
            #     websocket.status_dict_asr_online["cache"] = dict()
        if len(rec_result["text"]):
            # 2pass-sentence模式下，只在检测到句子结束时发送消息
            if websocket.mode == "2pass-sentence":
                # 获取当前识别的文本
                text = rec_result["text"]
                # logger.info(f"2pass-sentence模式收到原始文本: '{text}'")
                
                # 初始化句子缓存（如果不存在）
                if not hasattr(websocket, 'sentence_cache'):
                    websocket.sentence_cache = ""
                    
                # 检查是否有句子结束的标点符号
                punctuation_marks = ["。", "？", "！", ".", "?", "!"]
                
                # 直接检查文本中是否包含标点符号
                has_punctuation = False
                for punct in punctuation_marks:
                    if punct in text:
                        has_punctuation = True
                        break
                
                if has_punctuation:
                    # 查找所有标点符号的位置
                    punct_positions = []
                    for punct in punctuation_marks:
                        pos = text.find(punct)
                        while pos != -1:
                            punct_positions.append(pos)
                            pos = text.find(punct, pos + 1)
                    
                    # 按位置排序
                    punct_positions.sort()
                    # 找到最后一个标点符号的位置
                    last_punct_pos = punct_positions[-1]
                    
                    # 提取完整的句子（包含标点符号）
                    complete_sentence = text[:last_punct_pos + 1]
                    logger.info(f"检测到句子结束标点，提取句子: '{complete_sentence}'")
                    
                    # 打印字符编码，用于调试
                    logger.info(f"句子中的字符编码: {[ord(c) for c in complete_sentence]}")
                    
                    # 发送完整句子
                    mode = "2pass-sentence"
                    message = json.dumps(
                        {
                            "mode": mode,
                            "text": complete_sentence,
                            "wav_name": websocket.wav_name,
                            "is_final": False,
                            "is_sentence_end": True
                        },
                        ensure_ascii=False
                    )
                    logger.info(f"发送断句信息，JSON内容: {message}")
                    await websocket.send(message)
                    
                    # 保留剩余部分作为下一句的开始
                    websocket.sentence_cache = text[last_punct_pos + 1:]
                    logger.info(f"保留剩余部分作为下一句的开始: '{websocket.sentence_cache}'")
                else:
                    # 如果没有检测到句子结束，则更新缓存
                    websocket.sentence_cache = text
                    logger.info(f"未检测到句子结束标点，更新缓存: '{websocket.sentence_cache}'")
                    
            # 普通模式下正常发送流式结果
            elif websocket.mode != "2pass-final":
                mode = "2pass-online" if "2pass" in websocket.mode else websocket.mode
                message = json.dumps(
                    {
                        "mode": mode,
                        "text": rec_result["text"],
                        "wav_name": websocket.wav_name,
                        "is_final": websocket.is_speaking,
                    },
                    ensure_ascii=False
                )
                await websocket.send(message)


# 添加WAV文件头解析函数
def parse_wav_header(data):
    """
    解析WAV文件头，返回采样率和数据开始位置
    """
    try:
        if len(data) < 44:  # WAV头至少44字节
            logger.warning("数据太短，无法解析WAV头")
            return None, None
        
        # 检查是否是RIFF格式
        if data[0:4] != b'RIFF':
            logger.warning("不是有效的WAV文件：缺少RIFF标记")
            return None, None
            
        # 检查是否是WAVE格式
        if data[8:12] != b'WAVE':
            logger.warning("不是有效的WAV文件：缺少WAVE标记")
            return None, None
            
        # 查找fmt子块
        if data[12:16] != b'fmt ':
            logger.warning("不是标准WAV格式：缺少fmt子块")
            return None, None
            
        # 解析采样率（位于fmt子块中）
        sample_rate = struct.unpack('<I', data[24:28])[0]
        logger.info(f"从WAV头解析出采样率: {sample_rate}Hz")
        
        # 查找data子块
        data_pos = 12
        while data_pos + 8 <= len(data):
            chunk_id = data[data_pos:data_pos+4]
            chunk_size = struct.unpack('<I', data[data_pos+4:data_pos+8])[0]
            
            if chunk_id == b'data':
                data_start = data_pos + 8
                logger.info(f"找到数据块，开始位置: {data_start}，大小: {chunk_size}")
                return sample_rate, data_start
                
            data_pos += 8 + chunk_size
        
        # 如果没找到data子块，使用默认值
        logger.warning("未找到data子块，使用默认值")
        return sample_rate, 44
        
    except Exception as e:
        logger.error(f"解析WAV头时出错: {str(e)}")
        logger.exception(e)
        return None, None


# 添加重采样函数
def resample_audio(audio_data, src_sr, target_sr=16000):
    """
    将音频数据从源采样率重采样到目标采样率
    
    参数:
        audio_data: 音频数据，字节格式
        src_sr: 源采样率
        target_sr: 目标采样率，默认16000Hz
        
    返回:
        重采样后的音频数据，字节格式
    """
    try:
        # 转换字节数据为numpy数组
        audio_np = np.frombuffer(audio_data, dtype=np.int16)
        
        # 使用librosa进行高质量重采样
        if HAS_LIBROSA:
            logger.info(f"使用librosa将音频从{src_sr}Hz重采样到{target_sr}Hz")
            # 转换为float32，范围[-1, 1]
            audio_float = audio_np.astype(np.float32) / 32768.0
            # 重采样
            resampled_audio = librosa.resample(audio_float, orig_sr=src_sr, target_sr=target_sr)
            # 转回int16
            resampled_audio = (resampled_audio * 32768.0).astype(np.int16)
        else:
            # 简单的重采样方法（降低质量但不需要额外依赖）
            logger.info(f"使用简单方法将音频从{src_sr}Hz重采样到{target_sr}Hz")
            # 计算重采样比例
            ratio = src_sr / target_sr
            # 创建新的音频数组
            resampled_len = int(len(audio_np) / ratio)
            resampled_audio = np.zeros(resampled_len, dtype=np.int16)
            
            # 简单的抽样
            for i in range(resampled_len):
                src_idx = int(i * ratio)
                if src_idx < len(audio_np):
                    resampled_audio[i] = audio_np[src_idx]
        
        # 转回字节格式
        return resampled_audio.tobytes()
    
    except Exception as e:
        logger.error(f"重采样过程中出错: {str(e)}")
        logger.exception(e)
        return audio_data  # 出错时返回原始数据


if len(args.certfile) > 0:
    ssl_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    # Generate with Lets Encrypt, copied to this location, chown to current user and 400 permissions
    ssl_cert = args.certfile
    ssl_key = args.keyfile

    ssl_context.load_cert_chain(ssl_cert, keyfile=ssl_key)
    start_server = websockets.serve(
        ws_serve, args.host, args.port, subprotocols=["binary"], ping_interval=None, ssl=ssl_context
    )
else:
    start_server = websockets.serve(
        ws_serve, args.host, args.port, subprotocols=["binary"], ping_interval=None
    )
asyncio.get_event_loop().run_until_complete(start_server)
asyncio.get_event_loop().run_forever()
