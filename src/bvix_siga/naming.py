"""Nomes locais seguros e determinísticos (passo 6 do prompt; EX-04; PD-03/PD-13).

Regras:
- nunca converte identificadores para número (preserva zeros à esquerda);
- remove caracteres inválidos em Windows/SMB/SharePoint e nomes reservados;
- limita o comprimento do componente preservando a extensão de origem;
- homônimos no mesmo contexto ficam distintos pelo ordinal da listagem (determinístico entre execuções).
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Mapping, Optional

from .errors import IdentificacaoInvalida

_INVALIDOS = re.compile(r'[<>:"/\\|?*\x00-\x1f#%]')
_RESERVADOS = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}
MAX_COMPONENTE = 120


def limpar_componente(valor: str, max_len: int = MAX_COMPONENTE) -> str:
    v = unicodedata.normalize("NFC", str(valor)).strip()
    v = _INVALIDOS.sub("_", v)
    v = re.sub(r"\s+", " ", v).strip(" .")
    if not v:
        v = "_"
    if v.split(".")[0].upper() in _RESERVADOS:
        v = "_" + v
    if len(v) > max_len:
        h = hashlib.sha256(v.encode()).hexdigest()[:8]
        v = v[: max_len - 9] + "~" + h
    return v


_EXT_COLADA = re.compile(r"^(.*?)[_.\s]*_(jpe?g|png|gif|bmp|tiff?|pdf|docx?|xlsx?|mp4|mov|avi|heic|webp|txt|zip)$", re.I)


def corrigir_extensao(nome: str, tipo_tecnico: Optional[str] = None) -> str:
    """Evidência 26/11: há arquivos no SIGA como 'CNH SEG__jpg' (sem ponto). Converte para 'CNH SEG.jpg';
    se ainda faltar extensão, usa o tipo técnico detectado (jpg, png, pdf…)."""
    base, ext = separar_extensao(nome)
    if ext:
        return nome
    m = _EXT_COLADA.match(nome.strip())
    if m:
        return f"{m.group(1).rstrip(' ._')}.{m.group(2).lower()}"
    if tipo_tecnico and tipo_tecnico not in ("desconhecido", "html", "ole", "zip"):
        return f"{nome}.{tipo_tecnico}"
    return nome


def separar_extensao(nome: str) -> tuple[str, str]:
    m = re.match(r"^(.*?)(\.[A-Za-z0-9]{1,8})?$", nome.strip())
    base, ext = (m.group(1), m.group(2) or "") if m else (nome, "")
    return base or "_", ext


def nome_anexo(nome_original: str, ordinal: int, contexto: str, versao: int = 1) -> str:
    """Ex.: 'e03__h0002__Laudo pericial.pdf'. Ordinal e contexto garantem unicidade; extensão preservada."""
    base, ext = separar_extensao(nome_original)
    ctx = "p" if contexto == "processo" else "h" + limpar_componente(contexto, 20)
    sufixo = f"__v{versao}" if versao > 1 else ""
    reserva = len(ext) + len(sufixo) + 20
    base_ok = limpar_componente(base, MAX_COMPONENTE - reserva)
    ext_ok = "." + limpar_componente(ext[1:], 8) if ext else ""
    return f"{ordinal:03d}__{ctx}__{base_ok}{sufixo}{ext_ok}"


def nome_historico(extensao: str, versao: int) -> str:
    ext = extensao if extensao.startswith(".") else "." + extensao
    return f"historico__v{versao}{ext}"


def pasta_processo(padrao: str, campos: Mapping[str, Optional[str]], obrigatorios: list[str]) -> str:
    """Forma a pasta do processo pelo padrão aprovado (PD-03). Campo obrigatório ausente => EX-03.
    Nunca substitui silenciosamente um campo por outro."""
    faltando = [c for c in obrigatorios if not (campos.get(c) or "").strip()]
    if faltando:
        raise IdentificacaoInvalida(f"campos obrigatórios ausentes: {', '.join(faltando)}")
    valores = {k: limpar_componente(v, 60) if v else "SEM-" + k.upper() for k, v in campos.items()}
    try:
        bruto = padrao.format(**valores)
    except KeyError as e:
        raise IdentificacaoInvalida(f"padrão de pasta usa campo desconhecido: {e}") from e
    partes = [limpar_componente(p) for p in re.split(r"[\\/]", bruto) if p.strip()]
    return "/".join(partes)


def mascarar(valor: Optional[str], visiveis: int = 3) -> str:
    """Para logs gerais/evidências: mantém só o final."""
    if not valor:
        return ""
    v = str(valor)
    return "*" * max(0, len(v) - visiveis) + v[-visiveis:]


# --- layout "unica": todos os arquivos numa pasta só, identificados pelo prefixo (placa_número) ---
def nome_historico_unico(prefixo: str, extensao: str, versao: int) -> str:
    ext = extensao if extensao.startswith(".") else "." + extensao
    sufixo = f"_v{versao}" if versao > 1 else ""
    return f"{limpar_componente(prefixo, 60)}_HISTORICO{sufixo}{ext}"


def nome_anexo_unico(prefixo: str, rotulo: Optional[str], ordinal: int, nome_original: str, versao: int = 1) -> str:
    """Ex.: 'ABC1D23_2026-10422_Termo de Adesao_001_XYZ9K88.pdf'. Rótulo do tipo + ordinal garantem unicidade."""
    import unicodedata as _u
    base, ext = separar_extensao(nome_original)
    rot = _u.normalize("NFKD", rotulo or "Anexo").encode("ascii", "ignore").decode() or "Anexo"
    rot = limpar_componente(rot.replace("/", "-"), 40)
    sufixo = f"_v{versao}" if versao > 1 else ""
    ext_ok = "." + limpar_componente(ext[1:], 8) if ext else ""
    reserva = len(prefixo) + len(rot) + len(ext_ok) + len(sufixo) + 8
    return f"{limpar_componente(prefixo, 60)}_{rot}_{ordinal:03d}_{limpar_componente(base, max(20, MAX_COMPONENTE - reserva))}{sufixo}{ext_ok}"
