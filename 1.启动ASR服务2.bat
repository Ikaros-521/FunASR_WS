@echo off
chcp 65001

SET CONDA_PATH=.\Miniconda3

REM 激活base环境
CALL %CONDA_PATH%\Scripts\activate.bat %CONDA_PATH%

SET KMP_DUPLICATE_LIB_OK=TRUE
SET CONDA_PATH=.\Miniconda3
set HF_ENDPOINT=https://hf-mirror.com
set HF_HOME=%CD%\hf_download
set MODELSCOPE_CACHE=%CD%\hf_download

set disable_update=True

python funasr_wss_server.py --port 10096 --certfile "" --asr_model iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-pytorch --asr_model_revision master --asr_model_online iic/speech_paraformer-large_asr_nat-zh-cn-16k-common-vocab8404-online --asr_model_online_revision master 

cmd /k