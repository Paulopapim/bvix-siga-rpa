# Checklist de descoberta — SIGA

Marque com evidência (print/HAR mascarado, data e responsável). ✅ feito · ⏳ pendente · ⚠️ achado de risco.

## PD-01 Acesso
- ✅ A URL entrega o SIGA (título "SIGA", 26/11)
- ✅ Login por formulário Login/Senha; sem MFA/captcha na primeira sessão
- ⚠️ Perfil tem MOVIMENTAÇÃO, "Fechar Sinistro" e "Modo Projeto": **pedir conta só de consulta**
- ⚠️ Cloudflare na frente do portal: combinar volume e horário com a reguladora
- ⏳ Duração da sessão e comportamento de expiração (o que aparece quando expira)
- ⏳ Login simultâneo (humano + robô) derruba a outra sessão?
- ⏳ Janela de acesso e conta para o executor (não usar conta pessoal)

## PD-05 Listagem e universo
- ✅ "Localizar Sinistros" (MOVIMENTAÇÃO > Sinistro - Novo): tabela com Número, Nome, Placa, Veículo, CPF/CNPJ; 10/25/50/100 por página
- ✅ A resposta `executeRule.do` traz JSON com `idsin`, `empid`, `numerosin`, `placa`, `cpfcnpj`, `tipoevento`
- ⏳ "Próximo" consulta o servidor ou pagina localmente? Quantos registros a busca sem filtro devolve?
- ⏳ Existe total? Ordenação estável (observado: número decrescente)?
- ⏳ "Sinistro - Antigo": outro universo? Mesmo formato?
- ⏳ Filtro por seguradora (`empid`? "Situação do Evento = BVIX"?), período e status
- ⏳ O botão Excel da listagem serve como prova independente do universo (contagem)?

## PD-03/PD-04 Identificação
- ✅ "CPF / CNPJ" mistura PF e PJ
- ✅ `tipoevento` nulo em parte dos registros
- ✅ Mesmo CPF/CNPJ em várias placas; placas genéricas (ex.: danos ao patrimônio)
- ⏳ O que é "evento" para o negócio: tipo de evento, número do sinistro ou data?
- ⏳ De quem é o CNPJ (segurado/associado/estipulante)?
- ⏳ Aprovação do uso de `numerosin`/`idsin` como complemento da pasta

## PD-06 Histórico
- ✅ Onde fica: CONSULTA > Cronograma > busca > "Abrir evento" → form "Novo Histórico"
- ✅ "Imprimir histórico" gera um PDF por cadeia de 3 URLs (wfrcore → openreport.jsp → WFRReports/Generated/<GUID>.PDF)
- ⏳ Provar no piloto que o PDF traz todas as entradas (contar entradas da tela × PDF)
- ⏳ A impressão tem carimbo de data/hora que muda a cada extração?

## PD-07/PD-08 Anexos
- ✅ Aba Anexos: agrupados por tipo, com contagem x/y (prova de completude)
- ✅ "Cinza" = linha de tipo com anexos (fundo rgb(197,197,197))
- ✅ Cada anexo tem ID oculto, nome, usuário e data de inclusão (tamanho não aparece)
- ✅ Download: "abrir" → visualizador carrega de arquivos.arcoconsultoria.com/arquivos/siga/BVIX/<NÚMERO>/<uuid>-<nome>
- ⚠️ Botões proibidos na aba: deletar todos, excluir, inserir, importar SGA
- ⏳ A URL de arquivos exige sessão? O uuid muda a cada abertura?
- ⏳ "Baixar todos": formato do pacote e como ele falha
- ⏳ Tempo médio por anexo, tamanho médio e máximo

## PD-09 Constatação/terceiro
- ✅ `tipoevento = CONSTATACAO DE DANOS` aparece na listagem
- ⏳ Como identificar o processo do terceiro vinculado

## PD-15 Medição (piloto)
- ⏳ Processos/hora, anexos/hora, bytes, latência, taxa de falha; projeção para o universo
