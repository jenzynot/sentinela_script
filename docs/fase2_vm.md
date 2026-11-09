# Fase 2 — VM Windows Server automatizada

A VM é o **servidor da casa**: hospeda o painel (IIS) e expõe o RDP. Para a rede ela é só mais um dispositivo da `br0`: pega IP do `dnsmasq`, obedece ao firewall do host e é varrida pelo Sentinela.

```
host Mint ── VirtualBox ── VM "servidor-casa"
                │            adaptador 1: bridged → br0, MAC 08:00:27:5e:00:10
                │            dnsmasq: sempre 192.168.50.10 (dhcp-host)
                └─ provision/vm.py envelopa o VBoxManage via subprocess
```

## Pré-requisitos

- Fase 1 de pé (`br0` existe: `./network/rede.sh status`).
- Seu usuário no grupo `vboxusers` (o `setup_host.sh` faz isso; precisa de logout/login).
- ISO de **avaliação** do Windows Server 2019 ou 2022 (180 dias, gratuita) no Microsoft Evaluation Center.
- Bloco `VM_*` do `.env` preenchido. Para 2022: `VM_OSTYPE=Windows2022_64`.
- ~60 GB livres na partição das VMs e 4 GB de RAM sobrando.

## Uso

Rode como **seu usuário**, não root (as VMs do VirtualBox pertencem a quem as cria):

```bash
.venv/bin/python -m provision.vm imagens    # confirme o índice da edição "Desktop Experience"
.venv/bin/python -m provision.vm tudo       # 20 a 60 minutos, sem nenhum clique
.venv/bin/python -m provision.vm status
```

`tudo` executa, em ordem:

| Etapa | VBoxManage | O que garante |
|---|---|---|
| `criar` | `createvm` → `modifyvm` → `createmedium` → `storagectl` → `storageattach` | VM registrada, NIC em bridge na `br0` com MAC fixo. Idempotente: se já existe, pula. |
| `instalar` | `unattended install … --install-additions --start-vm=headless` | Windows instalado sem clique. A senha vai por arquivo temporário 600, nunca na linha de comando. |
| `aguardar` | `guestproperty get … /VirtualBox/GuestAdd/RunLevel` | Espera 3 leituras seguidas com os Guest Additions ativos (não cai no meio de um reboot). |
| `configurar` | `guestcontrol run powershell -EncodedCommand …` | RDP ligado com NLA + regra do firewall do Windows; IIS com o "Painel da Casa". Tenta de novo se a VM ainda estiver ocupada. |
| `autorizar` | — (banco + `nft`) | MAC da VM em `TB_DISPOSITIVOS` (autorizado) e no conjunto do firewall. Precisa da Fase 3; se o banco não estiver pronto, o `tudo` avisa e segue. |

Outras ações: `iniciar`, `parar` (desligamento ACPI), `destruir --sim`.

Para acompanhar a instalação visualmente: `VBoxManage startvm servidor-casa --type separate` (abre a tela de uma VM que já está rodando headless).

## Critério de pronto

> RDP do celular na VM funciona, sem roteador da faculdade.

1. Celular na rede *Sentinela* (registrado no portal).
2. App **Microsoft Remote Desktop** (Android/iOS) → PC `192.168.50.10` → usuário `VM_USUARIO` / `VM_SENHA`.
3. No navegador do celular: `http://192.168.50.10` mostra o Painel da Casa.

## Problemas comuns

| Sintoma | Causa / correção |
|---|---|
| `VERR_INTNET_FLT_IF_NOT_FOUND` ao iniciar | A `br0` não existe: `sudo systemctl start sentinela-bridge`. |
| `aguardar` estoura o tempo | Abra a tela (`--type separate`). Em geral: índice de imagem errado (`imagens`) ou senha recusada pela política. |
| RDP não conecta mas o ping responde | `configurar` não rodou até o fim: rode `python -m provision.vm configurar` de novo. |
| VM sem internet | MAC fora da whitelist: `python -m provision.vm autorizar`. |
| Instalação lenta | Normal com 2 vCPUs; não interrompa. |
