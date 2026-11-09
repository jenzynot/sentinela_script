# Sentinela

[![CI](https://github.com/jenzynot/sentinela_script/actions/workflows/ci.yml/badge.svg)](https://github.com/jenzynot/sentinela_script/actions/workflows/ci.yml)

> ExpoTech 2026.2 · Missão FOUNDATION — *Infraestrutura: Redes que Conectam Casas*

"Data center doméstico" controlado: um host Linux Mint que cria e vigia a própria rede, uma VM Windows Server como servidor da casa, e um agente (**Sentinela**) que monitora dispositivos e portas, com portal cativo para registro self-service na whitelist.

**Princípio de arquitetura:** o host é o gateway; a VM é um cliente protegido. Tudo que precisa ver ou controlar o tráfego da rede mora no host.

```
                         ┌──────────────────── host Linux Mint (gateway) ────────────────────┐
 celular ──Wi-Fi (AP)──┐ │ hostapd   dnsmasq (DHCP/DNS)   nftables (whitelist, NAT, portal)  │
                       ├─┤ br0 192.168.50.1                                                   ├── NAT ── uplink ── internet
 VM Windows Server ────┘ │ portal.py (8080)   agente Sentinela   MySQL vigia_de_rede          │
   (bridged, .10)        │ VirtualBox   WireGuard (wg0)   backup diário                        │
   IIS + RDP             └────────────────────────────────────────────────────────────────────┘
```

**Começando agora?** [`docs/development.md`](docs/development.md) (bootstrap, testes, ver funcionando) · [`docs/arquitetura.md`](docs/arquitetura.md) (componentes, stack, fluxos, decisões)

Planejamento: [`planejamento_sentinela.md`](planejamento_sentinela.md) · Testes: [`planejamento_testes.md`](planejamento_testes.md) · Diário técnico: [`docs/diario_tecnico.md`](docs/diario_tecnico.md)

## Estrutura

```
sentinela_script/
├── network/        # gerar_configs.py (hostapd/dnsmasq/NM a partir do .env), rede.sh (br0)
├── captive/        # portal.py, firewall.nft, firewall_ctl.py, ressync.py, dados.py, sudoers
├── provision/      # vm.py + vbox.py: VM Windows Server via VBoxManage (subprocess)
├── sentinela/      # agente: Scanner, Repositorio, Whitelist, Alerta, Sentinela
├── security/       # backup.sh, restore.sh, wireguard.sh
├── sql/            # schema.sql, setup_banco.sh
├── systemd/        # units agrupadas em sentinela.target
├── docs/           # guias por fase, segurança, roteiro de ensaio, diário técnico
├── tests/          # pytest: um marker por job do CI
├── setup_host.sh   # Fase 0: pacotes do host
└── instalar.sh     # implanta cada fase em /opt/sentinela
```

## Do zero à demo (no host Mint)

```bash
git clone https://github.com/jenzynot/sentinela_script.git && cd sentinela_script
sudo ./setup_host.sh                  # Fase 0 — pacotes, .venv, teste de modo AP (logout/login depois)
cp .env.example .env && nano .env     # placa Wi-Fi, senhas, ISO da VM

sudo ./instalar.sh rede               # Fase 1   — br0 + AP + DHCP/DNS + NAT
sudo ./instalar.sh banco              # Fases 3-4 — MySQL protegido + schema + usuário dedicado
sudo ./instalar.sh portal             # Fase 1.5 — portal cativo + ressync
.venv/bin/python -m provision.vm tudo # Fase 2   — VM Windows Server (como seu usuário, 20–60 min)
sudo ./instalar.sh agente             # Fase 5   — agente Sentinela
sudo ./instalar.sh seguranca          # Fase 6   — firewall endurecido + backup diário
sudo ./instalar.sh vpn                # Fase 6   — WireGuard (opcional)

sudo ./instalar.sh verificar          # estado de tudo
```

A ordem de instalação segue as dependências (o portal grava no banco), não a numeração das fases. Cada etapa é idempotente: depois de um `git pull`, rode de novo.

| Fase | Guia | Pronto quando |
|---|---|---|
| 0 | este README | `setup_host.sh` sem erro e modo AP suportado |
| 1 | [`docs/fase1_rede.md`](docs/fase1_rede.md) | celular conecta no SSID e pega IP |
| 1.5 | [`docs/fase1_5_portal.md`](docs/fase1_5_portal.md) | portal abre sozinho; senha certa libera a navegação |
| 2 | [`docs/fase2_vm.md`](docs/fase2_vm.md) | RDP do celular na VM |
| 3–4 | [`docs/fase3_banco.md`](docs/fase3_banco.md) | `setup_banco.sh` ok, tudo InnoDB |
| 5 | [`docs/fase5_agente.md`](docs/fase5_agente.md) | aparelho fora da whitelist gera alerta |
| 6 | [`docs/seguranca.md`](docs/seguranca.md) | restore ensaiado; roteiro da Kali executado |
| 7 | [`docs/roteiro_ensaio.md`](docs/roteiro_ensaio.md) · [`docs/testes_manuais.md`](docs/testes_manuais.md) | demo cronometrada ≤ 12 min |

## Testes e CI

A cada push em `main` e em cada pull request, o GitHub Actions roda 5 jobs num Ubuntu 24.04 (mesma base do Mint 22):

| Job | Marker | O que prova |
|---|---|---|
| 0 · Unidade + lint | `unidade` | configs de rede geradas e validadas, provisionamento da VM (VBoxManage falso), regras do agente, parsers; `shellcheck` em todos os scripts |
| 1 · Banco | `banco` | schema idempotente, InnoDB, FK e UNIQUE aplicadas, upsert do portal, JOINs; `setup_banco.sh` com menor privilégio; **backup → incidente → restore** |
| 2 · Firewall | `firewall` | `firewall.nft` carrega e recarrega sem duplicar, chain `input` fechada, liberar/revogar MAC, injeção recusada, `ressync` espelha o banco |
| 3 · Rede simulada | `rede` | namespaces + veth numa bridge: `mac_do_ip`, `Scanner` real (arp-scan + nmap), dois ciclos do agente gerando os alertas certos e nenhum falso positivo |
| 4 · Portal | `portal` | rotas Flask: detecção de portal do Android/iOS/Windows, senha errada/certa, MAC não identificado |

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -m unidade        # roda em qualquer lugar
.venv/bin/python -m pytest                   # sem MySQL/nft/root, os demais são pulados
sudo -E .venv/bin/python -m pytest -m rede   # Job 3 precisa de root
```

Fora do CI, faltando infraestrutura, o teste é **pulado**; no CI (`CI=true`) ele **falha** — verde tem que significar "testado". O que o CI não alcança (rádio, celular, VM Windows, RDP) está em [`docs/testes_manuais.md`](docs/testes_manuais.md).
