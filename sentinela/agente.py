"""sentinela/agente.py — o ciclo do Sentinela.

Loop de cada ciclo:
  1. varre a rede (arp-scan) e as portas de quem respondeu (nmap)
  2. abre uma varredura em TB_VARREDURAS
  3. para cada dispositivo: cadastra se o MAC for novo, grava a presença e as portas
  4. compara com a vez anterior em que o dispositivo foi visto:
       - MAC fora da whitelist que acabou de chegar  -> dispositivo_nao_autorizado
       - porta aberta que não estava aberta antes     -> porta_nova
  5. marca como inativo quem sumiu, fecha a varredura, commit
  6. só então notifica (e-mail), com os alertas já gravados
"""
import logging
import os
from datetime import datetime

from .alerta import NAO_AUTORIZADO, PORTA_NOVA, Alerta, nivel_porta_nova, notificadores_do_ambiente
from .config import carregar_env
from .repositorio import Repositorio
from .scanner import Scanner
from .whitelist import Whitelist

log = logging.getLogger("sentinela")


class Sentinela:
    def __init__(self, scanner: Scanner, rede: str, fabrica_repositorio=Repositorio,
                 notificadores=()):
        self.scanner = scanner
        self.rede = rede
        self.fabrica_repositorio = fabrica_repositorio
        self.notificadores = list(notificadores)

    def executar_ciclo(self) -> int:
        # Varredura primeiro, sem transação aberta (pode levar minutos).
        dispositivos = self.scanner.descobrir(self.rede)
        portas_por_ip = self.scanner.varrer_portas([d.ip for d in dispositivos])
        agora = datetime.now().replace(microsecond=0)

        repo = self.fabrica_repositorio()
        try:
            whitelist = Whitelist(repo).carregar()
            alerta = Alerta(repo, self.notificadores)
            id_varredura = repo.abrir_varredura(agora)
            anterior = repo.varredura_anterior(id_varredura)
            presentes_antes = repo.presentes_em(anterior) if anterior else set()

            presentes, total_portas = set(), 0
            for d in dispositivos:
                id_disp, novo = repo.registrar_visto(d.mac, agora)
                presentes.add(id_disp)
                abertas = [p for p in portas_por_ip.get(d.ip, []) if p.estado == "open"]
                id_pres = repo.registrar_presenca(id_varredura, id_disp, d.ip)
                repo.registrar_portas(id_pres, abertas)
                total_portas += len(abertas)

                # Fora da whitelist: alerta quando CHEGA (não a cada ciclo em que continua lá)
                if not whitelist.autorizado(d.mac) and id_disp not in presentes_antes:
                    detalhe = "nunca visto antes" if novo else "voltou à rede"
                    alerta.disparar(id_varredura, id_disp, NAO_AUTORIZADO,
                                    f"MAC {d.mac} ({d.ip}) fora da whitelist — {detalhe}",
                                    "alto", agora)

                antes = repo.portas_da_presenca_anterior(id_disp, id_varredura)
                if antes is not None:   # primeira aparição não tem base de comparação
                    for p in abertas:
                        if (p.numero, p.protocolo) not in antes:
                            alerta.disparar(
                                id_varredura, id_disp, PORTA_NOVA,
                                f"porta {p.numero}/{p.protocolo} ({p.servico or '?'}) "
                                f"abriu em {d.mac} ({d.ip})",
                                nivel_porta_nova(p.numero), agora)

            ausentes = repo.marcar_ausentes(presentes)
            resultado = "alerta" if alerta.emitidos else "ok"
            resumo = (f"{len(dispositivos)} dispositivo(s), {total_portas} porta(s) aberta(s), "
                      f"{len(alerta.emitidos)} alerta(s), {ausentes} saíram da rede; "
                      f"whitelist com {len(whitelist)} MAC(s)")
            repo.fechar_varredura(id_varredura, len(dispositivos), total_portas,
                                  len(alerta.emitidos), resultado, resumo)
            repo.commit()
        except Exception:
            repo.rollback()
            raise
        finally:
            repo.fechar()

        log.info("varredura %d: %s", id_varredura, resumo)
        alerta.notificar(id_varredura)
        return id_varredura


def criar_sentinela(interface: str, rede: str, faixa_portas: str | None = None) -> Sentinela:
    carregar_env()
    return Sentinela(
        scanner=Scanner(interface, faixa_portas or os.environ.get("SENTINELA_PORTAS") or None),
        rede=rede,
        notificadores=notificadores_do_ambiente(),
    )
