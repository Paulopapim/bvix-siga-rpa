"""Relatórios: inventário de auditoria (CSV UTF-8), pendências, resumo operacional (JSON + Markdown)."""

from __future__ import annotations

import csv
import json
from datetime import datetime
from pathlib import Path
from datetime import timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import logging

from .models import EstadoProcesso

log_rel = logging.getLogger("bvix_siga.relatorios")
from .fatias import FATIAS_PADRAO, robo_de
from .state import Estado

CAMPOS_INVENTARIO = ["protocolo", "id_interno", "estado_processo", "pasta", "tipo", "chave_item", "id_origem",
                     "nome_original", "contexto", "ordinal", "tamanho_origem", "data_origem", "estado_item",
                     "ausente_na_origem", "versao", "caminho_relativo", "tamanho", "sha256", "confirmado_em",
                     "tentativas", "codigo_excecao", "motivo"]


def gerar(estado: Estado, pasta: Path, tz: str = "America/Sao_Paulo") -> dict[str, Path]:
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        fuso = ZoneInfo(tz)
    except ZoneInfoNotFoundError:   # Windows sem o pacote tzdata: Brasília não tem horário de verão desde 2019
        fuso = timezone(timedelta(hours=-3))
    carimbo = datetime.now(fuso).strftime("%Y%m%d_%H%M%S")
    procs = {r["protocolo"]: r for r in estado.processos()}

    inv = pasta / f"inventario_{carimbo}.csv"
    with open(inv, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=CAMPOS_INVENTARIO, delimiter=";")
        w.writeheader()
        for it in estado.itens():
            p = procs[it["protocolo"]]
            base = {"protocolo": it["protocolo"], "id_interno": p["id_interno"], "estado_processo": p["estado"],
                    "pasta": p["pasta"], "tipo": it["tipo"], "chave_item": it["chave"], "id_origem": it["id_origem"],
                    "nome_original": it["nome_original"], "contexto": it["contexto"], "ordinal": it["ordinal"],
                    "tamanho_origem": it["tamanho_origem"], "data_origem": it["data_origem"],
                    "estado_item": it["estado"], "ausente_na_origem": it["ausente_na_origem"],
                    "tentativas": it["tentativas"], "codigo_excecao": it["codigo_excecao"], "motivo": it["ultimo_erro"]}
            versoes = estado.versoes(it["chave"])
            if not versoes:
                w.writerow(base)
            for v in versoes:
                w.writerow({**base, "versao": v["versao"], "caminho_relativo": v["caminho_relativo"],
                            "tamanho": v["tamanho"], "sha256": v["sha256"], "confirmado_em": v["confirmado_em"]})
        # processos sem nenhum item (tratamento/não encontrado) também aparecem
        com_itens = {it["protocolo"] for it in estado.itens()}
        for proto, p in procs.items():
            if proto not in com_itens:
                w.writerow({"protocolo": proto, "id_interno": p["id_interno"], "estado_processo": p["estado"],
                            "pasta": p["pasta"], "codigo_excecao": p["codigo_excecao"], "motivo": p["ultimo_erro"],
                            "tentativas": p["tentativas"]})

    pend = pasta / f"pendencias_{carimbo}.csv"
    abertos = estado.processos([EstadoProcesso.PENDENTE, EstadoProcesso.TRATAMENTO, EstadoProcesso.NAO_ENCONTRADO,
                                EstadoProcesso.DESCOBERTO, EstadoProcesso.EM_ANDAMENTO])
    with open(pend, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f, delimiter=";")
        w.writerow(["protocolo", "estado", "codigo_excecao", "primeiro_erro", "ultimo_erro", "tentativas",
                    "itens_nao_confirmados", "acao_sugerida"])
        for p in abertos:
            nc = [i for i in estado.itens(p["protocolo"]) if i["estado"] != "confirmado" and not i["ausente_na_origem"]]
            acao = {"tratamento": "decisão humana (identificação, colisão ou anexo sem arquivo na origem — ver código)", "nao_encontrado": "conferir protocolo na origem",
                    "pendente": "retomar"}.get(p["estado"], "processar")
            w.writerow([p["protocolo"], p["estado"], p["codigo_excecao"], p["primeiro_erro"], p["ultimo_erro"],
                        p["tentativas"], len(nc), acao])

    execs = [dict(r) for r in estado.db.execute("SELECT * FROM execucoes ORDER BY id")]
    for e in execs:
        e["resumo"] = json.loads(e["resumo"]) if e["resumo"] else None
    resumo = {"gerado_em": carimbo, "contagens": estado.contagens(), "execucoes": execs}
    rj = pasta / f"resumo_{carimbo}.json"
    rj.write_text(json.dumps(resumo, ensure_ascii=False, indent=2), encoding="utf-8")

    c = resumo["contagens"]
    linhas = [f"# Resumo operacional — {carimbo}", "", "## Processos por estado", "",
              "| Estado | Qtde |", "|---|---|", *[f"| {k} | {v} |" for k, v in sorted(c["processos"].items())],
              "", "## Itens por estado", "", "| Estado | Qtde |", "|---|---|",
              *[f"| {k} | {v} |" for k, v in sorted(c["itens"].items())],
              "", f"Arquivos preservados (todas as versões): {c['versoes']['arquivos']} — {c['versoes']['bytes']:,} bytes",
              "", "## Execuções", "", "| # | Modo | Início | Fim | Status |", "|---|---|---|---|---|",
              *[f"| {e['id']} | {e['modo']} | {e['inicio']} | {e['fim'] or ''} | {e['status']} |" for e in execs]]
    rm = pasta / f"resumo_{carimbo}.md"
    rm.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    acomp = gerar_acompanhamento(estado, pasta, tz)
    return {"inventario": inv, "pendencias": pend, "resumo_json": rj, "resumo_md": rm, **acomp}


# ----------------------------------------------------------------------------------------------------------------
# Acompanhamento (arquivos de nome fixo, atualizados durante a carga; abrem no Excel)
# ----------------------------------------------------------------------------------------------------------------
def _gravar(caminho: Path, conteudo_writer) -> None:
    tmp = caminho.with_suffix(caminho.suffix + ".tmp")
    with open(tmp, "w", newline="", encoding="utf-8-sig") as f:
        conteudo_writer(f)
    try:
        tmp.replace(caminho)
    except PermissionError:          # arquivo aberto no Excel: grava com outro nome
        alt = caminho.with_name(caminho.stem + "_novo" + caminho.suffix)
        tmp.replace(alt)


GB = 1024 ** 3          # mesma unidade do Explorer do Windows (1,53 GB = 1.644.581.788 bytes)
FINAIS = ("completo", "completo_sem_anexos", "tratamento")


def _grupo(protocolo: str) -> str:
    return protocolo[:4] if protocolo[:4].isdigit() else "outros"


def projecao_espaco(estado: Estado) -> dict | None:
    """Projeta o espaço total ao final: média de bytes por sinistro concluído, por ano (2025 é mais pesado que 2026),
    vezes a quantidade de sinistros daquele ano no SIGA. Faixa de 90% pela variação da média (aprox. normal).
    Capacidade recomendada = 2x o limite superior, arredondado para cima em múltiplos de 50 GB."""
    import math
    rows = estado.db.execute(
        "SELECT p.protocolo, COALESCE(SUM(v.tamanho),0) b FROM processos p "
        "LEFT JOIN itens i ON i.protocolo=p.protocolo LEFT JOIN versoes v ON v.chave=i.chave "
        f"WHERE p.estado IN ({','.join('?' * len(FINAIS))}) GROUP BY p.protocolo", FINAIS).fetchall()
    if len(rows) < 20:
        return None
    universo: dict[str, int] = {}
    for r in estado.db.execute("SELECT protocolo FROM processos"):
        g = _grupo(r["protocolo"])
        universo[g] = universo.get(g, 0) + 1
    amostra: dict[str, list[int]] = {}
    for r in rows:
        amostra.setdefault(_grupo(r["protocolo"]), []).append(r["b"])
    todos = [r["b"] for r in rows]
    total = var = 0.0
    medias = []
    for g, n_univ in sorted(universo.items()):
        a = amostra.get(g) if len(amostra.get(g, [])) >= 5 else todos     # grupo sem amostra: média geral
        m = sum(a) / len(a)
        sd = math.sqrt(sum((x - m) ** 2 for x in a) / (len(a) - 1)) if len(a) > 1 else 0.0
        concluidos = len(amostra.get(g, []))
        restantes = max(n_univ - concluidos, 0)
        total += sum(amostra.get(g, [])) + restantes * m           # o que já foi baixado + projeção do resto
        var += (restantes * sd / math.sqrt(len(a))) ** 2
        if g != "outros":
            medias.append(f"{g}: {m / 1024 ** 2:.1f} MB ({concluidos} medidos)")
    z = 1.645 * math.sqrt(var)
    baixo, alto = max(total - z, 0) / GB, (total + z) / GB
    recomendado = int(math.ceil(2 * alto / 50) * 50) or 50
    return {"gb": total / GB, "baixo": baixo, "alto": alto, "recomendado": recomendado, "base": len(rows),
            "medias": " | ".join(medias),
            "texto": f"~{total / GB:.0f} GB (faixa provável {baixo:.0f} a {alto:.0f} GB; base: {len(rows)} sinistros concluídos)"}


def _local(iso: str | None, fuso) -> str:
    if not iso:
        return ""
    try:
        return datetime.fromisoformat(iso).astimezone(fuso).strftime("%d/%m/%Y %H:%M:%S")
    except ValueError:
        return iso


ROBO_CAB = ["Robô", "Faixa de sinistros", "Situação", "Total", "Concluídos", "Tratamento", "Pendentes/em andamento",
            "Não iniciados", "% concluído", "Último concluído", "Concluído às", "Ritmo (por hora)", "Término estimado"]


CONCL_CAB = ["Nº", "Chave", "Robô", "Placa", "CPF/CNPJ", "Situação", "Arquivos salvos", "Tamanho (MB)",
             "Anexos sem arquivo no SIGA", "Pasta no destino", "Concluído em (Brasília)"]


def concluidos(estado: Estado, procs, fuso) -> list[list]:
    """Todos os sinistros FINALIZADOS (concluído, sem anexos, tratamento), do mais recente para o mais antigo,
    com a pasta onde ficaram, quantidade de arquivos e tamanho."""
    arqs = {r["protocolo"]: r for r in estado.db.execute(
        "SELECT i.protocolo, COUNT(v.id) n, COALESCE(SUM(v.tamanho),0) b, MIN(v.caminho_relativo) c "
        "FROM itens i JOIN versoes v ON v.chave=i.chave GROUP BY i.protocolo")}
    sem = {r["protocolo"]: r["n"] for r in estado.db.execute(
        "SELECT protocolo, COUNT(*) n FROM itens WHERE codigo_excecao='EX-06-SEM-ARQUIVO' GROUP BY protocolo")}
    rot = {"completo": "CONCLUÍDO", "completo_sem_anexos": "CONCLUÍDO (sem anexos)", "tratamento": "TRATAMENTO"}
    fin = sorted((p for p in procs if p["estado"] in FINAIS), key=lambda p: p["atualizado_em"] or "", reverse=True)
    out = []
    for n, p in enumerate(fin, start=1):
        ident = json.loads(p["identificacao"]) if p["identificacao"] else {}
        a = arqs.get(p["protocolo"])
        pasta = str(a["c"]).replace("\\", "/").split("/")[0] if a and a["c"] else ""
        out.append([n, p["protocolo"], robo_de(p["protocolo"]), ident.get("placa") or "", ident.get("cpfcnpj") or "",
                    rot[p["estado"]], a["n"] if a else 0, round((a["b"] if a else 0) / 1024 ** 2, 1),
                    sem.get(p["protocolo"], 0), pasta, _local(p["atualizado_em"], fuso)])
    return out


def por_robo(estado: Estado, procs, agora) -> tuple[list[list], str]:
    """Uma linha por robô (fatia) + TOTAL. Ritmo = sinistros finalizados por ele na última hora.
    Previsão geral = quando o robô MAIS LENTO terminar (é ele que define o fim da carga)."""
    jan = (agora.astimezone(timezone.utc) - timedelta(minutes=60)).isoformat(timespec="seconds")
    recentes: dict[str, int] = {}
    for r in estado.db.execute("SELECT DISTINCT protocolo FROM eventos WHERE chave IS NULL AND em >= ? AND para IN "
                               "('completo','completo_sem_anexos','tratamento')", (jan,)):
        rb = robo_de(r["protocolo"])
        recentes[rb] = recentes.get(rb, 0) + 1
    ini = estado.db.execute("SELECT MIN(inicio) i FROM execucoes WHERE id IN (SELECT DISTINCT execucao_id FROM eventos "
                            "WHERE chave IS NULL AND em >= ?)", (jan,)).fetchone()["i"]
    desde = max(agora.astimezone(timezone.utc) - timedelta(minutes=60), datetime.fromisoformat(ini)) if ini else None
    horas = max((agora.astimezone(timezone.utc) - desde).total_seconds() / 3600, 1 / 60) if desde else 1.0
    dados: dict[str, dict] = {nome: {"faixa": fx, "total": 0, "concl": 0, "trat": 0, "pend": 0, "falta": 0, "ult": None}
                              for nome, fx in FATIAS_PADRAO}
    dados["-"] = {"faixa": "fora das faixas", "total": 0, "concl": 0, "trat": 0, "pend": 0, "falta": 0, "ult": None}
    for p in procs:
        d = dados[robo_de(p["protocolo"])]
        d["total"] += 1
        e = p["estado"]
        if e in ("completo", "completo_sem_anexos"):
            d["concl"] += 1
        elif e == "tratamento":
            d["trat"] += 1
        elif e in ("pendente", "em_andamento"):
            d["pend"] += 1
        elif e == "descoberto":
            d["falta"] += 1
        if e in FINAIS and (d["ult"] is None or (p["atualizado_em"] or "") > (d["ult"][1] or "")):
            d["ult"] = (p["protocolo"], p["atualizado_em"])
    linhas, fins, parados = [], [], []
    fuso = agora.tzinfo
    for nome, d in dados.items():
        if nome == "-" and not d["total"]:
            continue
        resta = d["falta"] + d["pend"]
        rh = recentes.get(nome, 0) / horas
        if not resta:
            sit, fim = "TERMINOU", "-"
        elif rh > 0:
            sit = "RODANDO"
            t = agora + timedelta(hours=resta / rh)
            fins.append((t, nome))
            fim = f"{t:%d/%m %H:%M} (~{resta / rh:.0f} h)"
        else:
            sit, fim = "PARADO", "-"
            parados.append(nome)
        pct = (d["concl"] + d["trat"]) / d["total"] if d["total"] else 0
        linhas.append([nome, d["faixa"], sit, d["total"], d["concl"], d["trat"], d["pend"], d["falta"], round(pct, 4),
                       d["ult"][0] if d["ult"] else "", _local(d["ult"][1], fuso) if d["ult"] else "",
                       round(rh), fim])
    tot = [sum(l[i] for l in linhas) for i in range(3, 8)]
    pct = (tot[1] + tot[2]) / tot[0] if tot[0] else 0
    fim_geral = max(fins)[0] if fins else None
    linhas.append(["TOTAL", "", "", *tot, round(pct, 4), "", "", round(sum(l[11] for l in linhas)),
                   f"{fim_geral:%d/%m %H:%M}" if fim_geral else "-"])
    prev = ""
    if fins:
        t, quem = max(fins)
        prev = f"~{(t - agora).total_seconds() / 3600:.1f} h → término estimado {t:%d/%m %H:%M} (robô mais lento: {quem})"
        if parados:
            prev += f"; ATENÇÃO: {', '.join(parados)} parado(s) com sinistros por fazer"
    elif parados:
        prev = f"robôs parados ({', '.join(parados)}) com sinistros por fazer"
    return linhas, prev


def _ritmo(estado: Estado, restantes: int, agora) -> tuple[str, str]:
    """Ritmo dos ÚLTIMOS 60 MIN, somando todos os robôs (conta sinistros que chegaram a uma situação final).
    Se nada terminou na última hora, os robôs estão parados: não inventa previsão."""
    jan = agora.astimezone(timezone.utc) - timedelta(minutes=60)
    lim = jan.isoformat(timespec="seconds")
    r = estado.db.execute(
        "SELECT COUNT(DISTINCT protocolo) n, MIN(em) primeiro FROM eventos WHERE chave IS NULL AND em >= ? AND para IN "
        "('completo','completo_sem_anexos','tratamento')", (lim,)).fetchone()
    if not r["n"]:
        return ("robôs parados (nenhum sinistro concluído na última hora)" if restantes else "", "")
    ini = estado.db.execute("SELECT MIN(e.inicio) i FROM execucoes e WHERE e.id IN (SELECT DISTINCT execucao_id FROM "
                            "eventos WHERE chave IS NULL AND em >= ?)", (lim,)).fetchone()["i"]
    desde = max(jan, datetime.fromisoformat(ini)) if ini else jan
    horas = max((agora.astimezone(timezone.utc) - desde).total_seconds() / 3600, 1 / 60)
    por_hora = r["n"] / horas
    if not restantes:
        return f"{por_hora:.0f} sinistros por hora (última hora, todos os robôs)", "carga concluída"
    h = restantes / por_hora
    fim = agora + timedelta(hours=h)
    return (f"{por_hora:.0f} sinistros por hora (última hora, todos os robôs)",
            f"~{h:.1f} h para o restante → término estimado {fim:%d/%m %H:%M}")


def gerar_acompanhamento(estado: Estado, pasta: Path, tz: str = "America/Sao_Paulo",
                         snapshot: bool = False) -> dict[str, Path]:
    """snapshot=True (comando relatorio): além do 'ultimo', grava uma cópia com data e hora no nome."""
    pasta.mkdir(parents=True, exist_ok=True)
    try:
        fuso = ZoneInfo(tz)
    except ZoneInfoNotFoundError:
        fuso = timezone(timedelta(hours=-3))
    agora = datetime.now(fuso)
    procs = estado.processos()
    itens_por = {}
    for it in estado.itens():
        itens_por.setdefault(it["protocolo"], []).append(it)
    rotulo = {"completo": "CONCLUÍDO", "completo_sem_anexos": "CONCLUÍDO (sem anexos)", "tratamento": "TRATAMENTO",
              "pendente": "PENDENTE (será tentado de novo)", "em_andamento": "EM ANDAMENTO",
              "descoberto": "NÃO INICIADO", "nao_encontrado": "NÃO ENCONTRADO"}
    linhas, erros = [], []
    cont = {"arquivos": 0}
    for p in procs:
        ident = json.loads(p["identificacao"]) if p["identificacao"] else {}
        its = itens_por.get(p["protocolo"], [])
        anexos = [i for i in its if i["tipo"] == "anexo" and not i["ausente_na_origem"]]
        hist = [i for i in its if i["tipo"] == "historico"]
        baixados = [i for i in anexos if i["estado"] == "confirmado"]
        sem_arq = [i for i in anexos if i["codigo_excecao"] == "EX-06-SEM-ARQUIVO"]
        com_erro = [i for i in anexos if i["estado"] in ("falho", "pendente") and i not in sem_arq]
        evid = p["evidencia"] if "evidencia" in p.keys() else None
        for i in its:
            if i["estado"] in ("falho", "pendente") or i["codigo_excecao"]:
                if i["estado"] != "confirmado":
                    erros.append([p["protocolo"], ident.get("placa") or "", i["tipo"], i["nome_original"] or "",
                                  i["id_origem"] or "", i["codigo_excecao"] or "", i["ultimo_erro"] or "",
                                  i["tentativas"], (i["evidencia"] if "evidencia" in i.keys() else "") or ""])
                    evid = evid or (i["evidencia"] if "evidencia" in i.keys() else None)
        if p["estado"] in ("pendente", "tratamento", "nao_encontrado") and not its:
            erros.append([p["protocolo"], ident.get("placa") or "", "processo", "", "", p["codigo_excecao"] or "",
                          p["ultimo_erro"] or "", p["tentativas"], evid or ""])
        cont["arquivos"] += len(baixados) + sum(1 for h in hist if h["estado"] == "confirmado")
        linhas.append([p["protocolo"], robo_de(p["protocolo"]), ident.get("numero") or p["protocolo"], ident.get("placa") or "",
                       rotulo.get(p["estado"], p["estado"]),
                       "SIM" if any(h["estado"] == "confirmado" for h in hist) else "NÃO",
                       len(anexos) if its else "", len(baixados) if its else "", len(com_erro) if its else "",
                       len(sem_arq) if its else "",
                       (len(anexos) - len(baixados) - len(sem_arq)) if its else "",
                       p["codigo_excecao"] or "", p["ultimo_erro"] or "", evid or "", _local(p["atualizado_em"], fuso)])

    cab = ["chave", "robo", "numero_sinistro", "placa", "situacao", "historico_baixado", "anexos_no_siga", "anexos_baixados",
           "anexos_com_erro", "anexos_sem_arquivo_na_origem", "anexos_faltando", "codigo_erro", "motivo_erro",
           "print_do_erro", "atualizado_em"]
    ac = pasta / "acompanhamento_atual.csv"
    _gravar(ac, lambda f: (csv.writer(f, delimiter=";").writerow(cab), csv.writer(f, delimiter=";").writerows(linhas)))
    er = pasta / "erros_atual.csv"
    _gravar(er, lambda f: (csv.writer(f, delimiter=";").writerow(
        ["chave", "placa", "tipo", "arquivo", "id_anexo_siga", "codigo_erro", "motivo", "tentativas", "print_do_erro"]),
        csv.writer(f, delimiter=";").writerows(erros)))

    # resumo com progresso e previsão
    from collections import Counter
    c = Counter(p["estado"] for p in procs)
    total = len(procs)
    concl = c["completo"] + c["completo_sem_anexos"]
    trat, pend = c["tratamento"], c["pendente"] + c["em_andamento"]
    falta = c["descoberto"]
    vb = estado.db.execute("SELECT COALESCE(SUM(tamanho),0) b FROM versoes").fetchone()["b"]
    ritmo, previsao = _ritmo(estado, falta + pend, agora)
    robos, prev_robos = por_robo(estado, procs, agora)
    if prev_robos:
        previsao = prev_robos
    proj = projecao_espaco(estado)
    pct = (100 * concl / total) if total else 0
    md = [f"# Acompanhamento da carga — {agora:%d/%m/%Y %H:%M}", "",
          f"**Progresso: {concl:,} de {total:,} sinistros concluídos ({pct:.1f}%)**".replace(",", "."), "",
          "| Situação | Sinistros |", "|---|---|",
          f"| ✅ Concluídos | {concl} |", f"| ⚠️ Tratamento (decisão humana, ex.: arquivo sem existir no SIGA) | {trat} |",
          f"| 🔁 Pendentes (serão tentados de novo) | {pend} |", f"| ⏳ Não iniciados | {falta} |",
          f"| ❓ Não encontrados | {c['nao_encontrado']} |", "",
          f"Arquivos baixados: **{cont['arquivos']:,}** · Espaço: **{vb / GB:.2f} GB**".replace(",", "."),
          f"Anexos/sinistros com erro: **{len(erros)}** (detalhe e prints em erros_atual.csv)", ""]
    if ritmo:
        md += [f"Ritmo: {ritmo}", f"Previsão: {previsao}", ""]
    if proj:
        md += [f"Espaço projetado ao final: **{proj['texto']}**",
               f"Capacidade recomendada para o servidor: **{proj['recomendado']} GB**", ""]
    md += ["Arquivos: `acompanhamento_atual.csv` (1 linha por sinistro) · `erros_atual.csv` (1 linha por erro, com print)"]
    rm = pasta / "resumo_atual.md"
    tmp = rm.with_suffix(".tmp")
    tmp.write_text("\n".join(md) + "\n", encoding="utf-8")
    tmp.replace(rm)
    saida = {"acompanhamento": ac, "erros": er, "resumo": rm}
    resumo_tab = [("Gerado em", f"{agora:%d/%m/%Y %H:%M}"), ("Sinistros no SIGA (universo)", total),
                  ("Concluídos", concl), ("Tratamento (decisão humana)", trat),
                  ("Pendentes (serão tentados de novo)", pend), ("Não iniciados", falta),
                  ("Não encontrados", c["nao_encontrado"]), ("% concluído", round(pct / 100, 4)),
                  ("Arquivos baixados", cont["arquivos"]), ("Espaço usado (GB)", round(vb / GB, 2)),
                  ("Erros registrados", len(erros)), ("Ritmo", ritmo or "-"), ("Previsão", previsao or "-"),
                  ("Espaço projetado ao final (GB)", proj["texto"] if proj else "-"),
                  ("Média por sinistro", proj["medias"] if proj else "-"),
                  ("Capacidade recomendada (GB)", proj["recomendado"] if proj else "-"),
                  ("Onde ver", "aba Por robô = cada robô | aba Concluídos = todos os finalizados | "
                               "aba Por sinistro = todos os 13 mil | aba Erros = falhas com print")]
    try:
        xl = _gravar_excel(pasta, agora, resumo_tab, cab, linhas, erros, snapshot, robos,
                           concluidos(estado, procs, fuso))
        saida.update(xl)
    except ImportError:
        log_rel.warning("openpyxl não instalado: Excel não gerado (pip install openpyxl)")
    except Exception:  # noqa: BLE001  relatório nunca derruba a carga
        log_rel.warning("falha ao gerar o Excel de acompanhamento", exc_info=True)
    return saida


def _gravar_excel(pasta: Path, agora, resumo_tab, cab, linhas, erros, snapshot: bool,
                  robos: list[list] | None = None, concl: list[list] | None = None) -> dict[str, Path]:
    """Excel com 3 abas (Resumo, Por sinistro, Erros) em relatorios/AAAA-MM-DD/."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    dia = pasta / f"{agora:%Y-%m-%d}"
    dia.mkdir(parents=True, exist_ok=True)
    wb = Workbook()
    neg = Font(bold=True, color="FFFFFF")
    cab_fill = PatternFill("solid", fgColor="1F4E78")
    cores = {"CONCLUÍDO": "E2EFDA", "TRATAMENTO": "FCE4D6", "PENDENTE": "FFF2CC", "NÃO ENCONTRADO": "F8CBAD"}

    ws = wb.active
    ws.title = "Resumo"
    ws.append(["Acompanhamento da carga SIGA – Bvix", ""])
    ws["A1"].font = Font(bold=True, size=14)
    ws.append([])
    for k, v in resumo_tab:
        ws.append([k, v])
    for row in ws.iter_rows(min_row=3, max_col=1):
        row[0].font = Font(bold=True)
    for row in ws.iter_rows(min_row=3, min_col=2, max_col=2):
        if ws.cell(row=row[0].row, column=1).value == "% concluído":
            row[0].number_format = "0.0%"
        elif isinstance(row[0].value, int):
            row[0].number_format = "#,##0"
    ws.column_dimensions["A"].width = 38
    ws.column_dimensions["B"].width = 70

    def tabela(nome, cabecalho, dados, larguras, col_link=None):
        w = wb.create_sheet(nome)
        w.append(cabecalho)
        for cel in w[1]:
            cel.font, cel.fill = neg, cab_fill
            cel.alignment = Alignment(wrap_text=True, vertical="center")
        for d in dados:
            w.append(["" if x is None else x for x in d])
        for i, lg in enumerate(larguras, start=1):
            w.column_dimensions[get_column_letter(i)].width = lg
        w.freeze_panes = "A2"
        if dados:
            w.auto_filter.ref = f"A1:{get_column_letter(len(cabecalho))}{len(dados) + 1}"
        if col_link:
            for r in range(2, len(dados) + 2):
                cel = w.cell(row=r, column=col_link)
                if cel.value:
                    cel.hyperlink = str(cel.value)
                    cel.value = "abrir print"
                    cel.font = Font(color="0563C1", underline="single")
        return w

    if robos:
        wr = tabela("Por robô", ROBO_CAB, robos, [8, 42, 12, 9, 11, 11, 13, 12, 11, 16, 20, 12, 22])
        wr.auto_filter.ref = None
        cor_sit = {"RODANDO": "E2EFDA", "TERMINOU": "DDEBF7", "PARADO": "F8CBAD"}
        for r in range(2, len(robos) + 2):
            wr.cell(row=r, column=9).number_format = "0.0%"
            for c in (4, 5, 6, 7, 8):
                wr.cell(row=r, column=c).number_format = "#,##0"
            sit = wr.cell(row=r, column=3).value
            if sit in cor_sit:
                wr.cell(row=r, column=3).fill = PatternFill("solid", fgColor=cor_sit[sit])
        for c in range(1, len(ROBO_CAB) + 1):
            wr.cell(row=len(robos) + 1, column=c).font = Font(bold=True)
        wr.append([])
        wr.append(["Ritmo = sinistros finalizados por hora na última hora. O fim da carga é o término do robô mais lento."])

    if concl is not None:
        wc = tabela("Concluídos", CONCL_CAB, concl, [7, 22, 7, 11, 20, 22, 10, 11, 12, 42, 20])
        fills_c = {"CONCLUÍDO": PatternFill("solid", fgColor="E2EFDA"), "TRATAMENTO": PatternFill("solid", fgColor="FCE4D6")}
        for r in range(2, len(concl) + 2):
            v = str(wc.cell(row=r, column=6).value or "")
            for k, f in fills_c.items():
                if v.startswith(k):
                    wc.cell(row=r, column=6).fill = f
        if not concl:
            wc.append(["", "Nenhum sinistro concluído ainda."])

    cab_ptbr = ["Chave", "Robô", "Nº sinistro", "Placa", "Situação", "Histórico baixado", "Anexos no SIGA", "Anexos baixados",
                "Anexos com erro", "Sem arquivo na origem", "Anexos faltando", "Código do erro", "Motivo do erro",
                "Print do erro", "Atualizado em (Brasília)"]
    w = tabela("Por sinistro", cab_ptbr, linhas, [22, 7, 14, 12, 26, 10, 10, 10, 10, 12, 10, 18, 60, 14, 20], col_link=14)
    fills = {k: PatternFill("solid", fgColor=v) for k, v in cores.items()}
    for r in range(2, len(linhas) + 2):
        sit = str(w.cell(row=r, column=5).value or "")
        for chave_cor, f in fills.items():
            if sit.startswith(chave_cor):
                w.cell(row=r, column=5).fill = f
                break
    tabela("Erros", ["Chave", "Placa", "Tipo", "Arquivo", "ID anexo SIGA", "Código", "Motivo", "Tentativas", "Print"],
           erros, [22, 12, 10, 40, 14, 20, 70, 10, 14], col_link=9)

    ultimo = dia / f"acompanhamento_{agora:%Y-%m-%d}_ultimo.xlsx"
    tmp = ultimo.with_suffix(".tmp.xlsx")
    wb.save(tmp)
    res = {}
    try:
        tmp.replace(ultimo)
        res["excel"] = ultimo
    except PermissionError:                         # aberto no Excel: salva ao lado
        alt = dia / f"acompanhamento_{agora:%Y-%m-%d_%Hh%M}.xlsx"
        tmp.replace(alt)
        res["excel"] = alt
    if snapshot:
        foto = dia / f"acompanhamento_{agora:%Y-%m-%d_%Hh%M}.xlsx"
        if not foto.exists():
            wb.save(foto)
        res["excel_snapshot"] = foto
    return res
