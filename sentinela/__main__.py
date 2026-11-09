"""python -m sentinela — roda o agente em loop (é o que o sentinela-agente.service chama).

    sudo .venv/bin/python -m sentinela                 # loop, intervalo do .env
    sudo .venv/bin/python -m sentinela --uma-vez       # um ciclo só (bom pra demo)
"""
import argparse
import logging
import os
import signal
import sys
import threading

from .agente import criar_sentinela
from .config import carregar_env

log = logging.getLogger("sentinela")


def configurar_log(arquivo: str | None) -> None:
    handlers = [logging.StreamHandler(sys.stderr)]          # journald no systemd
    if arquivo:
        try:
            os.makedirs(os.path.dirname(arquivo), exist_ok=True)
            handlers.append(logging.FileHandler(arquivo))    # evidência para o relatório
        except OSError as e:
            print(f"aviso: sem log em arquivo ({e})", file=sys.stderr)
    logging.basicConfig(level=logging.INFO, handlers=handlers,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")


def main(argv=None) -> int:
    carregar_env()
    p = argparse.ArgumentParser(prog="python -m sentinela", description="Agente Sentinela")
    p.add_argument("--interface", default=os.environ.get("SENTINELA_INTERFACE", "br0"))
    p.add_argument("--rede", default=os.environ.get("REDE_SEGMENTO", "192.168.50.0/24"))
    p.add_argument("--intervalo", type=int, default=int(os.environ.get("SENTINELA_INTERVALO", "60")))
    p.add_argument("--uma-vez", action="store_true", help="roda um ciclo e sai")
    p.add_argument("--log", default=os.environ.get("SENTINELA_LOG", "/var/log/sentinela/sentinela.log"))
    args = p.parse_args(argv)

    configurar_log(args.log)
    if os.geteuid() != 0:
        log.error("o agente precisa de root (arp-scan e nmap usam pacotes crus)")
        return 1

    sentinela = criar_sentinela(args.interface, args.rede)
    parar = threading.Event()
    signal.signal(signal.SIGTERM, lambda *_: parar.set())
    log.info("Sentinela vigiando %s em %s (a cada %ds)", args.rede, args.interface, args.intervalo)

    while not parar.is_set():
        try:
            sentinela.executar_ciclo()
        except Exception:
            log.exception("ciclo falhou — tentando de novo no próximo intervalo")
            if args.uma_vez:
                return 1
        if args.uma_vez:
            return 0
        parar.wait(args.intervalo)
    log.info("Sentinela encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())
