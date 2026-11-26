# Relatório de acompanhamento em Excel (não faz login; pode rodar com os robôs rodando):
#   powershell -ExecutionPolicy Bypass -File .\rodar_relatorio.ps1
Set-Location $PSScriptRoot
.\.venv\Scripts\python.exe -m pip install --quiet openpyxl tzdata
$saida = & .\.venv\Scripts\bvix-siga.exe relatorio -c "config\config.piloto.toml"
$saida | Where-Object { $_ -notlike "PASTA_EXCEL=*" } | ForEach-Object { Write-Host $_ }
$linha = $saida | Where-Object { $_ -like "PASTA_EXCEL=*" } | Select-Object -First 1
if ($linha) {
    $pasta = $linha.Substring(12)
    Write-Host "`nExcel salvo em: $pasta" -ForegroundColor Green
    Write-Host "  acompanhamento_<data>_ultimo.xlsx  (versão mais recente do dia)"
    Write-Host "  acompanhamento_<data>_HHhMM.xlsx   (foto deste momento)"
    Write-Host "  Abas: Resumo | Por sinistro | Erros (com link para o print)"
    Start-Process explorer.exe $pasta
}
