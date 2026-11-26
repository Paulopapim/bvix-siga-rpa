# Rodar e monitorar pelo Orquestrador EMK

O Orquestrador EMK (https://orquestrador.emktecnologia.com.br) **executa** o robô por meio de um **agente** instalado no servidor e **mostra** no portal:
- a situação de cada execução (Na fila, Em execução, Concluído, Falhou, Timeout, Cancelado);
- a duração e o código de saída;
- o log em tempo real, com uma linha `PROGRESSO:` a cada 10 minutos.

A API pública (`/api/v1/docs/`) só lista agentes, automações e execuções, e dispara execuções. Não existe um endereço para o robô "enviar status": o monitoramento é a própria execução vista no portal.

## 1. Preparar o servidor (uma vez)
1. Instale o robô: `git clone https://github.com/Paulopapim/bvix-siga-rpa.git` e rode `instalar_servidor.bat`.
2. No portal, abra **Configurações › Meus agentes › + Criar agente**. A chave de instalação aparece **uma única vez**: guarde-a.
3. Ainda em Configurações, use **Baixar o agente**, instale-o no servidor com essa chave e confira em **Agentes** se ele aparece "Ativo" e com heartbeat.

> Navegador visível: o robô abre o Chromium. Se o agente rodar como serviço do Windows, sem área de trabalho, use a variável `visivel = false`.

## 2. Senha no Cofre
Em **Cofre › + Nova credencial**, crie a credencial com variável de ambiente **`SIGA`**, o usuário e a senha do SIGA.
O agente entrega ao robô `SIGA` (senha) e `SIGA_USER` (usuário). Sem cofre, o robô usa `config\usuario.txt` e `config\senha_provisoria.txt`.

## 3. Automação
Em **Automações › + Nova automação**:

| Campo | Valor |
|---|---|
| Nome | Robô SIGA Bvix – Preservação |
| Comando | `C:\caminho\bvix-siga-rpa\rodar_orquestrador.bat` |
| Diretório de trabalho | `C:\caminho\bvix-siga-rpa` |
| Timeout (s) | `259200` (72 h, para a carga completa) |
| Logs em tempo real | marcado |
| Credenciais do cofre | `SIGA` |

Variáveis personalizadas (todas opcionais; marque **API** nas que quiser mudar pela API):

| Variável | Tipo | Padrão | Uso |
|---|---|---|---|
| `comando` | str | `retomar` | `retomar`, `carga-historica`, `descobrir`, `relatorio`, `preflight`, `reconciliar` |
| `fatias` | str | vazio | robôs em paralelo separados por `;`, ex.: `2025-,2026-1,SEMNUMERO-;2026-00,2026-01,2026-02,2026-03,2026-04;2026-05,2026-06,2026-07,2026-08,2026-09` |
| `limite` | int | — | máximo de sinistros (teste) |
| `max_paginas` | int | — | limita a descoberta (teste) |
| `visivel` | bool | do arquivo de configuração | mostrar o navegador |
| `pendencias_ok` | bool | `true` | terminar com pendências (ex.: anexo ausente na origem) conta como "Concluído" |
| `intervalo_min` | int | `10` | minutos entre as linhas `PROGRESSO:` |
| `simulador` | bool | `false` | **teste do agente sem acessar o SIGA**; grava só em `saida_simulador\` |

Primeiro teste recomendado: execute com `simulador = true`. Deve terminar em "Concluído" e criar a pasta `saida_simulador`.

## 4. Códigos de saída
| Código | Portal | Significado |
|---|---|---|
| 0 | Concluído | terminou (com pendências, se `pendencias_ok = true`) |
| 10 | Falhou | terminou com pendências (só com `pendencias_ok = false`) |
| 2 | Falhou | configuração, parâmetro ou credencial ausente |
| 3 | Falhou | login, permissão ou verificação extra no SIGA |
| 4 | Falhou | pasta de destino indisponível ou sem espaço |
| 5 | Falhou | SIGA fora do ar ou sessão |
| 6 | Falhou | já existe outro robô rodando nos mesmos sinistros |
| 1 | Falhou | erro inesperado (ver log) |

Com vários robôs (`fatias`), a execução termina quando todos terminam e vale o **pior** código entre eles. Cada linha do log vem marcada com `[R1]`, `[R2]`...

## 5. Cuidados
- **Não rode pelo orquestrador ao mesmo tempo que os scripts `rodar_*.ps1`** na mesma pasta de saída. Se tentar, o robô sai com código 6, sem estragar nada.
- Cancelar no portal encerra também os robôs filhos (cada um confere a cada 15 s se o processo principal continua vivo). A próxima execução com `retomar` continua de onde parou.
- Excel e relatórios continuam em `relatorios\AAAA-MM-DD\` na pasta de saída. Para gerá-los, rode a automação com `comando = relatorio`.
