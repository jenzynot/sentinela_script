"""Job 3 — Rede simulada + Sentinela ponta a ponta (planejamento_testes.md §2).

Cria "dispositivos falsos" com network namespaces + veth pendurados numa
bridge, sem hardware nenhum. Precisa de root (no CI: `sudo -E`).

CONTRATO DO AGENTE (Fase 5)
---------------------------
Os testes do agente ficam pulados até o pacote `sentinela/` existir, e
passam a valer sozinhos quando ele for criado. O que eles esperam:

    sentinela/scanner.py
        Scanner(interface: str)
            .descobrir(rede: str) -> list[obj com .ip, .mac]
            .portas(ip: str)      -> list[obj com .numero, .protocolo, .estado]
            Scanner.parse_nmap_xml(xml: str) -> dict[ip, list[porta]]   (staticmethod)

    sentinela/agente.py
        criar_sentinela(interface: str, rede: str) -> obj com
            .executar_ciclo() -> int   (id da TB_VARREDURAS criada)
        Lê as credenciais MYSQL_* do ambiente.

    Tipos gravados em TB_ALERTAS.tipo_alerta:
        "dispositivo_nao_autorizado", "porta_nova"

Se a Fase 5 decidir outra interface, ajuste este contrato junto.
"""
import os
import socket
import subprocess
import time

import pytest

from conftest import indisponivel, inserir_dispositivo, resetar_banco

pytestmark = pytest.mark.rede

BRIDGE = "brsentinela"
GATEWAY = "10.99.0.1"
REDE = "10.99.0.0/24"
# (namespace, veth do lado do host, MAC, IP) — MACs "locally administered"
DISPOSITIVOS = [
    ("sent-ns1", "vsent1", "02:5e:00:00:00:01", "10.99.0.11"),
    ("sent-ns2", "vsent2", "02:5e:00:00:00:02", "10.99.0.12"),
    ("sent-ns3", "vsent3", "02:5e:00:00:00:03", "10.99.0.13"),
]
NS1, NS2, NS3 = DISPOSITIVOS


def sh(*args, check=True):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()}")
    return r


def _destruir_rede():
    for ns, veth, _, _ in DISPOSITIVOS:
        sh("ip", "netns", "del", ns, check=False)
        sh("ip", "link", "del", veth, check=False)
    sh("ip", "link", "del", BRIDGE, check=False)


def _criar_rede():
    sh("ip", "link", "add", BRIDGE, "type", "bridge")
    sh("ip", "addr", "add", f"{GATEWAY}/24", "dev", BRIDGE)
    sh("ip", "link", "set", BRIDGE, "up")
    for ns, veth, mac, ip in DISPOSITIVOS:
        par = f"{veth}p"
        sh("ip", "netns", "add", ns)
        sh("ip", "link", "add", veth, "type", "veth", "peer", "name", par)
        sh("ip", "link", "set", par, "netns", ns)
        sh("ip", "link", "set", veth, "master", BRIDGE)
        sh("ip", "link", "set", veth, "up")
        em_ns = ("ip", "netns", "exec", ns)
        sh(*em_ns, "ip", "link", "set", par, "name", "eth0")
        sh(*em_ns, "ip", "link", "set", "eth0", "address", mac)
        sh(*em_ns, "ip", "addr", "add", f"{ip}/24", "dev", "eth0")
        sh(*em_ns, "ip", "link", "set", "eth0", "up")
        sh(*em_ns, "ip", "link", "set", "lo", "up")


def _esperar(condicao, segundos=10, descricao="condição"):
    limite = time.monotonic() + segundos
    while time.monotonic() < limite:
        if condicao():
            return
        time.sleep(0.2)
    raise TimeoutError(f"tempo esgotado esperando {descricao}")


@pytest.fixture(scope="module")
def rede_simulada():
    if os.geteuid() != 0:
        indisponivel("Job 3 precisa de root (rode com sudo -E)")
    _destruir_rede()   # sobra de uma execução interrompida
    _criar_rede()
    for _, _, _, ip in DISPOSITIVOS:
        _esperar(lambda ip=ip: sh("ping", "-c1", "-W1", ip, check=False).returncode == 0,
                 descricao=f"{ip} responder ping")
    yield
    _destruir_rede()


class Servico:
    """Um servidor TCP rodando dentro de um namespace (uma 'porta aberta')."""

    def __init__(self, dispositivo, porta: int):
        ns, _, _, ip = dispositivo
        self.ip, self.porta = ip, porta
        self.proc = subprocess.Popen(
            ["ip", "netns", "exec", ns, "python3", "-m", "http.server", str(porta),
             "--bind", ip],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _esperar(self._aberta, descricao=f"porta {porta} em {ip}")

    def _aberta(self):
        try:
            with socket.create_connection((self.ip, self.porta), timeout=0.5):
                return True
        except OSError:
            return False

    def parar(self):
        self.proc.terminate()
        self.proc.wait(timeout=5)


# --- Leitura de MAC (já existe: captive/portal.py) ---------------------------

@pytest.mark.parametrize("dispositivo", DISPOSITIVOS, ids=lambda d: d[0])
def test_mac_do_ip_le_o_mac_certo_da_tabela_arp(rede_simulada, dispositivo):
    """Dado   um dispositivo na bridge que já falou com o host
    Quando  chamo mac_do_ip() com o IP dele
    Então   recebo o MAC configurado no namespace"""
    from portal import mac_do_ip

    _, _, mac, ip = dispositivo
    sh("ping", "-c1", "-W1", ip)

    assert mac_do_ip(ip) == mac


def test_mac_do_ip_de_ip_desconhecido_e_none(rede_simulada):
    from portal import mac_do_ip

    assert mac_do_ip("10.99.0.250") is None


# --- Scanner (Fase 5) --------------------------------------------------------

NMAP_XML = """<?xml version="1.0" encoding="UTF-8"?>
<nmaprun scanner="nmap">
  <host>
    <status state="up"/>
    <address addr="10.99.0.11" addrtype="ipv4"/>
    <address addr="02:5E:00:00:00:01" addrtype="mac"/>
    <ports>
      <port protocol="tcp" portid="22"><state state="open"/><service name="ssh"/></port>
      <port protocol="tcp" portid="80"><state state="open"/><service name="http"/></port>
      <port protocol="tcp" portid="443"><state state="closed"/><service name="https"/></port>
    </ports>
  </host>
</nmaprun>
"""


def test_parser_do_nmap_extrai_as_portas_abertas():
    """Dado   um XML real de saída do nmap
    Quando  passo pelo parser
    Então   as portas abertas aparecem com número, protocolo e estado"""
    scanner = pytest.importorskip("sentinela.scanner", reason="agente ainda não existe (Fase 5)")

    resultado = scanner.Scanner.parse_nmap_xml(NMAP_XML)

    portas = {(p.numero, p.protocolo, p.estado) for p in resultado["10.99.0.11"]}
    assert {(22, "tcp", "open"), (80, "tcp", "open")} <= portas


def test_scanner_descobre_todos_os_dispositivos(rede_simulada):
    """Dado   3 namespaces na bridge
    Quando  o Scanner varre a rede
    Então   encontra os 3, cada um com IP e MAC corretos"""
    scanner = pytest.importorskip("sentinela.scanner", reason="agente ainda não existe (Fase 5)")

    achados = scanner.Scanner(BRIDGE).descobrir(REDE)

    pares = {(d.ip, d.mac.lower()) for d in achados}
    assert {(ip, mac) for _, _, mac, ip in DISPOSITIVOS} <= pares


def test_scanner_detecta_porta_aberta(rede_simulada):
    """Dado   um serviço escutando na porta 80 de um namespace
    Quando  o Scanner varre as portas desse IP
    Então   reporta 80/tcp aberta"""
    scanner = pytest.importorskip("sentinela.scanner", reason="agente ainda não existe (Fase 5)")
    servico = Servico(NS1, 80)
    try:
        portas = scanner.Scanner(BRIDGE).portas(NS1[3])
    finally:
        servico.parar()

    assert (80, "tcp", "open") in {(p.numero, p.protocolo, p.estado) for p in portas}


# --- Ciclos do agente + alertas (Fase 5) -------------------------------------

def _alertas(cx, id_varredura):
    cur = cx.cursor()
    cur.execute("""
        SELECT LOWER(d.endereco_mac), a.tipo_alerta
        FROM TB_ALERTAS a JOIN TB_DISPOSITIVOS d ON d.id_dispositivo = a.id_dispositivo
        WHERE a.id_varredura = %s
    """, (id_varredura,))
    return set(cur.fetchall())


@pytest.fixture(scope="module")
def dois_ciclos(rede_simulada):
    """ns1 e ns2 autorizados, ns3 não. Ciclo 1 sem portas abertas;
    entre os ciclos, ns1 abre a porta 80."""
    agente = pytest.importorskip("sentinela.agente", reason="agente ainda não existe (Fase 5)")
    cx = resetar_banco()
    inserir_dispositivo(cx, NS1[2], nome="ns1", autorizado=True)
    inserir_dispositivo(cx, NS2[2], nome="ns2", autorizado=True)

    sentinela = agente.criar_sentinela(BRIDGE, REDE)
    ciclo1 = sentinela.executar_ciclo()
    servico = Servico(NS1, 80)
    try:
        ciclo2 = sentinela.executar_ciclo()
    finally:
        servico.parar()

    yield cx, ciclo1, ciclo2
    cx.close()


def test_alerta_para_mac_fora_da_whitelist(dois_ciclos):
    """Dado   ns3 fora da whitelist
    Quando  o Sentinela roda um ciclo
    Então   TB_ALERTAS ganha 'dispositivo_nao_autorizado' para o MAC de ns3"""
    cx, ciclo1, _ = dois_ciclos

    assert (NS3[2], "dispositivo_nao_autorizado") in _alertas(cx, ciclo1)


def test_alerta_de_porta_nova_entre_ciclos(dois_ciclos):
    """Dado   ns1 sem portas no ciclo 1
    Quando  ns1 abre a porta 80 e roda o ciclo 2
    Então   o diff gera 'porta_nova' para ns1"""
    cx, _, ciclo2 = dois_ciclos

    assert (NS1[2], "porta_nova") in _alertas(cx, ciclo2)


def test_sem_falso_positivo_para_autorizado_sem_porta_nova(dois_ciclos):
    """Dado   ns2 autorizado e sem nenhuma porta aberta
    Quando  rodam os dois ciclos
    Então   nenhum alerta é gerado para ns2 (e ns1 não alerta no ciclo 1)"""
    cx, ciclo1, ciclo2 = dois_ciclos
    alertas1, alertas2 = _alertas(cx, ciclo1), _alertas(cx, ciclo2)

    assert not {a for a in alertas1 | alertas2 if a[0] == NS2[2]}
    assert not {a for a in alertas1 if a[0] == NS1[2]}


def test_ciclo_registra_presencas_e_portas(dois_ciclos):
    """O ciclo 2 grava as 3 presenças e a porta 80 de ns1 em TB_PORTAS."""
    cx, _, ciclo2 = dois_ciclos
    cur = cx.cursor()
    cur.execute("""
        SELECT LOWER(d.endereco_mac), p.endereco_ip
        FROM TB_PRESENCAS p JOIN TB_DISPOSITIVOS d ON d.id_dispositivo = p.id_dispositivo
        WHERE p.id_varredura = %s
    """, (ciclo2,))
    assert {(mac, ip) for _, _, mac, ip in DISPOSITIVOS} <= set(cur.fetchall())

    cur.execute("""
        SELECT po.numero_porta, po.protocolo
        FROM TB_PORTAS po
        JOIN TB_PRESENCAS p    ON p.id_presenca = po.id_presenca
        JOIN TB_DISPOSITIVOS d ON d.id_dispositivo = p.id_dispositivo
        WHERE p.id_varredura = %s AND LOWER(d.endereco_mac) = %s
    """, (ciclo2, NS1[2]))
    assert (80, "tcp") in set(cur.fetchall())
