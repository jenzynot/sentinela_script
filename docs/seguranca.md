# Fase 6 — Segurança e hardening

```bash
sudo ./instalar.sh seguranca   # firewall endurecido + backup diário + primeiro backup
sudo ./instalar.sh vpn         # opcional: servidor WireGuard
```

## 1. Firewall (`captive/firewall.nft`), regra por regra

Uma tabela só (`inet portal`), carregada no boot pelo `sentinela-firewall.service`. Recarregar não duplica regras.

### `input` — o que pode falar **com o host** (`policy drop`)

| Regra | Por quê |
|---|---|
| `iif lo accept` | processos locais (MySQL em 127.0.0.1, etc.) |
| `ct state established,related accept` | respostas do que o próprio host iniciou |
| `ct state invalid drop` | pacotes sem conexão válida (varreduras malformadas) |
| ICMP / ICMPv6 | ping, *path MTU discovery* e descoberta de vizinhos do IPv6 |
| `udp dport { 68, 546 }` | respostas de DHCP para o próprio host no uplink |
| `br0`: `udp 53, 67` / `tcp 53, 8080` | o segmento só enxerga DNS, DHCP e o portal |
| `udp dport 51820` | WireGuard |
| `iifname "wg0" accept` | quem está na VPN é tratado como "de casa" |
| *(resto)* | **cai** — MySQL, SSH e qualquer serviço do host ficam inacessíveis de fora |

### `forward` — o que pode **atravessar** o host (`policy drop`)

| Regra | Por quê |
|---|---|
| `ct state established,related accept` | respostas voltam sem reavaliar a whitelist |
| `ether saddr @autorizados accept` | **a whitelist**: só MAC registrado sai para a internet |
| `iifname "wg0" oifname "br0" accept` | da VPN para a rede da casa (RDP na VM de fora) |

### NAT

| Regra | Por quê |
|---|---|
| `prerouting`: HTTP de MAC fora da whitelist → `:8080` | dispara o portal cativo |
| `postrouting`: `iifname "br0" oifname != { br0, wg0 } masquerade` | só o tráfego do segmento para a internet é mascarado |

## 2. Contas, senhas e privilégios

| Item | Medida |
|---|---|
| Portal e ressync | usuário de sistema `sentinela` (sem shell, sem home); sudoers libera **só** `/usr/sbin/nft` |
| Agente | root, por necessidade (pacotes crus do `arp-scan`/`nmap -sS`) |
| MySQL | `root` só pelo socket (sem senha para vazar); `sentinela` só com DML em `vigia_de_rede`; nada ouve fora do `127.0.0.1` |
| Segredos | só no `.env` (fora do Git) → `/etc/sentinela/sentinela.env` (640 root:sentinela); `hostapd.conf` 600; chaves WireGuard 600 |
| Senhas mínimas | MySQL 12+, Wi-Fi WPA2 8–63, VM pela política do Windows — os scripts recusam senhas fracas ou as de exemplo |
| RDP | NLA ligado (autentica antes de abrir a sessão) |

## 3. DNS seguro

- O `dnsmasq` ignora o DNS da rede de onde o host pega internet (`no-resolv`) e usa resolvedores escolhidos: **Quad9** (bloqueia domínios maliciosos conhecidos) e **Cloudflare** (`DNS_UPSTREAM`).
- `domain-needed` + `bogus-priv`: nomes sem domínio e consultas reversas de IPs privados não saem para a internet.
- Melhoria futura: DNS sobre TLS (ex.: `stubby` entre o `dnsmasq` e a internet).

## 4. VPN de acesso remoto (WireGuard)

```bash
sudo ./instalar.sh vpn
sudo /opt/sentinela/security/wireguard.sh peer celular     # mostra um QR code
```

- App **WireGuard** no celular → *Ler QR code*. Com o túnel ligado (fora da rede de casa): RDP em `192.168.50.10`.
- **Túnel dividido:** só a rede da casa passa pela VPN; o resto do tráfego do celular segue normal.
- Chave pré-compartilhada por peer (camada extra de proteção).
- Precisa de `VPN_ENDPOINT` (IP público/DDNS) e de encaminhamento de `51820/udp` no roteador de onde o host está. **Em rede de faculdade isso costuma ser bloqueado** — para a demo, dá para usar o próprio celular como uplink e mostrar a VPN pela rede 4G de outro aparelho, ou apresentar a configuração e o `wg show`.

## 5. Backup e restore

- `security/backup.sh`: `mysqldump --single-transaction` (consistente sem travar o agente), compactado, conferido com `gzip -t` antes de valer, permissão 600, retenção de 7 dias.
- Cron: todo dia às 02:00 → `/var/log/sentinela_backup.log` (histórico = evidência).
- `security/restore.sh`: confere o arquivo, pede confirmação (`SIM`) e **tira um backup do estado atual antes de sobrescrever**.
- **O CI ensaia o incidente a cada push** (Job 1): backup → banco muda → restore → banco volta exatamente ao estado do backup.

Ensaio manual antes da apresentação:

```bash
sudo /opt/sentinela/security/backup.sh
sudo mysql vigia_de_rede -e "DELETE FROM TB_ALERTAS"          # "incidente"
sudo /opt/sentinela/security/restore.sh /var/backups/sentinela/<o arquivo acima>
sudo mysql vigia_de_rede -e "SELECT COUNT(*) FROM TB_ALERTAS"  # voltou
sudo systemctl restart sentinela-ressync                        # firewall espelha o banco de novo
```

## 6. Testes de invasão com Kali/Parrot (na própria rede)

A VM atacante entra na `br0` como **convidada**, não como infraestrutura:

```bash
# imagem pronta para VirtualBox (kali.org/get-kali → Virtual Machines)
VBoxManage import kali-linux-*-virtualbox-amd64.ova --vsys 0 --vmname kali
VBoxManage modifyvm kali --nic1 bridged --bridgeadapter1 br0
VBoxManage startvm kali
```

Roteiro (cada resultado vira evidência no relatório). Tudo contra a **própria** rede do projeto:

| Teste | Comando (na Kali) | Esperado |
|---|---|---|
| Kali não registrada aparece | — (só conectar) | Sentinela: `dispositivo_nao_autorizado` |
| Sem registro, sem internet | `curl -m5 https://example.com` | falha (forward em drop) |
| Superfície do host | `nmap -sS -p- 192.168.50.1` | só 53, 67/udp e 8080 |
| Superfície da VM | `nmap -sV 192.168.50.10` | 80 (IIS) e 3389 (RDP) |
| Segurança do RDP | `nmap --script rdp-enum-encryption -p 3389 192.168.50.10` | NLA (CredSSP) exigido |
| Servidor web | `nikto -h http://192.168.50.10` | achados para o relatório |
| **Clonagem de MAC** | `sudo macchanger -m <MAC do celular registrado> eth0` | **fura a whitelist** — vulnerabilidade conhecida (abaixo) |

## 7. Vulnerabilidades conhecidas (documentadas de propósito)

| Vulnerabilidade | Impacto | Mitigação possível |
|---|---|---|
| **Clonagem de MAC** | quem copia o MAC de um aparelho registrado passa pela whitelist | 802.1X/WPA2-Enterprise (identidade por usuário, não por MAC); o Sentinela ao menos registra o mesmo MAC aparecendo com IPs diferentes |
| **Senha compartilhada do portal** | quem sabe a senha registra quantos aparelhos quiser | senha por pessoa/convite com validade |
| **Tráfego dentro da `br0` não passa pela whitelist** | a tabela `inet` filtra o que é *roteado* (para a internet/VPN); um aparelho não registrado ainda alcança a VM pela camada 2 (ex.: RDP direto) | tabela `bridge` no nftables filtrando por MAC entre portas da bridge; enquanto isso, o RDP exige NLA e o Sentinela alerta a presença |
| **`sudo nft` sem restrição de argumentos** | se o portal for comprometido, o atacante pode reescrever o firewall (mas não vira root) | script intermediário que só aceita "liberar/revogar MAC" |
| **Servidor de desenvolvimento do Flask** | não feito para carga nem exposição ampla | `gunicorn`/`waitress` atrás do portal |
| **HTTP sem TLS no portal** | a senha do portal trafega em claro no Wi-Fi (mitigado se o Wi-Fi usa WPA2) | certificado próprio no portal |
