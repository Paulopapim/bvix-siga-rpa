"""Quedas entre download, gravação e confirmação; nomes; destino."""

from __future__ import annotations

import pytest

from bvix_siga import naming
from bvix_siga.destination import DestinoArquivos, sha256_arquivo
from bvix_siga.errors import ColisaoChave, IdentificacaoInvalida
from bvix_siga.models import Filtro


def test_queda_apos_promover_antes_de_confirmar_reconcilia(criar_ambiente, monkeypatch):
    amb = criar_ambiente()
    original = amb.estado.confirmar_versao
    estourou = {"v": False}

    def confirmar(*a, **k):
        if not estourou["v"]:
            estourou["v"] = True
            raise KeyboardInterrupt("queda simulada após gravação, antes do commit")
        return original(*a, **k)

    monkeypatch.setattr(amb.estado, "confirmar_versao", confirmar)
    with pytest.raises(KeyboardInterrupt):
        amb.orq.executar("carga-historica", Filtro())
    monkeypatch.setattr(amb.estado, "confirmar_versao", original)
    arquivos_antes = amb.arquivos()
    assert len(arquivos_antes) == 1      # arquivo gravado e não confirmado
    r = amb.orq.executar("retomar", Filtro())
    assert r.status == "concluida"
    # o arquivo órfão foi reaproveitado por hash, sem duplicar
    assert amb.estado.contagens()["versoes"]["arquivos"] == len(amb.arquivos())


def test_queda_com_historico_regenerado_diferente_vira_versao(criar_ambiente, monkeypatch):
    amb = criar_ambiente(carimbo_impressao=True)
    original = amb.estado.confirmar_versao
    estourou = {"v": False}

    def confirmar(*a, **k):
        if not estourou["v"]:
            estourou["v"] = True
            raise KeyboardInterrupt()
        return original(*a, **k)

    monkeypatch.setattr(amb.estado, "confirmar_versao", confirmar)
    with pytest.raises(KeyboardInterrupt):
        amb.orq.executar("carga-historica", Filtro())
    monkeypatch.setattr(amb.estado, "confirmar_versao", original)
    amb.orq.executar("retomar", Filtro())
    hist = [p for p in amb.arquivos() if p.name.startswith("historico")]
    primeiro = sorted(p for p in hist if "2026-00001" in str(p))
    assert [p.name for p in primeiro] == ["historico__v1.pdf", "historico__v2.pdf"]  # órfão preservado como v1


def test_destino_nao_sobrescreve(tmp_path):
    d = DestinoArquivos(tmp_path / "dest")
    a, b = tmp_path / "a.bin", tmp_path / "b.bin"
    a.write_bytes(b"aaa")
    b.write_bytes(b"bbb")
    p1 = d.publicar(a, "x/arq.bin", sha256_arquivo(a))
    p2 = d.publicar(a, "x/arq.bin", sha256_arquivo(a))
    assert not p1.reaproveitado and p2.reaproveitado
    with pytest.raises(ColisaoChave):
        d.publicar(b, "x/arq.bin", sha256_arquivo(b))
    assert (tmp_path / "dest/x/arq.bin").read_bytes() == b"aaa"
    assert not list((tmp_path / "dest/x").glob(".*tmp"))


def test_destino_rejeita_caminho_fora_da_raiz(tmp_path):
    d = DestinoArquivos(tmp_path / "dest")
    a = tmp_path / "a.bin"
    a.write_bytes(b"a")
    with pytest.raises(ColisaoChave):
        d.publicar(a, "../fora.bin", sha256_arquivo(a))


def test_nomes_seguros_e_deterministicos():
    n = naming.nome_anexo('Laudo: "final"/v2?.PDF', 3, "processo")
    assert n == naming.nome_anexo('Laudo: "final"/v2?.PDF', 3, "processo")
    assert n.endswith(".PDF") and not any(c in n for c in '<>:"/\\|?*')
    longo = naming.nome_anexo("a" * 400 + ".pdf", 1, "processo")
    assert len(longo) <= naming.MAX_COMPONENTE and longo.endswith(".pdf")
    assert naming.limpar_componente("CON") == "_CON"
    assert naming.nome_anexo("x.pdf", 1, "processo", versao=2).endswith("__v2.pdf")


def test_pasta_preserva_zeros_e_exige_campos():
    p = naming.pasta_processo("{placa}_{cpfcnpj}", {"placa": "ABC0123", "cpfcnpj": "012.345.678-90"}, ["placa"])
    assert p == "ABC0123_012.345.678-90"
    with pytest.raises(IdentificacaoInvalida):
        naming.pasta_processo("{placa}_{evento}", {"placa": "ABC0123", "evento": None}, ["evento"])
    with pytest.raises(IdentificacaoInvalida):
        naming.pasta_processo("{placa}_{inexistente}", {"placa": "A"}, [])


def test_cli_simulador_ponta_a_ponta(tmp_path):
    from bvix_siga.cli import main
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        '[origem]\nurl="https://star.arcoconsultoria.com/open.do?sys=SIG"\n'
        '[destino]\ntipo="arquivos"\nraiz="./destino"\nespaco_minimo_gb=0\n'
        '[execucao]\nstaging="./staging"\nbanco="./estado.sqlite"\nlogs="./logs"\nrelatorios="./rel"\n'
        '[pasta]\npadrao="{placa}__{protocolo}"\ncampos_obrigatorios=["placa","protocolo"]\n', encoding="utf-8")
    assert main(["carga-historica", "-c", str(cfg), "--simulador"]) == 0
    assert list((tmp_path / "rel").glob("inventario_*.csv"))
    assert main(["relatorio", "-c", str(cfg), "--simulador"]) == 0
    assert main(["preflight", "-c", str(tmp_path / "nao_existe.toml")]) == 2


def _pdf_com_id(conteudo: bytes, id_geracao: str) -> bytes:
    import zlib
    corpo = zlib.compress(conteudo)
    return (b"%PDF-1.4\n1 0 obj << /Length " + str(len(corpo)).encode() + b" /Filter /FlateDecode >>\nstream\n" + corpo +
            b"\nendstream\nendobj\ntrailer << /ID [<" + id_geracao.encode() + b">] >>\n" + b"x" * 300 + b"\n%%EOF\n")


def test_historico_regerado_com_id_diferente_nao_cria_versao(criar_ambiente, monkeypatch):
    """Evidência 26/11: o SIGA gera o mesmo histórico com /ID diferente a cada impressão."""
    amb = criar_ambiente()
    cont = {"n": 0}

    def exportar(protocolo, pasta):
        cont["n"] += 1
        p = pasta / f"historico_{protocolo}.pdf"
        p.write_bytes(_pdf_com_id(f"BT (Historico {protocolo}) Tj ET".encode(), f"GUID{cont['n']:04d}"))
        return p

    monkeypatch.setattr(amb.sim, "exportar_historico", exportar)
    amb.orq.executar("carga-historica", Filtro())
    amb.orq.executar("incremental", Filtro())
    hist = [p.name for p in amb.arquivos() if p.name.startswith("historico") and "2026-00001" in str(p)]
    assert hist == ["historico__v1.pdf"]


def test_extensao_colada_no_nome_e_corrigida():
    """Evidência 26/11: arquivos 'CNH SEG__jpg' / 'CRLV SEG COMPLETO__pdf' no SIGA."""
    assert naming.corrigir_extensao("CNH SEG__jpg", "jpg") == "CNH SEG.jpg"
    assert naming.corrigir_extensao("CRLV SEG COMPLETO__pdf", "pdf") == "CRLV SEG COMPLETO.pdf"
    assert naming.corrigir_extensao("sem extensao", "png") == "sem extensao.png"
    assert naming.corrigir_extensao("foto.jpeg", "jpg") == "foto.jpeg"


def test_dois_robos_em_paralelo_por_fatia_sem_duplicar(tmp_path):
    import threading
    from bvix_siga.config import PoliticaTentativas
    from bvix_siga.destination import DestinoArquivos
    from bvix_siga.orchestrator import Orquestrador, Parametros
    from bvix_siga.siga.simulator import SigaSimulado, ProcessoSim, AnexoSim, pdf
    from bvix_siga.state import Estado
    procs = [ProcessoSim(f"{a}-{i:05d}", f"{a}{i}", f"P{a[-1]}{i:04d}", "COLISÃO", "1",
                         anexos=[AnexoSim(f"f{k}.pdf", pdf(f"{a}{i}{k}")) for k in range(3)])
             for a in ("2025", "2026") for i in range(1, 16)]
    banco = tmp_path / "estado.sqlite"
    est0 = Estado(banco)
    sim0 = SigaSimulado(procs); sim0.autenticar()
    par = lambda: Parametros("{placa}_{protocolo}", ["protocolo"], tmp_path / "stg", layout="por_placa",  # noqa: E731
                             tentativas=PoliticaTentativas(espera_inicial_s=0))
    Orquestrador(sim0, DestinoArquivos(tmp_path / "dest"), est0, par()).descobrir(Filtro(), est0.iniciar_execucao("descobrir", ""))
    erros = []

    def robo(fatia):
        try:
            o = Orquestrador(SigaSimulado(procs), DestinoArquivos(tmp_path / "dest"), Estado(banco), par(), dormir=lambda s: None)
            o.executar("retomar", Filtro(), fatias=[fatia])
        except Exception as e:  # noqa: BLE001
            erros.append(e)
    t = [threading.Thread(target=robo, args=(f,)) for f in ("2025-", "2026-")]
    [x.start() for x in t]; [x.join() for x in t]
    assert not erros
    est = Estado(banco)
    assert {p["estado"] for p in est.processos()} == {"completo"}
    assert est.contagens()["versoes"]["arquivos"] == 30 * 4                     # 30 sinistros x (histórico + 3)
    assert len([p for p in (tmp_path / "dest").rglob("*") if p.is_file()]) == 120


def test_pasta_saida_e_destino_configuraveis(tmp_path, monkeypatch):
    from bvix_siga.config import carregar
    cfgdir = tmp_path / "config"; cfgdir.mkdir()
    (cfgdir / "c.toml").write_text(
        '[origem]\nurl="https://star.arcoconsultoria.com/open.do?sys=SIG"\n[destino]\ntipo="arquivos"\nraiz="./x"\n'
        '[execucao]\n[pasta]\npadrao="{placa}"\n', encoding="utf-8")
    (cfgdir / "pasta_saida.txt").write_text("# pasta base\nD:\\SIGA_BVIX\n", encoding="utf-8")
    cfg = carregar(cfgdir / "c.toml")
    assert str(cfg.banco).endswith("estado.sqlite") and "SIGA_BVIX" in str(cfg.banco)
    assert "SIGA_BVIX" in str(cfg.destino_raiz) and str(cfg.destino_raiz).endswith("destino")
    monkeypatch.setenv("SIGA_PASTA_DESTINO", str(tmp_path / "rede"))
    cfg = carregar(cfgdir / "c.toml")
    assert cfg.destino_raiz == tmp_path / "rede" and "SIGA_BVIX" in str(cfg.banco)


def test_pasta_grupo_placa_numero_cpfcnpj():
    from bvix_siga.naming import pasta_grupo
    g = "{placa}_{protocolo}_{cpfcnpj}"
    assert pasta_grupo(g, {"placa": "URY1H51", "protocolo": "2026-10432", "cpfcnpj": "48.368.074/0001-01"}) \
        == "URY1H51_2026-10432_48368074000101"
    assert pasta_grupo(g, {"placa": "ABC1D23", "protocolo": "2026-00001", "cpfcnpj": "012.345.678-90"}) \
        == "ABC1D23_2026-00001_01234567890"
    assert pasta_grupo(g, {"placa": "", "protocolo": "SEMNUMERO-9", "cpfcnpj": None}) == "SEMPLACA_SEMNUMERO-9_SEMCPFCNPJ"


def test_layout_grupo_ponta_a_ponta(tmp_path):
    """Decisão 27/11: destino\\PLACA_NÚMERO_CPFCNPJ\\NÚMERO_HISTORICO.pdf e NÚMERO_<Tipo>_<nnn>_<nome>."""
    from bvix_siga.config import PoliticaTentativas
    from bvix_siga.destination import DestinoArquivos
    from bvix_siga.models import Filtro
    from bvix_siga.orchestrator import Orquestrador, Parametros
    from bvix_siga.siga.simulator import SigaSimulado, cenario_piloto
    from bvix_siga.state import Estado
    par = Parametros("{placa}_{protocolo}", ["protocolo"], tmp_path / "stg", layout="por_placa",
                     padrao_grupo="{placa}_{protocolo}_{cpfcnpj}", tentativas=PoliticaTentativas(espera_inicial_s=0))
    sim = SigaSimulado(cenario_piloto())
    Orquestrador(sim, DestinoArquivos(tmp_path / "dest"), Estado(tmp_path / "e.sqlite"), par,
                 dormir=lambda s: None).executar("carga-historica", Filtro())
    pastas = sorted(p.name for p in (tmp_path / "dest").iterdir() if p.is_dir())
    assert "ABC1D23_2026-00001_00000000000191" in pastas
    assert "ABC1D23_2026-00002_00000000000191" in pastas          # mesma placa, sinistros em pastas separadas
    for p in (tmp_path / "dest").iterdir():
        numero = p.name.split("_")[1]
        assert all(f.name.startswith(numero) for f in p.iterdir())
    assert any(f.name == "2026-00001_HISTORICO.pdf" for f in (tmp_path / "dest" / "ABC1D23_2026-00001_00000000000191").iterdir())


def test_relatorio_nao_quebra_em_console_cp1252(tmp_path, monkeypatch, capsys):
    """27/11: 'relatorio' caiu com UnicodeEncodeError (✅) no PowerShell em cp1252."""
    import io
    import sys
    from bvix_siga import cli
    cfgdir = tmp_path / "config"; cfgdir.mkdir()
    (cfgdir / "c.toml").write_text(
        '[origem]\nurl="https://star.arcoconsultoria.com/open.do?sys=SIG"\n[destino]\ntipo="arquivos"\nraiz="./d"\n'
        '[execucao]\nbanco="./e.sqlite"\nrelatorios="./r"\nlogs="./l"\nstaging="./s"\n[pasta]\npadrao="{placa}"\n',
        encoding="utf-8")
    for k in ("SIGA_PASTA_SAIDA", "SIGA_PASTA_DESTINO"):
        monkeypatch.setenv(k, "")
    falso = io.TextIOWrapper(io.BytesIO(), encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", falso)
    assert cli.main(["relatorio", "-c", str(cfgdir / "c.toml")]) == 0
    falso.flush()
    assert b"PASTA_EXCEL=" in falso.buffer.getvalue()


def test_zerar_renomeia_sem_apagar_e_recusa_com_robo(tmp_path, monkeypatch, capsys):
    import os
    from bvix_siga import cli
    cfgdir = tmp_path / "config"; cfgdir.mkdir()
    (cfgdir / "c.toml").write_text(
        '[origem]\nurl="https://star.arcoconsultoria.com/open.do?sys=SIG"\n[destino]\ntipo="arquivos"\nraiz="./saida_x/destino"\n'
        '[execucao]\nbanco="./saida_x/estado.sqlite"\nrelatorios="./saida_x/r"\nlogs="./saida_x/l"\nstaging="./saida_x/s"\n'
        '[pasta]\npadrao="{placa}"\n', encoding="utf-8")
    for k in ("SIGA_PASTA_SAIDA", "SIGA_PASTA_DESTINO"):
        monkeypatch.setenv(k, "")
    base = tmp_path / "saida_x"; (base / "destino" / "P1").mkdir(parents=True)
    (base / "estado.sqlite").write_bytes(b"x"); (base / "destino" / "P1" / "a.pdf").write_bytes(b"%PDF")
    c = str(cfgdir / "c.toml")
    (base / "estado.fatia-2025.lock").write_text(str(os.getpid()))          # robô "vivo"
    assert cli.main(["zerar", "-c", c, "--confirmar"]) == 6 and base.exists()
    (base / "estado.fatia-2025.lock").unlink()
    assert cli.main(["zerar", "-c", c]) == 0 and base.exists()              # sem --confirmar: só o plano
    assert cli.main(["zerar", "-c", c, "--confirmar"]) == 0
    assert not base.exists()
    antigas = list(tmp_path.glob("saida_x_antiga_*"))
    assert len(antigas) == 1 and (antigas[0] / "destino" / "P1" / "a.pdf").read_bytes() == b"%PDF"


def test_descobrir_recusa_com_robos_rodando(tmp_path, monkeypatch):
    import os
    from bvix_siga import cli
    cfgdir = tmp_path / "config"; cfgdir.mkdir()
    (cfgdir / "c.toml").write_text(
        '[origem]\nurl="https://star.arcoconsultoria.com/open.do?sys=SIG"\n[destino]\ntipo="arquivos"\nraiz="./o/d"\n'
        '[execucao]\nbanco="./o/estado.sqlite"\nrelatorios="./o/r"\nlogs="./o/l"\nstaging="./o/s"\n[pasta]\npadrao="{placa}"\n',
        encoding="utf-8")
    for k in ("SIGA_PASTA_SAIDA", "SIGA_PASTA_DESTINO"):
        monkeypatch.setenv(k, "")
    (tmp_path / "o").mkdir()
    (tmp_path / "o" / "estado.fatia-2025.lock").write_text(str(os.getpid()))
    assert cli.main(["descobrir", "-c", str(cfgdir / "c.toml"), "--simulador"]) == 6


def test_relatorio_projeta_espaco_e_capacidade(tmp_path):
    from bvix_siga import reports
    from bvix_siga.state import Estado
    from bvix_siga.models import EstadoProcesso
    est = Estado(tmp_path / "e.sqlite")
    ex = est.iniciar_execucao("carga-historica", "")
    for i in range(1, 41):
        for ano in ("2025", "2026"):
            p = f"{ano}-{i:05d}"
            est.registrar_processo(p, f"{ano}{i}", ex)
    for i in range(1, 21):                                   # 20 de cada ano concluídos: 2025 = 10 MB, 2026 = 2 MB
        for ano, mb in (("2025", 10), ("2026", 2)):
            p = f"{ano}-{i:05d}"
            est.registrar_item(f"H-{p}", p, "historico", nome_original="h", contexto="processo", ordinal=0, exec_id=ex)
            est.confirmar_versao(f"H-{p}", 1, "x" * 64, mb * 1024 ** 2, f"{p}/h.pdf", ex)
            est.mudar_processo(p, EstadoProcesso.COMPLETO, ex)
    pr = reports.projecao_espaco(est)
    assert abs(pr["gb"] - (40 * 10 + 40 * 2) / 1024) < 0.01          # 400 MB + 80 MB
    assert pr["recomendado"] >= 50 and "2025: 10.0 MB" in pr["medias"]
    arq = reports.gerar_acompanhamento(est, tmp_path / "r")
    txt = arq["resumo"].read_text(encoding="utf-8")
    assert "Espaço projetado ao final" in txt and "Capacidade recomendada" in txt and "sinistros por hora" in txt


def test_relatorio_tem_aba_por_robo_e_coluna_robo(tmp_path):
    import openpyxl
    from bvix_siga import reports
    from bvix_siga.fatias import robo_de
    from bvix_siga.models import EstadoProcesso
    from bvix_siga.state import Estado
    assert (robo_de("2025-00001"), robo_de("2026-10432"), robo_de("SEMNUMERO-9"), robo_de("2026-03999"),
            robo_de("2026-09757-ID1"), robo_de("2027-00001")) == ("R1", "R1", "R1", "R2", "R3", "-")
    est = Estado(tmp_path / "e.sqlite")
    ex = est.iniciar_execucao("retomar", "")
    for p in ("2025-00001", "2026-00001", "2026-05001", "2026-05002"):
        est.registrar_processo(p, p[-1], ex)
    for p in ("2025-00001", "2026-05001"):
        est.mudar_processo(p, EstadoProcesso.COMPLETO, ex)
    arq = reports.gerar_acompanhamento(est, tmp_path / "r")
    wb = openpyxl.load_workbook(arq["excel"])
    assert wb.sheetnames[:4] == ["Resumo", "Por robô", "Concluídos", "Por sinistro"]
    conc = [r for r in wb["Concluídos"].iter_rows(min_row=2, values_only=True) if r[0]]
    assert sorted(r[1] for r in conc) == ["2025-00001", "2026-05001"]            # só os finalizados, todos juntos
    linhas = {r[0]: r for r in wb["Por robô"].iter_rows(min_row=2, values_only=True) if r[0]}
    assert linhas["R1"][4] == 1 and linhas["R2"][7] == 1 and linhas["R3"][3] == 2 and linhas["TOTAL"][3] == 4
    assert linhas["R1"][2] == "TERMINOU" and linhas["R2"][2] == "PARADO"
    assert wb["Por sinistro"]["B1"].value == "Robô" and wb["Por sinistro"]["B2"].value == "R1"


def test_zerar_plano_b_move_conteudo_quando_pasta_bloqueada(tmp_path, monkeypatch):
    """27/11: WinError 5 ao renomear saida_final (pasta observada pelo Windows). Plano B: mover o conteúdo."""
    import pathlib
    from bvix_siga import cli
    cfgdir = tmp_path / "config"; cfgdir.mkdir()
    (cfgdir / "c.toml").write_text(
        '[origem]\nurl="https://star.arcoconsultoria.com/open.do?sys=SIG"\n[destino]\ntipo="arquivos"\nraiz="./sf/destino"\n'
        '[execucao]\nbanco="./sf/estado.sqlite"\nrelatorios="./sf/r"\nlogs="./sf/l"\nstaging="./sf/s"\n[pasta]\npadrao="{placa}"\n',
        encoding="utf-8")
    for k in ("SIGA_PASTA_SAIDA", "SIGA_PASTA_DESTINO"):
        monkeypatch.setenv(k, "")
    base = tmp_path / "sf"; (base / "destino" / "P1").mkdir(parents=True)
    (base / "estado.sqlite").write_bytes(b"db"); (base / "destino" / "P1" / "a.pdf").write_bytes(b"%PDF")
    original = pathlib.Path.rename

    def rename_bloqueado(self, alvo):
        if self == base:
            raise PermissionError(5, "Acesso negado")
        return original(self, alvo)
    monkeypatch.setattr(pathlib.Path, "rename", rename_bloqueado)
    assert cli.main(["zerar", "-c", str(cfgdir / "c.toml"), "--confirmar"]) == 0
    antiga = next(tmp_path.glob("sf_antiga_*"))
    assert (antiga / "estado.sqlite").read_bytes() == b"db" and (antiga / "destino" / "P1" / "a.pdf").exists()
    assert base.exists() and not any(base.iterdir())                      # sf ficou vazia: carga nova começa do zero
    import logging                                                       # zerar não pode abrir o log da pasta
    assert not any(isinstance(h, logging.FileHandler) and str(base) in h.baseFilename
                   for h in logging.getLogger("bvix_siga").handlers)
