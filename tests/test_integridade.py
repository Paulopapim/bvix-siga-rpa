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
