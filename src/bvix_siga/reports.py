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
        linhas.append([p["protocolo"], ident.get("numero") or p["protocolo"], ident.get("placa") or "",
                       rotulo.get(p["estado"], p["estado"]),
                       "SIM" if any(h["estado"] == "confirmado" for h in hist) else "NÃO",
                       len(anexos) if its else "", len(baixados) if its else "", len(com_erro) if its else "",
                       len(sem_arq) if its else "",
                       (len(anexos) - len(baixados) - len(sem_arq)) if its else "",
                       p["codigo_excecao"] or "", p["ultimo_erro"] or "", evid or "", p["atualizado_em"]])

    cab = ["chave", "numero_sinistro", "placa", "situacao", "historico_baixado", "anexos_no_siga", "anexos_baixados",
           "anexos_com_erro", "anexos_sem_arquivo_na_origem", "anexos_faltando", "codigo_erro", "motivo_erro",
           "print_do_erro", "atualizado_em_utc"]
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
    ritmo = previsao = ""
    ult = estado.db.execute("SELECT id, inicio FROM execucoes WHERE modo IN ('carga-historica','retomar','incremental') "
                            "ORDER BY id DESC LIMIT 1").fetchone()
    if ult:
        feitos = estado.db.execute("SELECT COUNT(DISTINCT protocolo) n FROM eventos WHERE execucao_id=? AND para IN "
                                   "('completo','completo_sem_anexos','tratamento','pendente')", (ult["id"],)).fetchone()["n"]
        ini = datetime.fromisoformat(ult["inicio"])
        seg = (datetime.now(ini.tzinfo) - ini).total_seconds()
        if feitos and seg > 0:
            por_proc = seg / feitos
            ritmo = f"{por_proc:.0f} s por sinistro ({3600 / por_proc:.0f} por hora) na execução #{ult['id']}"
            restante = (falta + pend) * por_proc
            fim = agora + timedelta(seconds=restante)
            previsao = f"~{restante / 3600:.1f} h para o restante → término estimado {fim:%d/%m %H:%M}"
    pct = (100 * concl / total) if total else 0
    md = [f"# Acompanhamento da carga — {agora:%d/%m/%Y %H:%M}", "",
          f"**Progresso: {concl:,} de {total:,} sinistros concluídos ({pct:.1f}%)**".replace(",", "."), "",
          "| Situação | Sinistros |", "|---|---|",
          f"| ✅ Concluídos | {concl} |", f"| ⚠️ Tratamento (decisão humana, ex.: arquivo sem existir no SIGA) | {trat} |",
          f"| 🔁 Pendentes (serão tentados de novo) | {pend} |", f"| ⏳ Não iniciados | {falta} |",
          f"| ❓ Não encontrados | {c['nao_encontrado']} |", "",
          f"Arquivos baixados: **{cont['arquivos']:,}** · Espaço: **{vb / 1e9:.2f} GB**".replace(",", "."),
          f"Anexos/sinistros com erro: **{len(erros)}** (detalhe e prints em erros_atual.csv)", ""]
    if ritmo:
        md += [f"Ritmo: {ritmo}", f"Previsão: {previsao}", ""]
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
                  ("Arquivos baixados", cont["arquivos"]), ("Espaço usado (GB)", round(vb / 1e9, 2)),
                  ("Erros registrados", len(erros)), ("Ritmo", ritmo or "-"), ("Previsão", previsao or "-")]
    try:
        xl = _gravar_excel(pasta, agora, resumo_tab, cab, linhas, erros, snapshot)
        saida.update(xl)
    except ImportError:
        log_rel.warning("openpyxl não instalado: Excel não gerado (pip install openpyxl)")
    except Exception:  # noqa: BLE001  relatório nunca derruba a carga
        log_rel.warning("falha ao gerar o Excel de acompanhamento", exc_info=True)
    return saida


def _gravar_excel(pasta: Path, agora, resumo_tab, cab, linhas, erros, snapshot: bool) -> dict[str, Path]:
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

    cab_ptbr = ["Chave", "Nº sinistro", "Placa", "Situação", "Histórico baixado", "Anexos no SIGA", "Anexos baixados",
                "Anexos com erro", "Sem arquivo na origem", "Anexos faltando", "Código do erro", "Motivo do erro",
                "Print do erro", "Atualizado em (UTC)"]
    w = tabela("Por sinistro", cab_ptbr, linhas, [22, 14, 12, 26, 10, 10, 10, 10, 12, 10, 18, 60, 14, 22], col_link=13)
    fills = {k: PatternFill("solid", fgColor=v) for k, v in cores.items()}
    for r in range(2, len(linhas) + 2):
        sit = str(w.cell(row=r, column=4).value or "")
        for chave_cor, f in fills.items():
            if sit.startswith(chave_cor):
                w.cell(row=r, column=4).fill = f
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
