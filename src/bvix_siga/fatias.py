"""Divisão padrão dos sinistros entre os 3 robôs em paralelo (fatias = prefixos da chave, sem sobreposição).
Manter igual ao rodar_paralelo.ps1 e ao rodar_tudo.bat."""

from __future__ import annotations

FATIAS_PADRAO: list[tuple[str, str]] = [
    ("R1", "2025-,2026-1,SEMNUMERO-"),                    # 2025, 2026-10000+ e os sem número
    ("R2", "2026-00,2026-01,2026-02,2026-03,2026-04"),    # 2026-00001 a 2026-04999
    ("R3", "2026-05,2026-06,2026-07,2026-08,2026-09"),    # 2026-05000 a 2026-09999
]


def robo_de(chave: str, fatias: list[tuple[str, str]] | None = None) -> str:
    for nome, prefixos in fatias or FATIAS_PADRAO:
        if any(chave.startswith(p.strip()) for p in prefixos.split(",") if p.strip()):
            return nome
    return "-"
