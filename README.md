# Sentinela

> ExpoTech 2026.2 · Missão FOUNDATION — *Infraestrutura: Redes que Conectam Casas*

"Data center doméstico" controlado: um host Linux Mint que cria e vigia a própria rede, uma VM Windows Server como servidor da casa, e um agente (**Sentinela**) que monitora dispositivos e portas, com portal cativo para registro self-service na whitelist.

**Princípio de arquitetura:** o host é o gateway; a VM é um cliente protegido. Tudo que precisa ver ou controlar o tráfego da rede mora no host.

O planejamento completo está em [`planejamento_sentinela.md`](planejamento_sentinela.md) e o diário técnico em [`docs/diario_tecnico.md`](docs/diario_tecnico.md).

## Estrutura

```
sentinela_script/
├── network/        # hostapd.conf, dnsmasq.conf, firewall.nft, scripts de subida do AP
├── provision/      # automação VBoxManage (criar/configurar a VM via subprocess)
├── captive/        # portal cativo: portal.py, firewall_ctl.py, ressync.py
├── sentinela/      # agente: Scanner, Repositorio, Whitelist, Alerta
├── security/       # backup.sh, restore.sh, WireGuard, hardening
├── sql/            # schema.sql
├── docs/           # diário técnico + relatório
├── tests/          # pytest: um marker por job do CI
├── .github/        # workflow do GitHub Actions
├── setup_host.sh   # Fase 0: prepara o host Mint
├── requirements.txt
├── requirements-dev.txt
└── README.md
```

## Preparar o host (Fase 0)

No host Linux Mint, a partir do seu usuário comum:

```bash
git clone <url-do-repo> sentinela_script
cd sentinela_script
sudo ./setup_host.sh
cp .env.example .env   # e preencha as senhas
```

O script atualiza o sistema, instala `virtualbox`, `hostapd`, `dnsmasq`, `nftables`, `iw`, `mysql-server`, `nmap`, `arp-scan`, `python3`, `python3-venv` e `git`, cria o `.venv` com as dependências do `requirements.txt` e verifica se a placa Wi-Fi suporta modo AP.

`hostapd` e `dnsmasq` ficam **desabilitados** de propósito: eles só sobem na Fase 1, já configurados para a `br0`.

## Testes e CI

Especificação em [`planejamento_testes.md`](planejamento_testes.md). A cada push em `main` e em cada pull request, o GitHub Actions (`.github/workflows/ci.yml`) roda 4 jobs num Linux real:

| Job | Marker | O que prova |
|---|---|---|
| 1 · Banco | `banco` | schema idempotente, InnoDB, FK e UNIQUE aplicadas, upsert do portal, JOINs do relatório |
| 2 · Firewall | `firewall` | `firewall.nft` carrega, liberar/revogar MAC, MAC inválido recusado, `ressync` espelha o banco |
| 3 · Rede simulada | `rede` | namespaces + veth numa bridge: `mac_do_ip`, Scanner, alertas do agente |
| 4 · Portal | `portal` | rotas Flask: senha errada/certa, MAC não identificado |

Localmente:

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest                   # sem MySQL/nft, os testes são pulados
.venv/bin/python -m pytest -m banco          # só um job
sudo -E .venv/bin/python -m pytest -m rede   # Job 3 precisa de root
```

Fora do CI, quando falta infraestrutura (MySQL, `nft`, root), o teste é **pulado**. No CI (`CI=true`), ele **falha**: o pipeline não pode ficar verde só porque algo não subiu.

Os testes do agente (Job 3) ficam pulados até a Fase 5. O contrato esperado (`Scanner`, `criar_sentinela`, tipos de alerta) está descrito no topo de `tests/test_rede.py`.

## Fases

| Fase | Entrega | Status |
|---|---|---|
| 0 | Host e repositório preparados | ✅ |
| 1 | Rede controlada (AP + `br0` + `dnsmasq` + NAT) | ⏳ (`captive/firewall.nft` já cobre o NAT) |
| 1.5 | Portal cativo | 🧪 código + testes no CI · ⏳ teste com celular real |
| 2 | VM Windows Server automatizada | ⏳ |
| 3 | Banco de dados | ⏳ |
| 4 | Schema do banco | 🧪 `sql/schema.sql` + testes no CI |
| 5 | Agente Sentinela | ⏳ |
| 6 | Segurança e hardening | ⏳ |
| 7 | Documentação e ensaio | ⏳ |

Caminho crítico: **Fase 1 → Fase 2 → Fase 5**.
