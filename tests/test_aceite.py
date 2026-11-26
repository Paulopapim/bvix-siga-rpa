"""Testes mapeados aos critérios de aceite CA-01..CA-12 e exceções EX-01..EX-11 do PDD (dados fictícios)."""

from __future__ import annotations

import csv

from bvix_siga import reports
from bvix_siga.models import Filtro
from bvix_siga.siga.simulator import AnexoSim, Falhas, ProcessoSim, pdf


def test_ca01_cobertura_do_recorte(criar_ambiente):
    amb = criar_ambiente()
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.descoberta.cobertura_comprovada
    assert len(r.descoberta.protocolos) == 5 == r.descoberta.total_exibido


def test_ca01_ex02_pagina_repetida_nao_comprova_cobertura(criar_ambiente):
    procs = [ProcessoSim(f"2026-{i:05d}", str(i), f"PLA{i:04d}", "COLISÃO", "1") for i in range(1, 26)]
    amb = criar_ambiente(procs, Falhas(pagina_repetida_em=2))
    r = amb.orq.executar("carga-historica", Filtro())
    assert not r.descoberta.cobertura_comprovada
    assert any("repete" in a for a in r.descoberta.anomalias)
    assert r.status == "concluida_com_pendencias"


def test_ex02_fim_prematuro(criar_ambiente):
    procs = [ProcessoSim(f"2026-{i:05d}", str(i), f"PLA{i:04d}", "COLISÃO", "1") for i in range(1, 26)]
    amb = criar_ambiente(procs, Falhas(fim_prematuro_em=2))
    amb.sim.autenticar()
    d = amb.orq.descobrir(Filtro(), amb.estado.iniciar_execucao("t", ""))
    assert not d.cobertura_comprovada and any("prematuro" in a for a in d.anomalias)


def test_piloto_lista_protocolos_registra_nao_encontrado(criar_ambiente):
    amb = criar_ambiente()
    r = amb.orq.executar("carga-historica", Filtro(protocolos=("2026-00001", "2026-99999")))
    assert amb.estado_de("2026-99999") == "nao_encontrado"
    assert amb.estado_de("2026-00001") == "completo"
    assert r.descoberta.nao_encontrados == ["2026-99999"]


def test_ca02_historico_e_todos_anexos(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    assert amb.estado_de("2026-00001") == "completo"
    nomes = [p.name for p in amb.arquivos() if "2026-00001" in str(p)]
    assert any(n.startswith("historico__v1") for n in nomes)
    assert sum(1 for n in nomes if "__p__" in n or "__h" in n) == 3      # 2 do processo + 1 de entrada do histórico
    assert amb.estado_de("2026-00005") == "completo"
    assert len([p for p in amb.arquivos() if "2026-00005" in str(p)]) == 51  # 50 anexos + histórico


def test_ca03_mesma_placa_nao_mistura(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    p1, p2 = amb.estado.processo("2026-00001")["pasta"], amb.estado.processo("2026-00002")["pasta"]
    assert p1 != p2 and p1.startswith("ABC1D23") and p2.startswith("ABC1D23")


def test_ca03_ex04_colisao_de_chave_vai_para_tratamento(criar_ambiente):
    procs = [ProcessoSim("2026-00010", "10", "ABC1D23", "COLISÃO", "00.000.000/0001-91", anexos=[AnexoSim("a.pdf", pdf("a"))]),
             ProcessoSim("2026-00011", "11", "ABC1D23", "COLISÃO", "00.000.000/0001-91", anexos=[AnexoSim("b.pdf", pdf("b"))])]
    amb = criar_ambiente(procs, padrao="{placa}_{evento}_{cpfcnpj}", obrig=("placa", "evento", "cpfcnpj"))
    amb.orq.executar("carga-historica", Filtro())
    estados = sorted([amb.estado_de("2026-00010"), amb.estado_de("2026-00011")])
    assert estados == ["completo", "tratamento"]
    # a pasta contém só os arquivos de UM processo
    assert not any("b.pdf" in p.name for p in amb.arquivos())


def test_ex03_identificacao_ausente_nao_inventa_valor(criar_ambiente):
    amb = criar_ambiente(padrao="{placa}_{evento}_{cpfcnpj}", obrig=("placa", "evento", "cpfcnpj"))
    amb.orq.executar("carga-historica", Filtro())
    p = amb.estado.processo("2026-00004")   # evento nulo (como observado no SIGA)
    assert p["estado"] == "tratamento" and p["codigo_excecao"] == "EX-03"
    assert not any("2026-00004" in str(x) or "QWE4R56" in str(x) for x in amb.arquivos())


def test_ca04_recuperacao_por_identificacao(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    ident = amb.estado.processo("2026-00003")["identificacao"]
    assert "012.345.678-90" in ident     # valor original preservado (zeros à esquerda/máscara)
    pasta = amb.estado.processo("2026-00003")["pasta"]
    assert (amb.tmp / "destino" / pasta / "historico").is_dir()


def test_ca05_ex09_constatacao_sem_anexos(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    assert amb.estado_de("2026-00002") == "completo_sem_anexos"
    assert any("2026-00002" in str(p) and p.name.startswith("historico") for p in amb.arquivos())


def test_ca05_listagem_inacessivel_nao_vira_sem_anexos(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(listagem_incompleta={"2026-00002"}))
    amb.orq.executar("carga-historica", Filtro())
    p = amb.estado.processo("2026-00002")
    assert p["estado"] == "pendente" and p["codigo_excecao"] == "EX-07-LISTAGEM"


def test_ca06_ex05_historico_invalido_nao_marca_sucesso(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(historico_vazio={"2026-00001"}, historico_tela_login={"2026-00003"}))
    amb.orq.executar("carga-historica", Filtro())
    assert amb.estado_de("2026-00001") == "pendente"
    assert amb.estado_de("2026-00003") == "pendente"
    assert not any(p.name.startswith("historico") and "2026-00003" in str(p) for p in amb.arquivos())


def test_ca06_ex06_download_transitorio_recupera(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(download_falha_vezes={"2026-00001#1": 2}))
    amb.orq.executar("carga-historica", Filtro())
    assert amb.estado_de("2026-00001") == "completo"
    assert len(amb.esperas) >= 2 and amb.esperas[1] > amb.esperas[0]   # espera progressiva


def test_ca06_ex06_download_esgota_tentativas_fica_pendente(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(download_falha_vezes={"2026-00001#1": 99}))
    amb.orq.executar("carga-historica", Filtro())
    assert amb.estado_de("2026-00001") == "pendente"
    assert amb.estado_de("2026-00005") == "completo"      # os demais seguem


def test_ex07_arquivo_truncado(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(download_truncado={"2026-00004#1"}))
    amb.orq.executar("carga-historica", Filtro())
    assert amb.estado_de("2026-00004") == "pendente"


def test_troca_de_processo_detectada(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(troca_processo={"2026-00003"}))
    amb.orq.executar("carga-historica", Filtro())
    p = amb.estado.processo("2026-00003")
    assert p["estado"] == "pendente" and p["codigo_excecao"] == "EX-03-TROCA"


def test_ca07_reexecucao_idempotente(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    antes = {p: p.read_bytes() for p in amb.arquivos()}
    amb.orq.executar("incremental", Filtro())
    depois = {p: p.read_bytes() for p in amb.arquivos()}
    assert antes == depois                         # nada duplicado nem sobrescrito
    assert amb.estado.contagens()["versoes"]["arquivos"] == len(antes)


def test_ca07_homonimos_e_bytes_iguais_continuam_itens_distintos(criar_ambiente):
    procs = [ProcessoSim("2026-00020", "20", "AAA0A00", "COLISÃO", "1",
                         anexos=[AnexoSim("foto.jpg", b"\xff\xd8\xff" + b"z" * 100),
                                 AnexoSim("foto.jpg", b"\xff\xd8\xff" + b"z" * 100)])]
    amb = criar_ambiente(procs)
    amb.orq.executar("carga-historica", Filtro())
    anexos = [p for p in amb.arquivos() if "anexos" in str(p)]
    assert len(anexos) == 2 and anexos[0].name != anexos[1].name


def test_ca08_incremental_novo_processo_novo_anexo_e_historico_alterado(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    amb.sim.processos["2026-00002"].anexos.append(AnexoSim("laudo.pdf", pdf("laudo")))
    amb.sim.processos["2026-00001"].historico.append("Nova tratativa com corretor")
    amb.sim.processos["2026-00006"] = ProcessoSim("2026-00006", "1006", "NEW0A01", "FURTO", "3")
    r = amb.orq.executar("incremental", Filtro())
    assert r.descoberta.novos == 1 and amb.estado_de("2026-00006") == "completo_sem_anexos"
    assert amb.estado_de("2026-00002") == "completo"            # deixou de ser "sem anexos"
    hist = sorted(p.name for p in amb.arquivos() if "2026-00001" in str(p) and p.name.startswith("historico"))
    assert hist == ["historico__v1.pdf", "historico__v2.pdf"]  # versão anterior preservada


def test_ca09_ex11_reconciliacao_do_corte(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro(), limite=3)
    amb.sim.processos["2026-00007"] = ProcessoSim("2026-00007", "1007", "LAS7T00", "COLISÃO", "4")
    r = amb.orq.reconciliar(Filtro())
    assert r["status"] == "com_diferencas"
    assert "2026-00007" in r["nao_inventariados"]
    assert set(r["nao_finalizados"]) == {"2026-00004", "2026-00005"}


def test_ca11_somente_leitura_na_origem(criar_ambiente):
    amb = criar_ambiente()
    amb.orq.executar("carga-historica", Filtro())
    assert amb.sim.operacoes_escrita == 0
    from bvix_siga import source
    metodos = {m for m in dir(source.FonteSiga) if not m.startswith("_")}
    assert metodos == {"autenticar", "verificar_sessao", "enumerar", "abrir_processo", "exportar_historico",
                       "listar_anexos", "baixar_anexo", "encerrar"}


def test_ca12_auditoria_de_ponta_a_ponta(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(download_falha_vezes={"2026-00001#1": 99}))
    amb.orq.executar("carga-historica", Filtro())
    arqs = reports.gerar(amb.estado, amb.tmp / "rel")
    with open(arqs["inventario"], encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f, delimiter=";"))
    confirmados = [l for l in linhas if l["estado_item"] == "confirmado"]
    assert all(l["sha256"] and l["caminho_relativo"] for l in confirmados)
    falhos = [l for l in linhas if l["protocolo"] == "2026-00001" and l["estado_item"] == "pendente"]
    assert falhos and falhos[0]["codigo_excecao"] == "EX-06"
    assert amb.estado.eventos("2026-00001")      # trilha de transições


def test_ex01_mfa_interrompe(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(mfa=True))
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.status == "suspensa" and "EX-01-INTERVENCAO" in r.motivo_suspensao
    assert not amb.arquivos()


def test_ex01_sessao_expirada_reautentica_uma_vez(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(sessao_expira_apos_chamadas=20))
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.status == "concluida"


def test_ex01_sessao_nao_volta_suspende_sem_falso_sucesso(criar_ambiente):
    amb = criar_ambiente(falhas=Falhas(sessao_expira_apos_chamadas=20, sessao_nao_volta=True))
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.status == "suspensa"
    # retomar depois que a sessão volta
    amb.sim.falhas = Falhas()
    amb.sim._expirou = False
    r2 = amb.orq.executar("retomar", Filtro())
    assert r2.status == "concluida"
    assert {p["estado"] for p in amb.estado.processos()} <= {"completo", "completo_sem_anexos"}


def test_ex08_destino_sem_permissao_suspende(criar_ambiente, monkeypatch):
    amb = criar_ambiente()
    from bvix_siga.errors import DestinoIndisponivel
    def falha(*a, **k):
        raise DestinoIndisponivel("sem permissão")
    monkeypatch.setattr(amb.destino, "verificar", falha)
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.status == "suspensa" and r.motivo_suspensao.startswith("EX-08")


def test_ex08_destino_falha_no_meio_nao_confirma_item(criar_ambiente, monkeypatch):
    amb = criar_ambiente()
    from bvix_siga.errors import DestinoIndisponivel
    original = amb.destino.publicar
    n = {"c": 0}
    def publicar(*a, **k):
        n["c"] += 1
        if n["c"] == 4:
            raise DestinoIndisponivel("disco cheio")
        return original(*a, **k)
    monkeypatch.setattr(amb.destino, "publicar", publicar)
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.status == "suspensa"
    nao_conf = [i for i in amb.estado.itens() if i["estado"] != "confirmado"]
    assert nao_conf    # o item afetado não foi confirmado
    for v in amb.estado.db.execute("SELECT caminho_relativo FROM versoes"):
        assert (amb.tmp / "destino" / v["caminho_relativo"]).exists()   # tudo confirmado existe de fato


def test_layout_pasta_unica_identifica_por_placa(criar_ambiente):
    amb = criar_ambiente(padrao="{placa}_{protocolo}")
    amb.params.layout = "unica"
    amb.orq.executar("carga-historica", Filtro())
    arqs = amb.arquivos()
    assert all(p.parent == amb.tmp / "destino" for p in arqs)            # nenhuma subpasta
    nomes = [p.name for p in arqs]
    assert "ABC1D23_2026-00001_HISTORICO.pdf" in nomes
    assert "ABC1D23_2026-00002_HISTORICO.pdf" in nomes                   # mesma placa, processos separados
    assert sum(n.startswith("XYZ9K88_2026-00003_") and "foto" in n for n in nomes) == 2   # homônimos distintos
    assert sum(n.startswith("MNB7V65_2026-00005_") for n in nomes) == 51
    amb.orq.executar("incremental", Filtro())
    assert len(amb.arquivos()) == len(arqs)                               # reexecução não duplica


def test_listagem_incompleta_baixa_o_que_listou_e_fica_pendente(criar_ambiente, monkeypatch):
    amb = criar_ambiente()
    original = amb.sim.listar_anexos

    def parcial(protocolo):
        lst = original(protocolo)
        if protocolo == "2026-00005":
            lst.anexos = lst.anexos[:10]
            lst.completa = False
            lst.observacao = "Documentos: listados 10 de 50"
        return lst
    monkeypatch.setattr(amb.sim, "listar_anexos", parcial)
    amb.orq.executar("carga-historica", Filtro())
    p = amb.estado.processo("2026-00005")
    assert p["estado"] == "pendente" and p["codigo_excecao"] == "EX-07-LISTAGEM"
    assert len([x for x in amb.arquivos() if "2026-00005" in str(x) and "anexos" in str(x)]) == 10


def test_layout_pasta_por_placa(criar_ambiente):
    amb = criar_ambiente(padrao="{placa}_{protocolo}")
    amb.params.layout = "por_placa"
    amb.orq.executar("carga-historica", Filtro())
    raiz = amb.tmp / "destino"
    assert sorted(p.name for p in raiz.iterdir()) == ["ABC1D23", "MNB7V65", "QWE4R56", "XYZ9K88"]
    abc = sorted(p.name for p in (raiz / "ABC1D23").iterdir())
    assert "2026-00001_HISTORICO.pdf" in abc and "2026-00002_HISTORICO.pdf" in abc   # 2 sinistros, mesma placa
    assert len(list((raiz / "MNB7V65").iterdir())) == 51
    amb.orq.executar("incremental", Filtro())
    assert len(list((raiz / "MNB7V65").iterdir())) == 51


def test_numeros_repetidos_e_zero_nao_perdem_sinistros(criar_ambiente):
    """Evidência 26/11: o SIGA tem 2 sinistros 2026-09757 (IDs diferentes) e 10 com número '0'."""
    procs = [ProcessoSim("2026-09757", "501", "AAA1A11", "COLISÃO", "1", anexos=[AnexoSim("a.pdf", pdf("a"))]),
             ProcessoSim("2026-09757", "502", "BBB2B22", "COLISÃO", "2", anexos=[AnexoSim("b.pdf", pdf("b"))]),
             ProcessoSim("0", "601", "CCC3C33", None, "3", anexos=[AnexoSim("c.pdf", pdf("c"))]),
             ProcessoSim("0", "602", "CCC3C33", None, "3"),
             ProcessoSim("2026-00001", "700", "DDD4D44", "FURTO", "4")]
    amb = criar_ambiente(procs, padrao="{placa}_{protocolo}")
    amb.params.layout = "por_placa"
    r = amb.orq.executar("carga-historica", Filtro())
    assert r.descoberta.cobertura_comprovada and len(r.descoberta.protocolos) == 5
    chaves = {p["protocolo"]: p["estado"] for p in amb.estado.processos()}
    assert set(chaves) == {"2026-09757-ID501", "2026-09757-ID502", "SEMNUMERO-601", "SEMNUMERO-602", "2026-00001"}
    assert all(e.startswith("completo") for e in chaves.values())
    raiz = amb.tmp / "destino"
    assert "2026-09757-ID501_HISTORICO.pdf" in [p.name for p in (raiz / "AAA1A11").iterdir()]
    assert "2026-09757-ID502_HISTORICO.pdf" in [p.name for p in (raiz / "BBB2B22").iterdir()]
    ccc = sorted(p.name for p in (raiz / "CCC3C33").iterdir())
    assert "SEMNUMERO-601_HISTORICO.pdf" in ccc and "SEMNUMERO-602_HISTORICO.pdf" in ccc


def test_descoberta_antiga_com_numero_repetido_e_renomeada(criar_ambiente):
    procs = [ProcessoSim("2026-09757", "501", "AAA1A11", "COLISÃO", "1"),
             ProcessoSim("2026-09757", "502", "BBB2B22", "COLISÃO", "2")]
    amb = criar_ambiente(procs)
    amb.estado.registrar_processo("2026-09757", "501", None)       # como ficou no banco antes da correção
    amb.sim.autenticar()
    amb.orq.descobrir(Filtro(), amb.estado.iniciar_execucao("descobrir", ""))
    assert {p["protocolo"] for p in amb.estado.processos()} == {"2026-09757-ID501", "2026-09757-ID502"}


def test_retomar_sem_reler_lista_mantem_placa(criar_ambiente):
    amb = criar_ambiente(padrao="{placa}_{protocolo}")
    amb.params.layout = "por_placa"
    amb.sim.autenticar()
    amb.orq.descobrir(Filtro(), amb.estado.iniciar_execucao("descobrir", ""))
    p = amb.sim.processos["2026-00004"]
    p.placa = None                                   # tela não traz a placa; a listagem trouxe
    amb.orq.executar("retomar", Filtro())
    assert (amb.tmp / "destino" / "QWE4R56" / "2026-00004_HISTORICO.pdf").exists()


def test_anexo_sem_arquivo_na_origem_vai_para_tratamento_sem_retentar(criar_ambiente):
    """Evidência 26/11 (2025-00001): SIGA lista o anexo mas o servidor não tem o arquivo."""
    amb = criar_ambiente(falhas=Falhas(arquivo_ausente={"2026-00001#processo#1"}))
    amb.orq.executar("carga-historica", Filtro())
    p = amb.estado.processo("2026-00001")
    assert p["estado"] == "tratamento" and p["codigo_excecao"] == "EX-06-SEM-ARQUIVO"
    itens = {i["nome_original"]: i for i in amb.estado.itens("2026-00001")}
    assert itens["BO.pdf"]["estado"] == "falho" and itens["BO.pdf"]["tentativas"] == 1   # sem retentativa
    assert itens["CNH.jpg"]["estado"] == "confirmado"                                     # os demais seguem
    assert amb.esperas == []
    r = amb.orq.executar("retomar", Filtro())                                             # retomar não insiste
    assert amb.estado.processo("2026-00001")["estado"] == "tratamento"


def test_acompanhamento_lista_baixados_erros_e_faltantes(criar_ambiente):
    import csv as _csv
    amb = criar_ambiente(falhas=Falhas(arquivo_ausente={"2026-00001#processo#1"}, download_falha_vezes={"2026-00005#3": 99}))
    amb.orq.executar("carga-historica", Filtro())
    arqs = reports.gerar_acompanhamento(amb.estado, amb.tmp / "rel")
    with open(arqs["acompanhamento"], encoding="utf-8-sig") as f:
        linhas = {l["chave"]: l for l in _csv.DictReader(f, delimiter=";")}
    assert linhas["2026-00001"]["situacao"] == "TRATAMENTO"
    assert linhas["2026-00001"]["anexos_sem_arquivo_na_origem"] == "1"
    assert linhas["2026-00005"]["anexos_no_siga"] == "50" and linhas["2026-00005"]["anexos_com_erro"] == "1"
    assert linhas["2026-00005"]["anexos_faltando"] == "1"
    assert linhas["2026-00002"]["situacao"].startswith("CONCLUÍDO")
    with open(arqs["erros"], encoding="utf-8-sig") as f:
        erros = list(_csv.DictReader(f, delimiter=";"))
    assert {e["codigo_erro"] for e in erros} == {"EX-06-SEM-ARQUIVO", "EX-06"}
    resumo = arqs["resumo"].read_text(encoding="utf-8")
    assert "Progresso:" in resumo and "Previsão" in resumo
