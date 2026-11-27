"""Modelos de domínio e contratos de dados entre módulos."""

from __future__ import annotations

import enum
import hashlib
from dataclasses import dataclass, field
from typing import Optional


class EstadoItem(str, enum.Enum):
    DESCOBERTO = "descoberto"
    EM_ANDAMENTO = "em_andamento"
    CONFIRMADO = "confirmado"
    PENDENTE = "pendente"          # falha transitória esgotada ou dependência; elegível para retomada
    FALHO = "falho"                # falha permanente; exige tratamento


class EstadoProcesso(str, enum.Enum):
    DESCOBERTO = "descoberto"
    EM_ANDAMENTO = "em_andamento"
    COMPLETO = "completo"                          # histórico + todos os anexos confirmados, listagem completa
    COMPLETO_SEM_ANEXOS = "completo_sem_anexos"    # histórico confirmado + listagem verificadamente vazia (EX-09)
    PENDENTE = "pendente"
    TRATAMENTO = "tratamento"                      # identificação/colisão/permissão: humano decide
    NAO_ENCONTRADO = "nao_encontrado"              # protocolo da lista aprovada não existe na origem


ESTADOS_PROCESSO_FINAIS = {EstadoProcesso.COMPLETO, EstadoProcesso.COMPLETO_SEM_ANEXOS}


class TipoItem(str, enum.Enum):
    HISTORICO = "historico"
    ANEXO = "anexo"


@dataclass(frozen=True)
class Filtro:
    """Recorte aprovado (PD-05). Campos livres até a descoberta mostrar os filtros reais."""
    seguradora: str = "BVIX"
    periodo_inicio: Optional[str] = None
    periodo_fim: Optional[str] = None
    status: tuple[str, ...] = ()
    protocolos: tuple[str, ...] = ()  # piloto por lista

    def descricao(self) -> str:
        return (f"seguradora={self.seguradora};inicio={self.periodo_inicio};fim={self.periodo_fim};"
                f"status={','.join(self.status)};protocolos={len(self.protocolos)}")


@dataclass(frozen=True)
class RegistroListagem:
    """Linha da listagem "Localizar Sinistros" (evidência 26/11: idsin, numerosin, placa, cpfcnpj, tipoevento)."""
    protocolo: str                 # numerosin, formato AAAA-NNNNN
    id_interno: Optional[str] = None   # idsin
    placa: Optional[str] = None
    cpfcnpj: Optional[str] = None
    tipo_evento: Optional[str] = None


@dataclass
class PaginaListagem:
    numero: int
    registros: list[RegistroListagem]
    total_exibido: Optional[int] = None
    cursor: Optional[str] = None
    ultima: bool = False

    @property
    def protocolos(self) -> list[str]:
        return [r.protocolo for r in self.registros]


@dataclass
class DetalheProcesso:
    """Valores exibidos na tela do processo. Strings sempre (preserva zeros à esquerda e máscaras)."""
    protocolo: str
    id_interno: Optional[str] = None
    placa: Optional[str] = None
    evento: Optional[str] = None
    cpfcnpj: Optional[str] = None
    valores_originais: dict[str, str] = field(default_factory=dict)
    apolice: Optional[str] = None

    def campos(self) -> dict[str, Optional[str]]:
        return {"protocolo": self.protocolo, "id_interno": self.id_interno, "placa": self.placa,
                "evento": self.evento, "cpfcnpj": self.cpfcnpj, "apolice": self.apolice}


@dataclass(frozen=True)
class AnexoRef:
    """Anexo inventariado na origem. id_origem é usado quando o SIGA o expõe (PD-07)."""
    nome_original: str
    contexto: str                 # "processo" ou id/ordem da entrada do histórico
    ordinal: int                  # posição na listagem dentro do contexto
    id_origem: Optional[str] = None
    tamanho: Optional[int] = None
    data: Optional[str] = None
    rotulo: Optional[str] = None    # nome do tipo de anexo no SIGA (ex.: "Termo de Adesão"); não entra na identidade

    def chave(self, protocolo: str) -> str:
        """Identidade estável do item. Sem id de origem, usa mapeamento determinístico
        processo + contexto + ordinal + nome (+ tamanho/data se exibidos). Hash de bytes NÃO entra:
        bytes iguais em itens distintos continuam itens distintos."""
        if self.id_origem:
            base = f"{protocolo}|id|{self.id_origem}"
        else:
            base = f"{protocolo}|{self.contexto}|{self.ordinal}|{self.nome_original}|{self.tamanho}|{self.data}"
        return "A-" + hashlib.sha256(base.encode("utf-8")).hexdigest()[:24]


@dataclass
class ListagemAnexos:
    anexos: list[AnexoRef]
    completa: bool                # o adaptador só retorna True se percorreu todas as seções/páginas
    observacao: str = ""


def chave_historico(protocolo: str) -> str:
    return "H-" + hashlib.sha256(f"{protocolo}|historico".encode()).hexdigest()[:24]


# --- identidade do processo (evidência 26/11: o SIGA tem números repetidos e número "0") ---
import re as _re
_NUM_VALIDO = _re.compile(r"^\d{4}-\d+$")


def numero_valido(numero: Optional[str]) -> bool:
    return bool(numero and _NUM_VALIDO.match(numero))


def chave_processo(numero: Optional[str], id_interno: Optional[str], numero_repetido: bool) -> str:
    """Número normal e único -> o próprio número; repetido -> NÚMERO-ID<idsin>; inválido/'0' -> SEMNUMERO-<idsin>."""
    if not numero_valido(numero):
        return f"SEMNUMERO-{id_interno}"
    if numero_repetido:
        return f"{numero}-ID{id_interno}"
    return numero


def numero_da_chave(chave: str) -> Optional[str]:
    if chave.startswith("SEMNUMERO-"):
        return None
    return chave.split("-ID")[0] if "-ID" in chave else chave


def chave_composta(chave: str) -> bool:
    return chave.startswith("SEMNUMERO-") or "-ID" in chave
