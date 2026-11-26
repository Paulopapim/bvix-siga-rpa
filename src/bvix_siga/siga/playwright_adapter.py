"""Adaptador SIGA real (Playwright + Chromium).

Estado da implementação (descoberta de 26/11/2026):
- autenticar ................ IMPLEMENTADO (formulário LoginPrincipal observado)
- verificar_sessao .......... IMPLEMENTADO (marca de usuário logado / volta à tela de login)
- enumerar .................. VALIDADO 26/11: paginação no servidor, 100/página, ordem decrescente contígua
- abrir_processo ............ IMPLEMENTADO A VALIDAR: CONSULTA > Cronograma > busca > "Abrir evento" (form Novo Histórico)
- exportar_historico ........ IMPLEMENTADO A VALIDAR: cadeia wfrcore -> openreport.jsp -> WFRReports/Generated/<GUID>.PDF
- listar_anexos ............. IMPLEMENTADO A VALIDAR: aba Anexos, tipos com contagem x/y, ID oculto por anexo
- baixar_anexo .............. IMPLEMENTADO A VALIDAR: "abrir" -> captura URL em arquivos.arcoconsultoria.com -> GET com sessão

Regras de segurança da interface (incidente de 26/11: duplo clique no cronograma abriu modo de edição):
- nunca usar duplo clique em formulários de cadastro;
- todo clique passa por `_clique_seguro`, que recusa controles de escrita (selectors.PROIBIDOS);
- se aparecer botão "save" visível (modo de edição), cancelar e levantar erro.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Iterator, Optional

from ..config import Config
from ..errors import (ArquivoAusenteNaOrigem, AutenticacaoIntervencao, DownloadFalhou, HistoricoInvalido, OrigemIndisponivel, PermissaoNegada,
                      ProcessoTrocado, RpaError, SessaoExpirada)
from ..models import AnexoRef, DetalheProcesso, Filtro, ListagemAnexos, PaginaListagem, RegistroListagem
from . import selectors as S

log = logging.getLogger("bvix_siga.siga")


class ListagemIncompletaAdaptador(RpaError):
    codigo = "EX-07-LISTAGEM"
    transitoria = True


class PendenteDescoberta(RpaError):
    codigo = "PENDENTE-DESCOBERTA"
    sistemica = True   # impede carga com etapa não mapeada


_RE_RULE = re.compile(r"_ruleReturn\s*=\s*\['(.*)',\s*'(?:true|false)'\]", re.S)


def parse_rule_return(corpo: str) -> Optional[list[dict]]:
    """Extrai a lista JSON de `$mainform().document._ruleReturn = ['[...]', 'true'];`."""
    import json
    m = _RE_RULE.search(corpo)
    if not m:
        return None
    js = re.sub(r"\\(.)", lambda x: {"n": "\n", "t": "\t", "r": "\r"}.get(x.group(1), x.group(1)), m.group(1))
    try:
        dados = json.loads(js)
    except json.JSONDecodeError:
        return None
    return dados if isinstance(dados, list) else None


def registro_de(d: dict) -> RegistroListagem:
    s = lambda v: None if v is None else str(v).strip() or None  # noqa: E731  strings: preserva zeros
    return RegistroListagem(protocolo=s(d.get("numerosin")), id_interno=s(d.get("idsin")), placa=s(d.get("placa")),
                            cpfcnpj=s(d.get("cpfcnpj")), tipo_evento=s(d.get("tipoevento")))


class SigaPlaywright:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        self._pw = self._browser = self._ctx = self.page = None
        self._registros: dict[str, RegistroListagem] = {}
        self._registros_id: dict[str, RegistroListagem] = {}

    # ------------------------------------------------------------ infra
    def _iniciar(self):
        if self.page:
            return
        from playwright.sync_api import sync_playwright
        self._pw = sync_playwright().start()
        # janela maximizada: o layout do SIGA (janelas internas do Maker) corta conteúdo em telas pequenas
        self._browser = self._pw.chromium.launch(headless=not self.cfg.modo_visivel, args=["--start-maximized"])
        self._ctx = self._browser.new_context(accept_downloads=True, locale="pt-BR", timezone_id=self.cfg.timezone,
                                              no_viewport=True)
        self._ctx.set_default_timeout(self.cfg.timeout_navegacao_ms)
        self.page = self._ctx.new_page()

    def _frame_com(self, seletor: str, timeout_ms: Optional[int] = None):
        """Procura em todos os iframes (o SIGA aninha até 5 níveis)."""
        import time
        limite = time.monotonic() + (timeout_ms or self.cfg.timeout_navegacao_ms) / 1000
        while time.monotonic() < limite:
            for fr in self.page.frames:
                try:
                    if fr.locator(seletor).count() > 0:
                        return fr
                except Exception:  # noqa: BLE001 frame destacado durante a busca
                    continue
            self.page.wait_for_timeout(250)
        return None

    @staticmethod
    def _js_click(locator) -> None:
        """Itens de menu do Maker ficam recolhidos (invisíveis); clique via DOM, como um usuário faria pelo menu."""
        locator.evaluate("e => e.click()")

    def _menu(self, rotulo: str, timeout_ms: Optional[int] = None) -> None:
        """Clica num item do menu lateral pelo texto exato. Os itens ficam recolhidos (invisíveis) e o texto fica num
        <span>, então a busca é feita no DOM de cada frame (validado 26/11: <a ...><span class=menu-item-text>…</span></a>)."""
        import time
        js = """(rotulo) => { const a = [...document.querySelectorAll('a.list-group-item, a')]
                   .find(x => (x.textContent || '').replace(/\\s+/g, ' ').trim() === rotulo);
                 if (!a) return false; a.click(); return true; }"""
        limite = time.monotonic() + (timeout_ms or self.cfg.timeout_navegacao_ms) / 1000
        while time.monotonic() < limite:
            for fr in self.page.frames:
                try:
                    if fr.evaluate(js, rotulo):
                        return
                except Exception:  # noqa: BLE001
                    continue
            self.page.wait_for_timeout(500)
        raise PermissaoNegada(f"item de menu '{rotulo}' não encontrado para o perfil")

    def _clique_seguro(self, locator, descricao: str) -> None:
        texto = (locator.inner_text(timeout=2000) or "").strip().lower()
        if any(p == texto or texto.startswith(p) for p in S.PROIBIDOS):
            raise PermissaoNegada(f"clique recusado em controle de escrita: '{texto}' ({descricao})")
        locator.click()

    # ------------------------------------------------------------ autenticação
    def autenticar(self) -> None:
        """Login com conferência dos campos ANTES de enviar (incidente 26/11 09:51: a tela de login recarregou
        durante o preenchimento e a senha caiu no campo Login). Nunca clica em 'Entrar' com campos divergentes."""
        self._iniciar()
        usuario, senha = self.cfg.credenciais()
        for tentativa in (1, 2, 3):
            try:
                self.page.goto(self.cfg.url, wait_until="load")
                self.page.wait_for_load_state("networkidle", timeout=15000)
            except Exception as e:  # noqa: BLE001
                if tentativa == 3:
                    raise OrigemIndisponivel(f"falha ao abrir URL: {e}") from e
                continue
            if self._frame_com(S.LOGADO_MARCA, 2000) and not self._frame_com(S.LOGIN_USUARIO, 500):
                return
            fr = self._frame_com(S.LOGIN_USUARIO)
            if fr is None:
                raise AutenticacaoIntervencao("tela de login não reconhecida (captcha/Cloudflare/alteração de layout?)")
            self.page.wait_for_timeout(1500)                  # deixa o form terminar de carregar
            fr = self._frame_com(S.LOGIN_USUARIO)
            try:
                u, p = fr.locator(S.LOGIN_USUARIO).first, fr.locator(S.LOGIN_SENHA).first
                u.click(); u.fill(usuario)
                p.click(); p.fill(senha)
                ok = (u.input_value() == usuario and p.input_value() == senha and
                      fr.locator(S.LOGIN_SENHA).first.get_attribute("type") == "password")
            except Exception:  # noqa: BLE001  frame recarregou no meio
                ok = False
            if not ok:
                log.warning("login: campos não conferem após preenchimento (tentativa %d); recarregando sem enviar", tentativa)
                try:
                    fr.locator(S.LOGIN_USUARIO).first.fill("")
                    fr.locator(S.LOGIN_SENHA).first.fill("")
                except Exception:  # noqa: BLE001
                    pass
                continue
            fr.locator(S.LOGIN_BOTAO).first.click()
            if self._frame_com(S.LOGADO_MARCA, self.cfg.timeout_navegacao_ms):
                log.info("autenticado no SIGA")
                return
            if self._frame_com(S.LOGIN_USUARIO, 2000):
                raise PermissaoNegada("login recusado (credencial inválida, vazia ou bloqueada)")
            raise AutenticacaoIntervencao("após login apareceu tela não mapeada (MFA/troca de senha?)")
        raise AutenticacaoIntervencao("não foi possível preencher o login de forma confiável após 3 tentativas")

    def verificar_sessao(self) -> None:
        if not self.page:
            raise SessaoExpirada("navegador não iniciado")
        if self._frame_com(S.LOGIN_MARCA_FRAME, 1000):
            raise SessaoExpirada("voltou para a tela de login")
        if not self._frame_com(S.LOGADO_MARCA, 5000):
            raise OrigemIndisponivel("menu do usuário não encontrado")

    # ------------------------------------------------------------ listagem
    def enumerar(self, filtro: Filtro) -> Iterator[PaginaListagem]:
        """Abre MOVIMENTAÇÃO > Sinistro - Novo > Localizar Sinistros e lê as respostas JSON.
        A VALIDAR NO PILOTO: se 'Próximo' busca no servidor, ordenação/estabilidade, filtro de seguradora,
        e se 'Sinistro - Antigo' contém outra parte do universo."""
        if filtro.protocolos:
            yield from self._enumerar_por_protocolos(filtro.protocolos)
            return
        self._menu("Sinistro - Novo")
        fr = self._frame_com(S.BOTAO_LOCALIZAR)
        with self.page.expect_response(lambda r: S.REGRA_ENDPOINT in r.url and S.REGRA_MARCA_LISTAGEM in (r.text() or "")) as resp:
            fr.locator(S.BOTAO_LOCALIZAR).first.click()
        # validado 26/11: o seletor 100/página recarrega do servidor a partir do início; 'Próximo' pagina no servidor
        lista = self._frame_com(S.LISTA_TABELA)
        with self.page.expect_response(lambda r: S.REGRA_ENDPOINT in r.url and S.REGRA_MARCA_LISTAGEM in (r.text() or "")) as resp:
            lista.locator(S.LISTA_TAMANHO_PAGINA).first.select_option("100")
        numero = 1
        dados = parse_rule_return(resp.value.text()) or []
        while True:
            regs = [registro_de(d) for d in dados]
            for r in regs:
                self._registros[r.protocolo] = r
                if r.id_interno:
                    self._registros_id[r.id_interno] = r
            lista = self._frame_com(S.LISTA_TABELA)
            prox = lista.locator(S.LISTA_PROXIMO).first if lista else None
            ultima = (not regs) or prox is None or not prox.is_enabled()
            yield PaginaListagem(numero=numero, registros=regs, total_exibido=None, cursor=f"pagina-{numero}",
                                 ultima=ultima)
            if ultima:
                return
            try:
                with self.page.expect_response(lambda r: S.REGRA_ENDPOINT in r.url and S.REGRA_MARCA_LISTAGEM in (r.text() or ""),
                                               timeout=self.cfg.timeout_navegacao_ms) as resp:
                    prox.click()
                dados = parse_rule_return(resp.value.text()) or []
            except Exception:  # noqa: BLE001 sem nova resposta: paginação local ou fim
                log.warning("Próximo não gerou nova consulta; paginação pode ser local (validar no piloto)")
                return
            numero += 1

    def _enumerar_por_protocolos(self, protocolos) -> Iterator[PaginaListagem]:
        raise PendenteDescoberta("busca por lista de protocolos: validar filtro 'Número' no piloto")

    # ------------------------------------------------------------ processo
    _JS_TEXTO_FORM = """() => document.body.innerText + ' ' +
        [...document.querySelectorAll('input, textarea')].map(i => i.value).join(' ')"""

    def _frame_evento(self, protocolo: Optional[str] = None):
        """Form 'Novo Histórico' do processo. Usa a janela guardada na abertura; senão procura pelo número
        no texto E nos campos (o número do evento fica num <input>, fora do innerText; validado 26/11)."""
        atual = getattr(self, "_atual", None) or {}
        protocolo = protocolo or atual.get("protocolo")
        fr = atual.get("frame")
        if fr is not None and atual.get("protocolo") == protocolo:
            try:
                if not fr.is_detached() and fr.locator(S.HIST_MARCA_FORM).count():
                    return fr
            except Exception:  # noqa: BLE001
                pass
        candidatos = []
        for fr in self.page.frames:
            try:
                if fr.locator(S.HIST_MARCA_FORM).count() and (not protocolo or protocolo in fr.evaluate(self._JS_TEXTO_FORM)):
                    candidatos.append(fr)
            except Exception:  # noqa: BLE001
                continue
        return candidatos[-1] if candidatos else None

    def _fechar_evento(self) -> None:
        """Fecha a janela do evento pelo botão do fluxo 'Novo Historico - Fechar' (validado 26/11: fecha sem diálogo).
        Nunca 'Salvar'. Espera a janela sumir para o próximo processo abrir numa janela nova."""
        import time
        for fr in list(self.page.frames):
            try:
                if fr.locator(S.HIST_MARCA_FORM).count() and fr.locator(S.EVENTO_FECHAR).count():
                    self._js_click(fr.locator(S.EVENTO_FECHAR).last)
            except Exception:  # noqa: BLE001
                continue
        limite = time.monotonic() + 10
        while time.monotonic() < limite:
            vivos = 0
            for fr in self.page.frames:
                try:
                    vivos += fr.locator(S.HIST_MARCA_FORM).count()
                except Exception:  # noqa: BLE001
                    continue
            if not vivos:
                return
            self.page.wait_for_timeout(300)
        log.warning("janela do evento anterior não fechou em 10s")

    def _abriu_aba(self, abas_antes) -> bool:
        return any(a not in abas_antes for a in self._ctx.pages)

    def _fechar_abas_extras(self) -> None:
        """Fecha abas que o SIGA abriu para mostrar arquivos (nunca a aba principal)."""
        for aba in list(self._ctx.pages):
            if aba is not self.page:
                try:
                    aba.close()
                except Exception:  # noqa: BLE001
                    pass

    def _fechar_visualizador(self, esperar_ms: int = 0) -> None:
        """Fecha a janela interna 'novo - abrir imagem' (div.WFRIframeForm; último botão do cabeçalho = ×).
        Com esperar_ms, aguarda a janela aparecer (ela abre de forma assíncrona após a regra)."""
        import time
        limite = time.monotonic() + esperar_ms / 1000
        while True:
            if self._fechar_visualizador_uma_vez() or time.monotonic() >= limite:
                break
            self.page.wait_for_timeout(200)
        self.page.wait_for_timeout(100)

    def _fechar_visualizador_uma_vez(self) -> int:
        total = 0
        # validado 26/11 10:30: o × é <a class="OptionClose"><span class="fas fa-times"></a> (a classe muda no hover);
        # fecha com mousedown/mouseup/click. A janela some do DOM.
        js = """() => { let n = 0; document.querySelectorAll('div.WFRIframeForm').forEach(w => {
                  const h = w.querySelector('.card-header');
                  if (h && /novo - abrir imagem/i.test(h.textContent || '')) {
                    const ic = h.querySelector('.fa-times'); const x = ic ? ic.closest('a') : null;
                    if (x) { ['mousedown', 'mouseup', 'click'].forEach(t => x.dispatchEvent(
                               new MouseEvent(t, {bubbles: true, cancelable: true, view: window}))); n++; } } });
                  return n; }"""
        for fr in self.page.frames:
            try:
                total += int(fr.evaluate(js) or 0)
            except Exception:  # noqa: BLE001
                continue
        return total

    def capturar_evidencia(self, nome: str) -> Optional[Path]:
        """Print da tela do robô (pasta evidencias/, ao lado de relatorios/). Contém dados de sinistro: acesso restrito."""
        if not self.page:
            return None
        try:
            from datetime import datetime
            from ..naming import limpar_componente
            pasta = Path(self.cfg.relatorios).parent / "evidencias"
            pasta.mkdir(parents=True, exist_ok=True)
            arq = pasta / f"{datetime.now():%Y%m%d_%H%M%S}_{limpar_componente(nome, 80)}.png"
            self.page.screenshot(path=str(arq))
            return arq
        except Exception:  # noqa: BLE001
            return None

    def _alerta_arquivo_ausente(self) -> Optional[str]:
        """Se o SIGA mostrou o alerta 'O sistema não pode encontrar o caminho/arquivo', fecha com OK e devolve o texto."""
        for fr in self.page.frames:
            try:
                txt = fr.evaluate("""() => { const a = document.querySelector('.swal2-container .swal2-html-container,'
                                     + '.swal2-container .swal2-content, .swal-text, .sweet-alert p');
                                     return a ? (a.textContent || '').trim() : null; }""")
                if txt and re.search(r"n[ãa]o pode encontrar|not find|n[ãa]o encontrad", txt, re.I):
                    atual = (getattr(self, "_atual", None) or {}).get("protocolo", "")
                    self._ultima_evidencia = self.capturar_evidencia(f"{atual}_arquivo_ausente")  # antes do OK
                    fr.locator(S.ALERTA_OK).first.click()
                    return txt
            except Exception:  # noqa: BLE001
                continue
        return None

    def _tolerar_alerta(self) -> None:
        """Fecha o alerta conhecido 'Erro de conversão' do SIGA."""
        for fr in self.page.frames:
            try:
                if fr.locator(f"text={S.ALERTA_TOLERADO}").count():
                    fr.locator(S.ALERTA_OK).first.click()
                    log.info("alerta conhecido do SIGA fechado: %s", S.ALERTA_TOLERADO)
            except Exception:  # noqa: BLE001
                continue

    def _frame_evento_por_id(self, idi: str):
        """Janela 'Novo Histórico' cujo SIN_ID é o ID interno pedido (para sinistros sem número/número repetido)."""
        for fr in self.page.frames:
            try:
                if fr.locator(S.HIST_MARCA_FORM).count():
                    sin = fr.evaluate("() => { try { return String(parent.ebfGetClientFormVariable('SIN_ID')) } "
                                      "catch (e) { return null } }")
                    if sin == str(idi):
                        return fr
            except Exception:  # noqa: BLE001
                continue
        return None

    def abrir_processo(self, protocolo: str, id_interno: Optional[str] = None) -> DetalheProcesso:
        from ..models import chave_composta, numero_da_chave
        chave = protocolo
        idi = id_interno or ((self._registros.get(chave).id_interno) if self._registros.get(chave) else None)
        reg = self._registros_id.get(idi) if idi else self._registros.get(chave)
        self._fechar_visualizador()
        self._fechar_evento()
        self._atual = None
        self._tipo_carregado = None
        fr = self._frame_com(S.CRONO_BUSCA, 2000)
        if fr is None:
            self._menu("Cronograma")
            fr = self._frame_com(S.CRONO_BUSCA)
        if chave_composta(chave):
            # Número '0' ou repetido no SIGA: abre pelo ID interno com o mesmo fluxo do botão "Abrir evento"
            if not idi:
                raise ProcessoTrocado(f"{chave}: sem ID interno para abrir")
            fr.evaluate("""(v) => parent.ebfFlowExecute('Novo Controle de Eventos - Abrir Novo Historico (Cliente)',
                                                         parent.ebfListParamsCreate(v))""", str(idi))
            import time
            limite = time.monotonic() + self.cfg.timeout_navegacao_ms / 1000
            fe = None
            self.page.wait_for_timeout(2000)
            while time.monotonic() < limite and fe is None:
                self._tolerar_alerta()
                fe = self._frame_evento_por_id(idi)
                if fe is None:
                    self.page.wait_for_timeout(500)
            if fe is None:
                raise OrigemIndisponivel(f"form 'Novo Histórico' de {chave} não abriu")
            numero = numero_da_chave(chave)
            if numero and numero not in fe.evaluate(self._JS_TEXTO_FORM):
                raise ProcessoTrocado(f"form aberto para ID {idi} não mostra {numero}")
            self._atual = {"protocolo": chave, "id_interno": idi, "frame": fe}
            return DetalheProcesso(protocolo=chave, id_interno=idi,
                                   placa=reg.placa if reg else None, evento=reg.tipo_evento if reg else None,
                                   cpfcnpj=reg.cpfcnpj if reg else None,
                                   valores_originais={"numero": (reg.protocolo if reg else "") or "",
                                                      "placa": (reg.placa if reg else "") or "",
                                                      "tipoevento": (reg.tipo_evento if reg else "") or "",
                                                      "cpfcnpj": (reg.cpfcnpj if reg else "") or "",
                                                      "idsin": idi})
        if not fr.locator(S.CRONO_BUSCA).is_visible():
            fr.evaluate("() => limparPesquisa()")                       # volta ao campo de pesquisa
        fr.locator(S.CRONO_BUSCA).fill(protocolo)
        fr.locator(S.CRONO_BUSCA).press("Tab")                          # onchange dispara a pesquisa
        # validado 26/11: cada opção do select2 tem id "select2-evento_select-result-<x>-<idsin>".
        # A seleção é feita pela API do componente (clique visual pode ser bloqueado por janelas sobrepostas).
        import time
        limite = time.monotonic() + self.cfg.timeout_navegacao_ms / 1000
        exatas = []
        while time.monotonic() < limite:
            opcoes = fr.evaluate("""() => [...document.querySelectorAll('.select2-results__option')]
                                     .map(o => ({id: o.id || '', txt: (o.textContent || '').trim()}))""")
            exatas = [o for o in opcoes if re.match(rf"^{re.escape(protocolo)}\b", o["txt"])]
            if exatas:
                break
            self.page.wait_for_timeout(500)
        if len(exatas) != 1:
            raise ProcessoTrocado(f"busca por {protocolo} retornou {len(exatas)} opções exatas")
        valor = exatas[0]["id"].rsplit("-", 1)[-1]
        if idi and valor != str(idi):
            raise ProcessoTrocado(f"opção {valor} difere do idsin {idi}")
        fr.evaluate("""(v) => { const $ = window.j || window.jQuery; const s = $('#evento_select');
                         s.val(v).trigger('change'); try { s.select2('close'); } catch (e) {} }""", valor)
        if str(fr.evaluate(S.CRONO_SELECT_VALOR)) != valor:
            raise ProcessoTrocado(f"não foi possível selecionar {protocolo}")
        idi = idi or valor
        self._js_click(fr.locator(S.CRONO_ABRIR_EVENTO).first)
        self.page.wait_for_timeout(2000)
        self._tolerar_alerta()
        import time
        limite = time.monotonic() + self.cfg.timeout_navegacao_ms / 1000
        fe = None
        while time.monotonic() < limite and fe is None:
            fe = self._frame_evento(protocolo)
            if fe is None:
                self.page.wait_for_timeout(500)
                self._tolerar_alerta()
        if fe is None:
            raise OrigemIndisponivel(f"form 'Novo Histórico' de {protocolo} não abriu")
        self._atual = {"protocolo": protocolo, "id_interno": idi, "frame": fe}
        return DetalheProcesso(protocolo=protocolo, id_interno=idi,
                               placa=reg.placa if reg else None, evento=reg.tipo_evento if reg else None,
                               cpfcnpj=reg.cpfcnpj if reg else None,
                               valores_originais={"placa": (reg.placa if reg else "") or "",
                                                  "tipoevento": (reg.tipo_evento if reg else "") or "",
                                                  "cpfcnpj": (reg.cpfcnpj if reg else "") or "",
                                                  "idsin": idi or ""})

    def _get(self, caminho: str):
        base = self.cfg.url.split("/open.do")[0]
        r = self._ctx.request.get(f"{base}/{caminho.lstrip('/')}", timeout=self.cfg.timeout_download_ms)
        if r.status in (401, 403):
            raise SessaoExpirada(f"HTTP {r.status} em {caminho[:40]}")
        if r.status >= 500:
            raise OrigemIndisponivel(f"HTTP {r.status}")
        return r

    def exportar_historico(self, protocolo: str, pasta_staging: Path) -> Path:
        from urllib.parse import quote
        atual = getattr(self, "_atual", None) or {}
        if atual.get("protocolo") != protocolo or not atual.get("id_interno"):
            raise ProcessoTrocado("histórico pedido para processo diferente do aberto")
        u1 = S.HIST_URL_1.format(report=quote(S.HIST_RELATORIO_ID), id_interno=atual["id_interno"])
        m = re.search(r"openWFRReportFinal\('[^']*',\s*'([^']+)'", self._get(u1).text())
        if not m:
            raise HistoricoInvalido("relatório não retornou openreport.jsp")
        m2 = re.search(r"window\.location\s*=\s*'([^']+\.PDF)'", self._get(m.group(1)).text(), re.I)
        if not m2:
            raise HistoricoInvalido("openreport.jsp não indicou o PDF gerado")
        r = self._get(m2.group(1))
        if "pdf" not in (r.headers.get("content-type") or ""):
            raise HistoricoInvalido(f"content-type inesperado: {r.headers.get('content-type')}")
        destino = pasta_staging / f"historico_{protocolo}.pdf"
        destino.write_bytes(r.body())
        return destino

    def _carregar_tipo(self, fe, id_tipo: str, nome_tipo: Optional[str] = None, esperado: Optional[int] = None):
        """Clica no tipo de anexo e espera #tabela-anexos mostrar SÓ linhas desse tipo (evita ler a tabela velha,
        observado 26/11). Retorna a lista de linhas [id, #, tipo, arquivo, usuário, data]."""
        import time
        info = fe.evaluate("""(idt) => { const tr = [...document.querySelectorAll('#tabela-tipo-anexo tbody tr')]
                     .find(r => (r.children[0]?.textContent || '').trim() === idt);
                   if (!tr) return null; const nome = (tr.children[2]?.textContent || '').trim();
                   // limpa só a exibição local da tabela (nada vai ao servidor) para não ler linhas velhas
                   try { const $ = window.j || window.jQuery; $('#tabela-anexos').DataTable().clear().draw(); }
                   catch (e) { document.querySelectorAll('#tabela-anexos tbody tr').forEach(x => x.remove()); }
                   tr.children[2].click(); return nome; }""", id_tipo)
        if info is None:
            raise ListagemIncompletaAdaptador(f"tipo de anexo {id_tipo} não encontrado")
        self._tipo_carregado = None
        nome_tipo = nome_tipo or info
        limite = time.monotonic() + 15
        linhas = []
        while time.monotonic() < limite:
            self.page.wait_for_timeout(250)
            linhas = fe.evaluate("""() => { try { const $ = window.j || window.jQuery;   // mostra todas as linhas (só exibição)
                         const t = $('#tabela-anexos').DataTable(); if (t.page.len() !== -1) t.page.len(-1).draw(false); }
                       catch (e) {}
                       return [...document.querySelectorAll('#tabela-anexos tbody tr')]
                       .map(r => [...r.children].map(c => (c.textContent || '').trim()))
                       .filter(c => c.length >= 6 && /^\\d+$/.test(c[0])); }""")
            if linhas and all(l[2] == nome_tipo for l in linhas) and (esperado is None or len(linhas) >= esperado):
                self._tipo_carregado = id_tipo
                return linhas
        return [l for l in linhas if l[2] == nome_tipo]

    def listar_anexos(self, protocolo: str) -> ListagemAnexos:
        fe = self._frame_evento(protocolo)
        if fe is None or (getattr(self, "_atual", None) or {}).get("protocolo") != protocolo:
            raise ProcessoTrocado("aba Anexos pedida sem o processo aberto")
        self._js_click(fe.locator(S.ANEXOS_ABA).first)
        fe.wait_for_timeout(1500)
        anexos: list[AnexoRef] = []
        divergencias = []
        tipos = fe.locator(S.ANEXOS_TIPOS_LINHAS)
        for i in range(tipos.count()):
            celulas = [c.strip() for c in tipos.nth(i).locator("td").all_inner_texts()]
            if len(celulas) < 4 or "/" not in celulas[3]:
                continue
            id_tipo, nome_tipo, qtde = celulas[0], celulas[2], int(celulas[3].split("/")[0] or 0)
            if qtde == 0:
                continue
            linhas_tipo = self._carregar_tipo(fe, id_tipo, nome_tipo, qtde)
            lidas = 0
            for c in linhas_tipo:
                lidas += 1
                anexos.append(AnexoRef(nome_original=c[3], contexto=f"tipo{id_tipo}", ordinal=lidas, id_origem=c[0],
                                       tamanho=None, data=c[5], rotulo=nome_tipo))
            if lidas != qtde:
                divergencias.append(f"{nome_tipo}: listados {lidas} de {qtde}")
        self._anexos_vistos = {a.id_origem: a for a in anexos}
        return ListagemAnexos(anexos=anexos, completa=not divergencias, observacao="; ".join(divergencias))

    def baixar_anexo(self, protocolo: str, anexo: AnexoRef, pasta_staging: Path) -> Path:
        fe = self._frame_evento(protocolo)
        if fe is None:
            raise ProcessoTrocado(f"janela do evento {protocolo} não encontrada para baixar o anexo")
        id_tipo = anexo.contexto.removeprefix("tipo")
        # otimização: só recarrega a tabela se o tipo mudou (antes recarregava a cada anexo)
        linha = fe.locator(S.ANEXOS_LINHAS).filter(has=fe.locator(f"td:text-is('{anexo.id_origem}')"))
        if getattr(self, "_tipo_carregado", None) != id_tipo or linha.count() != 1:
            self._carregar_tipo(fe, id_tipo)
            linha = fe.locator(S.ANEXOS_LINHAS).filter(has=fe.locator(f"td:text-is('{anexo.id_origem}')"))
        if linha.count() != 1:
            raise DownloadFalhou(f"linha do anexo {anexo.id_origem} não encontrada no tipo {id_tipo}")
        # validado 26/11: a regra 'novo - abrir imagem - obter url' devolve a URL no corpo do executeRule.do;
        # o visualizador de PDF do Chromium não gera requisição observável, então a URL é lida da resposta.
        # Escuta as respostas da regra; ao mesmo tempo observa o alerta de "arquivo inexistente" do SIGA.
        capturadas: list[str] = []

        def ao_responder(r):
            if S.REGRA_ENDPOINT in r.url:
                try:
                    t = r.text() or ""
                    if "_ruleReturn" in t:
                        capturadas.append(t)
                except Exception:  # noqa: BLE001
                    pass
        self.page.on("response", ao_responder)
        abas_antes = set(self._ctx.pages)
        try:
            self._js_click(linha.locator(S.ANEXO_ABRIR).first)          # nunca 'excluir'
            import time
            limite = time.monotonic() + self.cfg.timeout_navegacao_ms / 1000
            url = None
            while time.monotonic() < limite and url is None:
                for t in capturadas:
                    m = re.search(r"_ruleReturn\s*=\s*'(https?://[^']+)'", t)
                    if m and S.ANEXOS_HOST in m.group(1):
                        url = m.group(1)
                        break
                if url:
                    break
                # evidência 26/11: em parte dos sinistros (2025) o SIGA abre o arquivo numa ABA NOVA
                for aba in self._ctx.pages:
                    if aba not in abas_antes and S.ANEXOS_HOST in (aba.url or ""):
                        url = aba.url
                        break
                if url:
                    break
                aviso = self._alerta_arquivo_ausente()
                if aviso:
                    erro = ArquivoAusenteNaOrigem(f"anexo {anexo.id_origem} ({anexo.nome_original}): {aviso[:200]}")
                    erro.evidencia = getattr(self, "_ultima_evidencia", None)
                    raise erro
                self.page.wait_for_timeout(150)
        finally:
            self.page.remove_listener("response", ao_responder)
        if not url:
            raise DownloadFalhou(f"URL do anexo {anexo.id_origem} não veio na resposta do SIGA")
        # Decisão 26/11 (negócio): cada placa/processo recebe a própria cópia, inclusive de documentos compartilhados
        # entre processos vinculados da mesma frota. O vínculo é garantido pela listagem do próprio processo
        # (tabela limpa antes de cada tipo); a pasta de origem no SIGA fica registrada no log de auditoria.
        m_orig = re.search(r"/BVIX/([^/]+)/", url, re.I)
        origem = m_orig.group(1) if m_orig else "?"
        if origem != protocolo:
            log.warning("%s: anexo %s (%s) é compartilhado; arquivo armazenado no SIGA em %s; copiado para este processo",
                        protocolo, anexo.id_origem, anexo.nome_original, origem)
        r = self._ctx.request.get(url, timeout=self.cfg.timeout_download_ms)
        if r.status != 200:
            raise DownloadFalhou(f"HTTP {r.status} ao baixar anexo {anexo.id_origem}")
        abriu_aba = self._abriu_aba(abas_antes)
        self._fechar_abas_extras()
        self._fechar_visualizador(esperar_ms=0 if abriu_aba else 8000)
        from ..naming import limpar_componente
        destino = pasta_staging / f"{anexo.id_origem}__{limpar_componente(anexo.nome_original)}"
        destino.write_bytes(r.body())
        return destino

    def encerrar(self) -> None:
        for obj, m in ((self._ctx, "close"), (self._browser, "close"), (self._pw, "stop")):
            try:
                if obj:
                    getattr(obj, m)()
            except Exception:  # noqa: BLE001
                pass
        self.page = self._ctx = self._browser = self._pw = None
