"""provision/vm.py — Fase 2: VM Windows Server (servidor da casa) sem clique.

Uso (como o SEU usuário, não root — ele precisa estar no grupo vboxusers):
    .venv/bin/python -m provision.vm imagens      # lista as edições da ISO
    .venv/bin/python -m provision.vm tudo         # criar → instalar → aguardar → configurar → autorizar
    .venv/bin/python -m provision.vm status
    .venv/bin/python -m provision.vm criar|instalar|aguardar|configurar|autorizar|iniciar|parar
    .venv/bin/python -m provision.vm destruir --sim

Configuração no .env (VM_*). A VM entra na br0 pelo adaptador "bridged" com MAC
fixo: o dnsmasq dá sempre o mesmo IP (VM_IP) e o MAC vai para a whitelist.
"""
import argparse
import base64
import logging
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from sentinela.config import RAIZ, carregar_env

from .vbox import ErroVBox, VBoxManage

log = logging.getLogger("provision")

POWERSHELL = r"C:\Windows\System32\WindowsPowerShell\v1.0\powershell.exe"


@dataclass
class ConfigVM:
    nome: str
    iso: str
    ostype: str
    memoria_mb: int
    cpus: int
    disco_gb: int
    pasta: Path
    bridge: str
    mac: str            # aa:bb:cc:dd:ee:ff
    usuario: str
    senha: str
    indice_imagem: int
    hostname: str

    @property
    def mac_vbox(self) -> str:
        """O VBoxManage quer o MAC sem separadores: 0800275E0010."""
        return self.mac.replace(":", "").upper()

    @property
    def disco(self) -> Path:
        return self.pasta / self.nome / f"{self.nome}.vdi"

    @classmethod
    def do_ambiente(cls, env=os.environ) -> "ConfigVM":
        mac = env.get("VM_MAC", "08:00:27:5e:00:10").strip().lower()
        if not re.fullmatch(r"([0-9a-f]{2}:){5}[0-9a-f]{2}", mac):
            raise ValueError(f"VM_MAC inválido: {mac!r}")
        if int(mac[:2], 16) & 1:
            raise ValueError("VM_MAC precisa ser unicast (primeiro octeto par)")
        dominio = env.get("REDE_DOMINIO", "casa.lan")
        return cls(
            nome=env.get("VM_NOME", "servidor-casa"),
            iso=env.get("VM_ISO", ""),
            ostype=env.get("VM_OSTYPE", "Windows2019_64"),
            memoria_mb=int(env.get("VM_MEMORIA_MB", "4096")),
            cpus=int(env.get("VM_CPUS", "2")),
            disco_gb=int(env.get("VM_DISCO_GB", "60")),
            pasta=Path(env.get("VM_PASTA") or Path.home() / "VirtualBox VMs"),
            bridge=env.get("VM_BRIDGE", "br0"),
            mac=mac,
            usuario=env.get("VM_USUARIO", "casa"),
            senha=env.get("VM_SENHA", ""),
            indice_imagem=int(env.get("VM_INDICE_IMAGEM", "2")),
            hostname=env.get("VM_HOSTNAME", f"srv-casa.{dominio}"),
        )


def validar_senha_windows(senha: str, usuario: str) -> None:
    """Política padrão do Windows Server: 8+ caracteres, 3 de 4 categorias e
    sem o nome do usuário. Senha fraca faz a instalação desatendida travar
    sem aviso — melhor recusar antes."""
    if len(senha) < 8:
        raise ValueError("VM_SENHA precisa ter pelo menos 8 caracteres")
    categorias = sum(bool(re.search(p, senha)) for p in (r"[a-z]", r"[A-Z]", r"\d", r"[^\w]"))
    if categorias < 3:
        raise ValueError("VM_SENHA precisa de 3 destes: minúscula, maiúscula, dígito, símbolo")
    if usuario.lower() in senha.lower():
        raise ValueError("VM_SENHA não pode conter o nome do usuário")


def script_configuracao(hostname_curto: str) -> str:
    """PowerShell que roda DENTRO da VM: liga o RDP e publica o painel da casa."""
    return rf"""
$ErrorActionPreference = 'Stop'

# --- RDP (alvo da demo: celular -> RDP na VM) ---
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server' -Name fDenyTSConnections -Value 0
# NLA ligado: autentica antes de abrir a sessão gráfica
Set-ItemProperty 'HKLM:\System\CurrentControlSet\Control\Terminal Server\WinStations\RDP-Tcp' -Name UserAuthentication -Value 1
# Grupo de regras "Área de Trabalho Remota" pelo ID neutro (funciona em qualquer idioma)
Enable-NetFirewallRule -Group '@FirewallAPI.dll,-28752'

# --- Serviço da casa: IIS com o painel ---
Install-WindowsFeature -Name Web-Server -IncludeManagementTools | Out-Null
$html = @'
<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Painel da Casa</title>
<style>body{{font-family:system-ui,sans-serif;max-width:40rem;margin:2rem auto;padding:0 1rem}}
td{{padding:.3rem .8rem;border-bottom:1px solid #ddd}}</style></head>
<body><h1>Painel da Casa</h1>
<p>Servidor <b>{hostname_curto}</b> &mdash; Windows Server na rede protegida pelo Sentinela.</p>
<table><tr><td>Painel web</td><td>IIS, porta 80</td></tr>
<tr><td>Acesso remoto</td><td>RDP, porta 3389 (NLA)</td></tr></table>
<p><small>Substitua este arquivo (C:\inetpub\wwwroot\index.html) pelo servi&ccedil;o da casa escolhido.</small></p>
</body></html>
'@
Set-Content -Path 'C:\inetpub\wwwroot\index.html' -Value $html -Encoding UTF8

Write-Output 'sentinela: configuracao concluida (RDP + IIS)'
"""


def codificar_powershell(script: str) -> str:
    """-EncodedCommand: base64 de UTF-16LE. Evita o inferno de aspas na linha de comando."""
    return base64.b64encode(script.encode("utf-16-le")).decode("ascii")


@contextmanager
def arquivo_de_senha(senha: str):
    """Senha em arquivo 600 temporário: não aparece no `ps` de outros usuários."""
    fd, caminho = tempfile.mkstemp(prefix="sentinela-vm-")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(senha)
        os.chmod(caminho, 0o600)
        yield caminho
    finally:
        os.unlink(caminho)


class ProvisionadorVM:
    def __init__(self, cfg: ConfigVM, vbox: VBoxManage | None = None, dormir=time.sleep):
        self.cfg = cfg
        self.vbox = vbox or VBoxManage()
        self.dormir = dormir

    # --- consultas ---------------------------------------------------------
    def existe(self) -> bool:
        return f'"{self.cfg.nome}"' in self.vbox("list", "vms")

    def info(self) -> dict[str, str]:
        saida = self.vbox("showvminfo", self.cfg.nome, "--machinereadable")
        info = {}
        for linha in saida.splitlines():
            if "=" in linha:
                k, v = linha.split("=", 1)
                info[k.strip('"')] = v.strip('"')
        return info

    def propriedade(self, nome: str) -> str | None:
        saida = self.vbox("guestproperty", "get", self.cfg.nome, nome).strip()
        return saida.split("Value:", 1)[1].strip() if saida.startswith("Value:") else None

    # --- etapas ------------------------------------------------------------
    def criar(self) -> None:
        c = self.cfg
        if self.existe():
            log.info("VM '%s' já existe — pulando criação", c.nome)
            return
        self.vbox("createvm", "--name", c.nome, "--ostype", c.ostype,
                  "--basefolder", c.pasta, "--register")
        self.vbox("modifyvm", c.nome,
                  "--memory", c.memoria_mb, "--cpus", c.cpus, "--ioapic", "on",
                  "--vram", 128, "--graphicscontroller", "vboxsvga",
                  "--firmware", "bios", "--boot1", "dvd", "--boot2", "disk",
                  "--boot3", "none", "--boot4", "none",
                  # rede: adaptador em bridge na br0, MAC fixo (IP fixo + whitelist)
                  "--nic1", "bridged", "--bridgeadapter1", c.bridge,
                  "--nictype1", "82540EM", "--macaddress1", c.mac_vbox,
                  "--vrde", "off")
        self.vbox("createmedium", "disk", "--filename", c.disco,
                  "--size", c.disco_gb * 1024, "--format", "VDI")
        self.vbox("storagectl", c.nome, "--name", "SATA", "--add", "sata",
                  "--controller", "IntelAhci", "--portcount", 2)
        self.vbox("storageattach", c.nome, "--storagectl", "SATA", "--port", 0,
                  "--device", 0, "--type", "hdd", "--medium", c.disco)
        self.vbox("storageattach", c.nome, "--storagectl", "SATA", "--port", 1,
                  "--device", 0, "--type", "dvddrive", "--medium", "emptydrive")
        log.info("VM '%s' criada (bridge %s, MAC %s)", c.nome, c.bridge, c.mac)

    def instalar(self) -> None:
        c = self.cfg
        if not c.iso or not Path(c.iso).is_file():
            raise ValueError(f"VM_ISO não encontrada: {c.iso!r}")
        validar_senha_windows(c.senha, c.usuario)
        with arquivo_de_senha(c.senha) as senha_arq:
            self.vbox("unattended", "install", c.nome,
                      f"--iso={c.iso}", f"--user={c.usuario}",
                      f"--password-file={senha_arq}", f"--full-user-name={c.usuario}",
                      f"--hostname={c.hostname}", f"--image-index={c.indice_imagem}",
                      "--install-additions", "--start-vm=headless")
        log.info("instalação desatendida iniciada (headless) — leva de 20 a 60 min")

    def aguardar(self, timeout_s: int = 90 * 60, intervalo_s: int = 30,
                 confirmacoes: int = 3) -> None:
        """Espera os Guest Additions ficarem de pé de forma ESTÁVEL.

        A instalação reinicia o Windows algumas vezes; exigir várias leituras
        seguidas evita configurar a VM no meio de um reboot."""
        limite = time.monotonic() + timeout_s
        seguidas = 0
        while time.monotonic() < limite:
            nivel = self.propriedade("/VirtualBox/GuestAdd/RunLevel")
            seguidas = seguidas + 1 if nivel and nivel.isdigit() and int(nivel) >= 2 else 0
            if seguidas >= confirmacoes:
                log.info("Guest Additions ativos (RunLevel %s)", nivel)
                return
            self.dormir(intervalo_s)
        raise TimeoutError("a VM não ficou pronta a tempo — veja a tela com "
                           f"`VBoxManage startvm {self.cfg.nome} --type separate`")

    def configurar(self, tentativas: int = 5, pausa_s: int = 60) -> str:
        c = self.cfg
        script = codificar_powershell(script_configuracao(c.hostname.split(".")[0].upper()))
        with arquivo_de_senha(c.senha) as senha_arq:
            for tentativa in range(1, tentativas + 1):
                try:
                    saida = self.vbox(
                        "guestcontrol", c.nome, "run", f"--exe={POWERSHELL}",
                        f"--username={c.usuario}", f"--passwordfile={senha_arq}",
                        "--wait-stdout", "--wait-stderr", "--timeout=1800000",
                        "--", "powershell.exe", "-NoProfile", "-NonInteractive",
                        "-ExecutionPolicy", "Bypass", "-EncodedCommand", script)
                    log.info("VM configurada: RDP ligado e painel da casa publicado")
                    return saida
                except ErroVBox as e:
                    if tentativa == tentativas:
                        raise
                    log.warning("guestcontrol falhou (tentativa %d/%d): %s",
                                tentativa, tentativas, e)
                    self.dormir(pausa_s)
        raise AssertionError("inalcançável")

    def autorizar(self) -> None:
        """Servidor da casa entra na whitelist: banco (verdade) + firewall (espelho)."""
        sys.path.insert(0, str(RAIZ / "captive"))
        from dados import registrar_autorizado
        from firewall_ctl import liberar_mac
        registrar_autorizado(self.cfg.mac, "Servidor da casa (VM Windows)")
        liberar_mac(self.cfg.mac)
        log.info("MAC %s autorizado no banco e no firewall", self.cfg.mac)

    def iniciar(self) -> None:
        self.vbox("startvm", self.cfg.nome, "--type", "headless")

    def parar(self) -> None:
        self.vbox("controlvm", self.cfg.nome, "acpipowerbutton")

    def destruir(self) -> None:
        try:
            self.vbox("controlvm", self.cfg.nome, "poweroff")
        except ErroVBox:
            pass   # já estava desligada
        self.vbox("unregistervm", self.cfg.nome, "--delete")

    def status(self) -> str:
        if not self.existe():
            return f"VM '{self.cfg.nome}' não existe"
        estado = self.info().get("VMState", "?")
        ip = self.propriedade("/VirtualBox/GuestInfo/Net/0/V4/IP") or "—"
        return f"VM '{self.cfg.nome}': {estado} · IP {ip} · MAC {self.cfg.mac}"


def main(argv=None) -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    p = argparse.ArgumentParser(prog="python -m provision.vm", description="VM do servidor da casa")
    p.add_argument("acao", choices=["imagens", "criar", "instalar", "aguardar", "configurar",
                                    "autorizar", "tudo", "status", "iniciar", "parar", "destruir"])
    p.add_argument("--sim", action="store_true", help="confirma ações destrutivas")
    args = p.parse_args(argv)

    carregar_env()
    if os.geteuid() == 0:
        log.error("rode como seu usuário (grupo vboxusers), não como root: "
                  "as VMs do VirtualBox pertencem ao usuário que as cria")
        return 1
    try:
        cfg = ConfigVM.do_ambiente()
        vm = ProvisionadorVM(cfg)
        if args.acao == "imagens":
            print(vm.vbox("unattended", "detect", f"--iso={cfg.iso}", "--machine-readable"))
        elif args.acao == "tudo":
            vm.criar()
            vm.instalar()
            vm.aguardar()
            vm.configurar()
            try:
                vm.autorizar()
            except Exception as e:   # banco/firewall ainda não de pé não invalida a VM
                log.warning("VM pronta, mas não autorizada (%s). Depois da Fase 3 rode: "
                            "python -m provision.vm autorizar", e)
            print(vm.status())
        elif args.acao == "destruir" and not args.sim:
            log.error("isso apaga a VM e o disco. Repita com --sim para confirmar.")
            return 1
        elif args.acao == "status":
            print(vm.status())
        else:
            getattr(vm, args.acao)()
    except (ValueError, ErroVBox, TimeoutError) as e:
        log.error("%s", e)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
