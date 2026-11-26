# Mapa de telas do SIGA — evidências da descoberta

Sessão de descoberta: 26/11/2026, ~08:50 (America/Sao_Paulo), conta do usuário Bvix (login feito pelo próprio usuário), somente leitura.
Dados pessoais omitidos ou mascarados.

## PD-01: acesso
| Item | Evidência |
|---|---|
| URL | `https://star.arcoconsultoria.com/open.do?sys=SIG`, título da página "SIGA". A URL entrega o SIGA. |
| Login | Formulário "LoginPrincipal" em iframe: campos com placeholder `Login` / `Senha`, botão `Entrar`, link "Esqueceu a senha?". Não apareceu MFA nem captcha. |
| Plataforma | Softwell Maker/Webrun: `wfr.js`, `openform.do?formID=…`, `executeRule.do`, token `WEBRUN-CSRFTOKEN`. Recursos também vêm de `siga.arcoconsultoria.com`. |
| CDN | Cloudflare (`/cdn-cgi/rum`). Pode haver proteção contra bots ou limite de taxa; isso entra na autorização com a reguladora. |
| Perfil | O usuário (BVIX) vê CADASTRO, CONSULTA, **MOVIMENTAÇÃO** (Sinistro Antigo/Novo, Criar Sindicância, Alterar Tipo de Evento, Alterar Telefone, Ordem de Compra…), RELATÓRIOS, UTILITÁRIOS, além de "Modo Gerente" e "Modo Projeto". **O perfil não é somente leitura.** |
| Frames | Até 5 níveis de iframe aninhados (`form.jsp` → `openform.do` → `tmp/SIG/<id>/<id>.html`). Os IDs `WFRInput…` e os caminhos `tmp/SIG/…` são gerados; não servem como seletor. |

## PD-05: listagem (MOVIMENTAÇÃO > Sinistro - Novo > "Localizar Sinistros")
- Tela "Abertura de Eventos": tem botões verdes que **CRIAM sinistro** (COLISÕES, FURTO, ROUBO, VIDROS, CONSTATACAO DE DANOS…). O robô **nunca** deve clicar neles.
- "Localizar - Sinistros": tabela `#tabela_localizar` (DataTables, client-side), com colunas `# | Número | Nome | Placa | Veículo | CPF / CNPJ`; filtros por Número, Nome, Placa, Veículo, CPF/CNPJ; 10/25/50/100 por página; Anterior/Próximo; botão Excel.
- Cada `<tr>` traz o atributo **`idsinistro`**, um ID interno estável.
- Os dados vêm de `POST executeRule.do`, que devolve JSON com `ordem, idsin, empid, numerosin, nome, cpfcnpj, placa, veiculo, tipoeventoid, tipoevento`.
- A ordenação padrão observada é por número decrescente (2026-10516, 10515…). Não aparece total de registros na tela.
- Número do sinistro no formato `AAAA-NNNNN`.

## PD-03/PD-04: identificação (observações)
- A coluna "CPF / CNPJ" mistura CPF (pessoa física) e CNPJ. Um "CNPJ" obrigatório falharia nos segurados pessoa física.
- O mesmo CPF/CNPJ aparece com placas diferentes. Há placas que parecem genéricas (ex.: veículo "DANOS AO PATRIMONIO"), o que confirma a RN-09.
- `tipoevento` (ex.: CONSTATACAO DE DANOS, COLISÃO) vem **nulo** em parte dos registros. Se "evento" for o tipo de evento, haverá ausências (EX-03).
- O campo "Situação do Evento" do cadastro mostra "BVIX". Ele pode ser o filtro de seguradora (a confirmar).

## Tela "Cadastro de Sinistro" (aberta por duplo clique na listagem)
- Abas: Cadastro, Integração, Furto e roubo, Usuários responsáveis, Log, Localizar.
- Toolbar: `add`, `edit`, `save`, `cancel`, `history`, **"Fechar Sinistro"**.
- Grade de cronograma `#idTabelaCadastro`: Regulagem, Tarefa Atual, Tarefa livre, Sindicância, Finalizado, Tipo Cronograma.
- ⚠️ **Um duplo clique na grade do cronograma colocou o formulário em modo de edição.** Foi cancelado sem salvar; o Log do sinistro continua vazio. Regra para o robô: não usar duplo clique nem foco em campos dentro do cadastro; preferir leitura via rede ou ações explícitas de visualização.
- Nesta tela **não** apareceram "imprimir histórico" nem a lista de anexos.

## Caminho até histórico e anexos (descoberto 26/11, ~09:20)
CONSULTA > **Cronograma** (form "Consulta Cronograma do Evento", formID 464570699):
1. Campo `#evento_pesquisa` (placeholder "digite o evento aqui... mínimo 3 caracteres"). A pesquisa dispara no `onchange` (sair do campo com Tab), não no Enter.
2. Aparece um select2 `#evento_select` com opções "NÚMERO NOME PLACA" (ex.: busca parcial "2025-01" lista 2025-01999, 01998…).
3. Botão "Abrir evento" (olho) abre o form **"Novo Histórico"** (formID 464570582).
4. ⚠️ Ao abrir, o portal mostrou o alerta "Erro de conversão: "null" para Inteiro!". Foi só fechado com OK. É um erro do próprio SIGA e o robô deve tolerá-lo.

### Form "Novo Histórico" (tem **Salvar** e **Fechar**: o robô nunca clica em Salvar)
- Cabeçalho: Nome, Telefones, Protocolo Integração, **Evento** (número), Origem, Veículo, **Placa**, Modelo, **Cobertura** (ex.: "Terceiro" → PD-09), Situação do evento.
- Abas: Histórico, Anexos, SIGA Parts, Lançamentos, Oficina, ISA, Notificações, Análise, Cotação, Autorização, Financeiro, Indenização, Salvado.
- "Últimos históricos": tabela com Número, Data, Histórico, Tarefa, Usuário, Ações (✏️ editar = **proibido**, 👁 visualizar).

### PD-06: "imprimir histórico" ✅
- Botão `#imprimir_historico` → fluxo "Novo Historico - Abrir Relatorio de Historicos".
- Gera uma cadeia de 3 requisições GET, todas com a sessão:
  1. `wfrcore?action=reportOpenExternal&Order=&localreport=OFF&nopopup=false&sys=SIG&reportID=Histórico do Sinistro&exptype=PDF&callfunction=true&numero_sinistro=<ID interno>` → HTML com `openWFRReportFinal('1','openreport.jsp?id=<GUID>&type=PDF…')`
  2. `openreport.jsp?id=<GUID>&type=PDF&sys=SIG&name=…` → HTML com `window.location = 'WFRReports/Generated/<GUID>.PDF'`
  3. `WFRReports/Generated/<GUID>.PDF` → `application/pdf`, `%PDF-1.4`. Amostra: 4 páginas, 45 KB, processo com 17 entradas de histórico.
- `numero_sinistro` é o **ID interno** (o mesmo tipo do `idsin` da listagem), não o número AAAA-NNNNN.
- ⏳ Falta no piloto: confirmar que o PDF traz todas as entradas e se muda a cada geração (carimbo de data/hora).

### PD-07: anexos ✅ (estrutura)
- Aba Anexos, tabela **`#tabela-tipo-anexo`**: `[id oculto] | # | Nome do tipo | qtde/limite` (ex.: "Constatação / Nexo Causal 7/50", "Fotos Iniciais Evento 4/150"). **Linhas com anexos têm fundo cinza `rgb(197,197,197)`**: é o "cinza" do PDD.
- Clique simples na linha do tipo carrega **`#tabela-anexos`**: `[ID do anexo oculto] | # | Tipo | Arquivo | Usuário inclusão | Data inclusão | Abrir | Excluir`.
  - O ID oculto (ex.: 8429625) é a **identidade estável do anexo** (ADR-08).
  - A contagem "x/y" de cada tipo serve de **prova de completude** da listagem.
- "Abrir" (ícone save_alt) → fluxo `novo - abrir imagem - obter url` com parâmetros (`e:\siga\anexos\bvix\<NÚMERO>\`, nome, id) → abre o visualizador "novo - abrir imagem", que carrega o arquivo de `https://arquivos.arcoconsultoria.com/arquivos/siga/BVIX/<NÚMERO>/<uuid>-<nome>`.
- ⚠️ No servidor da reguladora, os anexos ficam em **`e:\siga\anexos\bvix\<NÚMERO DO SINISTRO>\`**. Um pedido de cópia direta dessa pasta é um ótimo plano B.
- ⚠️ Controles **proibidos** na aba: `#deletar_todos_anexos` (remover todos), link "excluir" por linha (`Remover Anexo`), `#inserir_anexo` (upload), `#importar_anexos_sga`.
- Outros: `#baixar_anexo_zip` ("Baixar Todos Anexos (Cliente)") e `#baixar_arquivos` ("Baixar Arquivos"): lote, desligado (RN-07).

## Pendente de descoberta
- Diferença entre "Sinistro - Antigo" e "Sinistro - Novo" (PD-05).
- Filtro de seguradora e total do universo.
- Se a URL de `arquivos.arcoconsultoria.com` exige sessão (relevante para LGPD; não testado de propósito).
- Se o `<uuid>` do arquivo muda a cada abertura (cópia temporária).

## Validação de 26/11 (~09:30), pela sessão do usuário, sem gravar nada
| Item | Resultado |
|---|---|
| Paginação "Localizar Sinistros" | ✅ "Próximo" consulta o servidor (10 → 10 seguintes, contíguos, ordem decrescente). O seletor de 100/página funciona e reinicia do topo. Não há total. |
| Escopo da listagem | Todas as linhas amostradas têm `empid=394`; `idsin` é contíguo. ⚠️ A numeração de 2026 já está em 10.516, então **o universo pode ser bem maior que 12 mil** (somando 2025 e anos anteriores). Confirmar em PD-05/PD-15. |
| PDF do histórico | ✅ A cadeia de 3 URLs funciona (4 páginas/45 KB; um sinistro recente deu 1 página/26 KB). ⚠️ **A mesma impressão gerada 2× tem hash diferente**: muda só o `/ID` do trailer e um bloco de metadados; os streams de conteúdo são idênticos. Correção: `validation.impressao_pdf` (hash do conteúdo descomprimido) evita versões falsas. |
| Lista de anexos (2025-01998) | ✅ 44 tipos, 7 com arquivos (todos cinza), 21 anexos; **contagem x/y bate com as linhas em 7/7 tipos**. Extensões: .jpeg e .pdf. |
| Link do anexo | ✅ A regra "obter url" devolve `https://arquivos.arcoconsultoria.com/arquivos/siga/BVIX/<NÚMERO>/<uuid>-<nome>`. O fetch pelo navegador é barrado por CORS; o robô usa a sessão do Playwright. ⏳ Se o link funciona sem login (ponto de LGPD a levantar com a reguladora). |
