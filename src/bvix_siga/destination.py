"""Destino de persistência (PD-02). Interface + implementação de sistema de arquivos (local ou UNC).

Garantias da publicação (passo 7):
- o arquivo é escrito como temporário no MESMO diretório do final e promovido sem sobrescrever;
- após a promoção, o hash do arquivo final é relido e comparado (confirmação da gravação);
- se o destino já tem o caminho com o MESMO hash, a publicação é idempotente (reconcilia queda
  entre gravação e atualização do estado); com hash DIFERENTE, nunca sobrescreve (EX-04/EX-10).

SharePoint: implementar `Destino` com upload via Microsoft Graph autorizado; fora desta versão (PD-02 aberto).
"""

from __future__ import annotations

import hashlib
import os
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Protocol

from .errors import DestinoIndisponivel, ColisaoChave

BLOCO = 1024 * 1024


def sha256_arquivo(caminho: Path) -> str:
    h = hashlib.sha256()
    with open(caminho, "rb") as f:
        for bloco in iter(lambda: f.read(BLOCO), b""):
            h.update(bloco)
    return h.hexdigest()


@dataclass(frozen=True)
class Publicado:
    caminho_relativo: str
    sha256: str
    tamanho: int
    reaproveitado: bool  # já existia com o mesmo hash


class Destino(Protocol):
    def verificar(self, espaco_minimo_bytes: int) -> None: ...
    def hash_existente(self, caminho_relativo: str) -> Optional[str]: ...
    def publicar(self, origem: Path, caminho_relativo: str, sha256_esperado: str) -> Publicado: ...


class DestinoArquivos:
    """Pasta local ou compartilhamento UNC (\\\\servidor\\share\\...)."""

    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def _abs(self, rel: str) -> Path:
        p = (self.raiz / rel).resolve()
        if self.raiz.resolve() not in p.parents and p != self.raiz.resolve():
            raise ColisaoChave(f"caminho fora da raiz do destino: {rel}")
        return p

    def verificar(self, espaco_minimo_bytes: int) -> None:
        try:
            self.raiz.mkdir(parents=True, exist_ok=True)
            teste = self.raiz / f".preflight-{uuid.uuid4().hex}"
            teste.write_bytes(b"ok")
            if teste.read_bytes() != b"ok":
                raise DestinoIndisponivel("leitura após escrita divergente")
            teste.unlink()
            livre = shutil.disk_usage(self.raiz).free
        except DestinoIndisponivel:
            raise
        except OSError as e:
            raise DestinoIndisponivel(f"destino sem acesso/permissão: {e}") from e
        if livre < espaco_minimo_bytes:
            raise DestinoIndisponivel(f"espaço livre {livre} < mínimo {espaco_minimo_bytes}")

    def hash_existente(self, caminho_relativo: str) -> Optional[str]:
        p = self._abs(caminho_relativo)
        return sha256_arquivo(p) if p.exists() else None

    def publicar(self, origem: Path, caminho_relativo: str, sha256_esperado: str) -> Publicado:
        final = self._abs(caminho_relativo)
        try:
            final.parent.mkdir(parents=True, exist_ok=True)
            if final.exists():
                atual = sha256_arquivo(final)
                if atual == sha256_esperado:
                    return Publicado(caminho_relativo, atual, final.stat().st_size, True)
                raise ColisaoChave(f"destino já contém arquivo diferente em {caminho_relativo}")
            tmp = final.parent / f".{final.name}.{uuid.uuid4().hex}.tmp"
            try:
                with open(origem, "rb") as src, open(tmp, "wb") as dst:
                    shutil.copyfileobj(src, dst, BLOCO)
                    dst.flush()
                    os.fsync(dst.fileno())
                try:
                    os.link(tmp, final)          # promoção atômica que falha se o alvo existir
                    tmp.unlink()
                except (OSError, NotImplementedError):
                    if final.exists():
                        raise ColisaoChave(f"concorrência na promoção de {caminho_relativo}")
                    os.replace(tmp, final)       # fallback (FS sem hard link); executor único
            finally:
                if tmp.exists():
                    tmp.unlink()
            confirmado = sha256_arquivo(final)
        except ColisaoChave:
            raise
        except OSError as e:
            raise DestinoIndisponivel(f"falha ao gravar {caminho_relativo}: {e}") from e
        if confirmado != sha256_esperado:
            raise DestinoIndisponivel(f"hash pós-gravação divergente em {caminho_relativo}")
        return Publicado(caminho_relativo, confirmado, final.stat().st_size, False)
