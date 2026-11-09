"""sentinela/whitelist.py — quem pode estar na rede.

A whitelist é a coluna TB_DISPOSITIVOS.autorizado (gravada pelo portal).
Carregada uma vez por ciclo: um registro feito no meio do ciclo vale no próximo.
"""


class Whitelist:
    def __init__(self, repositorio):
        self._repo = repositorio
        self._macs: set[str] = set()

    def carregar(self) -> "Whitelist":
        self._macs = {m.lower() for m in self._repo.macs_autorizados()}
        return self

    def autorizado(self, mac: str) -> bool:
        return mac.lower() in self._macs

    def __len__(self) -> int:
        return len(self._macs)
