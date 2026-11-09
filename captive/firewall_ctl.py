"""captive/firewall_ctl.py — liberar/revogar MACs no conjunto nftables.

O processo que chama (portal, ressync) não roda como root: usa `sudo nft`,
liberado por uma entrada estreita no sudoers (menor privilégio).
"""
import json
import re
import subprocess

TABELA = ("inet", "portal")
CONJUNTO = "autorizados"
_MAC_RE = re.compile(r"^([0-9a-f]{2}:){5}[0-9a-f]{2}$")


def normalizar_mac(mac: str) -> str:
    """Valida e devolve o MAC em minúsculas.

    A validação impede que um texto qualquer vire sintaxe nftables
    (ex.: "aa:..:ff, bb:..:ff" liberaria dois MACs de uma vez).
    """
    mac = (mac or "").strip().lower()
    if not _MAC_RE.match(mac):
        raise ValueError(f"MAC inválido: {mac!r}")
    return mac


def _nft(*args: str, entrada: str | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(["sudo", "nft", *args], input=entrada,
                          capture_output=True, text=True)


def liberar_mac(mac: str) -> None:
    """Coloca o MAC no conjunto. `add` é idempotente: MAC já presente não dá erro."""
    mac = normalizar_mac(mac)
    r = _nft("add", "element", *TABELA, CONJUNTO, "{ " + mac + " }")
    if r.returncode != 0:
        raise RuntimeError(f"nft falhou ao liberar {mac}: {r.stderr.strip()}")


def revogar_mac(mac: str) -> None:
    """Tira o MAC do conjunto. Revogar um MAC ausente não é erro."""
    mac = normalizar_mac(mac)
    r = _nft("delete", "element", *TABELA, CONJUNTO, "{ " + mac + " }")
    if r.returncode != 0 and "No such file or directory" not in r.stderr:
        raise RuntimeError(f"nft falhou ao revogar {mac}: {r.stderr.strip()}")


def macs_autorizados() -> set[str]:
    """Conteúdo atual do conjunto, em minúsculas."""
    r = _nft("-j", "list", "set", *TABELA, CONJUNTO)
    if r.returncode != 0:
        raise RuntimeError(f"nft falhou ao listar o conjunto: {r.stderr.strip()}")
    for item in json.loads(r.stdout)["nftables"]:
        if "set" in item:
            return {str(e).lower() for e in item["set"].get("elem", [])}
    return set()


def sincronizar(macs) -> None:
    """Faz o conjunto ficar exatamente igual a `macs`, numa única transação.

    flush + add no mesmo `nft -f`: ou aplica tudo, ou nada.
    """
    macs = sorted({normalizar_mac(m) for m in macs})
    script = f"flush set {TABELA[0]} {TABELA[1]} {CONJUNTO}\n"
    if macs:
        script += (f"add element {TABELA[0]} {TABELA[1]} {CONJUNTO} "
                   "{ " + ", ".join(macs) + " }\n")
    r = _nft("-f", "-", entrada=script)
    if r.returncode != 0:
        raise RuntimeError(f"nft falhou ao sincronizar: {r.stderr.strip()}")
