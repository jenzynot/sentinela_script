"""provision/vbox.py — envelope fino do VBoxManage via subprocess.

A execução é injetável: nos testes, um "executor" falso grava os comandos em
vez de rodá-los, então dá para validar a sequência inteira sem VirtualBox.
"""
import shutil
import subprocess
from typing import Callable

Executor = Callable[[list[str]], str]


class ErroVBox(RuntimeError):
    pass


def executar_de_verdade(comando: list[str]) -> str:
    r = subprocess.run(comando, capture_output=True, text=True)
    if r.returncode != 0:
        raise ErroVBox(f"{' '.join(comando[:3])}… falhou ({r.returncode}): "
                       f"{(r.stderr or r.stdout).strip()}")
    return r.stdout


class VBoxManage:
    def __init__(self, executar: Executor | None = None, binario: str = "VBoxManage"):
        self.binario = binario
        self.executar = executar or executar_de_verdade

    def __call__(self, *args) -> str:
        return self.executar([self.binario, *map(str, args)])

    @staticmethod
    def disponivel() -> bool:
        return shutil.which("VBoxManage") is not None
