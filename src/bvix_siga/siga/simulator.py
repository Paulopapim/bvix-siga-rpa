"""Simulador do SIGA com falhas injetáveis. Usado nos testes e no piloto sem acesso (CLI --simulador).

Só contém dados fictícios. Modela o que foi observado em 26/11 (listagem com idsin/numerosin/placa/cpfcnpj/
tipoevento) e hipóteses ainda não verificadas para histórico/anexos (PD-06/PD-07)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator, Optional

from ..errors import (AutenticacaoIntervencao, DownloadFalhou, OrigemIndisponivel, PermissaoNegada,
                      SessaoExpirada)
from ..models import AnexoRef, DetalheProcesso, Filtro, ListagemAnexos, PaginaListagem, RegistroListagem


@dataclass
class AnexoSim:
    nome: str
    conteudo: bytes
    contexto: str = "processo"
    id_origem: Optional[str] = None
    data: Optional[str] = None


@dataclass
class ProcessoSim:
    protocolo: str
    id_interno: str
    placa: Optional[str]
    evento: Optional[str]
    cpfcnpj: Optional[str]
    historico: list[str] = field(default_factory=lambda: ["Comunicação inicial do sinistro"])
    anexos: list[AnexoSim] = field(default_factory=list)


@dataclass
class Falhas:
    mfa: bool = False
    permissao_negada: bool = False
    pagina_repetida_em: Optional[int] = None         # repete a página anterior neste número
    fim_prematuro_em: Optional[int] = None           # declara última página cedo
    total_exibido_falso: Optional[int] = None
    sessao_expira_apos_chamadas: Optional[int] = None
    sessao_nao_volta: bool = False
    troca_processo: set[str] = field(default_factory=set)        # abre outro processo (sempre)
    historico_vazio: set[str] = field(default_factory=set)
    historico_tela_login: set[str] = field(default_factory=set)
    listagem_incompleta: set[str] = field(default_factory=set)
    download_falha_vezes: dict[str, int] = field(default_factory=dict)   # "proto#ordinal" -> nº falhas
    download_truncado: set[str] = field(default_factory=set)
    arquivo_ausente: set[str] = field(default_factory=set)          # "proto#contexto#ordinal": SIGA lista, servidor não tem
    origem_fora: bool = False


def pdf(texto: str) -> bytes:
    corpo = f"%PDF-1.4\n% simulado\n{texto}\n" + ("x" * 300) + "\n%%EOF\n"
    return corpo.encode("utf-8")


class SigaSimulado:
    def __init__(self, processos: list[ProcessoSim], tamanho_pagina: int = 10, falhas: Optional[Falhas] = None,
                 carimbo_impressao: bool = False):
        self.lista = list(processos)                       # o SIGA real tem números repetidos e "0"
        self.processos = {p.protocolo: p for p in processos}
        self.tamanho_pagina = tamanho_pagina
        self.falhas = falhas or Falhas()
        self.carimbo_impressao = carimbo_impressao  # simula metadado que muda a cada impressão
        self.chamadas = 0
        self.logado = False
        self.impressoes = 0
        self._fail_count: dict[str, int] = {}
        self.operacoes_escrita = 0  # deve permanecer 0 (CA-11)
        self._expirou = False

    # ---------------------------------------------------------------- auth
    def autenticar(self) -> None:
        if self.falhas.mfa:
            raise AutenticacaoIntervencao("MFA exigido")
        if self.falhas.permissao_negada:
            raise PermissaoNegada("perfil sem acesso a sinistros")
        if self.falhas.sessao_nao_volta and self._expirou:
            raise SessaoExpirada("login recusado após expiração")
        self.logado = True

    def verificar_sessao(self) -> None:
        self._tick()

    def _tick(self) -> None:
        if self.falhas.origem_fora:
            raise OrigemIndisponivel("portal fora do ar")
        if not self.logado:
            raise SessaoExpirada("não autenticado")
        self.chamadas += 1
        lim = self.falhas.sessao_expira_apos_chamadas
        if lim is not None and self.chamadas > lim:
            self.logado = False
            self._expirou = True
            if not self.falhas.sessao_nao_volta:
                self.falhas.sessao_expira_apos_chamadas = None  # expira uma vez só
            raise SessaoExpirada("sessão expirou")

    # ---------------------------------------------------------------- listagem
    def enumerar(self, filtro: Filtro) -> Iterator[PaginaListagem]:
        self._tick()
        extras = [p for p in self.processos.values() if p not in self.lista]   # incluídos depois (testes)
        todos = sorted(self.lista + extras, key=lambda p: p.protocolo, reverse=True)  # ordem observada
        if filtro.protocolos:
            todos = [p for p in todos if p.protocolo in filtro.protocolos]
        paginas = [todos[i:i + self.tamanho_pagina] for i in range(0, len(todos), self.tamanho_pagina)] or [[]]
        total = self.falhas.total_exibido_falso if self.falhas.total_exibido_falso is not None else len(todos)
        anterior = None
        for n, chunk in enumerate(paginas, start=1):
            if self.falhas.pagina_repetida_em == n and anterior is not None:
                chunk = anterior
            ultima = n == len(paginas) or self.falhas.fim_prematuro_em == n
            yield PaginaListagem(numero=n, registros=[RegistroListagem(p.protocolo, p.id_interno, p.placa, p.cpfcnpj,
                                                                       p.evento) for p in chunk],
                                 total_exibido=total, cursor=f"p{n}", ultima=ultima)
            anterior = chunk
            if ultima:
                return

    def _proc(self, chave: str) -> ProcessoSim:
        from ..models import chave_composta
        if chave_composta(chave):
            idi = chave.rsplit("-", 1)[-1].removeprefix("ID")
            return next(p for p in self.lista if p.id_interno == idi)
        return self.processos[chave]

    # ---------------------------------------------------------------- processo
    def abrir_processo(self, protocolo: str, id_interno: Optional[str] = None) -> DetalheProcesso:
        self._tick()
        p = self._proc(protocolo)
        if protocolo in self.falhas.troca_processo:
            outro = next(x for x in self.processos.values() if x.protocolo != protocolo)
            p = outro
        from ..models import chave_composta
        return DetalheProcesso(protocolo=protocolo if chave_composta(protocolo) and p is self._proc(protocolo) else p.protocolo,
                               id_interno=p.id_interno, placa=p.placa, evento=p.evento,
                               cpfcnpj=p.cpfcnpj,
                               valores_originais={"placa": p.placa or "", "evento": p.evento or "",
                                                  "cpfcnpj": p.cpfcnpj or ""})

    def exportar_historico(self, protocolo: str, pasta_staging: Path) -> Path:
        self._tick()
        self.impressoes += 1
        p = self._proc(protocolo)
        destino = pasta_staging / f"historico_{protocolo}.pdf"
        if protocolo in self.falhas.historico_vazio:
            destino.write_bytes(b"")
        elif protocolo in self.falhas.historico_tela_login:
            destino.write_bytes(b"<html><body>LoginPrincipal Entre com seus dados</body></html>" + b" " * 400)
        else:
            carimbo = f"\nImpresso em #{self.impressoes}" if self.carimbo_impressao else ""
            destino.write_bytes(pdf(f"{protocolo}\n" + "\n".join(p.historico) + carimbo))
        return destino

    def listar_anexos(self, protocolo: str) -> ListagemAnexos:
        self._tick()
        p = self._proc(protocolo)
        if protocolo in self.falhas.listagem_incompleta:
            return ListagemAnexos(anexos=[], completa=False, observacao="seção de anexos não carregou")
        ordinais: dict[str, int] = {}
        refs = []
        for a in p.anexos:
            ordinais[a.contexto] = ordinais.get(a.contexto, 0) + 1
            refs.append(AnexoRef(nome_original=a.nome, contexto=a.contexto, ordinal=ordinais[a.contexto],
                                 id_origem=a.id_origem, tamanho=len(a.conteudo), data=a.data,
                                 rotulo="Documentos" if a.contexto == "processo" else f"Historico {a.contexto}"))
        return ListagemAnexos(anexos=refs, completa=True)

    def baixar_anexo(self, protocolo: str, anexo: AnexoRef, pasta_staging: Path) -> Path:
        self._tick()
        chave = f"{protocolo}#{anexo.ordinal}"
        if f"{protocolo}#{anexo.contexto}#{anexo.ordinal}" in self.falhas.arquivo_ausente:
            from ..errors import ArquivoAusenteNaOrigem
            raise ArquivoAusenteNaOrigem("O sistema não pode encontrar o caminho especificado")
        faltam = self.falhas.download_falha_vezes.get(chave, 0) - self._fail_count.get(chave, 0)
        if faltam > 0:
            self._fail_count[chave] = self._fail_count.get(chave, 0) + 1
            raise DownloadFalhou("erro no download")
        p = self._proc(protocolo)
        candidatos = [a for a in p.anexos if a.contexto == anexo.contexto]
        a = candidatos[anexo.ordinal - 1]
        destino = pasta_staging / f"dl_{anexo.ordinal}_{anexo.contexto}_{a.nome}"
        conteudo = a.conteudo[: len(a.conteudo) // 2] if chave in self.falhas.download_truncado else a.conteudo
        destino.write_bytes(conteudo)
        return destino

    def encerrar(self) -> None:
        self.logado = False


def cenario_piloto() -> list[ProcessoSim]:
    """Casos do piloto (prompt §piloto): múltiplos anexos, sem anexo, terceiro, placas repetidas, homônimos,
    alto volume, CPF no lugar de CNPJ, evento nulo."""
    return [
        ProcessoSim("2026-00001", "1001", "ABC1D23", "COLISÃO", "00.000.000/0001-91",
                    anexos=[AnexoSim("BO.pdf", pdf("bo")), AnexoSim("CNH.jpg", b"\xff\xd8\xff" + b"j" * 500),
                            AnexoSim("Orçamento.pdf", pdf("orc"), contexto="0002")]),
        ProcessoSim("2026-00002", "1002", "ABC1D23", "CONSTATACAO DE DANOS", "00.000.000/0001-91"),  # mesma placa, sem anexo
        ProcessoSim("2026-00003", "1003", "XYZ9K88", "COLISÃO", "012.345.678-90",
                    anexos=[AnexoSim("foto.jpg", b"\xff\xd8\xff" + b"a" * 300),
                            AnexoSim("foto.jpg", b"\xff\xd8\xff" + b"b" * 300)]),            # homônimos
        ProcessoSim("2026-00004", "1004", "QWE4R56", None, "11.111.111/0001-11",
                    anexos=[AnexoSim("doc.pdf", pdf("d"))]),                                   # evento nulo
        ProcessoSim("2026-00005", "1005", "MNB7V65", "ROUBO", "22.222.222/0001-22",
                    anexos=[AnexoSim(f"pagina_{i:02d}.pdf", pdf(f"p{i}")) for i in range(1, 51)]),  # 50 anexos
    ]
