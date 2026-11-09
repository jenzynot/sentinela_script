"""Unidade — Fase 5: parsers e regras do agente sem rede nem banco."""
from datetime import datetime

import pytest

from sentinela.agente import Sentinela
from sentinela.alerta import (NAO_AUTORIZADO, PORTA_NOVA, Alerta, nivel_porta_nova,
                              notificadores_do_ambiente)
from sentinela.scanner import Dispositivo, Porta, Scanner
from sentinela.whitelist import Whitelist

pytestmark = pytest.mark.unidade

ARP_SCAN = """\
Interface: br0, type: EN10MB, MAC: 02:aa:bb:cc:dd:ee, IPv4: 192.168.50.1
Starting arp-scan 1.10.0 with 256 hosts (https://github.com/royhills/arp-scan)
192.168.50.10\t08:00:27:5E:00:10\tPCS Systemtechnik GmbH
192.168.50.101\taa:bb:cc:00:11:22\t(Unknown: locally administered)
192.168.50.101\taa:bb:cc:00:11:22\t(Unknown: locally administered) (DUP: 2)

3 packets received by filter, 0 packets dropped by kernel
Ending arp-scan 1.10.0: 256 hosts scanned in 1.9 seconds (134.74 hosts/sec). 2 responded
"""


def test_parse_arp_scan_ignora_cabecalho_e_duplicatas():
    assert Scanner.parse_arp_scan(ARP_SCAN) == [
        Dispositivo("192.168.50.10", "08:00:27:5e:00:10"),
        Dispositivo("192.168.50.101", "aa:bb:cc:00:11:22"),
    ]


def test_parse_nmap_xml_com_varios_hosts_e_host_sem_portas():
    xml = """<?xml version="1.0"?><!DOCTYPE nmaprun><nmaprun>
      <host><address addr="192.168.50.10" addrtype="ipv4"/>
        <ports><port protocol="tcp" portid="3389"><state state="open"/>
          <service name="ms-wbt-server"/></port></ports></host>
      <host><address addr="192.168.50.101" addrtype="ipv4"/></host>
    </nmaprun>"""

    assert Scanner.parse_nmap_xml(xml) == {
        "192.168.50.10": [Porta(3389, "tcp", "open", "ms-wbt-server")],
        "192.168.50.101": [],
    }


def test_porta_sensivel_tem_risco_alto():
    assert nivel_porta_nova(3389) == "alto"
    assert nivel_porta_nova(23) == "alto"
    assert nivel_porta_nova(8080) == "medio"


def test_email_so_liga_com_smtp_e_destinatario():
    assert notificadores_do_ambiente({}) == []
    assert notificadores_do_ambiente({"SMTP_HOST": "smtp.x"}) == []
    [email] = notificadores_do_ambiente({"SMTP_HOST": "smtp.x", "ALERTA_EMAIL_PARA": "a@x, b@x"})
    assert email.destinatarios == ["a@x", "b@x"] and email.porta == 587


# --- dublês ------------------------------------------------------------------

class RepoFalso:
    """Banco em memória com a mesma interface do Repositorio."""

    def __init__(self, autorizados=()):
        self.autorizados = set(autorizados)
        self.dispositivos = {}          # mac -> id
        self.presencas = []             # (id_varr, id_disp, ip, portas)
        self.varreduras = []
        self.alertas = []
        self.commits = self.rollbacks = 0
        self.fechado = False

    def macs_autorizados(self): return set(self.autorizados)
    def abrir_varredura(self, quando):
        self.varreduras.append(quando)
        return len(self.varreduras)
    def varredura_anterior(self, id_v): return id_v - 1 if id_v > 1 else None
    def presentes_em(self, id_v): return {p[1] for p in self.presencas if p[0] == id_v}
    def registrar_visto(self, mac, quando):
        novo = mac not in self.dispositivos
        self.dispositivos.setdefault(mac, len(self.dispositivos) + 1)
        return self.dispositivos[mac], novo
    def registrar_presenca(self, id_v, id_d, ip):
        self.presencas.append([id_v, id_d, ip, []])
        return len(self.presencas)
    def registrar_portas(self, id_p, portas):
        self.presencas[id_p - 1][3] = [(p.numero, p.protocolo) for p in portas]
    def portas_da_presenca_anterior(self, id_d, id_v):
        anteriores = [p for p in self.presencas if p[1] == id_d and p[0] < id_v]
        return set(anteriores[-1][3]) if anteriores else None
    def registrar_alerta(self, id_v, id_d, tipo, descricao, nivel, quando):
        self.alertas.append((id_v, id_d, tipo, nivel))
        return len(self.alertas)
    def marcar_ausentes(self, presentes): return 0
    def fechar_varredura(self, *a): pass
    def commit(self): self.commits += 1
    def rollback(self): self.rollbacks += 1
    def fechar(self): self.fechado = True


class ScannerFalso:
    def __init__(self):
        self.rede = {}       # ip -> (mac, [portas abertas])

    def descobrir(self, rede):
        return [Dispositivo(ip, mac) for ip, (mac, _) in self.rede.items()]

    def varrer_portas(self, ips):
        return {ip: [Porta(n, "tcp", "open") for n in self.rede[ip][1]] for ip in ips}


AUTORIZADO, INTRUSO = "02:00:00:00:00:01", "02:00:00:00:00:66"


@pytest.fixture
def cenario():
    repo, scanner = RepoFalso(autorizados={AUTORIZADO}), ScannerFalso()
    sentinela = Sentinela(scanner, "192.168.50.0/24", fabrica_repositorio=lambda: repo)
    return repo, scanner, sentinela


def tipos(repo, id_v):
    return [(a[1], a[2]) for a in repo.alertas if a[0] == id_v]


def test_intruso_alerta_so_quando_chega_e_de_novo_quando_volta(cenario):
    repo, scanner, sentinela = cenario
    scanner.rede = {"192.168.50.2": (AUTORIZADO, []), "192.168.50.66": (INTRUSO, [])}

    c1 = sentinela.executar_ciclo()      # chegou -> alerta
    c2 = sentinela.executar_ciclo()      # continua lá -> sem alerta repetido
    del scanner.rede["192.168.50.66"]
    sentinela.executar_ciclo()           # saiu
    scanner.rede["192.168.50.66"] = (INTRUSO, [])
    c4 = sentinela.executar_ciclo()      # voltou -> alerta de novo

    id_intruso = repo.dispositivos[INTRUSO]
    assert tipos(repo, c1) == [(id_intruso, NAO_AUTORIZADO)]
    assert tipos(repo, c2) == []
    assert tipos(repo, c4) == [(id_intruso, NAO_AUTORIZADO)]


def test_porta_nova_compara_com_a_ultima_vez_que_o_dispositivo_foi_visto(cenario):
    repo, scanner, sentinela = cenario
    scanner.rede = {"192.168.50.2": (AUTORIZADO, [80])}

    c1 = sentinela.executar_ciclo()      # primeira aparição: sem base, sem alerta
    c2 = sentinela.executar_ciclo()      # mesma porta: nada
    scanner.rede["192.168.50.2"] = (AUTORIZADO, [80, 3389])
    c3 = sentinela.executar_ciclo()      # 3389 nova -> alerta alto

    assert tipos(repo, c1) == [] and tipos(repo, c2) == []
    assert [(a[2], a[3]) for a in repo.alertas if a[0] == c3] == [(PORTA_NOVA, "alto")]


def test_falha_no_meio_do_ciclo_desfaz_tudo(cenario):
    repo, scanner, sentinela = cenario
    scanner.rede = {"192.168.50.2": (AUTORIZADO, [])}
    repo.registrar_presenca = lambda *a: (_ for _ in ()).throw(RuntimeError("banco caiu"))

    with pytest.raises(RuntimeError):
        sentinela.executar_ciclo()

    assert repo.rollbacks == 1 and repo.commits == 0 and repo.fechado


def test_notificacao_sai_uma_vez_por_ciclo_e_falha_nao_derruba():
    enviados = []

    def quebrado(assunto, corpo):
        raise OSError("smtp fora do ar")

    alerta = Alerta(RepoFalso(), notificadores=[quebrado, lambda a, c: enviados.append((a, c))])
    agora = datetime.now()
    alerta.disparar(7, 1, NAO_AUTORIZADO, "intruso A", "alto", agora)
    alerta.disparar(7, 2, PORTA_NOVA, "porta 23 em B", "alto", agora)

    alerta.notificar(7)

    assert len(enviados) == 1
    assert "2 alerta(s)" in enviados[0][0]
    assert "intruso A" in enviados[0][1] and "porta 23 em B" in enviados[0][1]


def test_whitelist_ignora_maiusculas():
    wl = Whitelist(RepoFalso(autorizados={"AA:BB:CC:00:11:22"})).carregar()

    assert wl.autorizado("aa:bb:cc:00:11:22") and len(wl) == 1
