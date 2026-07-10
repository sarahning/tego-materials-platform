@echo off
cd /d "%~dp0"
set TEGO_PROPERTY_DEVICE=cpu
set DGLBACKEND=pytorch
if not defined RETRIEVAL_CSVS set "RETRIEVAL_CSVS=%~dp0mp20_with_jav_dielectric\mp20_with_jav_epsx_epsy_epsz.csv"
echo [Tego] Device: CPU
echo [Tego] Dataset: %RETRIEVAL_CSVS%
echo [Tego] Open: http://127.0.0.1:7860
python -m uvicorn backend.main:app --host 0.0.0.0 --port 7860 --workers 1
