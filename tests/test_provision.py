"""Unidade — Fase 2: provisionamento da VM sem VirtualBox (VBoxManage falso)."""
import base64
from pathlib import Path

import pytest

from provision.vbox import ErroVBox, VBoxManage
from provision.vm import (ConfigVM, ProvisionadorVM, codificar_powershell,
                          script_configuracao, validar_senha_windows)

pytestmark = pytest.mark.unidade


class VBoxFalso:
    """Grava os comandos e responde como o VBoxManage responderia."""

    def __init__(self, vms="", runlevels=(), falhas_guestcontrol=0):
        self.comandos = []
        self.vms = vms
        self.runlevels = list(runlevels)
        self.falhas_guestcontrol = falhas_guestcontrol

    def __call__(self, comando):
        self.comandos.append(comando)
        sub = comando[1]
        if sub == "list":
            return self.vms
        if sub == "guestproperty":
            valor = self.runlevels.pop(0) if self.runlevels else None
            return f"Value: {valor}\n" if valor is not None else "No value set!\n"
        if sub == "guestcontrol" and self.falhas_guestcontrol:
            self.falhas_guestcontrol -= 1
            raise ErroVBox("VERR_TIMEOUT")
        return ""

    def subcomandos(self):
        return [c[1] for c in self.comandos]

    def achar(self, sub):
        return next(c for c in self.comandos if c[1] == sub)


ENV = {
    "VM_NOME": "servidor-casa", "VM_ISO": "", "VM_MAC": "08:00:27:5E:00:10",
    "VM_USUARIO": "casa", "VM_SENHA": "Senha-Forte-2026", "VM_PASTA": "/tmp/vms",
}


@pytest.fixture
def cfg(tmp_path):
    iso = tmp_path / "server.iso"
    iso.write_bytes(b"iso")
    return ConfigVM.do_ambiente({**ENV, "VM_ISO": str(iso)})


def provisionador(cfg, **kw):
    falso = VBoxFalso(**kw)
    return ProvisionadorVM(cfg, VBoxManage(executar=falso), dormir=lambda s: None), falso


def test_criar_monta_a_vm_na_br0_com_mac_fixo(cfg):
    """Dado   nenhuma VM registrada
    Quando  rodo criar
    Então   a sequência é createvm → modifyvm → createmedium → storagectl → storageattach,
            com o adaptador 1 em bridge na br0 e o MAC fixo"""
    vm, falso = provisionador(cfg)

    vm.criar()

    assert falso.subcomandos() == ["list", "createvm", "modifyvm", "createmedium",
                                   "storagectl", "storageattach", "storageattach"]
    modify = falso.achar("modifyvm")
    assert modify[modify.index("--nic1") + 1] == "bridged"
    assert modify[modify.index("--bridgeadapter1") + 1] == "br0"
    assert modify[modify.index("--macaddress1") + 1] == "0800275E0010"
    assert falso.achar("createmedium")[-3:] == ["61440", "--format", "VDI"]


def test_criar_e_idempotente(cfg):
    vm, falso = provisionador(cfg, vms='"servidor-casa" {1234-abcd}\n')

    vm.criar()

    assert falso.subcomandos() == ["list"]


def test_instalar_usa_unattended_sem_senha_na_linha_de_comando(cfg):
    vm, falso = provisionador(cfg)

    vm.instalar()

    cmd = falso.achar("unattended")
    assert cmd[:4] == ["VBoxManage", "unattended", "install", "servidor-casa"]
    assert f"--iso={cfg.iso}" in cmd
    assert "--image-index=2" in cmd and "--install-additions" in cmd
    assert "--start-vm=headless" in cmd
    assert any(a.startswith("--password-file=") for a in cmd)
    assert not any(cfg.senha in a for a in cmd)
    # o arquivo temporário com a senha é apagado depois
    arq = next(a for a in cmd if a.startswith("--password-file=")).split("=", 1)[1]
    assert not Path(arq).exists()


def test_instalar_recusa_iso_inexistente(cfg):
    cfg.iso = "/nao/existe.iso"
    vm, _ = provisionador(cfg)

    with pytest.raises(ValueError, match="VM_ISO"):
        vm.instalar()


@pytest.mark.parametrize("senha, trecho", [
    ("Curta1!", "8 caracteres"),
    ("somenteminusculas", "3 destes"),
    ("Casa-Senha-2026", "nome do usuário"),
])
def test_senha_fraca_e_recusada_antes_de_instalar(senha, trecho):
    with pytest.raises(ValueError, match=trecho):
        validar_senha_windows(senha, "casa")


def test_aguardar_exige_leituras_estaveis(cfg):
    """Um RunLevel 3 isolado (no meio de um reboot) não basta: precisa de 3 seguidas."""
    vm, falso = provisionador(cfg, runlevels=[None, "3", None, "3", "3", "3"])

    vm.aguardar(confirmacoes=3)

    assert falso.subcomandos().count("guestproperty") == 6


def test_aguardar_estoura_o_tempo(cfg):
    vm, _ = provisionador(cfg)

    with pytest.raises(TimeoutError):
        vm.aguardar(timeout_s=0)


def test_configurar_roda_powershell_codificado_e_tenta_de_novo(cfg):
    vm, falso = provisionador(cfg, falhas_guestcontrol=2)

    vm.configurar(tentativas=5)

    chamadas = [c for c in falso.comandos if c[1] == "guestcontrol"]
    assert len(chamadas) == 3
    cmd = chamadas[-1]
    assert "--username=casa" in cmd and not any(cfg.senha in a for a in cmd)
    script = base64.b64decode(cmd[cmd.index("-EncodedCommand") + 1]).decode("utf-16-le")
    assert "fDenyTSConnections -Value 0" in script
    assert "Install-WindowsFeature -Name Web-Server" in script


def test_script_de_configuracao_liga_rdp_com_nla_e_publica_painel():
    script = script_configuracao("SRV-CASA")

    assert "UserAuthentication -Value 1" in script                 # NLA
    assert "@FirewallAPI.dll,-28752" in script                    # regra RDP neutra de idioma
    assert "SRV-CASA" in script and "Painel da Casa" in script
    assert base64.b64decode(codificar_powershell("ok")).decode("utf-16-le") == "ok"


@pytest.mark.parametrize("mac", ["nao-e-mac", "09:00:27:00:00:01"])
def test_mac_invalido_ou_multicast_e_recusado(mac):
    with pytest.raises(ValueError, match="VM_MAC"):
        ConfigVM.do_ambiente({**ENV, "VM_MAC": mac})


def test_destruir_tolera_vm_ja_desligada(cfg):
    class Desligada(VBoxFalso):
        def __call__(self, comando):
            if comando[1] == "controlvm":
                self.comandos.append(comando)
                raise ErroVBox("not running")
            return super().__call__(comando)

    falso = Desligada()
    ProvisionadorVM(cfg, VBoxManage(executar=falso)).destruir()

    assert falso.subcomandos() == ["controlvm", "unregistervm"]
