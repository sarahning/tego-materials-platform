@echo off
cd /d "%~dp0"
powershell -ExecutionPolicy Bypass -File ".\run_windows_cpu_true_hofmann.ps1"
