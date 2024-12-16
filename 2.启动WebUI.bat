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

start "" "http://127.0.0.1:8101/web/index.html"

python webui.py

cmd /k