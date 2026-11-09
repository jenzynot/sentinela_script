"""sentinela/config.py — leitura do .env (só biblioteca padrão).

Usado pelo agente, pelo provisionamento da VM e pelo gerador de configs de
rede. Os serviços systemd recebem as variáveis por `EnvironmentFile=`; este
módulo serve para quem roda os scripts à mão.
"""
import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
ARQUIVOS_ENV = (Path("/etc/sentinela/sentinela.env"), RAIZ / ".env")


def ler_env(arquivo) -> dict[str, str]:
    """Lê um arquivo KEY=VALUE. Linhas vazias e comentários (#) são ignorados;
    aspas em volta do valor são removidas."""
    valores = {}
    for linha in Path(arquivo).read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        valor = valor.strip()
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        valores[chave.strip()] = valor
    return valores


def carregar_env(arquivos=ARQUIVOS_ENV) -> None:
    """Carrega os arquivos em os.environ sem sobrescrever o que já existe.

    O primeiro arquivo legível ganha (o de /etc tem prioridade sobre o do repo).
    """
    for arquivo in arquivos:
        try:
            valores = ler_env(arquivo)
        except OSError:
            continue
        for chave, valor in valores.items():
            os.environ.setdefault(chave, valor)


def mysql_params() -> dict:
    return {
        "host": os.environ.get("MYSQL_HOST", "127.0.0.1"),
        "port": int(os.environ.get("MYSQL_PORT", "3306")),
        "user": os.environ.get("MYSQL_USER", "sentinela"),
        "password": os.environ.get("MYSQL_PASSWORD", ""),
        "database": os.environ.get("MYSQL_DATABASE", "vigia_de_rede"),
    }
