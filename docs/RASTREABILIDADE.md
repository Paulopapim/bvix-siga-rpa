# Matriz de rastreabilidade PDD → implementação → teste

Status: ✅ implementado e testado no simulador · 🟡 implementado, depende de evidência/aprovação · ⏳ pendente de descoberta · — fora do escopo.
"Aceite" = responsável a designar (PD-14/PD-16).

## Etapas (ET / TB)

| PDD | Implementação | Teste | Status |
|---|---|---|---|
| ET-06 / TB-01 Acessar e localizar | `SigaPlaywright.autenticar`, `verificar_sessao`; `Orquestrador.preflight` | test_ex01_* | 🟡 login real mapeado |
| TB-02 Conjunto de trabalho | `Orquestrador.descobrir` (anomalias, únicos, não encontrados); `SigaPlaywright.enumerar` | test_ca01_*, test_ex02_*, test_piloto_lista_* | 🟡 paginação real a validar |
| ET-07 / TB-03 Abrir e identificar | `abrir_processo` (registro da listagem), `naming.pasta_processo`, `Estado.reservar_pasta` | test_ca03_*, test_ex03_*, test_troca_de_processo | 🟡 regra PD-03/04 |
| ET-08 / TB-04 Histórico | `_item_historico`, `validation.validar_historico`, `SigaPlaywright.exportar_historico` (cadeia de URLs) | test_ca02, test_ca06_ex05, test_cadeia_relatorio | 🟡 mapeado; validar no piloto |
| ET-09 Identificar anexos | `listar_anexos` (tipos + contagem x/y) + `ListagemAnexos.completa` | test_ca05_listagem_inacessivel | 🟡 mapeado; validar no piloto |
| ET-10 / TB-05 Baixar individualmente | `_item_anexo`, `validar_anexo`, `SigaPlaywright.baixar_anexo` | test_ca06_ex06_*, test_ex07 | 🟡 mapeado; validar no piloto |
| ET-11 Falha do lote | lote desabilitado (ADR-06) | — | 🟡 PD-08 |
| TB-06 Confirmar preservação | `DestinoArquivos.publicar` (tmp → link → reler hash), `confirmar_versao` | test_destino_*, test_queda_* | ✅ |
| TB-07 Registrar resultado | estados + `eventos` + `reports.gerar` | test_ca12 | ✅ |
| TB-08 Atualizar acervo | modo `incremental` (revisita, versões, ausentes na origem) | test_ca08 | ✅ simulador / ⏳ marcador PD-10 |
| TB-09 Fechar extração | `reconciliar` | test_ca09 | ✅ simulador / [N] PD-11 |

## Regras (RN)

| RN | Como é atendida |
|---|---|
| RN-01, RN-02, RN-04 | Contexto AS-IS; sem requisito executável. O número do SIGA não é equiparado ao do sistema corporativo. |
| RN-03 | Histórico e todos os anexos inventariados; processo só COMPLETO com tudo confirmado. |
| RN-05 | `completo_sem_anexos` só com listagem completa; não exclui processos por estimativa. |
| RN-06 | Histórico pela função de impressão (⏳ PD-06). |
| RN-07 | Download individual; tentativas limitadas; lote desligado. |
| RN-08 / RN-16 | Sem leitura de conteúdo; só tipo técnico, tamanho e hash. Sem GED nem pagamento. |
| RN-09 / RN-10 | Placa isolada não serve; padrão configurável; ausência vai para TRATAMENTO; colisão é detectada. |
| RN-11 | Destino em pastas (local/UNC). SharePoint fica para PD-02. |
| RN-12 | Incremental + reconciliação. |
| RN-13 | Inventário CSV para amostragem (⏳ plano PD-14). |
| RN-14 / RN-15 | Preflight, códigos de saída e corte configurável ([N] PD-01/PD-11). |

## Exceções (EX)

| EX | Código no inventário | Tratamento | Teste |
|---|---|---|---|
| EX-01 | EX-01-SESSAO / -PERMISSAO / -INTERVENCAO | reautentica 1×; depois suspende (saída 3/5) | test_ex01_* |
| EX-02 | anomalias da descoberta / nao_encontrado | não declara cobertura | test_ca01_ex02, test_ex02 |
| EX-03 | EX-03, EX-03-TROCA | TRATAMENTO / tenta de novo | test_ex03, test_troca |
| EX-04 | EX-04 | TRATAMENTO; nunca mescla | test_ca03_ex04, test_destino_nao_sobrescreve |
| EX-05 | EX-05 | histórico pendente | test_ca06_ex05 |
| EX-06 | EX-06 | tentativas com espera progressiva → pendente | test_ca06_ex06_* |
| EX-07 | EX-07, EX-07-LISTAGEM | pendente; nunca "sem anexos" | test_ex07, test_ca05_listagem |
| EX-08 | EX-08 | suspende; item não confirmado (saída 4) | test_ex08_* |
| EX-09 | — | `completo_sem_anexos` | test_ca05_ex09 |
| EX-10 | — | nova versão; anterior preservada | test_ca08, test_queda_com_historico |
| EX-11 | — | reconciliação lista o que não foi verificado | test_ca09_ex11 |

## Critérios de aceite (CA)

| CA | Teste automatizado (simulador) | Evidência necessária na homologação |
|---|---|---|
| CA-01 | test_ca01_* | Contagem da origem (total/Excel) × inventário |
| CA-02 | test_ca02 | Amostra com múltiplos anexos conferida na origem |
| CA-03 | test_ca03_* | Dois processos reais com a mesma placa |
| CA-04 | test_ca04 | Usuário localiza a pasta pela identificação aprovada |
| CA-05 | test_ca05_* | Caso de constatação real |
| CA-06 | test_ca06_* | Falha forçada no piloto |
| CA-07 | test_ca07_* | Reexecução do piloto |
| CA-08 | test_ca08 | Anexo novo em processo já extraído |
| CA-09 | test_ca09_ex11 | Reconciliação no corte |
| CA-10 | — | Amostragem do negócio (PD-14) |
| CA-11 | test_ca11 | Perfil só leitura + revisão do Log de sinistros |
| CA-12 | test_ca12 | Inventário + trilha de eventos |

## Pendências (PD)

| PD | Onde impacta o código | Situação |
|---|---|---|
| PD-01 | `autenticar`, conta do executor | 🟡 URL/login confirmados; perfil com escrita ⚠️ |
| PD-02 | `destination` (SharePoint) | [N] |
| PD-03/04 | `[pasta]` da config | [N]; evidências em MAPA_TELAS |
| PD-05 | `enumerar` | 🟡 parcial |
| PD-06/07 | `exportar_historico`, `listar_anexos`, `baixar_anexo` | 🟡 telas mapeadas em 26/11; falta piloto |
| PD-08 | `[tentativas]` | [P] |
| PD-09 | `completo_sem_anexos` | [N] vínculo com terceiro |
| PD-10/11 | `incremental`, `reconciliar`, `corte` | [N] |
| PD-12/13 | inventário, versões | [P] |
| PD-14..16 | relatórios/runbook | [N] |
| PD-17 | — | fora do escopo |
| PD-18 | só o que está no SIGA | [P] |
