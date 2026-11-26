"""Validação técnica de arquivos baixados antes da publicação (EX-05, EX-07)."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .errors import DivergenciaInventario, HistoricoInvalido

_ASSINATURAS = {
    b"%PDF-": "pdf",
    b"PK\x03\x04": "zip",          # também docx/xlsx
    b"\xff\xd8\xff": "jpg",
    b"\x89PNG\r\n\x1a\n": "png",
    b"GIF8": "gif",
    b"II*\x00": "tif",
    b"MM\x00*": "tif",
    b"\xd0\xcf\x11\xe0": "ole",    # doc/xls/msg
}

# Indícios de que o "arquivo" é na verdade uma tela de login/erro do portal.
_MARCAS_TELA = [b"LoginPrincipal", b"WEBRUN-CSRFTOKEN", b"Entre com seus dados", b"Sess\xc3\xa3o expirada",
                b"cf-browser-verification", b"Attention Required! | Cloudflare"]


def tipo_tecnico(caminho: Path) -> str:
    with open(caminho, "rb") as f:
        cab = f.read(16)
    for assinatura, tipo in _ASSINATURAS.items():
        if cab.startswith(assinatura):
            return tipo
    low = cab.lstrip().lower()
    if low.startswith(b"<!doctype html") or low.startswith(b"<html"):
        return "html"
    return "desconhecido"


def parece_tela_do_portal(caminho: Path) -> bool:
    with open(caminho, "rb") as f:
        inicio = f.read(64 * 1024)
    return any(m in inicio for m in _MARCAS_TELA)


def validar_historico(caminho: Path, tipos_aceitos: set[str], tamanho_minimo: int) -> str:
    if not caminho.exists() or caminho.stat().st_size == 0:
        raise HistoricoInvalido("histórico vazio ou ausente")
    if caminho.stat().st_size < tamanho_minimo:
        raise HistoricoInvalido(f"histórico menor que o mínimo ({caminho.stat().st_size} B)")
    if parece_tela_do_portal(caminho):
        raise HistoricoInvalido("arquivo contém tela de login/erro do portal")
    tipo = tipo_tecnico(caminho)
    if tipos_aceitos and tipo not in tipos_aceitos:
        raise HistoricoInvalido(f"tipo técnico '{tipo}' não aceito para histórico")
    return tipo


def validar_anexo(caminho: Path, tamanho_esperado: Optional[int]) -> str:
    if not caminho.exists():
        raise DivergenciaInventario("arquivo baixado não encontrado no staging")
    tam = caminho.stat().st_size
    if tam == 0 and tamanho_esperado not in (0, None):
        raise DivergenciaInventario("arquivo vazio")
    if tamanho_esperado is not None and tam != tamanho_esperado:
        raise DivergenciaInventario(f"tamanho {tam} difere do inventário {tamanho_esperado}")
    tipo = tipo_tecnico(caminho)
    if tipo == "html" and parece_tela_do_portal(caminho):
        raise DivergenciaInventario("download retornou tela de login/erro do portal")
    return tipo


import re as _re
_GUID = _re.compile(rb"[0-9A-Fa-f]{8}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{4}-[0-9A-Fa-f]{12}")


def impressao_pdf(caminho: Path) -> Optional[str]:
    """Impressão digital do CONTEÚDO de um PDF: SHA-256 dos streams FlateDecode descomprimidos, com GUIDs neutralizados.
    Evidência 26/11: o mesmo histórico gerado duas vezes difere só no /ID do trailer e num bloco de metadados;
    as páginas são idênticas. Sem isso, cada execução criaria uma 'versão nova' falsa (CA-07)."""
    import hashlib
    import re
    import zlib
    dados = caminho.read_bytes()
    if not dados.startswith(b"%PDF"):
        return None
    h = hashlib.sha256()
    n = 0
    for m in re.finditer(rb"stream\r?\n", dados):
        inicio = m.end()
        fim = dados.find(b"endstream", inicio)
        dic = dados[max(0, m.start() - 300):m.start()]
        if fim < 0 or b"FlateDecode" not in dic:
            continue
        try:
            bruto = zlib.decompressobj().decompress(dados[inicio:fim])
            # validado 26/11: o gerador nomeia cada imagem com um GUID novo a cada impressão (/ppImage<GUID>)
            h.update(_GUID.sub(b"GUID", bruto))
            n += 1
        except zlib.error:
            continue
    return h.hexdigest() if n else None
