"""captive/ressync.py — repovoa o conjunto nftables a partir do banco.

Ordem no boot (systemd After=): firewall.nft → ressync.py → portal.py.
Banco é a fonte da verdade; o conjunto nftables é um espelho reconstruível.
"""
from dados import macs_autorizados
from firewall_ctl import sincronizar


def main() -> int:
    macs = macs_autorizados()
    sincronizar(macs)
    print(f"ressync: {len(macs)} MAC(s) autorizados aplicados ao firewall.")
    return len(macs)


if __name__ == "__main__":
    main()
