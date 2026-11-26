"""Seletores centralizados, ancorados em rótulos/placeholder/texto observados em 26/11/2026.
IDs gerados pelo Maker (WFRInput…, tmp/SIG/<n>.html, MenuLateralGamma-item-<n>) NÃO são usados."""

LOGIN_USUARIO = "input[placeholder='Login']"
LOGIN_SENHA = "input[placeholder='Senha']"
LOGIN_BOTAO = "button:has-text('Entrar')"
LOGIN_MARCA_FRAME = "text=Entre com seus dados abaixo"

LOGADO_MARCA = "a:has-text('Sair')"                       # item do menu do usuário
MENU_SINISTRO_NOVO = "a:text-is('Sinistro - Novo')"
MENU_SINISTRO_ANTIGO = "a:text-is('Sinistro - Antigo')"   # PD-05: universo pode estar dividido
BOTAO_LOCALIZAR = "text=Localizar Sinistros"

LISTA_TABELA = "#tabela_localizar"                        # id estável do componente HTML (não gerado)
LISTA_TAMANHO_PAGINA = "select"                           # opções 10/25/50/100 no frame da listagem
LISTA_PROXIMO = "button:has-text('Próximo')"
LISTA_FILTRO_NUMERO = "input[placeholder*='Número']"

REGRA_ENDPOINT = "executeRule.do"
REGRA_MARCA_LISTAGEM = "numerosin"

# Controles que o robô NUNCA aciona (CA-11). O clique seguro recusa qualquer alvo com estes textos.
PROIBIDOS = ("salvar", "save", "fechar sinistro", "excluir", "delete", "edit", "editar", "add", "incluir",
             "colisões", "furto", "roubo", "vidros", "constatacao de danos", "alterar", "criar", "finalizar",
             "modo projeto", "modo gerente", "alterar senha", "alterar empresa", "finalizar", "avançar", "avancar")

# CONSULTA > Cronograma -> "Novo Histórico" (descoberto 26/11 ~09:20)
MENU_CRONOGRAMA = "a:text-is('Cronograma')"
CRONO_BUSCA = "#evento_pesquisa"                 # dispara no onchange (Tab)
CRONO_SELECT2_OPCOES = ".select2-results__option"
CRONO_ABRIR_EVENTO = "button[data-content='Abrir evento']"   # onclick: Abrir Novo Historico (Cliente)
CRONO_SELECT_VALOR = "() => (window.j||window.jQuery)('#evento_select').val()"   # = idsin (validado 26/11)
# validado 26/11: há vários botões "Fechar" (modais internos); o que fecha o evento chama o fluxo abaixo
EVENTO_FECHAR = "button[onclick*=\"'Novo Historico - Fechar'\"]"
ALERTA_OK = "button.swal2-confirm, .swal-button--confirm, button:has-text('Ok')"
ALERTA_TOLERADO = "Erro de conversão"            # erro conhecido do próprio SIGA ao abrir o evento

HIST_MARCA_FORM = "#imprimir_historico"
HIST_RELATORIO_ID = "Histórico do Sinistro"
HIST_URL_1 = ("wfrcore?action=reportOpenExternal&Order=&localreport=OFF&nopopup=false&sys=SIG"
              "&reportID={report}&exptype=PDF&callfunction=true&numero_sinistro={id_interno}")

ANEXOS_ABA = "a[href='#pagina_anexos']"
ANEXOS_TIPOS_LINHAS = "#tabela-tipo-anexo tbody tr"
ANEXOS_LINHAS = "#tabela-anexos tbody tr"
ANEXO_ABRIR = "a[title='abrir']"
ANEXOS_HOST = "arquivos.arcoconsultoria.com"

# Controles da aba Anexos/Histórico que NUNCA podem ser acionados
IDS_PROIBIDOS = ("#deletar_todos_anexos", "#inserir_anexo", "#importar_anexos_sga", "a[title='excluir']",
                 "#salvar_todos", "#baixar_anexo_zip", "#baixar_arquivos",
                 "button:has-text('Finalizar')", "button:has-text('Avançar')", "button:has-text('Salvar')")
