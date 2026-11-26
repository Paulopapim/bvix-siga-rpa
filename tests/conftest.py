from __future__ import annotations

from pathlib import Path

import pytest

from bvix_siga.config import PoliticaTentativas
from bvix_siga.destination import DestinoArquivos
from bvix_siga.orchestrator import Orquestrador, Parametros
from bvix_siga.siga.simulator import SigaSimulado, cenario_piloto
from bvix_siga.state import Estado


class Ambiente:
    def __init__(self, tmp: Path, sim: SigaSimulado, padrao: str, obrig: list[str]):
        self.tmp = tmp
        self.sim = sim
        self.estado = Estado(tmp / "estado.sqlite")
        self.destino = DestinoArquivos(tmp / "destino")
        self.esperas: list[float] = []
        self.params = Parametros(pasta_padrao=padrao, pasta_campos_obrigatorios=obrig, staging=tmp / "staging",
                                 tentativas=PoliticaTentativas(max_tentativas=3, espera_inicial_s=0.01))
        self.orq = Orquestrador(sim, self.destino, self.estado, self.params, dormir=self.esperas.append)

    def arquivos(self) -> list[Path]:
        raiz = self.tmp / "destino"
        return sorted(p for p in raiz.rglob("*") if p.is_file() and not p.name.startswith(".")) if raiz.exists() else []

    def estado_de(self, protocolo: str) -> str:
        return self.estado.processo(protocolo)["estado"]


@pytest.fixture
def criar_ambiente(tmp_path):
    def _criar(processos=None, falhas=None, padrao="{placa}_{evento}_{cpfcnpj}__{protocolo}",
               obrig=("placa", "protocolo"), **kw):
        sim = SigaSimulado(processos if processos is not None else cenario_piloto(), falhas=falhas, **kw)
        return Ambiente(tmp_path, sim, padrao, list(obrig))
    return _criar
