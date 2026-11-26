"""Configuração (TOML) + segredos por variável de ambiente/cofre. Segredos nunca vêm do arquivo."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

from .errors import ConfiguracaoInvalida
from .models import Filtro


@dataclass
class PoliticaTentativas:
    max_tentativas: int = 3
    espera_inicial_s: float = 2.0
    fator: float = 2.0
    espera_max_s: float = 60.0
    falhas_consecutivas_para_suspender: int = 5   # origem indisponível em série => sistêmica

    def espera(self, tentativa: int) -> float:
        return min(self.espera_max_s, self.espera_inicial_s * (self.fator ** max(0, tentativa - 1)))


@dataclass
class Config:
    url: str
    destino_tipo: str
    destino_raiz: Path
    staging: Path
    banco: Path
    logs: Path
    relatorios: Path
    timezone: str
    filtro: Filtro
    pasta_padrao: str
    pasta_campos_obrigatorios: list[str]
    historico_tipos_aceitos: set[str]
    historico_tamanho_minimo: int
    espaco_minimo_bytes: int
    limite_processos: Optional[int]
    corte: Optional[str]
    tentativas: PoliticaTentativas
    pasta_layout: str = "por_processo"
    modo_visivel: bool = True
    timeout_navegacao_ms: int = 30000
    timeout_download_ms: int = 120000
    segredo_usuario_env: str = "SIGA_USERNAME"
    segredo_senha_env: str = "SIGA_PASSWORD"
    extras: dict = field(default_factory=dict)

    def credenciais(self) -> tuple[str, str]:
        u, s = os.environ.get(self.segredo_usuario_env), os.environ.get(self.segredo_senha_env)
        if not u or not s:
            raise ConfiguracaoInvalida(
                f"credenciais ausentes: defina {self.segredo_usuario_env}/{self.segredo_senha_env} pelo cofre/executor")
        return u, s


def carregar(caminho: str | Path) -> Config:
    p = Path(caminho)
    if not p.exists():
        raise ConfiguracaoInvalida(f"arquivo de configuração não encontrado: {p}")
    with open(p, "rb") as f:
        c = tomllib.load(f)
    # caminhos relativos partem da raiz do projeto quando o arquivo está em config/
    base = p.parent.parent if p.parent.name.lower() == "config" else p.parent

    def caminho_rel(v: str) -> Path:
        q = Path(v)
        return q if q.is_absolute() or str(v).startswith("\\\\") else (base / q)

    try:
        origem, destino, exec_, pasta = c["origem"], c["destino"], c["execucao"], c["pasta"]
    except KeyError as e:
        raise ConfiguracaoInvalida(f"seção obrigatória ausente: {e}") from e

    # ---- pastas configuráveis sem mexer no código (servidor novo) -------------------------------------------
    # 1) config/pasta_saida.txt (ou env SIGA_PASTA_SAIDA): pasta-base de TUDO (arquivos, banco, relatórios, logs,
    #    prints, staging). Ex.: D:\SIGA_BVIX
    # 2) config/pasta_destino.txt (ou env SIGA_PASTA_DESTINO): opcional, só para os ARQUIVOS baixados
    #    (ex.: \\servidor\share\Sinistros). Banco e staging continuam na pasta de saída (disco local).
    def _ler_pasta(env: str, arquivo: str) -> Optional[str]:
        v = os.environ.get(env, "").strip()
        if not v:
            f = p.parent / arquivo
            if f.exists():
                linhas = [x.strip().strip('"') for x in f.read_text(encoding="utf-8-sig").splitlines()]
                v = next((x for x in linhas if x and not x.startswith("#")), "")
        return v or None

    pasta_saida = _ler_pasta("SIGA_PASTA_SAIDA", "pasta_saida.txt")
    pasta_destino = _ler_pasta("SIGA_PASTA_DESTINO", "pasta_destino.txt")
    if pasta_saida:
        b = Path(pasta_saida)
        exec_ = {**exec_, "staging": str(b / "staging"), "banco": str(b / "estado.sqlite"),
                 "logs": str(b / "logs"), "relatorios": str(b / "relatorios")}
        destino = {**destino, "raiz": str(b / "destino")}
    if pasta_destino:
        destino = {**destino, "raiz": pasta_destino}

    url = origem.get("url", "")
    u = urlparse(url)
    if u.scheme != "https" or not u.netloc:
        raise ConfiguracaoInvalida("origem.url deve ser https")
    if destino.get("tipo") not in {"arquivos", "sharepoint"}:
        raise ConfiguracaoInvalida("destino.tipo deve ser 'arquivos' (local/UNC) ou 'sharepoint'")
    if destino["tipo"] == "sharepoint":
        raise ConfiguracaoInvalida("destino SharePoint ainda não implementado (PD-02 em aberto)")

    rec = c.get("recorte", {})
    filtro = Filtro(seguradora=rec.get("seguradora", "BVIX"), periodo_inicio=rec.get("periodo_inicio"),
                    periodo_fim=rec.get("periodo_fim"), status=tuple(rec.get("status", [])),
                    protocolos=tuple(str(x) for x in rec.get("protocolos", [])))
    t = c.get("tentativas", {})
    cfg = Config(
        url=url,
        destino_tipo=destino["tipo"],
        destino_raiz=caminho_rel(destino["raiz"]),
        staging=caminho_rel(exec_.get("staging", "./var/staging")),
        banco=caminho_rel(exec_.get("banco", "./var/estado.sqlite")),
        logs=caminho_rel(exec_.get("logs", "./var/logs")),
        relatorios=caminho_rel(exec_.get("relatorios", "./var/relatorios")),
        timezone=exec_.get("timezone", "America/Sao_Paulo"),
        filtro=filtro,
        pasta_padrao=pasta["padrao"],
        pasta_campos_obrigatorios=list(pasta.get("campos_obrigatorios", [])),
        historico_tipos_aceitos=set(c.get("historico", {}).get("tipos_aceitos", ["pdf"])),
        historico_tamanho_minimo=int(c.get("historico", {}).get("tamanho_minimo_bytes", 200)),
        espaco_minimo_bytes=int(destino.get("espaco_minimo_gb", 5) * 1024 ** 3),
        limite_processos=exec_.get("limite_processos"),
        corte=exec_.get("corte"),
        tentativas=PoliticaTentativas(**t),
        pasta_layout=pasta.get("layout", "por_processo"),
        modo_visivel=bool(origem.get("modo_visivel", True)),
        timeout_navegacao_ms=int(origem.get("timeout_navegacao_ms", 30000)),
        timeout_download_ms=int(origem.get("timeout_download_ms", 120000)),
        segredo_usuario_env=origem.get("segredo_usuario_env", "SIGA_USERNAME"),
        segredo_senha_env=origem.get("segredo_senha_env", "SIGA_PASSWORD"),
    )
    if cfg.pasta_layout not in {"por_processo", "unica", "por_placa"}:
        raise ConfiguracaoInvalida("pasta.layout deve ser 'por_processo', 'unica' ou 'por_placa'")
    if staging_dentro_destino(cfg):
        raise ConfiguracaoInvalida("staging não pode ficar dentro da raiz do destino")
    return cfg


def staging_dentro_destino(cfg: Config) -> bool:
    try:
        cfg.staging.resolve().relative_to(cfg.destino_raiz.resolve())
        return True
    except ValueError:
        return False
