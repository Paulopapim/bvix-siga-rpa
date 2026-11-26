"""Execução pelo Orquestrador EMK: parâmetros (EMK_VARS), cofre, códigos de saída e robôs em paralelo."""

import json
import shutil

import pytest

from bvix_siga import emk


def test_parametros_padrao():
    p = emk.parametros({})
    assert p["comando"] == "retomar" and p["robos"] == [] and p["pendencias_ok"] is True
    assert p["config"] == "config/config.piloto.toml" and p["simulador"] is False


def test_parametros_fatias_e_tipos():
    p = emk.parametros({"fatias": "2025-,2026-1,SEMNUMERO-; 2026-00,2026-01 ;2026-05;", "limite": "3",
                        "pendencias_ok": "false", "simulador": True})
    assert p["robos"] == ["2025-,2026-1,SEMNUMERO-", "2026-00,2026-01", "2026-05"]
    assert p["limite"] == 3 and p["pendencias_ok"] is False and p["simulador"] is True


@pytest.mark.parametrize("v", [{"comando": "apagar"}, {"fatias": "2026-;2026-1"},
                               {"comando": "descobrir", "fatias": "2025-"}])
def test_parametros_invalidos(v):
    with pytest.raises(ValueError):
        emk.parametros(v)


def test_emk_vars_invalido_sai_com_2(capsys):
    assert emk.main({"EMK_VARS": "{nao json"}) == 2
    assert "ERRO DE PARÂMETRO" in capsys.readouterr().out


def test_credenciais_do_cofre():
    assert emk.credenciais_do_cofre({"SIGA": "s", "SIGA_USER": "u"}) == {"SIGA_PASSWORD": "s", "SIGA_USERNAME": "u"}
    assert emk.credenciais_do_cofre({"SIGA_PASSWORD": "s", "SIGA_PASSWORD_USER": "u"}) == {"SIGA_USERNAME": "u"}
    assert emk.credenciais_do_cofre({"SIGA_USERNAME": "a", "SIGA_PASSWORD": "b"}) == {}


def test_combinar_pior_codigo():
    assert emk.combinar([0, 0]) == 0
    assert emk.combinar([0, 10]) == 10
    assert emk.combinar([10, 3, 0]) == 3
    assert emk.combinar([6, 10]) == 6
    assert emk.combinar([]) == 1


def _projeto(tmp_path, monkeypatch):
    """Cópia mínima do projeto para rodar o emk de ponta a ponta com o SIGA simulado."""
    raiz = emk.RAIZ
    (tmp_path / "config").mkdir()
    shutil.copy(raiz / "config" / "config.piloto.toml", tmp_path / "config" / "config.piloto.toml")
    monkeypatch.setattr(emk, "RAIZ", tmp_path)
    for k in ("SIGA_PASTA_SAIDA", "SIGA_PASTA_DESTINO", "SIGA_MODO_VISIVEL"):
        monkeypatch.setenv(k, "")          # registrado: o monkeypatch restaura o que o emk gravar
    return tmp_path


def test_ponta_a_ponta_simulador_um_robo(tmp_path, monkeypatch, capsys):
    proj = _projeto(tmp_path, monkeypatch)
    cod = emk.main({"EMK_VARS": json.dumps({"comando": "carga-historica", "simulador": True}),
                    "PYTHONPATH": str(emk.Path(__file__).resolve().parents[1] / "src")})
    out = capsys.readouterr().out
    assert "SIMULADOR" in out and "PROGRESSO: sinistros" in out
    assert cod == 0                                   # pendências do cenário viram "Concluído" (pendencias_ok)
    assert (proj / "saida_simulador" / "estado.sqlite").exists()
    assert not (proj / "saida_placa").exists()        # nunca grava na pasta da carga real
    assert any((proj / "saida_simulador" / "destino").rglob("*_HISTORICO*"))


def test_ponta_a_ponta_simulador_dois_robos(tmp_path, monkeypatch, capsys):
    _projeto(tmp_path, monkeypatch)
    monkeypatch.setattr(emk.threading.Event, "wait", lambda self, t=None: self.is_set())   # sem os 30 s
    vars_ = {"comando": "carga-historica", "simulador": True, "fatias": "2025-;2026-", "pendencias_ok": False}
    cod = emk.main({"EMK_VARS": json.dumps(vars_), "PYTHONPATH": str(emk.Path(__file__).resolve().parents[1] / "src")})
    out = capsys.readouterr().out
    assert "[R1] " in out and "[R2] " in out
    assert "[R1] terminou com código" in out and "[R2] terminou com código" in out
    assert cod in (0, 10)


def test_sem_credenciais_sai_com_2(tmp_path, monkeypatch, capsys):
    _projeto(tmp_path, monkeypatch)
    assert emk.main({"EMK_VARS": ""}) == 2
    assert "credenciais do SIGA ausentes" in capsys.readouterr().out
