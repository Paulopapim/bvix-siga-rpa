"""Execução pelo Orquestrador EMK (agente instalado no servidor).

Cadastro da automação no portal (Automações > + Nova automação):
  Comando ............ .venv\\Scripts\\python.exe -u -m bvix_siga.emk
  Diretório de trabalho  pasta do projeto (onde está o pyproject.toml)
  Timeout (s) ........ 259200 (72 h) para a carga completa
  Logs em tempo real . marcado
  Credenciais do cofre  credencial com variável SIGA  (o agente entrega SIGA = senha e SIGA_USER = usuário)

Variáveis personalizadas (todas opcionais; chegam em EMK_VARS como JSON):
  comando        str   retomar (padrão) | carga-historica | descobrir | relatorio | preflight | reconciliar
  fatias         str   robôs em paralelo, separados por ';'. Ex.: "2025-,2026-1,SEMNUMERO-;2026-00,2026-01;2026-05"
                       vazio = um robô só, com todos os sinistros
  limite         int   máximo de sinistros nesta execução (teste)
  max_paginas    int   limita a descoberta a N páginas (teste)
  config         str   arquivo de configuração (padrão config/config.piloto.toml)
  visivel        bool  mostra o navegador (padrão: o do arquivo de configuração)
  pendencias_ok  bool  true (padrão): terminar com pendências (ex.: anexo ausente na origem) = "Concluído"
  intervalo_min  int   minutos entre as linhas de PROGRESSO no log (padrão 10)
  simulador      bool  true = teste com o SIGA SIMULADO (não acessa o SIGA; bom para testar o agente)

Situação no portal: código de saída 0 = Concluído; qualquer outro = Falhou (ver o log da execução).
 2 configuração | 3 login/permissão | 4 destino | 5 SIGA fora/sessão | 6 outro robô ativo | 10 pendências | 1 inesperado
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[2]
COMANDOS = {"retomar", "carga-historica", "incremental", "descobrir", "relatorio", "preflight", "reconciliar"}
# gravidade para combinar os resultados de vários robôs (maior = pior)
GRAVIDADE = {0: 0, 10: 1, 6: 2, 5: 3, 4: 4, 3: 5, 2: 6, 1: 7}


def _bool(v, padrao: bool) -> bool:
    if v is None or v == "":
        return padrao
    if isinstance(v, bool):
        return v
    return str(v).strip().lower() in {"1", "true", "sim", "s", "yes", "on"}


def ler_vars(env: dict | None = None) -> dict:
    env = os.environ if env is None else env
    bruto = env.get("EMK_VARS", "").strip()
    if not bruto:
        return {}
    try:
        v = json.loads(bruto)
    except json.JSONDecodeError as e:
        raise ValueError(f"EMK_VARS não é JSON válido: {e}") from e
    return v if isinstance(v, dict) else {}


def parametros(v: dict) -> dict:
    comando = str(v.get("comando") or "retomar").strip()
    if comando not in COMANDOS:
        raise ValueError(f"comando inválido em EMK_VARS: {comando!r} (use {', '.join(sorted(COMANDOS))})")
    fatias_txt = str(v.get("fatias") or "").strip()
    robos = [r.strip().strip(",") for r in fatias_txt.split(";") if r.strip().strip(",")]
    if robos and comando not in {"retomar", "carga-historica", "incremental"}:
        raise ValueError(f"'fatias' só vale para retomar/carga-historica/incremental, não para {comando}")
    todos = [f.strip() for r in robos for f in r.split(",") if f.strip()]
    for i, f in enumerate(todos):          # fatias não podem se sobrepor (dois robôs no mesmo sinistro)
        for g in todos[i + 1:]:
            if f.startswith(g) or g.startswith(f):
                raise ValueError(f"fatias sobrepostas: {f!r} e {g!r}")
    def _int(nome):
        x = v.get(nome)
        return int(x) if x not in (None, "") else None
    return {"comando": comando, "robos": robos, "limite": _int("limite"), "max_paginas": _int("max_paginas"),
            "config": str(v.get("config") or "config/config.piloto.toml"),
            "visivel": v.get("visivel"), "pendencias_ok": _bool(v.get("pendencias_ok"), True),
            "intervalo_min": _int("intervalo_min") or 10, "simulador": _bool(v.get("simulador"), False)}


def credenciais_do_cofre(env: dict) -> dict:
    """Cofre do EMK entrega <NOME> (senha) e <NOME>_USER (usuário). Aceita SIGA ou SIGA_PASSWORD.
    Sem cofre, os arquivos config/usuario.txt e config/senha_provisoria.txt (1ª linha) são o plano B."""
    novo = {}
    if not env.get("SIGA_PASSWORD"):
        if env.get("SIGA"):
            novo["SIGA_PASSWORD"] = env["SIGA"]
    if not env.get("SIGA_USERNAME"):
        u = env.get("SIGA_USER") or env.get("SIGA_PASSWORD_USER")
        if u:
            novo["SIGA_USERNAME"] = u
    for var, arq in (("SIGA_USERNAME", "usuario.txt"), ("SIGA_PASSWORD", "senha_provisoria.txt")):
        if not env.get(var) and var not in novo:
            f = RAIZ / "config" / arq
            if f.exists():
                linha = next((x.strip() for x in f.read_text(encoding="utf-8-sig").splitlines() if x.strip()), "")
                if linha:
                    novo[var] = linha
    return novo


def combinar(codigos: list[int]) -> int:
    return max(codigos, key=lambda c: GRAVIDADE.get(c, 7)) if codigos else 1


def _progresso(cfg_path: Path) -> str:
    try:
        from .config import carregar
        from .state import Estado
        cfg = carregar(cfg_path)
        if not cfg.banco.exists():
            return "PROGRESSO: banco ainda não criado"
        c = Estado(cfg.banco).contagens()
        p, i = c["processos"], c["itens"]
        total = sum(p.values())
        feitos = p.get("completo", 0) + p.get("completo_sem_anexos", 0)
        return (f"PROGRESSO: sinistros {feitos}/{total} concluídos"
                f" | pendentes {p.get('pendente', 0)} | tratamento {p.get('tratamento', 0)}"
                f" | arquivos salvos {i.get('confirmado', 0)} | falhas {i.get('falho', 0) + i.get('pendente', 0)}"
                f" | {c['versoes']['bytes'] / 1024 ** 3:.1f} GB")
    except Exception as e:  # noqa: BLE001 - progresso nunca derruba a execução
        return f"PROGRESSO: indisponível ({type(e).__name__})"


def _repassar(proc: subprocess.Popen, prefixo: str) -> None:
    for linha in iter(proc.stdout.readline, ""):
        print(f"{prefixo}{linha.rstrip()}", flush=True)


def main(env: dict | None = None) -> int:
    env = dict(os.environ if env is None else env)
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
        sys.stderr.reconfigure(encoding="utf-8", errors="replace", line_buffering=True)
    except (AttributeError, ValueError):
        pass
    try:
        p = parametros(ler_vars(env))
    except ValueError as e:
        print(f"ERRO DE PARÂMETRO: {e}", flush=True)
        return 2
    env.update(credenciais_do_cofre(env))
    if p["simulador"]:                         # teste: nunca mistura com o banco/arquivos da carga real
        env["SIGA_USERNAME"], env["SIGA_PASSWORD"] = "simulador", "simulador"
        sim = RAIZ / "saida_simulador"
        env["SIGA_PASTA_SAIDA"], env["SIGA_PASTA_DESTINO"] = str(sim), str(sim / "destino")
    if not env.get("SIGA_USERNAME") or not env.get("SIGA_PASSWORD"):
        print("ERRO: credenciais do SIGA ausentes. Marque a credencial SIGA do Cofre na automação "
              "(ou crie config\\usuario.txt e config\\senha_provisoria.txt no servidor).", flush=True)
        return 2
    if p["visivel"] is not None:
        env["SIGA_MODO_VISIVEL"] = "1" if _bool(p["visivel"], True) else "0"
    env.update({"PYTHONUNBUFFERED": "1", "PYTHONIOENCODING": "utf-8", "BVIX_PAI_PID": str(os.getpid())})

    for k in ("SIGA_PASTA_SAIDA", "SIGA_PASTA_DESTINO", "SIGA_MODO_VISIVEL"):   # progresso lê as mesmas pastas
        if env.get(k):
            os.environ[k] = env[k]
    cfg = Path(p["config"])
    cfg = cfg if cfg.is_absolute() else RAIZ / cfg
    base = [sys.executable, "-u", "-m", "bvix_siga.cli", p["comando"], "-c", str(cfg)]
    if p["limite"]:
        base += ["--limite", str(p["limite"])]
    if p["max_paginas"]:
        base += ["--max-paginas", str(p["max_paginas"])]
    if p["simulador"]:
        base += ["--simulador"]
    execucoes = [(f"[R{n}] ", base + ["--fatia", f]) for n, f in enumerate(p["robos"], 1)] or [("", base)]

    print(f"ROBÔ SIGA BVIX via Orquestrador EMK | comando={p['comando']} | robôs={len(execucoes)} "
          f"| usuário SIGA={env['SIGA_USERNAME']} | config={cfg.name}"
          + (" | SIMULADOR (não acessa o SIGA)" if p["simulador"] else ""), flush=True)
    for pref, cmd in execucoes:
        if pref:
            print(f"{pref}fatia {cmd[-1]}", flush=True)

    procs: list[subprocess.Popen] = []
    fim = threading.Event()

    def encerrar(*_a):                       # cancelamento pelo portal: fecha os robôs filhos também
        fim.set()
        for pr in procs:
            if pr.poll() is None:
                pr.terminate()
    for s in ("SIGTERM", "SIGINT", "SIGBREAK"):
        if hasattr(signal, s):
            try:
                signal.signal(getattr(signal, s), encerrar)
            except (ValueError, OSError):
                pass

    leitores = []
    try:
        for n, (pref, cmd) in enumerate(execucoes):
            if n and not fim.wait(30):        # 30 s entre robôs: logins não simultâneos
                pass
            if fim.is_set():
                break
            pr = subprocess.Popen(cmd, cwd=str(RAIZ), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding="utf-8", errors="replace", bufsize=1)
            procs.append(pr)
            t = threading.Thread(target=_repassar, args=(pr, pref), daemon=True)
            t.start()
            leitores.append(t)
        longo = p["comando"] in {"retomar", "carga-historica", "incremental"}
        proximo = time.monotonic() + 60
        while any(pr.poll() is None for pr in procs):
            time.sleep(2)
            if longo and time.monotonic() >= proximo:
                print(_progresso(cfg), flush=True)
                proximo = time.monotonic() + p["intervalo_min"] * 60
    finally:
        for pr in procs:                      # saída anormal deste processo: não deixa robô órfão
            if pr.poll() is None:
                pr.terminate()
                try:
                    pr.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    pr.kill()
        for t in leitores:
            t.join(timeout=10)

    codigos = [pr.returncode if pr.returncode is not None else 1 for pr in procs]
    for (pref, _c), cod in zip(execucoes, codigos):
        print(f"{pref}terminou com código {cod}", flush=True)
    final = combinar(codigos)
    if p["comando"] in {"retomar", "carga-historica", "incremental"}:
        print(_progresso(cfg), flush=True)
    if fim.is_set():
        print("EXECUÇÃO CANCELADA", flush=True)
        return final or 1
    if final == 10 and p["pendencias_ok"]:
        print("CONCLUÍDO COM PENDÊNCIAS (ex.: anexos ausentes na origem). Ver relatorios\\...\\acompanhamento.", flush=True)
        return 0
    print("CONCLUÍDO" if final == 0 else f"FALHOU: código {final}", flush=True)
    return final


if __name__ == "__main__":
    sys.exit(main())
