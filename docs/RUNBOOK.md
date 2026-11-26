# Runbook operacional

## Pré-requisitos
- Windows ou Linux com Python 3.11+, `pip install -e .` e `playwright install chromium`.
- Conta **só de consulta** no SIGA. Credenciais vêm do cofre, injetadas como `SIGA_USERNAME` / `SIGA_PASSWORD`.
- Destino aprovado (PD-02) com permissão de escrita para a conta de serviço.
- Autorização formal da reguladora para acesso automatizado (volume e horário).

## Comandos
| Comando | Uso |
|---|---|
| `bvix-siga preflight -c config/config.toml` | Testa staging, destino, login e sessão. |
| `bvix-siga descobrir` | Enumera o recorte e grava o universo no banco, sem baixar nada. |
| `bvix-siga carga-historica [--limite N] [--protocolos A,B / @lista.txt]` | Processa o que ainda não está finalizado. |
| `bvix-siga incremental` | Redescobre e revisita processos: novos processos, anexos e versões de histórico. |
| `bvix-siga retomar` | Continua os pendentes sem redescobrir. |
| `bvix-siga reprocessar --protocolos ...` | Força o reprocessamento de uma lista. |
| `bvix-siga reconciliar` | Corte final: universo da origem × inventário. |
| `bvix-siga relatorio` | Gera inventário, pendências e resumo. |
| `--simulador` | Qualquer comando contra o SIGA simulado (treino e testes). |

## Códigos de saída
`0` ok · `10` concluída com pendências/diferenças · `2` configuração · `3` autenticação/permissão/intervenção (MFA) · `4` destino · `5` origem/sessão · `6` outra instância ativa · `1` inesperado.

## AutomationEdge (se for o executor)
Workflow com atividade "Run Command": `bvix-siga <comando> -c <config>`. As credenciais saem do Credential Vault como variáveis de ambiente da atividade. Desvie o fluxo pelo código de retorno: 0 encerra; 10 notifica Operação com o CSV de pendências; 2/3/4/5 abre incidente para o responsável (PD-16).

## Diretórios (`var/`)
`staging/` (temporário, restrito) · `estado.sqlite` + `.bak.sqlite` (backup automático antes de cada carga) · `logs/execucao.log` · `relatorios/` (inventário, pendências, resumo).

## Retomada após queda
1. Verifique a causa no log e no resumo da execução (`motivo_suspensao`).
2. Corrija o problema (sessão, destino, espaço).
3. Rode `bvix-siga retomar`. Arquivos gravados e não confirmados são reconciliados por hash, sem duplicar.

## Plano de homologação e corte (proposto)
1. Fechar a descoberta de PD-06/PD-07 (histórico e anexos) com o usuário de negócio.
2. Piloto em modo visível com `--protocolos` (≈20 casos: múltiplos anexos, sem anexo, terceiro, mesma placa, homônimos, 50+ anexos). Medir taxas (PD-15).
3. Amostragem do negócio (CA-10) e aceite dos parâmetros (PD-03, 12, 13).
4. Carga histórica autorizada (headless se homologado), com `incremental` diário.
5. No corte: `incremental` final → `reconciliar` → relatório → aceite. Se o acesso acabar antes, o relatório lista o recorte não verificado (EX-11).
