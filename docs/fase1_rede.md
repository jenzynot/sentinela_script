# Fase 1 — Rede controlada

O host Mint vira o gateway da casa: uma bridge `br0` com IP fixo, a placa Wi-Fi em modo AP pendurada nela, `dnsmasq` entregando DHCP/DNS e `nftables` fazendo NAT para a internet do host.

```
 celular ──Wi-Fi──┐
                  ├── br0 (192.168.50.1) ── host Mint ── NAT ── uplink (cabo/USB) ── internet
 VM Windows ──────┘        dnsmasq: DHCP .100–.200 + DNS
```

## Pré-requisitos

1. `sudo ./setup_host.sh` já rodou e o teste de **modo AP** passou.
2. **A internet do host não pode vir da mesma placa Wi-Fi do AP.** A placa do AP sai do NetworkManager. Use cabo, USB tethering do celular ou um segundo adaptador Wi-Fi para o uplink.
3. Descubra o nome da placa Wi-Fi:
   ```bash
   iw dev            # procure "Interface wlp2s0" (o nome muda de máquina pra máquina)
   ```

## Instalação

```bash
cp .env.example .env
nano .env                    # WIFI_IF, WIFI_SSID, WIFI_SENHA, MYSQL_PASSWORD, PORTAL_SENHA
sudo ./instalar.sh rede
sudo ./instalar.sh verificar
```

O `instalar.sh rede`:

| Passo | Resultado |
|---|---|
| `network/gerar_configs.py` | `/etc/sentinela/hostapd.conf` (600), `dnsmasq.conf`, drop-in do NetworkManager |
| `sentinela-bridge.service` | `br0` com `192.168.50.1/24`, `ip_forward=1`, rádio desbloqueado |
| `sentinela-firewall.service` | `captive/firewall.nft`: NAT (masquerade), whitelist vazia, redirect HTTP → portal |
| `sentinela-ap.service` | `hostapd` com `bridge=br0` |
| `sentinela-dhcp.service` | `dnsmasq` ouvindo **só** na `br0` (sem conflito com o `systemd-resolved`) |

Tudo fica agrupado em `sentinela.target` e sobe sozinho no boot.

## Critério de pronto

> O celular conecta no SSID e pega IP.

```bash
journalctl -fu sentinela-dhcp     # deve aparecer DHCPACK(br0) 192.168.50.1xx <mac> <nome>
journalctl -fu sentinela-ap       # AP-STA-CONNECTED <mac>
```

Até a Fase 1.5 o celular **conecta mas não navega**: a whitelist começa vazia e o `forward` do firewall tem `policy drop`. Isso é esperado.

## MAC do celular de teste

Android e iOS usam por padrão um MAC **aleatório mas estável por rede**. Isso funciona com a whitelist. O que quebra é a rotação periódica. No celular de teste:

- **Android:** Wi-Fi → (engrenagem da rede *Sentinela*) → Privacidade → **Usar MAC do dispositivo** (ou "MAC aleatório" sem rotação).
- **iOS:** Ajustes → Wi-Fi → (i) da rede → **Endereço Wi-Fi privado: Fixo** (iOS 18+) ou desligado.

Anote o MAC que aparece no `journalctl -u sentinela-dhcp`: é ele que vai para a whitelist.

## Problemas comuns

| Sintoma | Causa provável / correção |
|---|---|
| `sentinela-ap` falha com `nl80211: Could not configure driver mode` | O NetworkManager ainda segura a placa. `nmcli device status` deve mostrar `unmanaged`. Rode `sudo systemctl reload NetworkManager` e reinicie o serviço. |
| `rfkill` / `Operation not possible due to RF-kill` | `rfkill list` → `sudo rfkill unblock wlan`. |
| SSID não aparece | Canal não permitido pelo país: troque `WIFI_CANAL` (1, 6 ou 11) e confira `WIFI_PAIS=BR`. |
| Conecta mas não pega IP | `journalctl -u sentinela-dhcp`. Confira se a `br0` tem IP: `./network/rede.sh status`. |
| Host perdeu a internet | O uplink era a própria placa do AP. Veja o pré-requisito 2. |
| `dnsmasq: failed to create listening socket ... Address already in use` | Outro `dnsmasq` rodando (`systemctl status dnsmasq`). O `setup_host.sh` desabilita o da distro. |

## Para desfazer

```bash
sudo systemctl disable --now sentinela.target sentinela-ap sentinela-dhcp sentinela-firewall sentinela-bridge
sudo rm /etc/NetworkManager/conf.d/90-sentinela.conf && sudo systemctl reload NetworkManager
```
