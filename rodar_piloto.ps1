# Piloto do RPA SIGA - Bvix. Rodar no PowerShell, dentro desta pasta:
#   powershell -ExecutionPolicy Bypass -File .\rodar_piloto.ps1
# Primeira vez: instala o ambiente. Depois: só executa.
$ErrorActionPreference = "Continue"   # erros de programas externos são tratados por Checar()
Set-Location $PSScriptRoot

function Checar($msg) { if ($LASTEXITCODE -ne 0) { Write-Host "FALHOU: $msg (código $LASTEXITCODE)" -ForegroundColor Red; exit 1 } }

if (-not (Test-Path ".venv\Scripts\python.exe")) {
    Write-Host "Criando ambiente Python..." -ForegroundColor Cyan
    py -3 -m venv .venv; Checar "criar .venv (Python 3.11+ instalado?)"
}
$py = ".\.venv\Scripts\python.exe"
& $py -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('playwright') else 1)"
if ($LASTEXITCODE -ne 0) {
    Write-Host "Instalando dependências..." -ForegroundColor Cyan
    & $py -m pip install --upgrade pip; Checar "atualizar pip"
    & $py -m pip install "playwright>=1.48" "pytest>=8.3" tzdata; Checar "instalar playwright"
    & $py -m pip install -e . --no-deps; Checar "instalar o projeto"
    & $py -m playwright install chromium; Checar "baixar o Chromium"
}
& $py --version
& $py -m pip install --quiet tzdata openpyxl

# Credenciais só nesta janela (não ficam gravadas em arquivo)
# Usuário: config\usuario.txt (1ª linha). Se não existir, é pedido na tela.
$arqUsuario = Join-Path $PSScriptRoot "config\usuario.txt"
if (-not $env:SIGA_USERNAME -and (Test-Path $arqUsuario)) {
    $env:SIGA_USERNAME = (Get-Content $arqUsuario -TotalCount 1).Trim()
}
if (-not $env:SIGA_USERNAME) { $env:SIGA_USERNAME = Read-Host "Usuário SIGA" }
Write-Host "Usuário SIGA: $env:SIGA_USERNAME"
# Senha PROVISÓRIA em arquivo local (só a 1ª linha). Apague o arquivo para voltar a digitar a senha.
$arqSenha = Join-Path $PSScriptRoot "config\senha_provisoria.txt"
if (-not $env:SIGA_PASSWORD -and (Test-Path $arqSenha)) {
    $env:SIGA_PASSWORD = (Get-Content $arqSenha -TotalCount 1).Trim()
    Write-Host "Senha lida de config\senha_provisoria.txt"
}
if (-not $env:SIGA_PASSWORD) {
    $s = Read-Host "Senha SIGA" -AsSecureString
    $env:SIGA_PASSWORD = [Runtime.InteropServices.Marshal]::PtrToStringAuto([Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))
}

$cfg = "config\config.piloto.toml"
Write-Host "`nCarga piloto (inclui preflight): 1 página da lista (100 sinistros mais recentes), processa só 3" -ForegroundColor Cyan
.\.venv\Scripts\bvix-siga.exe carga-historica -c $cfg --max-paginas 1 --limite 3 -v
Write-Host "Código de saída: $LASTEXITCODE  (0 ok | 10 com pendências | 3 login | 4 destino | 5 sessão/origem)"

Write-Host "`nArquivos em saida_final\destino, relatórios em saida_final\relatorios, log em saida_final\logs\execucao.log" -ForegroundColor Green
$env:SIGA_PASSWORD = $null
