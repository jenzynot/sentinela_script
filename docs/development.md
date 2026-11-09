# Desenvolvimento — do clone ao "está funcionando"

Guia para quem acabou de abrir o projeto. Explica onde cada parte roda, como subir o ambiente, rodar os testes, ver o sistema funcionando e trabalhar no código sem quebrar nada.

Para entender **como** o sistema é montado (componentes, fluxos, decisões), leia [`arquitetura.md`](arquitetura.md).

---

## 1. Em 30 segundos: o que é o projeto

Um "data center doméstico": um host **Linux Mint** vira o gateway de uma rede Wi-Fi própria (`br0`, `192.168.50.0/24`), hospeda uma **VM Windows Server** (o "servidor da casa") e roda o **Sentinela**, um agente que varre a rede, grava tudo num MySQL e alerta quando aparece um aparelho fora da whitelist ou uma porta nova. Aparelhos entram na whitelist sozinhos por um **portal cativo**.

## 2. Três lugares, três alcances

Nem tudo roda em qualquer máquina. Antes de tentar "ver funcionando", saiba o que cada ambiente consegue:

| Ambiente | O que dá para fazer | O que **não** dá |
|---|---|---|
| **Sua máquina de dev** (WSL, Linux, VM) | editar, testes de unidade, e — com MySQL + root — toda a suíte do CI, inclusive o agente numa rede simulada | Wi-Fi/AP, celular real, VM Windows na `br0` |
| **GitHub Actions** (automático a cada push) | os 5 jobs: unidade, banco, firewall, rede simulada, portal | idem acima |
| **Host Mint** (bare-metal, o de verdade) | tudo: AP, portal no celular, VM, RDP, alertas ao vivo, VPN, demo | — |

> Regra prática: tudo que acontece **depois** de "o aparelho já está na `br0`" é testável fora do Mint. O que depende de rádio, celular ou Windows só se prova no Mint.

---

## 3. Bootstrap rápido (5 minutos, qualquer Linux/WSL)

Pré-requisitos: `git`, `python3` (3.12+) e `python3-venv`.

```bash
git clone https://github.com/jenzynot/sentinela_script.git
cd sentinela_script

python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt

.venv/bin/python -m pytest -m unidade        # deve terminar com "40 passed"
.venv/bin/python -m pytest                   # o resto aparece como "skipped" (falta infra)
```

Se o `venv` falhar com `ensurepip is not available`: `sudo apt install python3-venv` (no Ubuntu/WSL o pacote às vezes vem com a versão no nome, ex. `python3.14-venv`).

O `-m unidade` já exercita bastante coisa sem infraestrutura nenhuma:

- geração e validação das configs de rede (`hostapd.conf`, `dnsmasq.conf`);
- provisionamento da VM inteiro, com um `VBoxManage` falso que só grava os comandos;
- regras do agente (quando alertar, quando não), com banco e scanner em memória;
- parsers da saída do `arp-scan` e do `nmap`.

### Por que o resto aparece "skipped"?

Cada teste que precisa de infraestrutura (MySQL, `nft`, root) **se pula** quando ela falta — e mostra o motivo (`-ra` está ligado no `pytest.ini`):

```
SKIPPED [1] tests/test_banco.py:...: MySQL indisponível: 2003 (HY000): Can't connect ...
SKIPPED [1] tests/test_firewall.py:...: nft não instalado
SKIPPED [1] tests/test_rede.py:...: Job 3 precisa de root (rode com sudo -E)
```

No CI é o contrário: com `CI=true` no ambiente, infraestrutura faltando **falha** o teste. Assim um pipeline verde sempre significa "testado", nunca "não rodou".

---

## 4. Rodar a suíte completa na sua máquina (laboratório)

Opcional, mas é o jeito de ver o banco, o firewall e o **agente funcionando de verdade** sem o Mint — exatamente o que o CI faz.

> ⚠️ **Use um MySQL descartável.** Os testes **apagam e recriam o banco `vigia_de_rede`**, criam/removem usuários e removem o banco `test`. Nunca aponte os testes para o MySQL do host Mint de produção.
>
> ⚠️ Os testes de firewall carregam temporariamente uma tabela nftables com `input` em `policy drop` (removida no fim). Os de rede criam uma bridge `brsentinela` e 3 network namespaces (também removidos). Prefira uma VM ou máquina de laboratório. No WSL2 isso **não foi verificado**.

### 4.1 Dependências de sistema

```bash
sudo apt install mysql-client nftables nmap arp-scan iproute2
# (se mysql-client não existir na sua distro: default-mysql-client)
```

### 4.2 MySQL descartável (recomendado: Docker, igual ao CI)

```bash
docker run -d --name sentinela-mysql -e MYSQL_ROOT_PASSWORD=root -p 127.0.0.1:3306:3306 mysql:8.0

# espere ~20 s e crie o usuário que o código usa (só DML, como no host)
mysql -h127.0.0.1 -uroot -proot -e "
  CREATE USER IF NOT EXISTS 'sentinela'@'%' IDENTIFIED BY 'sentinela-ci';
  GRANT SELECT, INSERT, UPDATE, DELETE ON vigia_de_rede.* TO 'sentinela'@'%';"
```

Para apagar depois: `docker rm -f sentinela-mysql`.

<details>
<summary>Sem Docker (MySQL instalado na máquina)</summary>

O `root` do MySQL no Ubuntu autentica pelo socket, mas os testes precisam de um admin com senha via TCP:

```bash
sudo mysql -e "
  CREATE USER IF NOT EXISTS 'teste_admin'@'localhost' IDENTIFIED BY 'senha-teste';
  CREATE USER IF NOT EXISTS 'teste_admin'@'127.0.0.1' IDENTIFIED BY 'senha-teste';
  GRANT ALL ON *.* TO 'teste_admin'@'localhost' WITH GRANT OPTION;
  GRANT ALL ON *.* TO 'teste_admin'@'127.0.0.1' WITH GRANT OPTION;
  CREATE USER IF NOT EXISTS 'sentinela'@'localhost' IDENTIFIED BY 'sentinela-ci';
  CREATE USER IF NOT EXISTS 'sentinela'@'127.0.0.1' IDENTIFIED BY 'sentinela-ci';
  GRANT SELECT, INSERT, UPDATE, DELETE ON vigia_de_rede.* TO 'sentinela'@'localhost';
  GRANT SELECT, INSERT, UPDATE, DELETE ON vigia_de_rede.* TO 'sentinela'@'127.0.0.1';"
```

E use `MYSQL_ADMIN_USER=teste_admin` / `MYSQL_ADMIN_PASSWORD=senha-teste` no passo seguinte. Lembre: os testes apagam o `vigia_de_rede` desta instância.
</details>

### 4.3 Variáveis de ambiente (as mesmas do CI)

```bash
export MYSQL_HOST=127.0.0.1 MYSQL_PORT=3306
export MYSQL_ADMIN_USER=root MYSQL_ADMIN_PASSWORD=root      # quem recria o banco nos testes
export MYSQL_USER=sentinela MYSQL_PASSWORD=sentinela-ci     # quem o código usa
export MYSQL_DATABASE=vigia_de_rede PORTAL_SENHA=senha-ci
```

Variáveis exportadas têm prioridade sobre um `.env` que exista no repositório.

### 4.4 Um job por vez

```bash
.venv/bin/python -m pytest -m unidade            # Job 0
.venv/bin/python -m pytest -m banco              # Job 1 — schema, setup_banco.sh, backup/restore
.venv/bin/python -m pytest -m portal             # Job 4 — rotas do Flask
sudo -v && .venv/bin/python -m pytest -m firewall   # Job 2 — usa "sudo -n nft" (precisa do sudo em cache)

# Job 3 — namespaces + agente real; precisa de root. -E mantém as MYSQL_*;
# PYTHONDONTWRITEBYTECODE evita deixar __pycache__ do root no repositório.
sudo -E env PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest -m rede -p no:cacheprovider
```

O Job 3 é o mais interessante de olhar com `-v`: ele cria 3 "dispositivos" falsos (`10.99.0.11–13`), autoriza dois, sobe um servidor na porta 80 de um deles entre dois ciclos e confere que o Sentinela gerou `dispositivo_nao_autorizado` para o intruso, `porta_nova` para a porta que abriu, e **nada** para o autorizado que não mudou.

---

## 5. Ver o agente na sua própria rede (opcional)

Com o MySQL do passo 4 de pé e o schema aplicado (`mysql -h127.0.0.1 -uroot -proot < sql/schema.sql`), dá para rodar **um ciclo** do Sentinela na rede em que sua máquina está:

> ⚠️ Só faça isso numa rede **sua** ou em que você tenha autorização para varrer. `arp-scan` e `nmap` em rede alheia podem violar regras da instituição.

```bash
ip -br addr                              # descubra a interface e a rede (ex.: eth0, 192.168.1.0/24)
sudo -E .venv/bin/python -m sentinela --uma-vez \
     --interface eth0 --rede 192.168.1.0/24 --log /tmp/sentinela.log
```

Como a whitelist começa vazia, todo aparelho aparece como `dispositivo_nao_autorizado` — é o esperado. Para ver o resultado:

```bash
mysql -h127.0.0.1 -uroot -proot vigia_de_rede -e "
  SELECT tipo_alerta, nivel_risco, descricao FROM TB_ALERTAS ORDER BY id_alerta DESC LIMIT 10;
  SELECT resumo FROM TB_VARREDURAS ORDER BY id_varredura DESC LIMIT 1;"
```

> No WSL2 a "rede" vista é a NAT interna do WSL (normalmente só o host Windows aparece). Em Linux nativo ou numa VM em modo bridge você vê a rede real.

**O portal localmente:** `cd captive && ../.venv/bin/python portal.py` sobe na 8080, mas acessar `http://localhost:8080` responde **400** — o portal identifica o aparelho pelo MAC na tabela ARP, e `127.0.0.1` não tem MAC. É o comportamento correto; a página em si é coberta pelos testes do Job 4.

---

## 6. Subir no host Mint (o sistema de verdade)

Resumo — os detalhes de cada passo estão nos guias de fase linkados no [README](../README.md).

```bash
sudo ./setup_host.sh                   # pacotes do sistema + .venv + teste de modo AP. Faça logout/login depois.
cp .env.example .env && nano .env      # ver seção 7

sudo ./instalar.sh rede                # br0 + AP + DHCP/DNS + firewall/NAT  → celular pega IP
sudo ./instalar.sh banco               # MySQL protegido + schema + usuário  → antes do portal!
sudo ./instalar.sh portal              # portal cativo + ressync             → celular se registra
.venv/bin/python -m provision.vm tudo  # VM Windows (como SEU usuário, 20–60 min) → RDP funciona
sudo ./instalar.sh agente              # roda 1 ciclo de teste e sobe o serviço → alertas
sudo ./instalar.sh seguranca           # firewall endurecido + backup diário
sudo ./instalar.sh vpn                 # opcional: WireGuard

sudo ./instalar.sh verificar           # estado de tudo
```

Coisas que pegam quem está começando:

- **A ordem é a das dependências, não a das fases:** o portal (1.5) grava no banco (3), então `banco` vem antes de `portal`.
- **A internet do host não pode vir da placa Wi-Fi que vira AP.** Use cabo, USB tethering ou um segundo adaptador.
- **`provision.vm` roda como seu usuário**, não com `sudo` — VMs do VirtualBox pertencem a quem as cria. O script recusa root.
- **O `instalar.sh` copia o código para `/opt/sentinela`.** Editou o repositório? Rode a etapa de novo para implantar (é idempotente).
- **O `.env` é copiado para `/etc/sentinela/sentinela.env`** em toda etapa. Mudou uma senha? Edite o `.env` do repositório e rode a etapa de novo.

---

## 7. Configuração (`.env`)

Tudo configurável vive no `.env` (fora do Git; modelo em `.env.example`). Formato `CHAVE=valor`, sem espaços em volta do `=`, listas separadas por vírgula.

| Grupo | Variáveis | Usado por | Observações |
|---|---|---|---|
| Banco | `MYSQL_HOST`, `MYSQL_PORT`, `MYSQL_USER`, `MYSQL_PASSWORD`, `MYSQL_DATABASE` | portal, ressync, agente, `setup_banco.sh` | senha com 12+ caracteres; usuário não pode ser `root`; banco tem que ser `vigia_de_rede` |
| Wi-Fi | `WIFI_IF`, `WIFI_SSID`, `WIFI_SENHA`, `WIFI_CANAL`, `WIFI_PAIS` | `gerar_configs.py`, `rede.sh` | `WIFI_IF` vem de `iw dev`; senha 8–63 ou **vazia = rede aberta** |
| Rede | `REDE_SEGMENTO`, `REDE_GATEWAY`, `REDE_DOMINIO`, `DHCP_INICIO`, `DHCP_FIM`, `DNS_UPSTREAM` | `gerar_configs.py`, `rede.sh`, agente | gateway fora da faixa DHCP |
| Portal | `PORTAL_SENHA` | `portal.py` | vazia = ninguém se registra (falha fechada) |
| Agente | `SENTINELA_INTERFACE`, `SENTINELA_INTERVALO`, `SENTINELA_PORTAS`, `SENTINELA_LOG` | `python -m sentinela` | `SENTINELA_PORTAS` vazio = top 1000 do nmap |
| E-mail | `SMTP_HOST`, `SMTP_PORTA`, `SMTP_USUARIO`, `SMTP_SENHA`, `ALERTA_EMAIL_DE`, `ALERTA_EMAIL_PARA` | `alerta.py` | desligado se `SMTP_HOST` ou `ALERTA_EMAIL_PARA` estiver vazio |
| VPN | `VPN_ENDPOINT` | `wireguard.sh` | IP público/DDNS do host |
| VM | `VM_ISO`, `VM_OSTYPE`, `VM_INDICE_IMAGEM`, `VM_NOME`, `VM_MEMORIA_MB`, `VM_CPUS`, `VM_DISCO_GB`, `VM_USUARIO`, `VM_SENHA`, `VM_MAC`, `VM_IP` | `provision/vm.py`, `gerar_configs.py` | senha na política do Windows; MAC unicast |

Quem lê o quê: os serviços systemd recebem o arquivo por `EnvironmentFile=`; os scripts Python rodados à mão usam `sentinela.config.carregar_env()`, que lê `/etc/sentinela/sentinela.env` e depois o `.env` do repositório, **sem sobrescrever** variáveis já exportadas.

---

## 8. Fluxo de trabalho

### Antes de commitar

```bash
.venv/bin/python -m pytest -m unidade          # rápido, sempre
shellcheck -S warning $(git ls-files '*.sh')   # o CI roda isso (sudo apt install shellcheck)
```

Depois do push, acompanhe o CI: `gh run watch` (ou a aba *Actions* no GitHub). São 5 jobs, ~1 min cada, em paralelo.

### Onde colocar um teste novo

Todo teste tem um marker (definidos no `pytest.ini`; `--strict-markers` recusa marker desconhecido):

| Marker | Job | Use quando o teste precisa de... |
|---|---|---|
| `unidade` | 0 | nada — lógica pura, dublês, arquivos temporários |
| `banco` | 1 | MySQL (fixture `banco`: banco vazio com schema recém-aplicado) |
| `firewall` | 2 | `sudo nft` (fixture `ruleset`: carrega e remove o `firewall.nft`) |
| `rede` | 3 | root + namespaces (fixture `rede_simulada`) |
| `portal` | 4 | Flask + MySQL (fixture `cliente` com `mac_do_ip` e `liberar_mac` substituídos) |

Escreva no formato **dado → quando → então** (docstring), como os existentes. Infraestrutura opcional se resolve com `indisponivel("motivo")` do `conftest.py` — nunca com `pytest.skip` direto, para o CI continuar falhando quando algo não sobe.

### Convenções do código

- **Português** em nomes, comentários, mensagens e commits (o domínio do projeto é em português).
- **Segredos nunca no código nem na linha de comando:** vêm do ambiente; senhas para programas externos vão por arquivo 600 temporário ou pela entrada padrão (o `ps` mostra argumentos para todo mundo).
- **Scripts idempotentes:** rodar duas vezes não pode quebrar nem duplicar (instalador, schema, firewall, `setup_banco.sh`).
- **Valide entrada externa antes de usá-la:** MAC antes do `nft`, SSID/senha antes do `hostapd.conf`, nome de usuário antes do SQL.
- **Contrato do agente:** a interface que o Job 3 exige (`Scanner`, `criar_sentinela`, tipos de alerta) está no topo de `tests/test_rede.py`. Mudou a interface? Mude o contrato junto.

### Pegadinhas conhecidas

| Problema | Por quê | O que fazer |
|---|---|---|
| Script perde o `+x` | editar pelo Windows (`\\wsl.localhost\...`) zera o bit de execução | o modo está fixado no Git; se o `git status` mostrar *mode change*, rode `chmod +x` no arquivo (ou `git update-index --chmod=+x arquivo` ao adicionar um script novo) |
| `.sh` quebra com `\r: command not found` | CRLF vindo do Windows | o `.gitattributes` força LF; se escapou: `sed -i 's/\r$//' arquivo` |
| `mysqldump` ignora o host configurado | ele **não** lê `MYSQL_HOST` do ambiente (o cliente `mysql` lê) | os scripts passam `--host/--port` explicitamente quando a variável existe |
| `sudo .venv/bin/python` não acha as `MYSQL_*` | `sudo` limpa o ambiente | `sudo -E` |
| Teste de firewall pulado mesmo com `nft` instalado | ele usa `sudo -n` (não pergunta senha) | `sudo -v` antes |
| `ModuleNotFoundError: firewall_ctl` fora do pytest | `captive/` usa imports planos | rode de dentro de `captive/` (como o systemd faz) ou com `PYTHONPATH=captive` |

---

## 9. Comandos úteis (host Mint)

```bash
# estado geral
sudo ./instalar.sh verificar
systemctl list-units 'sentinela*'

# logs ao vivo
journalctl -fu sentinela-agente        # ciclos e alertas
journalctl -fu sentinela-portal        # registros
journalctl -fu sentinela-dhcp          # quem pegou IP
journalctl -fu sentinela-ap            # associações Wi-Fi
tail -f /var/log/sentinela/sentinela.log

# firewall e whitelist
sudo nft list table inet portal
sudo nft list set inet portal autorizados

# banco
sudo mysql vigia_de_rede
sudo mysql vigia_de_rede -e "SELECT endereco_mac, nome_dispositivo, autorizado, status FROM TB_DISPOSITIVOS"

# agente sob demanda
sudo /opt/sentinela/.venv/bin/python -m sentinela --uma-vez

# rede
./network/rede.sh status
cat /var/lib/misc/dnsmasq.leases

# VM
.venv/bin/python -m provision.vm status

# reiniciar tudo
sudo systemctl restart sentinela.target
```

---

## 10. Para onde ir agora

- Entender a arquitetura inteira: [`arquitetura.md`](arquitetura.md)
- Guias por fase: [`fase1_rede.md`](fase1_rede.md), [`fase1_5_portal.md`](fase1_5_portal.md), [`fase2_vm.md`](fase2_vm.md), [`fase3_banco.md`](fase3_banco.md), [`fase5_agente.md`](fase5_agente.md), [`seguranca.md`](seguranca.md)
- Preparar a apresentação: [`roteiro_ensaio.md`](roteiro_ensaio.md) e [`testes_manuais.md`](testes_manuais.md)
- Histórico das decisões: [`diario_tecnico.md`](diario_tecnico.md)
