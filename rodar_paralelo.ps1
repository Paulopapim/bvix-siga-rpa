# Abre 3 robôs em paralelo, cada um numa janela, com fatias que não se sobrepõem.
#   powershell -ExecutionPolicy Bypass -File .\rodar_paralelo.ps1
# ANTES: pare a carga normal (Ctrl+C). Carga normal e fatias não podem rodar juntas (o robô recusa).
Set-Location $PSScriptRoot
$fatias = @(
    "2025-,2026-1,SEMNUMERO-",                 # ~4.000 sinistros: 2025, 2026-10000+ e os sem número
    "2026-00,2026-01,2026-02,2026-03,2026-04", # ~4.950 sinistros: 2026-00001 a 2026-04999
    "2026-05,2026-06,2026-07,2026-08,2026-09"  # ~4.950 sinistros: 2026-05000 a 2026-09999
)
foreach ($f in $fatias) {
    # o caminho tem espaço ("EMK 2026"): precisa ir entre aspas para o PowerShell da nova janela
    $script = Join-Path $PSScriptRoot "rodar_fatia.ps1"
    Start-Process powershell -ArgumentList "-NoExit -ExecutionPolicy Bypass -File `"$script`" -Fatia `"$f`""
    Write-Host "Robô iniciado: $f" -ForegroundColor Green
    Start-Sleep -Seconds 30      # logins espaçados
}
Write-Host "`n3 robôs rodando. Para acompanhar: .\rodar_relatorio.ps1 (Excel em saida_placa\relatorios\<data>)"
Write-Host "Para parar um robô: Ctrl+C na janela dele. Rodar de novo continua de onde parou."
