@echo off
REM ============================================================================================
REM  CARGA COMPLETA AUTOMATICA - Robo SIGA Bvix
REM    1) Mapeamento (calculo da quantidade de sinistros no SIGA)
REM    2) 3 robos em paralelo baixando historicos e anexos (espera TODOS terminarem)
REM    3) Relatorio final em Excel (abre a pasta no fim)
REM  Usuario/senha: config\usuario.txt e config\senha_provisoria.txt
REM  Pode rodar de novo a qualquer momento: continua de onde parou (nao baixa de novo o que ja foi salvo).
REM  Enquanto roda, o PC nao entra em suspensao. NAO feche esta janela (fechar = para os 3 robos).
REM ============================================================================================
chcp 65001 >nul
cd /d "%~dp0"
title Robo SIGA Bvix - carga completa
set PYTHONIOENCODING=utf-8
set PY=.venv\Scripts\python.exe
if not exist "%PY%" (
  echo ERRO: ambiente nao instalado. Rode instalar_servidor.bat nesta pasta primeiro.
  pause
  exit /b 2
)
"%PY%" -m pip install --quiet tzdata openpyxl

echo.
echo ==================== [1/3] MAPEAMENTO: contando os sinistros no SIGA ====================
set "EMK_VARS={"comando": "descobrir", "pendencias_ok": false}"
"%PY%" -u -m bvix_siga.emk
set COD=%ERRORLEVEL%
if not "%COD%"=="0" (
  echo.
  echo PAROU NO MAPEAMENTO ^(codigo %COD%^): 10 = lista do SIGA nao comprovada ^| 3 = login ^| 5 = SIGA fora ^| 6 = robo ja rodando
  echo Nada foi baixado nesta etapa. Corrija e rode este arquivo de novo.
  pause
  exit /b %COD%
)

echo.
echo ==================== [2/3] DOWNLOAD: 3 robos em paralelo ====================
echo Linhas [R1] [R2] [R3] = cada robo. Linha PROGRESSO a cada 10 minutos.
set "EMK_VARS={"comando": "retomar", "fatias": "2025-,2026-1,SEMNUMERO-;2026-00,2026-01,2026-02,2026-03,2026-04;2026-05,2026-06,2026-07,2026-08,2026-09", "pendencias_ok": false}"
"%PY%" -u -m bvix_siga.emk
set COD=%ERRORLEVEL%

echo.
echo ==================== [3/3] RELATORIO FINAL ====================
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0rodar_relatorio.ps1"

echo.
if "%COD%"=="0" (
  echo CARGA CONCLUIDA SEM PENDENCIAS.
) else if "%COD%"=="10" (
  echo CARGA CONCLUIDA COM PENDENCIAS ^(ex.: anexo que nao existe no SIGA^). Veja a aba Erros do Excel.
  echo Rodar este arquivo de novo tenta outra vez os pendentes.
) else (
  echo OS ROBOS PARARAM ^(codigo %COD%^): 3 = login ^| 4 = destino/disco ^| 5 = SIGA fora/sessao ^| 6 = robo ja rodando ^| 1 = inesperado
  echo Rode este arquivo de novo: continua de onde parou.
)
pause
exit /b %COD%
