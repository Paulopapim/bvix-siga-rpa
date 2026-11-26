"""Taxonomia de exceções. Cada classe mapeia para um código de exceção do inventário (EX-xx do PDD)
e define se a falha é transitória (tentativas), permanente (tratamento humano) ou sistêmica (suspende a carga)."""

from __future__ import annotations


class RpaError(Exception):
    codigo = "ERRO"
    transitoria = False
    sistemica = False

    def __init__(self, motivo: str = ""):
        super().__init__(motivo or self.__class__.__name__)
        self.motivo = motivo or self.__class__.__name__


# --- Origem (SIGA) -------------------------------------------------------
class SessaoExpirada(RpaError):
    """EX-01. Sessão caiu: sistêmica (suspende), retomada exige novo login."""
    codigo = "EX-01-SESSAO"
    sistemica = True


class PermissaoNegada(RpaError):
    """EX-01. Acesso/permissão insuficiente: permanente, encaminhar ao responsável de acesso."""
    codigo = "EX-01-PERMISSAO"
    sistemica = True


class AutenticacaoIntervencao(RpaError):
    """EX-01. MFA, captcha ou troca de senha exigida: interromper e registrar pendência (PD-01)."""
    codigo = "EX-01-INTERVENCAO"
    sistemica = True


class OrigemIndisponivel(RpaError):
    """Portal fora do ar/timeout: transitória por item; sistêmica após limite consecutivo."""
    codigo = "ORIGEM-INDISPONIVEL"
    transitoria = True


class FalhaTransitoria(RpaError):
    codigo = "TRANSITORIA"
    transitoria = True


class EnumeracaoInconsistente(RpaError):
    """EX-02. Página repetida, fim prematuro, total divergente."""
    codigo = "EX-02"


class ProcessoTrocado(RpaError):
    """Tela aberta não corresponde ao protocolo da fila (troca de processo)."""
    codigo = "EX-03-TROCA"
    transitoria = True


class IdentificacaoInvalida(RpaError):
    """EX-03. Campo obrigatório ausente/ambíguo: segregar para tratamento."""
    codigo = "EX-03"


class ColisaoChave(RpaError):
    """EX-04. Dois protocolos geram a mesma pasta."""
    codigo = "EX-04"


class HistoricoInvalido(RpaError):
    """EX-05. Arquivo vazio, tela de login/erro no lugar do arquivo, geração parcial."""
    codigo = "EX-05"
    transitoria = True


class DownloadFalhou(RpaError):
    """EX-06."""
    codigo = "EX-06"
    transitoria = True


class ArquivoAusenteNaOrigem(RpaError):
    """Anexo listado no SIGA, mas o arquivo não existe no servidor da reguladora (evidência 26/11:
    'O sistema não pode encontrar o caminho especificado'). Permanente: não adianta tentar de novo."""
    codigo = "EX-06-SEM-ARQUIVO"


class ListagemIncompleta(RpaError):
    """EX-07/TB-06. Listagem de anexos inacessível ou não reconhecida como completa."""
    codigo = "EX-07-LISTAGEM"
    transitoria = True


class DivergenciaInventario(RpaError):
    """EX-07. Arquivo difere do inventário (tamanho/tipo)."""
    codigo = "EX-07"
    transitoria = True


# --- Destino --------------------------------------------------------------
class DestinoIndisponivel(RpaError):
    """EX-08. Repositório indisponível, sem espaço ou sem permissão: sistêmica."""
    codigo = "EX-08"
    sistemica = True


# --- Configuração ---------------------------------------------------------
class ConfiguracaoInvalida(RpaError):
    codigo = "CONFIG"
