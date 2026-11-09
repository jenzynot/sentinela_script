# Arquitetura do Sentinela

Documento de referência: o que existe, onde roda, como as peças conversam e por que foram feitas assim. Para subir o ambiente e rodar os testes, veja [`development.md`](development.md).

---

## 1. Visão geral

O Sentinela transforma um computador com Linux Mint num **gateway doméstico vigiado**:

- cria uma rede Wi-Fi própria e isolada (`br0`, `192.168.50.0/24`);
- controla quem sai para a internet por uma **whitelist de MACs** no firewall;
- deixa os aparelhos entrarem na whitelist sozinhos por um **portal cativo**;
- hospeda uma **VM Windows Server** como "servidor da casa" (painel web + RDP);
- roda um **agente** que varre a rede periodicamente, grava o histórico num **MySQL** e **alerta** quando aparece um aparelho desconhecido ou uma porta nova;
- oferece **VPN** para acesso de fora e **backup** diário com restore testado.

### O princípio que decide tudo

> **O host é o gateway; a VM é um cliente protegido.**

Se um componente precisa **ver ou controlar o tráfego dos outros**, ele mora no host. Se é um serviço que roda sozinho, pode ser VM. Por isso o firewall, o banco e o agente ficam no host: a VM é uma "folha" pendurada na `br0` e não enxerga o tráfego dos outros dispositivos.

---

## 2. Topologia

```
                                ┌──────────────────────── HOST LINUX MINT ─────────────────────────┐
                                │                                                                   │
  celular / notebook            │   wlpXsY (modo AP, hostapd)──┐                                    │
  ))) Wi-Fi WPA2 ))) ───────────┼──────────────────────────────┤                                    │
                                │                              │  br0  192.168.50.1/24             │
  VM Windows Server             │   vboxnetflt (bridged) ──────┤  ├─ dnsmasq: DHCP .100–.200, DNS   │   uplink
  08:00:27:5e:00:10 → .10 ──────┼──────────────────────────────┘  ├─ portal.py :8080                 ├── (cabo / USB) ── internet
  IIS :80 · RDP :3389           │                                 └─ agente: arp-scan + nmap        │       ▲
                                │                                                                   │       │ NAT (masquerade)
  celular fora de casa          │   wg0  10.8.0.1/24  (WireGuard :51820/udp) ──── forward ──► br0   │       │
  ))) 4G ))) ═══ túnel ═════════╪══════════════════════════════════════════════════════════════════╪═══════┘
                                │                                                                   │
                                │   nftables (inet portal) · MySQL 127.0.0.1:3306 · VirtualBox      │
                                └───────────────────────────────────────────────────────────────────┘
```

| Endereço | O quê |
|---|---|
| `192.168.50.0/24` | segmento da casa (`REDE_SEGMENTO`) |
| `192.168.50.1` | host: gateway, DNS, DHCP, portal (`REDE_GATEWAY`) |
| `192.168.50.10` | VM Windows Server — reserva DHCP por MAC (`VM_IP`/`VM_MAC`) |
| `192.168.50.100–200` | faixa DHCP dos demais aparelhos |
| `10.8.0.0/24` | rede da VPN; `10.8.0.1` = host, peers a partir de `.2` |
| `127.0.0.1:3306` | MySQL — só local |
| `:8080` | portal cativo (Flask) |
| `:51820/udp` | WireGuard |

---

## 3. Componentes

### 3.1 No host

| Componente | Implementação | Papel |
|---|---|---|
| Bridge `br0` | `network/rede.sh` (via `sentinela-bridge.service`) | segmento L2 da casa; IP do gateway; liga `ip_forward` |
| Access Point | `hostapd` com `/etc/sentinela/hostapd.conf` | rádio Wi-Fi; pendura a placa na `br0` (`bridge=br0`) |
| DHCP + DNS | `dnsmasq` com `/etc/sentinela/dnsmasq.conf` | entrega IP, gateway e DNS = host; só ouve na `br0` |
| Firewall | `nftables`, tabela `inet portal` (`captive/firewall.nft`) | whitelist, NAT, redirect do portal, proteção do host |
| Portal cativo | `captive/portal.py` (Flask) | registro self-service na whitelist |
| Controle do firewall | `captive/firewall_ctl.py` | liberar/revogar/sincronizar MACs no conjunto `autorizados` |
| Ressync | `captive/ressync.py` | no boot, reconstrói o conjunto a partir do banco |
| Banco | MySQL 8, banco `vigia_de_rede` | fonte da verdade: whitelist + histórico |
| Agente | pacote `sentinela/` | varredura, persistência, alertas |
| Hipervisor | VirtualBox + `provision/` | cria e configura a VM sem clique |
| VPN | WireGuard (`security/wireguard.sh`) | acesso remoto à rede da casa |
| Backup | `security/backup.sh` + cron | dump diário com retenção; `restore.sh` |

### 3.2 Na VM (Windows Server 2019/2022)

| Componente | Papel |
|---|---|
| IIS com `index.html` "Painel da Casa" | o "serviço da casa" exigido pelo roteiro (placeholder substituível) |
| RDP com NLA | alvo da demo de acesso remoto (celular → VM) |
| Guest Additions | permite ao host configurar a VM (`guestcontrol`) e ler o estado dela |

A VM **não** tem nenhuma função de rede ou segurança: pega IP do `dnsmasq`, obedece ao firewall do host e é varrida pelo agente como qualquer aparelho.

---

## 4. Stack

| Camada | Tecnologia | Versão-alvo | Por que esta |
|---|---|---|---|
| SO do host | Linux Mint 22 | base Ubuntu 24.04 | exigido pelo roteiro; o CI usa `ubuntu-24.04` para ter o mesmo kernel/pacotes |
| Linguagem | Python | 3.12 (a do Mint 22) | OOP exigido pelo roteiro; stdlib cobre parsing de XML, SMTP, subprocess |
| Web | Flask | ≥ 3.0 | portal de duas rotas; nada mais pesado se justifica |
| Banco | MySQL + `mysql-connector-python` | 8.0 / ≥ 9.0 | InnoDB com FKs de verdade; conector oficial, sem compilação |
| Firewall | nftables | 1.0.x | conjuntos (`set`) nativos: liberar um MAC é inserir um elemento, sem reescrever regras |
| AP / DHCP / DNS | hostapd, dnsmasq | pacotes da distro | padrão de fato para AP em Linux; dnsmasq faz DHCP+DNS num processo |
| Descoberta | arp-scan | 1.10 | ARP enxerga quem bloqueia ping (Windows bloqueia por padrão) |
| Portas | nmap | 7.x | SYN scan rápido, saída XML estável para parsing |
| Virtualização | VirtualBox + `VBoxManage` | 7.0 | instalação desatendida do Windows (`unattended install`) e controle por CLI |
| VPN | WireGuard (`wg`, `wg-quick`) | kernel | configuração mínima, chaves curtas, QR code para o celular |
| Serviços | systemd | — | ordem de boot declarativa (`After=`, `Requires=`, `PartOf=`) e reinício automático |
| Testes | pytest | ≥ 8.0 | fixtures para infraestrutura (banco, firewall, namespaces) |
| CI | GitHub Actions | `ubuntu-24.04` | Linux real com root: dá para testar nftables e namespaces |
| Lint | shellcheck | — | scripts bash são boa parte do projeto |

Dependências Python ficam no mínimo de propósito: `requirements.txt` tem só `mysql-connector-python` e `flask`; `requirements-dev.txt` acrescenta `pytest`. Os scripts que rodam antes do `.venv` existir (`network/gerar_configs.py`, `sentinela/config.py`) usam só a biblioteca padrão.

---

## 5. Estrutura do repositório

```
sentinela_script/
├── captive/                 portal cativo + firewall
│   ├── firewall.nft         ruleset completo (tabela inet portal); idempotente
│   ├── firewall_ctl.py      liberar_mac / revogar_mac / macs_autorizados / sincronizar (via sudo nft)
│   ├── portal.py            Flask :8080 — página de registro em qualquer GET, POST /registrar
│   ├── dados.py             acesso ao MySQL do portal/ressync (conectar, registrar_autorizado, macs_autorizados)
│   ├── ressync.py           banco → conjunto nftables, numa transação nft
│   └── sudoers.sentinela    usuário de serviço só pode rodar /usr/sbin/nft
│
├── network/                 Fase 1
│   ├── gerar_configs.py     .env → hostapd.conf, dnsmasq.conf, drop-in do NetworkManager (com validação)
│   └── rede.sh              subir | descer | status da br0
│
├── provision/               Fase 2 (pacote Python)
│   ├── vbox.py              VBoxManage com executor injetável (real ou falso nos testes)
│   └── vm.py                ConfigVM, ProvisionadorVM, CLI: criar/instalar/aguardar/configurar/autorizar/tudo…
│
├── sentinela/               Fase 5 (pacote Python) — o agente
│   ├── config.py            leitura do .env (stdlib), parâmetros do MySQL
│   ├── scanner.py           Scanner, Dispositivo, Porta; parsers do arp-scan e do nmap XML
│   ├── repositorio.py       Repositorio: toda a SQL do agente
│   ├── whitelist.py         Whitelist: MACs autorizados, carregados por ciclo
│   ├── alerta.py            Alerta, NotificadorEmail, níveis de risco
│   ├── agente.py            Sentinela.executar_ciclo(), criar_sentinela()
│   └── __main__.py          python -m sentinela (loop, --uma-vez, SIGTERM)
│
├── security/                Fase 6
│   ├── backup.sh            mysqldump consistente → .sql.gz (600), conferido, retenção
│   ├── restore.sh           confere, confirma, guarda o estado atual, restaura
│   └── wireguard.sh         servidor | peer <nome> | listar
│
├── sql/                     Fases 3–4
│   ├── schema.sql           5 tabelas InnoDB, idempotente
│   └── setup_banco.sh       hardening do MySQL + schema + usuário só-DML
│
├── systemd/                 units instaladas em /etc/systemd/system
│   ├── sentinela.target
│   └── sentinela-{bridge,firewall,ap,dhcp,ressync,portal,agente}.service
│
├── tests/                   pytest — um marker por job do CI
│   ├── conftest.py          fixtures: banco, ruleset; helper indisponivel()
│   ├── test_rede_configs.py · test_provision.py · test_agente_unidade.py   (unidade)
│   ├── test_banco.py        (banco: schema, setup_banco.sh, backup/restore)
│   ├── test_firewall.py     (firewall)
│   ├── test_rede.py         (rede: namespaces + agente real; contrato do agente no topo)
│   └── test_portal.py       (portal)
│
├── .github/
│   ├── workflows/ci.yml     5 jobs
│   └── actions/preparar/    action composta: Python, .venv, apt, usuário MySQL
│
├── docs/                    guias por fase, segurança, ensaio, diário técnico, este documento
├── setup_host.sh            Fase 0: pacotes do host + .venv + teste de modo AP
├── instalar.sh              implantação por etapa: rede | banco | portal | agente | seguranca | vpn | tudo | verificar
├── .env.example             todas as variáveis, comentadas
├── pytest.ini               pythonpath, markers, --strict-markers
├── requirements.txt / requirements-dev.txt
├── planejamento_sentinela.md / planejamento_testes.md   documentos de planejamento originais
└── .gitattributes / .gitignore
```

**Por que `captive/` e `network/` não são pacotes:** os scripts do portal são executados de dentro da própria pasta pelo systemd (`WorkingDirectory=/opt/sentinela/captive`) e usam imports planos (`from firewall_ctl import …`), como no planejamento. O `pytest.ini` põe essas pastas no `pythonpath` para os testes importarem igual. `sentinela/` e `provision/` são pacotes porque rodam com `python -m`.

---

## 6. Layout implantado no host

O `instalar.sh` separa **repositório de trabalho** (seu `~/…/sentinela_script`) de **instalação**:

| Caminho | Conteúdo | Dono / modo |
|---|---|---|
| `/opt/sentinela/` | cópia do código (sem `.git`, `tests`, `.env`) + `.venv` | `root:root`, scripts 755 |
| `/etc/sentinela/sentinela.env` | cópia do `.env` | `root:sentinela` 640 |
| `/etc/sentinela/hostapd.conf` | gerado (contém a senha do Wi-Fi) | `root` 600 |
| `/etc/sentinela/dnsmasq.conf` | gerado | 644 |
| `/etc/NetworkManager/conf.d/90-sentinela.conf` | placa do AP e `br0` fora do NetworkManager | 644 |
| `/etc/systemd/system/sentinela*.{service,target}` | units | 644 |
| `/etc/sudoers.d/sentinela` | `sentinela ALL=(root) NOPASSWD: /usr/sbin/nft` | 440 |
| `/etc/cron.d/sentinela-backup` | backup às 02:00 | 644 |
| `/etc/wireguard/` | `wg0.conf`, chaves, `clientes/<nome>.conf` | `root` 600/700 |
| `/var/backups/sentinela/` | `vigia_de_rede_<data>_<hora>_<ms>.sql.gz` | `root` 600 |
| `/var/log/sentinela/sentinela.log` | log do agente (também no journald) | `root` |
| `/var/log/sentinela_backup.log` | histórico dos backups | `root` |
| `/var/lib/misc/dnsmasq.leases` | concessões DHCP | dnsmasq |
| `~/VirtualBox VMs/servidor-casa/` | VM e disco (`.vdi`) | seu usuário |

**Usuários do sistema:**

| Usuário | Roda | Por quê |
|---|---|---|
| `sentinela` (sistema, sem shell/home) | portal, ressync | serviço exposto à rede não roda como root; só pode chamar `nft` via sudo |
| `root` | agente, bridge, firewall, hostapd, dnsmasq*, backup | pacotes crus (`arp-scan`, `nmap -sS`), configuração de rede |
| seu usuário (grupo `vboxusers`) | `provision.vm`, VirtualBox | VMs pertencem a quem as cria |

\* o `dnsmasq` abre as portas como root e depois troca sozinho para um usuário sem privilégios.

---

## 7. Boot e serviços (systemd)

```
multi-user.target
└── sentinela.target
    ├── sentinela-bridge.service      oneshot   rede.sh subir         (br0, ip_forward, NM solta a placa)
    ├── sentinela-firewall.service    oneshot   nft -f firewall.nft   After=bridge, nftables.service
    │   └── sentinela-ressync.service oneshot   ressync.py            After=firewall, mysql · PartOf=firewall · User=sentinela
    │       └── sentinela-portal.service        portal.py :8080       After=ressync · User=sentinela
    ├── sentinela-ap.service                    hostapd               Requires=bridge
    ├── sentinela-dhcp.service                  dnsmasq               Requires=bridge
    └── sentinela-agente.service                python -m sentinela   After=bridge, mysql · root
```

Pontos de projeto:

- **`firewall` → `ressync` → `portal`**: o firewall nasce com o conjunto `autorizados` **vazio**; o ressync o repovoa a partir do banco; só então o portal aceita registros.
- **`PartOf=sentinela-firewall.service` no ressync**: recarregar o firewall (que zera o conjunto) dispara o ressync de novo — a whitelist nunca fica vazia por esquecimento.
- **`After=nftables.service` no firewall**: se o serviço de firewall da distro estiver ativo, ele roda `flush ruleset`; carregar depois evita que nossa tabela seja apagada.
- **Instâncias próprias de `hostapd`/`dnsmasq`** (não as unidades da distro, que o `setup_host.sh` desabilita): configuração isolada em `/etc/sentinela`.
- `Restart=on-failure` nos serviços de longa duração (AP, DHCP, portal, agente).

---

## 8. Fluxos principais

### 8.1 Um aparelho novo entra na rede (portal cativo)

```
celular                hostapd/br0         dnsmasq            nftables                 portal.py              MySQL
   │ associa (WPA2) ──────►│                    │                   │                        │                     │
   │ DHCP DISCOVER ────────┼───────────────────►│ oferece .1xx,     │                        │                     │
   │◄──────────────────────┼────────────────────┤ gw=DNS=.1         │                        │                     │
   │ GET http://connectivitycheck…/generate_204 ┼──────────────────►│ prerouting: MAC ∉      │                     │
   │                       │                    │                   │ autorizados, tcp/80    │                     │
   │                       │                    │                   │ → redirect :8080 ─────►│ mac_do_ip(IP)       │
   │◄───────────────────────── página de registro (200, não 204) ───┼────────────────────────┤ (ip neigh)          │
   │  SO abre "Fazer login na rede"                                 │                        │                     │
   │ POST /registrar (nome, senha) ─────────────────────────────────┼───────────────────────►│ compare_digest      │
   │                       │                    │                   │                        │ INSERT … ON DUPLICATE KEY UPDATE ─►│
   │                       │                    │                   │◄── sudo nft add element│                     │
   │◄──────────────────────── "Dispositivo registrado!" ────────────┼────────────────────────┤                     │
   │ próximo pacote: forward → ether saddr ∈ @autorizados → accept → masquerade → internet  │                     │
```

- HTTPS **não** é interceptado (geraria erro de certificado); a detecção de portal dos sistemas usa HTTP justamente por isso.
- **Banco = verdade, conjunto = espelho:** o portal grava primeiro no banco e só então libera no firewall. Se o host reiniciar, o ressync reconstrói o conjunto.

### 8.2 Ciclo do agente

```
Sentinela.executar_ciclo()
 1. Scanner.descobrir(rede)          arp-scan --interface=br0 --retry=3 192.168.50.0/24  →  [(ip, mac)]
 2. Scanner.varrer_portas(ips)       nmap -sS -Pn -n -T4 --open --top-ports 1000 -oX - <todos os ips>  →  {ip: [Porta]}
    ── sem transação aberta até aqui (o nmap pode levar minutos) ──
 3. repo = Repositorio()             uma conexão, uma transação
 4. Whitelist(repo).carregar()       MACs com autorizado = TRUE
 5. abrir_varredura()                TB_VARREDURAS (resultado 'em_andamento')
 6. para cada dispositivo:
      registrar_visto(mac)           cadastra se novo; atualiza ultimo_visto, status='ativo'
      registrar_presenca()           TB_PRESENCAS (varredura × dispositivo × IP)
      registrar_portas()             TB_PORTAS (só as 'open')
      fora da whitelist E não estava na varredura anterior?  → alerta dispositivo_nao_autorizado (alto)
      porta aberta que não existia na última presença dele?   → alerta porta_nova (alto se 21/23/445/3306/3389/5900, senão médio)
 7. marcar_ausentes()                quem estava 'ativo' e não apareceu → 'inativo'
 8. fechar_varredura()               totais + resumo
 9. commit                           (qualquer exceção → rollback de tudo)
10. Alerta.notificar()               um e-mail com todos os alertas do ciclo, só depois do commit
```

### 8.3 Acesso remoto pela VPN

```
celular (4G) ══ WireGuard ══► host :51820/udp (input aceita) ─► wg0 10.8.0.1
                                                              └─ forward: iifname wg0 oifname br0 accept ─► VM 192.168.50.10:3389
```

Túnel dividido: o cliente só manda pela VPN `192.168.50.0/24` e `10.8.0.0/24`. A VM responde para `10.8.0.x` pelo gateway padrão dela (o host), e a resposta volta pelo `ct state established`.

### 8.4 Backup e restore

```
cron 02:00 → backup.sh → mysqldump --single-transaction --databases vigia_de_rede | gzip → .tmp → gzip -t → mv → apaga > 7 dias
restore.sh <arquivo> → gzip -t → confirmação "SIM" → backup.sh (estado atual) → gunzip | mysql → lembrete: restart ressync
```

---

## 9. Modelo de dados

```
TB_DISPOSITIVOS ─────────────┐ (quem — identidade = MAC)
  id_dispositivo PK          │
  endereco_mac UNIQUE        │
  nome_dispositivo, tipo     │
  autorizado  ◄── whitelist  │
  primeiro_visto, ultimo_visto, status (ativo|inativo|desconhecido)
        │ 1                  │ 1
        │                    │
        │ N                  │ N
TB_PRESENCAS                 TB_ALERTAS
  id_presenca PK               id_alerta PK
  id_varredura FK ──┐          id_varredura FK ──┐
  id_dispositivo FK │          id_dispositivo FK (pode ser NULL)
  endereco_ip       │          tipo_alerta, descricao, nivel_risco, data_alerta
        │ 1         │                            │
        │ N         ▼ N                          ▼ N
TB_PORTAS         TB_VARREDURAS (quando)
  id_porta PK       id_varredura PK
  id_presenca FK    data_varredura, quantidade_dispositivos, total_portas,
  numero_porta,     total_alertas, resultado_geral (em_andamento|ok|alerta), resumo
  protocolo, servico, status_porta
```

A peça central é **`TB_PRESENCAS`**: "este dispositivo apareceu nesta varredura com este IP". Com ela o sistema responde nativamente quem é novo, quem sumiu e que porta abriu em quem — e o IP fica registrado no tempo (o DHCP pode trocá-lo).

- Tudo **InnoDB**: no MyISAM as FKs seriam aceitas e ignoradas.
- `endereco_mac UNIQUE` sustenta o `ON DUPLICATE KEY UPDATE` do portal.
- Collation padrão do `utf8mb4` é case-insensitive: MAC em maiúscula ou minúscula é o mesmo registro.
- Schema idempotente (`IF NOT EXISTS`); mudanças futuras via `ALTER TABLE`.

**Quem escreve onde:**

| Tabela | Portal | Agente | Ressync |
|---|---|---|---|
| `TB_DISPOSITIVOS` | insere/atualiza (`autorizado = TRUE`) | insere (novo MAC), atualiza visto/status | lê |
| `TB_VARREDURAS`, `TB_PRESENCAS`, `TB_PORTAS`, `TB_ALERTAS` | — | escreve | — |

---

## 10. Firewall em uma página

Tabela única `inet portal` (IPv4 + IPv6). Detalhe regra a regra em [`seguranca.md`](seguranca.md).

| Chain | Hook | Política | Ideia |
|---|---|---|---|
| `input` | tráfego para o host | **drop** | o segmento só vê DNS, DHCP e o portal; de fora, só WireGuard |
| `forward` | tráfego através do host | **drop** | sai quem tem MAC em `@autorizados`; VPN entra na `br0` |
| `prerouting` (nat) | antes do roteamento | accept | HTTP de MAC não autorizado → `:8080` |
| `postrouting` (nat) | depois do roteamento | accept | masquerade só do que sai da `br0` para fora |

O **conjunto `autorizados`** (`type ether_addr`) é a whitelist viva. `firewall_ctl.py` é a única porta de escrita: valida o MAC (impede injetar sintaxe nft), usa `add element` (idempotente), trata "revogar ausente" como sucesso e faz `flush + add` numa única transação no `sincronizar()`.

> **Limite conhecido:** a tabela `inet` filtra o que é **roteado**. Tráfego entre dois aparelhos dentro da `br0` (comutado na camada 2) não passa por ela — um aparelho não registrado não chega à internet, mas alcança a VM diretamente. Ver [`seguranca.md` §7](seguranca.md#7-vulnerabilidades-conhecidas-documentadas-de-propósito).

---

## 11. Configuração e segredos

```
.env (repositório, fora do Git)
  └─ instalar.sh ─► /etc/sentinela/sentinela.env (640 root:sentinela)
                      ├─ systemd EnvironmentFile= ─► portal, ressync, agente
                      ├─ sentinela.config.carregar_env() ─► scripts Python rodados à mão
                      ├─ gerar_configs.py ─► hostapd.conf (600), dnsmasq.conf
                      └─ leitura por grep (sem executar o arquivo) ─► rede.sh, setup_banco.sh, wireguard.sh
```

Regras:

- **Nenhum segredo no código ou no Git.** O `.env.example` só tem valores de exemplo — e os scripts recusam alguns deles (`troque-esta-senha`).
- **Nenhum segredo na linha de comando:** senhas vão para o MySQL pela entrada padrão, para o VirtualBox por arquivo temporário 600, para o `mysql`/`mysqldump` por `MYSQL_PWD` (só no CI).
- O `.env` **nunca é executado** como shell (`source`): os scripts bash leem chave por chave com `grep`, então um valor com `$` ou aspas não vira código.
- `root` do MySQL autentica **pelo socket**: não existe senha de root para guardar.

---

## 12. Testes e CI

```
push / pull request
  └─ .github/workflows/ci.yml  (ubuntu-24.04, 5 jobs em paralelo)
       ├─ Job 0 · unidade   shellcheck + pytest -m unidade          sem serviços
       ├─ Job 1 · banco     pytest -m banco                         service mysql:8.0
       ├─ Job 2 · firewall  pytest -m firewall  (sudo nft)          service mysql:8.0 + nftables
       ├─ Job 3 · rede      sudo -E pytest -m rede (namespaces)     service mysql:8.0 + nmap + arp-scan
       └─ Job 4 · portal    pytest -m portal                        service mysql:8.0
```

- A action composta `.github/actions/preparar` monta Python 3.12, `.venv`, pacotes apt e o usuário `sentinela` (só DML) no MySQL do job.
- **Rede simulada (Job 3):** bridge `brsentinela` (`10.99.0.1/24`) + 3 network namespaces ligados por veth, cada um com MAC fixo. O agente real (arp-scan + nmap + MySQL) roda dois ciclos sobre eles.
- **Dublês onde a infraestrutura é impossível:** `VBoxManage` falso (provisionamento), `RepoFalso`/`ScannerFalso` (regras do agente), `mac_do_ip`/`liberar_mac` substituídos (portal).
- **Pulado localmente, falha no CI** (`indisponivel()` no `conftest.py`).
- **Contrato antes da implementação:** os testes do agente foram escritos antes do agente existir (ficavam pulados) e definiram a interface que a Fase 5 cumpriu.

O que o CI não cobre e por quê: [`testes_manuais.md`](testes_manuais.md).

---

## 13. Decisões de arquitetura (e alternativas descartadas)

| Decisão | Alternativa descartada | Motivo |
|---|---|---|
| Firewall, banco e agente no host | dentro da VM | a VM não vê o tráfego dos outros nem controla o firewall do segmento; se ela cair, o monitoramento cairia junto |
| AP no host | hotspot dentro da VM | o VirtualBox não entrega o rádio Wi-Fi físico ao convidado |
| Banco como fonte da verdade, nftables como espelho | estado só no nftables | o conjunto some no reboot; o banco persiste e tem histórico |
| Whitelist por conjunto nftables | uma regra por MAC | liberar/revogar vira inserir/remover elemento; uma regra fixa, sem recarregar o ruleset |
| Backup local com restore testado | backup em nuvem | resolve o requisito sem dependência externa na demo; nuvem fica como extensão |
| Código implantado em `/opt` | rodar do `/home` | o usuário de serviço não lê `/home/<usuário>`; separa trabalho de instalação |
| Configs geradas em Python | `envsubst` em templates | precisa de lógica (rede aberta × WPA2, reserva da VM) e validação testável |
| arp-scan para descoberta | ping sweep | Windows e celulares bloqueiam ICMP; ARP sempre responde no mesmo segmento |
| Alerta de intruso na chegada | a cada ciclo | evita enxurrada de alertas iguais; sair e voltar alerta de novo |
| Uma transação por ciclo, notificação após commit | gravação incremental | ciclo é tudo-ou-nada; ninguém é avisado de algo que não ficou gravado |
| Agente como root | capabilities (`CAP_NET_RAW`) | `nmap` com capabilities exige ajustes extras; root é explícito e documentado |
| Portal em Flask dev server | gunicorn/waitress | poucos clientes na demo; troca documentada como melhoria |

Limitações e vulnerabilidades assumidas (clonagem de MAC, senha compartilhada, tráfego L2 na `br0`, `sudo nft` amplo, HTTP no portal) estão em [`seguranca.md` §7](seguranca.md#7-vulnerabilidades-conhecidas-documentadas-de-propósito), com impacto e mitigação.

---

## 14. Extensões naturais

- Tabela `bridge` no nftables para aplicar a whitelist também dentro da `br0`.
- WPA2-Enterprise (802.1X) no lugar de "senha compartilhada + MAC".
- Painel web do próprio Sentinela (no host, lendo o `vigia_de_rede`) com varreduras e alertas.
- Detecção de **MAC repetido com IPs diferentes** na mesma varredura (indício de clonagem).
- Backup também fora do host (nuvem ou outro disco) mantendo o restore testado.
- DNS sobre TLS entre o `dnsmasq` e a internet.
