@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0Easy_Cidaren"
start "" "%~dp0.setup\python\pythonw.exe" "%~dp0Easy_Cidaren\restore_local_network.py"