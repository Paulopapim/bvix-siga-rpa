# bvix-siga-rpa

Robô (RPA) em Python + Playwright que preserva os **históricos (PDF) e todos os anexos** dos sinistros Bvix registrados no **SIGA** da reguladora atual, um por um, numa pasta por placa, com inventário, conferência de completude e relatório em Excel.

Referência funcional: PDD "Sinistros – Documentos" v0.2. Mapa de telas e evidências: `docs/MAPA_TELAS.md`.

> Este repositório contém **apenas código e documentação**. Arquivos baixados, banco de controle, relatórios, prints, senha, usuário e configuração de pastas do servidor **não são versionados** (ver `.gitignore`).

## Instalação num servidor/computador novo (Windows 64 bits)

1. Copie/clone o projeto para uma pasta (ex.: `D:\bvix-siga-rpa`).
2. Clique duas vezes em **`instalar_servidor.bat`**. Ele verifica/instala o Python 3.11+ (64 bits), cria o `.venv`, instala as bibliotecas (`requirements.txt`), baixa o Chromium do Playwright, roda os testes e pergunta a pasta de saída.
3. Crie as credenciais locais (não vão para o Git):
   - `config\usuario.txt`: usuário do SIGA (1ª linha)
   - `config\senha_provisoria.txt`: senha (1ª linha). Sem o arquivo, a senha é pedida na tela.

## Onde o robô salva

| Arquivo de configuração | Efeito |
|---|---|
| `config\pasta_saida.txt` | Pasta-base de **tudo**: `destino\` (arquivos), `relatorios\`, `evidencias\`, `logs\`, `estado.sqlite`. Prefira disco local. |
| `config\pasta_destino.txt` (opcional) | Só os **arquivos baixados** em outro lugar (ex.: pasta de rede `\\servidor\share\...`). |
| *(nenhum)* | Usa `saida_placa\` dentro do projeto. |

Modelos: `config\*.exemplo`. Para **continuar** uma carga em outro servidor, copie a pasta de saída inteira, inclusive o `estado.sqlite`.

Organização dos arquivos: `destino\<PLACA>\<NÚMERO>_HISTORICO.pdf` e `destino\<PLACA>\<NÚMERO>_<Tipo do anexo>_<nº>_<nome original>.<ext>`.

## Comandos (detalhes em `COMANDOS_ROBO_SIGA.txt`)

| Script | Uso |
|---|---|
| `rodar_piloto.ps1` | Teste com 3 sinistros |
| `rodar_descoberta.ps1` | Mapeia o universo (lista todos os sinistros, não baixa) |
| `rodar_paralelo.ps1` | **Carga com 3 robôs** em paralelo (fatias sem sobreposição) |
| `rodar_fatia.ps1 -Fatia "<prefixos>"` | Um robô de uma fatia (retomar um robô parado) |
| `rodar_carga_completa.ps1` | Carga com 1 robô (não usar junto com o paralelo) |
| `rodar_relatorio.ps1` | Excel de acompanhamento (Resumo / Por sinistro / Erros com print), a qualquer hora |

Executar: `powershell -ExecutionPolicy Bypass -File "<pasta>\rodar_paralelo.ps1"`

## Garantias principais

- **Só leitura na origem:** botões de escrita (Salvar, Excluir, Finalizar, Avançar, Inserir, Baixar todos) bloqueados.
- **Identidade pelo ID interno do SIGA** (há números repetidos e "0" no SIGA).
- **Completude:** contagem da coluna "Quantidade" de cada tipo × anexos listados e baixados.
- **Sem duplicar nem sobrescrever:** gravação atômica, conferência por SHA-256, versões preservadas; histórico comparado pelo conteúdo (ignora carimbos de geração).
- **Anexo sem arquivo no servidor da reguladora** → registrado com print (`EX-06-SEM-ARQUIVO`), sinistro em TRATAMENTO.
- **Retomada:** Ctrl+C a qualquer momento; rodar de novo continua de onde parou.

## Desenvolvimento

```bat
.venv\Scripts\python -m pytest -q          :: testes com SIGA simulado (dados fictícios)
.venv\Scripts\bvix-siga carga-historica -c config\config.piloto.toml --simulador
```

Estrutura: `src/bvix_siga/` (cli, config, orchestrator, state, destination, naming, validation, reports, siga/playwright_adapter, siga/selectors, siga/simulator) · `tests/` · `docs/` (arquitetura, mapa de telas, rastreabilidade PDD, runbook).
