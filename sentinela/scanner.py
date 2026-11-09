"""sentinela/scanner.py — quem está na rede (arp-scan) e que portas abriu (nmap)."""
import os
import re
import subprocess
import xml.etree.ElementTree as ET
from dataclasses import dataclass


@dataclass(frozen=True)
class Dispositivo:
    ip: str
    mac: str


@dataclass(frozen=True)
class Porta:
    numero: int
    protocolo: str
    estado: str
    servico: str = ""


_LINHA_ARP = re.compile(
    r"^(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5})\b")


class ErroScanner(RuntimeError):
    pass


class Scanner:
    """Descobre dispositivos por ARP (enxerga até quem bloqueia ping) e varre
    as portas com o nmap. Precisa de root para os pacotes crus."""

    def __init__(self, interface: str, faixa_portas: str | None = None, timeout_s: int = 600):
        self.interface = interface
        self.faixa_portas = faixa_portas      # ex.: "1-1024,3389"; None = top 1000 do nmap
        self.timeout_s = timeout_s

    def _rodar(self, comando: list[str]) -> str:
        try:
            r = subprocess.run(comando, capture_output=True, text=True, timeout=self.timeout_s)
        except FileNotFoundError as e:
            raise ErroScanner(f"{comando[0]} não instalado") from e
        except subprocess.TimeoutExpired as e:
            raise ErroScanner(f"{comando[0]} passou de {self.timeout_s}s") from e
        if r.returncode != 0:
            raise ErroScanner(f"{comando[0]} falhou ({r.returncode}): {r.stderr.strip()}")
        return r.stdout

    # --- descoberta --------------------------------------------------------
    def descobrir(self, rede: str) -> list[Dispositivo]:
        saida = self._rodar(["arp-scan", f"--interface={self.interface}",
                             "--retry=3", "--quiet", rede])
        return self.parse_arp_scan(saida)

    @staticmethod
    def parse_arp_scan(saida: str) -> list[Dispositivo]:
        """Uma linha por resposta: 'IP<tab>MAC[<tab>fabricante]'.
        Cabeçalho/rodapé são ignorados; respostas duplicadas (DUP) também."""
        vistos: dict[str, Dispositivo] = {}
        for linha in saida.splitlines():
            m = _LINHA_ARP.match(linha.strip())
            if m and m.group(1) not in vistos:
                vistos[m.group(1)] = Dispositivo(m.group(1), m.group(2).lower())
        return list(vistos.values())

    # --- portas ------------------------------------------------------------
    def varrer_portas(self, ips: list[str]) -> dict[str, list[Porta]]:
        """Uma chamada do nmap para todos os IPs (bem mais rápido que um por um)."""
        if not ips:
            return {}
        tipo = "-sS" if os.geteuid() == 0 else "-sT"    # SYN scan precisa de root
        portas = ["-p", self.faixa_portas] if self.faixa_portas else ["--top-ports", "1000"]
        comando = ["nmap", tipo, "-Pn", "-n", "-T4", "--open", *portas, "-oX", "-", *ips]
        return self.parse_nmap_xml(self._rodar(comando))

    def portas(self, ip: str) -> list[Porta]:
        return self.varrer_portas([ip]).get(ip, [])

    @staticmethod
    def parse_nmap_xml(xml: str) -> dict[str, list[Porta]]:
        resultado: dict[str, list[Porta]] = {}
        raiz = ET.fromstring(xml)
        for host in raiz.findall("host"):
            ip = next((a.get("addr") for a in host.findall("address")
                       if a.get("addrtype") == "ipv4"), None)
            if not ip:
                continue
            portas = []
            for p in host.findall("ports/port"):
                estado = p.find("state")
                servico = p.find("service")
                portas.append(Porta(
                    numero=int(p.get("portid")),
                    protocolo=p.get("protocol"),
                    estado=estado.get("state") if estado is not None else "unknown",
                    servico=servico.get("name", "") if servico is not None else "",
                ))
            resultado[ip] = portas
        return resultado
