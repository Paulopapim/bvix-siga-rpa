"""CLI. Códigos de saída (para AutomationEdge/agendador):
 0 concluída sem pendências | 10 concluída com pendências | 2 configuração | 3 autenticação/permissão/intervenção
 4 destino | 5 origem indisponível/sessão | 6 instância já ativa | 1 erro inesperado
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import replace
from pathlib import Path

from . import reports
from .config import Config, carregar
from .destination import DestinoArquivos
from .errors import ConfiguracaoInvalida, RpaError
from .orchestrator import Orquestrador, Parametros
from .state import Estado

SAIDA = {"concluida": 0, "reconciliado": 0, "concluida_com_pendencias": 10, "com_diferencas": 10}
SAIDA_ERRO = {"CONFIG": 2, "EX-01-PERMISSAO": 3, "EX-01-INTERVENCAO": 3, "EX-08": 4,
              "EX-01-SESSAO": 5, "ORIGEM-INDISPONIVEL": 5}


def _logging(cfg: Config, verbose: bool) -> None:
    cfg.logs.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    raiz = logging.getLogger("bvix_siga")
    raiz.setLevel(logging.DEBUG if verbose else logging.INFO)
    fh = logging.FileHandler(cfg.logs / "execucao.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler(sys.stderr)
    sh.setFormatter(fmt)
    raiz.handlers[:] = [fh, sh]


class Trava:
    """Uma instância ativa por ambiente (arquivo de trava ao lado do banco)."""

    def __init__(self, caminho: Path):
        self.caminho = caminho

    @staticmethod
    def _processo_vivo(pid: int) -> bool:
        if pid <= 0:
            return False
        if os.name == "nt":   # no Windows, os.kill encerraria o processo: consulta via API
            import ctypes
            k = ctypes.windll.kernel32
            h = k.OpenProcess(0x1000, False, pid)          # PROCESS_QUERY_LIMITED_INFORMATION
            if not h:
                return False
            codigo = ctypes.c_ulong()
            k.GetExitCodeProcess(h, ctypes.byref(codigo))
            k.CloseHandle(h)
            return codigo.value == 259                      # STILL_ACTIVE
        try:
            os.kill(pid, 0)
            return True
        except OSError:
            return False

    def __enter__(self):
        try:
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            try:
                pid = int(self.caminho.read_text().strip() or 0)
            except (OSError, ValueError):
                pid = 0
            if self._processo_vivo(pid):
                raise SystemExit(6)
            logging.getLogger("bvix_siga").warning("trava abandonada (pid %s encerrado); removendo", pid)
            self.caminho.unlink(missing_ok=True)
            fd = os.open(self.caminho, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return self

    def __exit__(self, *a):
        self.caminho.unlink(missing_ok=True)


def _montar(cfg: Config, simulador: bool):
    if simulador:
        from .siga.simulator import SigaSimulado, cenario_piloto
        fonte = SigaSimulado(cenario_piloto())
    else:
        from .siga.playwright_adapter import SigaPlaywright
        fonte = SigaPlaywright(cfg)
    estado = Estado(cfg.banco)
    destino = DestinoArquivos(cfg.destino_raiz)
    params = Parametros(pasta_padrao=cfg.pasta_padrao, pasta_campos_obrigatorios=cfg.pasta_campos_obrigatorios,
                        staging=cfg.staging, historico_tipos_aceitos=cfg.historico_tipos_aceitos,
                        historico_tamanho_minimo=cfg.historico_tamanho_minimo,
                        espaco_minimo_bytes=cfg.espaco_minimo_bytes, tentativas=cfg.tentativas,
                        layout=cfg.pasta_layout)
    return Orquestrador(fonte, destino, estado, params,
                        ao_progresso=lambda: reports.gerar_acompanhamento(estado, cfg.relatorios, cfg.timezone)), estado


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="bvix-siga", description="Preservação de históricos e anexos do SIGA")
    ap.add_argument("comando", choices=["preflight", "descobrir", "carga-historica", "incremental", "retomar",
                                        "reprocessar", "reconciliar", "relatorio"])
    ap.add_argument("-c", "--config", default="config/config.toml")
    ap.add_argument("--protocolos", help="lista separada por vírgula ou @arquivo.txt (piloto/reprocessar)")
    ap.add_argument("--limite", type=int, help="máximo de processos nesta execução (piloto)")
    ap.add_argument("--max-paginas", type=int, help="piloto: limita a descoberta a N páginas da listagem")
    ap.add_argument("--fatia", help="robôs em paralelo: prefixos das chaves deste robô, ex.: 2025- ou 2026-0,2026-1")
    ap.add_argument("--simulador", action="store_true", help="usa o SIGA simulado (sem acesso à origem)")
    ap.add_argument("-v", "--verbose", action="store_true")
    a = ap.parse_args(argv)

    try:
        cfg = carregar(a.config)
    except ConfiguracaoInvalida as e:
        print(f"configuração inválida: {e.motivo}", file=sys.stderr)
        return 2
    _logging(cfg, a.verbose)
    log = logging.getLogger("bvix_siga")

    protocolos: list[str] = []
    if a.protocolos:
        bruto = Path(a.protocolos[1:]).read_text(encoding="utf-8") if a.protocolos.startswith("@") else a.protocolos
        protocolos = [p.strip() for p in bruto.replace("\n", ",").split(",") if p.strip()]
    filtro = replace(cfg.filtro, protocolos=tuple(protocolos)) if protocolos else cfg.filtro
    limite = a.limite or cfg.limite_processos

    cfg.banco.parent.mkdir(parents=True, exist_ok=True)
    if a.comando == "relatorio":                      # só leitura: pode rodar com a carga em andamento
        estado = Estado(cfg.banco)
        arqs = reports.gerar_acompanhamento(estado, cfg.relatorios, cfg.timezone, snapshot=True)
        print(Path(arqs["resumo"]).read_text(encoding="utf-8"))
        print(json.dumps({k: str(v) for k, v in arqs.items()}, ensure_ascii=False, indent=2))
        if arqs.get("excel"):
            print(f"PASTA_EXCEL={Path(arqs['excel']).parent.resolve()}")
        return 0
    try:
        fatias = [f.strip() for f in (a.fatia or "").split(",") if f.strip()]
        sufixo = (".fatia-" + "_".join(fatias).replace("-", "")) if fatias else ""
        # carga sem fatia não pode rodar junto com robôs de fatia (pegariam os mesmos sinistros), e vice-versa
        for outra in cfg.banco.parent.glob(cfg.banco.stem + "*.lock"):
            if outra.name == cfg.banco.stem + sufixo + ".lock":
                continue
            eh_total = outra.name == cfg.banco.stem + ".lock"
            if (not fatias or eh_total) and a.comando in ("carga-historica", "incremental", "retomar", "reprocessar"):
                try:
                    pid = int(outra.read_text().strip() or 0)
                except (OSError, ValueError):
                    pid = 0
                if Trava._processo_vivo(pid):
                    print(f"outro robô ativo ({outra.name}); carga total e fatias não podem rodar juntas", file=sys.stderr)
                    return 6
        with Trava(cfg.banco.with_name(cfg.banco.stem + sufixo + ".lock")):
            orq, estado = _montar(cfg, a.simulador)
            if a.comando == "relatorio":
                arqs = reports.gerar(estado, cfg.relatorios, cfg.timezone)
                print(json.dumps({k: str(v) for k, v in arqs.items()}, ensure_ascii=False, indent=2))
                return 0
            if a.comando == "preflight":
                print(json.dumps(orq.preflight(), indent=2))
                return 0
            if a.comando == "descobrir":
                ex = estado.iniciar_execucao("descobrir", filtro.descricao())
                orq.preflight()
                d = orq.descobrir(filtro, ex, registrar=True, max_paginas=a.max_paginas)
                res = {"unicos": len(d.protocolos), "paginas": d.paginas, "total_exibido": d.total_exibido,
                       "cobertura_comprovada": d.cobertura_comprovada, "anomalias": d.anomalias,
                       "nao_encontrados": d.nao_encontrados, "novos": d.novos}
                estado.encerrar_execucao(ex, "concluida" if d.cobertura_comprovada else "concluida_com_pendencias", res)
                print(json.dumps(res, ensure_ascii=False, indent=2))
                return 0 if d.cobertura_comprovada else 10
            if a.comando == "reconciliar":
                r = orq.reconciliar(filtro)
                reports.gerar(estado, cfg.relatorios, cfg.timezone)
                print(json.dumps(r, ensure_ascii=False, indent=2))
                return SAIDA.get(r["status"], 10)
            if not fatias:
                estado.backup(cfg.banco.with_suffix(".bak.sqlite"))
            r = orq.executar(a.comando, filtro, limite, protocolos, a.max_paginas, fatias or None)
            reports.gerar(estado, cfg.relatorios, cfg.timezone)
            log.info("execução %s: %s (%d processados)", r.execucao_id, r.status, r.processados)
            if r.status == "suspensa":
                cod = (r.motivo_suspensao or "").split(":")[0]
                return SAIDA_ERRO.get(cod, 5)
            return SAIDA.get(r.status, 10)
    except SystemExit as e:
        if e.code == 6:
            print("outra instância está ativa (arquivo .lock)", file=sys.stderr)
        return int(e.code or 0)
    except RpaError as e:
        log.error("%s: %s", e.codigo, e.motivo)
        return SAIDA_ERRO.get(e.codigo, 1)
    except Exception:  # noqa: BLE001
        log.exception("erro inesperado")
        return 1


if __name__ == "__main__":
    sys.exit(main())
