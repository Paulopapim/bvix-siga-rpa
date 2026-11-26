@echo off
rem =====================================================================
rem  Robô SIGA - Bvix | Instalação em servidor/computador novo (Windows)
rem  Uso: clique duas vezes, ou no prompt:  instalar_servidor.bat
rem  Requisitos: Windows 64 bits, acesso à internet (pip e download do Chromium)
rem  Se a rede usar proxy, antes de rodar:  set HTTPS_PROXY=http://proxy:porta
rem =====================================================================
chcp 65001 >nul
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
echo.
echo === Robô SIGA - Bvix : instalação ===
echo Pasta do projeto: %CD%
echo.

rem ---------- 1) Python 3.11+ (64 bits) ----------
set "PY="
where py >nul 2>&1 && (py -3 -c "import sys" >nul 2>&1 && set "PY=py -3")
if not defined PY (where python >nul 2>&1 && (python -c "import sys" >nul 2>&1 && set "PY=python"))
if not defined PY (
    echo Python nao encontrado. Tentando instalar o Python 3.12 pelo winget...
    where winget >nul 2>&1 || goto :sem_python
    winget install -e --id Python.Python.3.12 --scope machine --accept-package-agreements --accept-source-agreements
    if errorlevel 1 goto :sem_python
    echo.
    echo Python instalado. FECHE esta janela e rode o instalar_servidor.bat de novo.
    pause
    exit /b 0
)
%PY% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if errorlevel 1 (
    echo ERRO: e preciso Python 3.11 ou mais novo.
    %PY% --version
    goto :fim_erro
)
%PY% -c "import struct, sys; sys.exit(0 if struct.calcsize('P') * 8 == 64 else 1)"
if errorlevel 1 (
    echo ERRO: o Python instalado e de 32 bits. Instale o Python 64 bits ^(o Playwright exige^).
    goto :fim_erro
)
echo [ok] Python:
%PY% --version

rem ---------- 2) Ambiente virtual (.venv) ----------
if not exist ".venv\Scripts\python.exe" (
    echo Criando ambiente .venv ...
    %PY% -m venv .venv || goto :fim_erro
)
set "VPY=.venv\Scripts\python.exe"
echo [ok] Ambiente .venv

rem ---------- 3) Bibliotecas ----------
echo Instalando bibliotecas (playwright, tzdata, openpyxl, pytest)...
"%VPY%" -m pip install --upgrade pip || goto :fim_erro
"%VPY%" -m pip install -r requirements.txt || goto :fim_erro
"%VPY%" -m pip install -e . --no-deps || goto :fim_erro
echo [ok] Bibliotecas

rem ---------- 4) Navegador Chromium do Playwright ----------
echo Baixando o Chromium do Playwright (~150 MB)...
"%VPY%" -m playwright install chromium || goto :fim_erro
echo [ok] Chromium

rem ---------- 5) Teste automatico (simulador, sem acessar o SIGA) ----------
echo Rodando os testes automaticos...
"%VPY%" -m pytest -q
if errorlevel 1 (
    echo ATENCAO: algum teste falhou. Envie a tela acima para o suporte antes de rodar a carga.
) else (
    echo [ok] Testes
)

rem ---------- 6) Pasta onde os arquivos serao salvos ----------
echo.
if exist "config\pasta_saida.txt" (
    echo Pasta de saida atual:
    type "config\pasta_saida.txt" | findstr /v /b "#"
    set /p TROCAR="Trocar a pasta de saida? (S/N) [N]: "
    if /i not "!TROCAR!"=="S" goto :pasta_destino
)
set "PASTA="
set /p PASTA="Pasta para salvar TUDO (ex.: D:\SIGA_BVIX). Enter = usar saida_placa dentro do projeto: "
if defined PASTA (
    if not exist "!PASTA!" mkdir "!PASTA!"
    > "config\pasta_saida.txt" echo !PASTA!
    echo [ok] Pasta de saida: !PASTA!
) else (
    echo [ok] Pasta de saida: %CD%\saida_placa ^(padrao^)
)

:pasta_destino
set "DEST="
set /p DEST="OPCIONAL - pasta so para os arquivos baixados (ex.: \\servidor\share\Sinistros). Enter = mesma pasta de saida: "
if defined DEST (
    > "config\pasta_destino.txt" echo !DEST!
    echo [ok] Arquivos baixados em: !DEST!
)

rem ---------- 7) Lembretes ----------
echo.
echo === Instalacao concluida ===
echo.
echo Antes de rodar:
echo  - Senha: crie config\senha_provisoria.txt com a senha na 1a linha ^(ou digite quando pedir^).
echo  - Usuario: esta nos arquivos rodar_*.ps1, linha  $env:SIGA_USERNAME = "..."
echo  - Computador ligado e sem hibernar durante a carga.
echo.
echo Comandos ^(ver COMANDOS_ROBO_SIGA.txt^):
echo  powershell -ExecutionPolicy Bypass -File "%CD%\rodar_piloto.ps1"       ^(teste com 3 sinistros^)
echo  powershell -ExecutionPolicy Bypass -File "%CD%\rodar_paralelo.ps1"     ^(3 robos^)
echo  powershell -ExecutionPolicy Bypass -File "%CD%\rodar_relatorio.ps1"    ^(Excel de acompanhamento^)
echo.
pause
exit /b 0

:sem_python
echo.
echo ERRO: Python nao encontrado e nao foi possivel instalar automaticamente.
echo Instale o Python 3.12 64 bits em https://www.python.org/downloads/windows/
echo  ^(marque "Add python.exe to PATH"^) e rode este arquivo de novo.
:fim_erro
echo.
echo A instalacao NAO terminou. Veja a mensagem de erro acima.
pause
exit /b 1
