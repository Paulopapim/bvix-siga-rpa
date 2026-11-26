"""Contrato da origem (adaptador SIGA). Somente operações de LEITURA: não existe método que grave na origem
(CA-11). O adaptador real (Playwright) e o simulador implementam este Protocol.

Partes que dependem de descoberta estão marcadas em cada método.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterator, Protocol

from .models import AnexoRef, DetalheProcesso, Filtro, ListagemAnexos, PaginaListagem


class FonteSiga(Protocol):
    def autenticar(self) -> None:
        """Login. Levanta AutenticacaoIntervencao se houver MFA/captcha/troca de senha. [descoberto 26/11]"""

    def verificar_sessao(self) -> None:
        """Levanta SessaoExpirada/PermissaoNegada/OrigemIndisponivel."""

    def enumerar(self, filtro: Filtro) -> Iterator[PaginaListagem]:
        """Percorre a listagem aprovada com ordenação estável. [parcialmente descoberto: Localizar Sinistros]"""

    def abrir_processo(self, protocolo: str, id_interno: str | None = None) -> DetalheProcesso:
        """Abre o processo SEM entrar em modo de edição. [cadastro descoberto; não usar duplo clique]"""

    def exportar_historico(self, protocolo: str, pasta_staging: Path) -> Path:
        """'Imprimir histórico' até um arquivo completo no staging. [PENDENTE PD-06]"""

    def listar_anexos(self, protocolo: str) -> ListagemAnexos:
        """Inventário de todas as seções/páginas; completa=True só com fim de listagem comprovado. [PENDENTE PD-07]"""

    def baixar_anexo(self, protocolo: str, anexo: AnexoRef, pasta_staging: Path) -> Path:
        """Download individual até o arquivo completo no staging. [PENDENTE PD-07]"""

    def encerrar(self) -> None: ...

    # Opcional: def capturar_evidencia(self, nome: str) -> Optional[Path]  (print da tela no momento do erro)
