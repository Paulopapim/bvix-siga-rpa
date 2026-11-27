"""Orquestração: preflight, descoberta, processamento por processo/item, incremental, retomada e reconciliação.

Invariantes (PDD TB-06/TB-07, CA-06):
- um item só é CONFIRMADO depois que o arquivo final foi gravado e o hash relido no destino;
- um processo só é COMPLETO com histórico confirmado + todos os anexos inventariados confirmados
  + listagem reconhecida como completa; sem anexos e listagem completa => COMPLETO_SEM_ANEXOS;
- falha sistêmica (sessão, permissão, destino, origem fora do ar em série) suspende a execução;
- nada é sobrescrito: conteúdo novo para o mesmo item vira nova versão (CA-07/CA-08).
"""

from __future__ import annotations

import logging
import shutil
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Iterable, Optional, TypeVar

from . import naming
from .config import PoliticaTentativas
from .destination import Destino, sha256_arquivo
from .errors import (ColisaoChave, EnumeracaoInconsistente, FalhaTransitoria, IdentificacaoInvalida, ListagemIncompleta,
                     OrigemIndisponivel, ProcessoTrocado, RpaError, SessaoExpirada)
from .models import (ESTADOS_PROCESSO_FINAIS, AnexoRef, EstadoItem, EstadoProcesso, Filtro, TipoItem,
                     chave_historico)
from .source import FonteSiga
from .state import Estado
from .validation import impressao_pdf, validar_anexo, validar_historico

log = logging.getLogger("bvix_siga")
T = TypeVar("T")


@dataclass
class Parametros:
    pasta_padrao: str
    pasta_campos_obrigatorios: list[str]
    staging: Path
    historico_tipos_aceitos: set[str] = field(default_factory=lambda: {"pdf"})
    historico_tamanho_minimo: int = 200
    espaco_minimo_bytes: int = 0
    tentativas: PoliticaTentativas = field(default_factory=PoliticaTentativas)
    padrao_grupo: str = "{placa}"    # nome da pasta no layout por_placa; ex.: "{placa}_{cpfcnpj}_{apolice}"
    layout: str = "por_processo"     # "por_processo" | "unica" (tudo numa pasta) | "por_placa" (pasta da placa, arquivos NÚMERO_…)


@dataclass
class ResultadoDescoberta:
    protocolos: list[str]
    paginas: int
    anomalias: list[str]
    total_exibido: Optional[int]
    cobertura_comprovada: bool
    nao_encontrados: list[str] = field(default_factory=list)
    novos: int = 0


@dataclass
class ResultadoExecucao:
    execucao_id: int
    status: str                      # concluida | concluida_com_pendencias | suspensa
    processados: int
    motivo_suspensao: Optional[str] = None
    descoberta: Optional[ResultadoDescoberta] = None


class SuspenderExecucao(Exception):
    def __init__(self, erro: RpaError):
        super().__init__(erro.motivo)
        self.erro = erro


class Orquestrador:
    def __init__(self, fonte: FonteSiga, destino: Destino, estado: Estado, params: Parametros,
                 dormir: Callable[[float], None] = time.sleep, ao_progresso: Optional[Callable[[], None]] = None,
                 progresso_cada: int = 10):
        self.fonte, self.destino, self.estado, self.p = fonte, destino, estado, params
        self.dormir = dormir
        self.ao_progresso = ao_progresso
        self.progresso_cada = progresso_cada
        self._falhas_origem_seguidas = 0
        self._autenticado = False

    # ------------------------------------------------------------------ preflight
    def preflight(self) -> dict[str, str]:
        checks: dict[str, str] = {}
        self.p.staging.mkdir(parents=True, exist_ok=True)
        teste = self.p.staging / f".pf-{uuid.uuid4().hex}"
        teste.write_bytes(b"ok")
        teste.unlink()
        checks["staging"] = "ok"
        livre = shutil.disk_usage(self.p.staging).free
        checks["staging_livre_bytes"] = str(livre)
        self.destino.verificar(self.p.espaco_minimo_bytes)
        checks["destino"] = "ok"
        self.fonte.autenticar()
        self._autenticado = True
        self.fonte.verificar_sessao()
        checks["origem_sessao"] = "ok"
        checks["relogio_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        return checks

    # ------------------------------------------------------------------ descoberta
    def descobrir(self, filtro: Filtro, exec_id: int, registrar: bool = True,
                  max_paginas: Optional[int] = None) -> ResultadoDescoberta:
        """Lê a listagem inteira e só depois registra. Identidade = ID interno (idsin): o SIGA tem números
        repetidos (ex.: 2 sinistros 2026-09757) e número '0' (validado 26/11)."""
        registros: list = []
        vistos_ids: set = set()
        paginas_vistas: list[tuple] = []
        anomalias: list[str] = []
        total: Optional[int] = None
        n_pag = 0
        chegou_ao_fim = False
        for pagina in self.fonte.enumerar(filtro):
            n_pag += 1
            anomalia = None
            ident = lambda r: r.id_interno or f"N:{r.protocolo}"  # noqa: E731
            assinatura = tuple(ident(r) for r in pagina.registros)
            if pagina.total_exibido is not None:
                if total is not None and pagina.total_exibido != total:
                    anomalia = f"total mudou de {total} para {pagina.total_exibido} durante a passagem"
                total = pagina.total_exibido
            if assinatura and assinatura in paginas_vistas:
                anomalia = f"página {pagina.numero} repete conteúdo anterior"
            repetidos = [x for x in assinatura if x in vistos_ids]
            if repetidos and not anomalia:
                anomalia = f"{len(repetidos)} sinistro(s) repetido(s) entre páginas (lista mudou?)"
            self.estado.registrar_pagina(exec_id, pagina.numero, pagina.cursor, pagina.total_exibido,
                                         pagina.protocolos, anomalia)
            if anomalia:
                anomalias.append(anomalia)
                log.warning("descoberta: %s", anomalia)
            paginas_vistas.append(assinatura)
            for reg in pagina.registros:
                if ident(reg) not in vistos_ids:
                    vistos_ids.add(ident(reg))
                    registros.append(reg)
            if anomalia and "repete" in anomalia:
                break  # paginação travada: não confiar no restante
            if pagina.ultima:
                chegou_ao_fim = True
                break
            if max_paginas and n_pag >= max_paginas:
                anomalias.append(f"piloto: descoberta limitada a {max_paginas} página(s)")
                break
        # chaves: número repetido com IDs diferentes ou número inválido -> chave composta
        from collections import Counter
        from .models import chave_processo, numero_valido
        cont = Counter(r.protocolo for r in registros)
        chaves: list[str] = []
        novos = 0
        compostas = 0
        for reg in registros:
            repetido = cont[reg.protocolo] > 1
            chave = chave_processo(reg.protocolo, reg.id_interno, repetido)
            chaves.append(chave)
            if chave != reg.protocolo:
                compostas += 1
                if registrar:
                    self.estado.renomear_processo(reg.protocolo, chave, exec_id)
            if registrar and self.estado.registrar_processo(chave, reg.id_interno, exec_id):
                novos += 1
            if registrar:
                atual = self.estado.processo(chave)
                if atual is not None and not atual["identificacao"]:
                    self.estado.salvar_identificacao(chave, {"numero": reg.protocolo, "id_interno": reg.id_interno,
                                                             "placa": reg.placa, "cpfcnpj": reg.cpfcnpj,
                                                             "evento": reg.tipo_evento, "fonte": "listagem"})
        if compostas:
            log.info("descoberta: %d sinistro(s) com número repetido/ausente receberam chave pelo ID interno", compostas)
        if total is not None and len(registros) < total:
            anomalias.append(f"fim prematuro: {len(registros)} únicos de {total} exibidos")
        if not chegou_ao_fim:
            anomalias.append("listagem não sinalizou a última página")
        nao_encontrados: list[str] = []
        if filtro.protocolos:
            achados = {r.protocolo for r in registros} | set(chaves)
            nao_encontrados = [p for p in filtro.protocolos if p not in achados]
            for p in nao_encontrados:
                if registrar:
                    self.estado.registrar_processo(p, None, exec_id)
                    self.estado.mudar_processo(p, EstadoProcesso.NAO_ENCONTRADO, exec_id, "EX-02",
                                               "protocolo da lista aprovada não encontrado na origem")
        comprovada = not anomalias and (total is None or len(registros) == total)
        return ResultadoDescoberta(protocolos=sorted(chaves), paginas=n_pag, anomalias=anomalias,
                                   total_exibido=total, cobertura_comprovada=comprovada,
                                   nao_encontrados=nao_encontrados, novos=novos)

    # ------------------------------------------------------------------ tentativas
    def _tentar(self, fn: Callable[[], T], descricao: str) -> T:
        pol = self.p.tentativas
        reautenticou = False
        tentativa = 0
        while True:
            tentativa += 1
            try:
                r = fn()
                self._falhas_origem_seguidas = 0
                return r
            except SessaoExpirada as e:
                if reautenticou:
                    raise SuspenderExecucao(e)
                log.warning("%s: sessão expirada; reautenticando uma vez", descricao)
                reautenticou = True
                try:
                    self.fonte.autenticar()
                except RpaError as e2:
                    raise SuspenderExecucao(e2)
                tentativa -= 1
            except Exception as bruto:  # noqa: BLE001  erros do navegador (timeout, elemento sumiu) viram transitórios
                e = bruto if isinstance(bruto, RpaError) else FalhaTransitoria(f"{type(bruto).__name__}: {str(bruto)[:300]}")
                if e is not bruto:
                    log.warning("%s: erro técnico tratado como transitório: %s", descricao, e.motivo)
                if e.sistemica:
                    raise SuspenderExecucao(e)
                if isinstance(e, OrigemIndisponivel):
                    self._falhas_origem_seguidas += 1
                    if self._falhas_origem_seguidas >= pol.falhas_consecutivas_para_suspender:
                        raise SuspenderExecucao(e)
                if not e.transitoria or tentativa >= pol.max_tentativas:
                    raise e
                espera = pol.espera(tentativa)
                log.info("%s: %s (tentativa %d/%d), aguardando %.1fs", descricao, e.codigo, tentativa,
                         pol.max_tentativas, espera)
                self.dormir(espera)

    # ------------------------------------------------------------------ publicação/versões
    def _preservar(self, chave: str, arquivo: Path, rel_por_versao: Callable[[int], str], exec_id: int,
                   impressao: Optional[str] = None) -> str:
        sha = sha256_arquivo(arquivo)
        if self.estado.versao_por_hash(chave, sha) or (impressao and self.estado.versao_por_impressao(chave, impressao)):
            self.estado.mudar_item(chave, EstadoItem.CONFIRMADO, exec_id, motivo="conteúdo já preservado")
            return "inalterado"
        versao = self.estado.proxima_versao(chave)
        while True:
            rel = rel_por_versao(versao)
            existente = self.destino.hash_existente(rel)
            if existente is None or existente == sha:
                break
            # arquivo órfão de queda anterior (gravado, não confirmado) com outro conteúdo: reconcilia como versão
            if not self.estado.versao_por_hash(chave, existente):
                self.estado.confirmar_versao(chave, versao, existente,
                                             self.destino_tamanho(rel), rel, exec_id)
                log.warning("reconciliado arquivo órfão %s como v%d", rel, versao)
            versao += 1
        pub = self.destino.publicar(arquivo, rel, sha)
        self.estado.confirmar_versao(chave, versao, pub.sha256, pub.tamanho, pub.caminho_relativo, exec_id, impressao)
        return "reaproveitado" if pub.reaproveitado else f"v{versao}"

    def _evidencia(self, tabela: str, chave: str, nome: str, erro: Optional[BaseException] = None) -> None:
        """Guarda o print do erro (se o adaptador souber tirar). Nunca derruba o processamento."""
        try:
            arq = getattr(erro, "evidencia", None) if erro is not None else None
            if not arq and hasattr(self.fonte, "capturar_evidencia"):
                arq = self.fonte.capturar_evidencia(nome)
            if arq:
                self.estado.registrar_evidencia(tabela, chave, str(arq))
        except Exception:  # noqa: BLE001
            log.debug("não foi possível registrar evidência de %s", nome)

    def destino_tamanho(self, rel: str) -> int:
        raiz = getattr(self.destino, "raiz", None)
        return (Path(raiz) / rel).stat().st_size if raiz else 0

    # ------------------------------------------------------------------ processo
    def processar(self, protocolo: str, exec_id: int) -> EstadoProcesso:
        st = self.estado
        row = st.processo(protocolo)
        id_interno = row["id_interno"] if row else None
        st.mudar_processo(protocolo, EstadoProcesso.EM_ANDAMENTO, exec_id)
        staging = self.p.staging / f"{exec_id}" / naming.limpar_componente(protocolo)
        staging.mkdir(parents=True, exist_ok=True)
        try:
            # 1) abrir e identificar
            def abrir():
                d = self.fonte.abrir_processo(protocolo, id_interno)
                if d.protocolo != protocolo:
                    raise ProcessoTrocado(f"tela mostra {d.protocolo}, fila esperava {protocolo}")
                return d
            det = self._tentar(abrir, f"{protocolo}/abrir")
            if row is not None and row["identificacao"]:          # completa com o que veio da listagem
                import json as _json
                lst = _json.loads(row["identificacao"])
                det.placa = det.placa or lst.get("placa")
                det.cpfcnpj = det.cpfcnpj or lst.get("cpfcnpj")
                det.evento = det.evento or lst.get("evento")
                det.apolice = det.apolice or lst.get("apolice")
            st.salvar_identificacao(protocolo, {**det.campos(), "valores_originais": det.valores_originais})
            try:
                pasta = naming.pasta_processo(self.p.pasta_padrao, det.campos(), self.p.pasta_campos_obrigatorios)
            except IdentificacaoInvalida as e:
                st.mudar_processo(protocolo, EstadoProcesso.TRATAMENTO, exec_id, e.codigo, e.motivo)
                return EstadoProcesso.TRATAMENTO
            try:
                self._dir_placa = naming.pasta_grupo(self.p.padrao_grupo, det.campos())
            except IdentificacaoInvalida as e:
                st.mudar_processo(protocolo, EstadoProcesso.TRATAMENTO, exec_id, e.codigo, e.motivo)
                return EstadoProcesso.TRATAMENTO
            conflito = st.reservar_pasta(protocolo, pasta)
            if conflito:
                e = ColisaoChave(f"pasta '{pasta}' já pertence a {conflito}")
                st.mudar_processo(protocolo, EstadoProcesso.TRATAMENTO, exec_id, e.codigo, e.motivo)
                return EstadoProcesso.TRATAMENTO

            # 2) histórico
            ch = chave_historico(protocolo)
            st.registrar_item(ch, protocolo, TipoItem.HISTORICO.value, nome_original="imprimir histórico",
                              contexto="processo", ordinal=0, exec_id=exec_id)
            self._item_historico(protocolo, ch, pasta, staging, exec_id)

            # 3) anexos
            listagem_ok = False
            try:
                listagem = self._tentar(lambda: self._listar(protocolo), f"{protocolo}/listar")
                listagem_ok = True
            except ListagemIncompleta as e:
                st.mudar_processo(protocolo, EstadoProcesso.EM_ANDAMENTO, exec_id, e.codigo, e.motivo,
                                  listagem_completa=False)
                listagem = getattr(e, "parcial", None)   # baixa o que foi listado; processo fica pendente
            if listagem is not None:
                presentes = set()
                for anexo in listagem.anexos:
                    chave = anexo.chave(protocolo)
                    presentes.add(chave)
                    self._item_anexo(protocolo, anexo, chave, pasta, staging, exec_id)
                ausentes = st.marcar_ausentes(protocolo, presentes) if listagem_ok else []
                if ausentes:
                    log.warning("%s: %d anexo(s) inventariados antes não aparecem mais na origem", protocolo, len(ausentes))

            # 4) fechamento do processo
            itens = st.itens(protocolo)
            nao_confirmados = [i for i in itens if i["estado"] != EstadoItem.CONFIRMADO.value and not i["ausente_na_origem"]]
            anexos_ativos = [i for i in itens if i["tipo"] == "anexo" and not i["ausente_na_origem"]]
            if not listagem_ok:
                final, cod, mot = EstadoProcesso.PENDENTE, "EX-07-LISTAGEM", "listagem de anexos não comprovada completa"
            elif nao_confirmados and all(i["codigo_excecao"] == "EX-06-SEM-ARQUIVO" for i in nao_confirmados):
                final, cod, mot = (EstadoProcesso.TRATAMENTO, "EX-06-SEM-ARQUIVO",
                                   f"{len(nao_confirmados)} anexo(s) listado(s) no SIGA sem arquivo no servidor da reguladora")
            elif nao_confirmados:
                final, cod, mot = EstadoProcesso.PENDENTE, "ITENS-PENDENTES", f"{len(nao_confirmados)} item(ns) não confirmados"
            elif not anexos_ativos:
                final, cod, mot = EstadoProcesso.COMPLETO_SEM_ANEXOS, None, "listagem verificada vazia"
            else:
                final, cod, mot = EstadoProcesso.COMPLETO, None, None
            st.mudar_processo(protocolo, final, exec_id, cod, mot, listagem_completa=listagem_ok)
            return final
        except SuspenderExecucao as s:
            st.mudar_processo(protocolo, EstadoProcesso.PENDENTE, exec_id, s.erro.codigo, s.erro.motivo)
            raise
        except RpaError as e:
            st.mudar_processo(protocolo, EstadoProcesso.PENDENTE, exec_id, e.codigo, e.motivo)
            self._evidencia("processos", protocolo, f"{protocolo}_{e.codigo}", e)
            return EstadoProcesso.PENDENTE
        except Exception as e:  # noqa: BLE001  nunca deixar o processo "em andamento" nem derrubar a carga
            log.exception("%s: erro inesperado", protocolo)
            st.mudar_processo(protocolo, EstadoProcesso.PENDENTE, exec_id, "INESPERADO", f"{type(e).__name__}: {str(e)[:300]}")
            self._evidencia("processos", protocolo, f"{protocolo}_INESPERADO", e)
            return EstadoProcesso.PENDENTE
        finally:
            shutil.rmtree(staging, ignore_errors=True)

    def _listar(self, protocolo: str):
        lst = self.fonte.listar_anexos(protocolo)
        if not lst.completa:
            e = ListagemIncompleta(lst.observacao or "adaptador não comprovou fim da listagem")
            e.parcial = lst
            raise e
        return lst

    def _item_historico(self, protocolo: str, chave: str, pasta: str, staging: Path, exec_id: int) -> None:
        st = self.estado
        st.mudar_item(chave, EstadoItem.EM_ANDAMENTO, exec_id)
        try:
            def exportar():
                arq = self.fonte.exportar_historico(protocolo, staging)
                tipo = validar_historico(arq, self.p.historico_tipos_aceitos, self.p.historico_tamanho_minimo)
                return arq, tipo
            arq, tipo = self._tentar(exportar, f"{protocolo}/historico")
            ext = arq.suffix or f".{tipo}"
            impressao = impressao_pdf(arq) if tipo == "pdf" else None   # ignora /ID e metadados de geração
            if self.p.layout == "unica":
                rel = lambda v: naming.nome_historico_unico(pasta, ext, v)  # noqa: E731
            elif self.p.layout == "por_placa":
                d = self._dir_placa
                rel = lambda v: f"{d}/{naming.nome_historico_unico(protocolo, ext, v)}"  # noqa: E731
            else:
                rel = lambda v: f"{pasta}/historico/{naming.nome_historico(ext, v)}"  # noqa: E731
            self._preservar(chave, arq, rel, exec_id, impressao)
        except SuspenderExecucao:
            st.mudar_item(chave, EstadoItem.PENDENTE, exec_id, "SUSPENSA", "execução suspensa")
            raise
        except ColisaoChave as e:
            st.mudar_item(chave, EstadoItem.FALHO, exec_id, e.codigo, e.motivo)
        except RpaError as e:
            if e.sistemica:  # ex.: destino indisponível durante a publicação
                st.mudar_item(chave, EstadoItem.PENDENTE, exec_id, e.codigo, e.motivo)
                raise SuspenderExecucao(e)
            st.mudar_item(chave, EstadoItem.PENDENTE if e.transitoria else EstadoItem.FALHO, exec_id, e.codigo, e.motivo)
            self._evidencia("itens", chave, f"{protocolo}_{e.codigo}", e)

    def _item_anexo(self, protocolo: str, anexo: AnexoRef, chave: str, pasta: str, staging: Path, exec_id: int) -> None:
        st = self.estado
        anterior = st.item(chave)
        st.registrar_item(chave, protocolo, TipoItem.ANEXO.value, id_origem=anexo.id_origem,
                          nome_original=anexo.nome_original, contexto=anexo.contexto, ordinal=anexo.ordinal,
                          tamanho=anexo.tamanho, data=anexo.data, exec_id=exec_id)
        if anterior is not None and anterior["estado"] == EstadoItem.CONFIRMADO.value:
            mudou = (anexo.tamanho is not None and anexo.tamanho != anterior["tamanho_origem"]) or \
                    (anexo.data is not None and anexo.data != anterior["data_origem"])
            if not mudou:
                return  # idempotente: já preservado e sem sinal de alteração
        st.mudar_item(chave, EstadoItem.EM_ANDAMENTO, exec_id)
        try:
            def baixar():
                arq = self.fonte.baixar_anexo(protocolo, anexo, staging)
                tipo = validar_anexo(arq, anexo.tamanho)
                return arq, tipo
            arq, tipo_arq = self._tentar(baixar, f"{protocolo}/anexo#{anexo.ordinal}")
            nome_ok = naming.corrigir_extensao(anexo.nome_original, tipo_arq)
            if nome_ok != anexo.nome_original:
                from dataclasses import replace as _replace
                anexo = _replace(anexo, nome_original=nome_ok)   # só o nome local; o original fica no inventário
            if self.p.layout == "unica":
                rel = lambda v: naming.nome_anexo_unico(pasta, anexo.rotulo, anexo.ordinal, anexo.nome_original, v)  # noqa: E731
            elif self.p.layout == "por_placa":
                d = self._dir_placa
                rel = lambda v: f"{d}/{naming.nome_anexo_unico(protocolo, anexo.rotulo, anexo.ordinal, anexo.nome_original, v)}"  # noqa: E731
            else:
                rel = lambda v: f"{pasta}/anexos/{naming.nome_anexo(anexo.nome_original, anexo.ordinal, anexo.contexto, v)}"  # noqa: E731
            self._preservar(chave, arq, rel, exec_id)
        except SuspenderExecucao:
            st.mudar_item(chave, EstadoItem.PENDENTE, exec_id, "SUSPENSA", "execução suspensa")
            raise
        except ColisaoChave as e:
            st.mudar_item(chave, EstadoItem.FALHO, exec_id, e.codigo, e.motivo)
        except RpaError as e:
            if e.sistemica:  # ex.: destino indisponível durante a publicação
                st.mudar_item(chave, EstadoItem.PENDENTE, exec_id, e.codigo, e.motivo)
                raise SuspenderExecucao(e)
            st.mudar_item(chave, EstadoItem.PENDENTE if e.transitoria else EstadoItem.FALHO, exec_id, e.codigo, e.motivo)
            self._evidencia("itens", chave, f"{protocolo}_{e.codigo}", e)

    # ------------------------------------------------------------------ modos
    def executar(self, modo: str, filtro: Filtro, limite: Optional[int] = None,
                 protocolos: Optional[Iterable[str]] = None, max_paginas: Optional[int] = None,
                 fatias: Optional[list[str]] = None) -> ResultadoExecucao:
        """modo: carga-historica | incremental | retomar | reprocessar"""
        exec_id = self.estado.iniciar_execucao(modo, filtro.descricao())
        desc: Optional[ResultadoDescoberta] = None
        processados = 0
        try:
            self.preflight()
            if modo in ("carga-historica", "incremental"):
                desc = self.descobrir(filtro, exec_id, max_paginas=max_paginas)
            fila = self._fila(modo, desc, protocolos)
            if fatias:   # vários robôs em paralelo: cada um só processa as chaves que começam com a sua fatia
                fila = [p for p in fila if any(p.startswith(f) for f in fatias)]
            if limite:
                fila = fila[:limite]
            for protocolo in fila:
                self.processar(protocolo, exec_id)
                processados += 1
                if self.ao_progresso and processados % self.progresso_cada == 0:
                    try:
                        self.ao_progresso()
                    except Exception:  # noqa: BLE001
                        log.warning("falha ao atualizar o acompanhamento", exc_info=True)
        except SuspenderExecucao as s:
            log.error("execução suspensa: %s %s", s.erro.codigo, s.erro.motivo)
            r = ResultadoExecucao(exec_id, "suspensa", processados, f"{s.erro.codigo}: {s.erro.motivo}", desc)
            self.estado.encerrar_execucao(exec_id, r.status, self._resumo(r))
            return r
        except RpaError as e:
            r = ResultadoExecucao(exec_id, "suspensa", processados, f"{e.codigo}: {e.motivo}", desc)
            self.estado.encerrar_execucao(exec_id, r.status, self._resumo(r))
            return r
        finally:
            try:
                self.fonte.encerrar()
            except Exception:  # noqa: BLE001
                pass
        pend = self.estado.processos([EstadoProcesso.PENDENTE, EstadoProcesso.TRATAMENTO,
                                      EstadoProcesso.NAO_ENCONTRADO, EstadoProcesso.DESCOBERTO])
        status = "concluida" if not pend and (desc is None or desc.cobertura_comprovada) else "concluida_com_pendencias"
        r = ResultadoExecucao(exec_id, status, processados, None, desc)
        self.estado.encerrar_execucao(exec_id, status, self._resumo(r))
        return r

    def _fila(self, modo: str, desc: Optional[ResultadoDescoberta], protocolos: Optional[Iterable[str]]) -> list[str]:
        nao_finais = [EstadoProcesso.DESCOBERTO, EstadoProcesso.EM_ANDAMENTO, EstadoProcesso.PENDENTE]
        if modo == "reprocessar":
            return list(protocolos or [])
        if modo in ("carga-historica", "retomar"):
            return [r["protocolo"] for r in self.estado.processos(nao_finais)]
        if modo == "incremental":
            # revisita tudo que está no universo: novos processos, novos anexos e mudanças de histórico (TB-08)
            universo = set(desc.protocolos if desc else [])
            return sorted(p["protocolo"] for p in self.estado.processos()
                          if p["protocolo"] in universo and p["estado"] not in
                          (EstadoProcesso.TRATAMENTO.value, EstadoProcesso.NAO_ENCONTRADO.value))
        raise ValueError(f"modo desconhecido: {modo}")

    def reconciliar(self, filtro: Filtro) -> dict:
        """Corte final (TB-09/CA-09): universo atual da origem x inventário."""
        exec_id = self.estado.iniciar_execucao("reconciliar", filtro.descricao())
        self.preflight()
        desc = self.descobrir(filtro, exec_id, registrar=False)
        universo = set(desc.protocolos)
        conhecidos = {r["protocolo"]: r["estado"] for r in self.estado.processos()}
        finais = {e.value for e in ESTADOS_PROCESSO_FINAIS}
        resultado = {
            "execucao_id": exec_id,
            "universo_origem": len(universo),
            "cobertura_comprovada": desc.cobertura_comprovada,
            "anomalias_descoberta": desc.anomalias,
            "nao_inventariados": sorted(universo - conhecidos.keys()),
            "inventariados_fora_do_universo": sorted(set(conhecidos) - universo),
            "nao_finalizados": sorted(p for p, e in conhecidos.items() if p in universo and e not in finais),
            "finalizados": sum(1 for p, e in conhecidos.items() if p in universo and e in finais),
        }
        status = "reconciliado" if (desc.cobertura_comprovada and not resultado["nao_inventariados"]
                                    and not resultado["nao_finalizados"]) else "com_diferencas"
        self.estado.encerrar_execucao(exec_id, status, resultado)
        try:
            self.fonte.encerrar()
        except Exception:  # noqa: BLE001
            pass
        resultado["status"] = status
        return resultado

    def _resumo(self, r: ResultadoExecucao) -> dict:
        d = {"status": r.status, "processados": r.processados, "motivo_suspensao": r.motivo_suspensao,
             "contagens": self.estado.contagens()}
        if r.descoberta:
            d["descoberta"] = {"unicos": len(r.descoberta.protocolos), "paginas": r.descoberta.paginas,
                               "total_exibido": r.descoberta.total_exibido, "novos": r.descoberta.novos,
                               "cobertura_comprovada": r.descoberta.cobertura_comprovada,
                               "anomalias": r.descoberta.anomalias, "nao_encontrados": r.descoberta.nao_encontrados}
        return d
