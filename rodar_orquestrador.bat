@echo off
REM Entrada do robo SIGA Bvix para o Orquestrador EMK (comando da automacao no portal).
REM Parametros chegam em EMK_VARS; credenciais pelo Cofre (variavel SIGA). Detalhes: docs\ORQUESTRADOR_EMK.md
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo ERRO: ambiente nao instalado. Rode instalar_servidor.bat nesta pasta primeiro.
  exit /b 2
)
".venv\Scripts\python.exe" -u -m bvix_siga.emk
exit /b %ERRORLEVEL%
