# ZERAR A CARGA (novo deploy): começa do zero SEM apagar nada.
# Renomeia a pasta da carga atual (banco + arquivos baixados) para <pasta>_antiga_AAAAMMDD_HHMM.
# Recusa se algum robô estiver rodando. Rodar dentro desta pasta:
#   powershell -ExecutionPolicy Bypass -File .\zerar_carga.ps1
$ErrorActionPreference = "Continue"
Set-Location $PSScriptRoot
$exe = ".\.venv\Scripts\bvix-siga.exe"
$cfg = "config\config.piloto.toml"
if (-not (Test-Path $exe)) { Write-Host "Ambiente não instalado. Rode instalar_servidor.bat primeiro." -ForegroundColor Red; exit 2 }

Write-Host "PLANO (nada é alterado ainda):" -ForegroundColor Cyan
& $exe zerar -c $cfg
if ($LASTEXITCODE -ne 0) { Write-Host "Cancelado (código $LASTEXITCODE)." -ForegroundColor Red; exit $LASTEXITCODE }

Write-Host ""
Write-Host "Depois disso o robô começa do ZERO: mapeia e baixa TODOS os sinistros de novo." -ForegroundColor Yellow
$r = Read-Host "Para confirmar, digite ZERAR"
if ($r -cne "ZERAR") { Write-Host "Cancelado. Nada foi alterado." -ForegroundColor Green; exit 0 }

& $exe zerar -c $cfg --confirmar
$cod = $LASTEXITCODE
if ($cod -eq 0) {
    Write-Host "`nPróximos passos:" -ForegroundColor Green
    Write-Host "  1) powershell -ExecutionPolicy Bypass -File .\rodar_descoberta.ps1   (mapeamento completo)"
    Write-Host "  2) powershell -ExecutionPolicy Bypass -File .\rodar_paralelo.ps1     (3 robôs)"
    Write-Host "  A carga anterior ficou nas pastas *_antiga_*; apague quando a nova estiver conferida."
}
exit $cod
