# Projeto Sentinela — Planejamento de Construção

> **Repositório:** `sentinela_script`
> **Contexto:** ExpoTech 2026.2 · Missão FOUNDATION — *Infraestrutura: Redes que Conectam Casas*
> **Resumo:** "Data center doméstico" controlado — um host Linux que cria e vigia a própria rede, uma VM Windows Server como servidor da casa, e um agente (Sentinela) que monitora dispositivos e portas, com portal cativo para registro self-service na whitelist.

---

## 1. Princípio de arquitetura (a régua que decide tudo)

**O host é o gateway; a VM é um cliente protegido.**

- Tudo que precisa **ver ou controlar o tráfego da rede inteira** mora no **host** (Linux Mint).
- A VM (Windows Server) **só hospeda o serviço da casa** e, no mais, se comporta como qualquer dispositivo do segmento.

Essa frase resolve qualquer dúvida de "isso fica onde?": se o componente precisa enxergar ou barrar o tráfego dos outros, é host; se é um serviço que roda sozinho, pode ser VM.

### Narrativa para a banca
A VM é o servidor da casa que queremos manter seguro; o host Mint é toda a camada de rede e segurança que vigia e defende esse servidor.

---

## 2. O que fica no host x o que fica na VM

### Host (Linux Mint) — gateway e infraestrutura
- **AP Wi-Fi:** `hostapd` + bridge `br0` (o rádio físico só existe aqui).
- **`dnsmasq`:** DHCP e DNS do segmento (entrega o próprio host como gateway/DNS).
- **Firewall `nftables`:** conjunto `autorizados`, NAT/masquerade e redirect da porta 80 para o portal.
- **Portal cativo:** `portal.py` (Flask), `firewall_ctl.py`, `ressync.py`.
- **Banco MySQL `vigia_de_rede`:** fica junto de quem escreve nele (portal e agente).
- **Agente Sentinela:** classes `Scanner`, `Repositorio`, `Whitelist`, `Alerta`.
- **VirtualBox** (hipervisor) + scripts Python de provisionamento (`VBoxManage`).
- **WireGuard** (a VPN de acesso remoto termina no gateway).
- **Backups** do banco + scripts de restore.

> A VM **Kali/Parrot** da Fase 6 também roda sob o VirtualBox, mas entra na `br0` como **convidado atacante**, não como infraestrutura.

### VM (Windows Server) — o cliente protegido, "servidor da casa"
- **Windows Server 2019+.**
- **Serviço da casa** exigido pelo roteiro (painel, app ou jogo) — razão de existir da VM.
- **RDP exposto** — alvo da demo de acesso remoto (celular → RDP na VM).
- **Nada de rede ou segurança:** recebe IP do `dnsmasq`, obedece ao firewall do host e é varrida pelo Sentinela como qualquer dispositivo.

### Erro comum a evitar
Não colocar o Sentinela (nem o banco, nem o firewall) **dentro** da VM. A VM é uma folha pendurada na `br0` — não vê o tráfego dos outros dispositivos nem controla o firewall do segmento. Monitoramento e firewall só funcionam de onde todo o tráfego passa: o host.

> Atenção à distinção de **dois painéis diferentes**: o *painel da casa* (serviço do roteiro) fica na VM; se o Sentinela tiver tela própria de relatórios, ela fica no host, junto do banco e do agente.

---

## 3. Mapa requisito → onde é atendido

| Bloco do roteiro | Como o Sentinela atende | Onde |
|---|---|---|
| **Computer Architecture (CASEMOD)** | Servidor físico com casemod, BIOS, boot, Windows 10 + Linux, partição para VMs | Host físico |
| **Server & Data Center Admin** | VM Windows Server sob VirtualBox hospedando o serviço da casa | VM |
| **Computer Network** | AP + bridge, DHCP/DNS, segmento isolado, RDP, firewall | Host |
| **Cyber Security** | Firewall com whitelist, VPN (WireGuard), varredura Nmap, logs, backups, VM Kali/Parrot | Host |
| **Algorithmic Thinking & OOP** | Agente em classes, portal em Flask, automação em Python | Host |
| **Development Tools** | Versionamento Git/GitHub (`sentinela_script`) | Host |
| **Cloud (opcional)** | Não adotado como core — backup local escolhido; nuvem fica como extensão futura | — |

---

## 4. Estrutura do repositório

```
sentinela_script/
├── network/        # hostapd.conf, dnsmasq.conf, firewall.nft, scripts de subida do AP
├── provision/      # automação VBoxManage (criar/configurar a VM via subprocess)
├── captive/        # portal cativo: portal.py, firewall_ctl.py, ressync.py
├── sentinela/      # agente: Scanner, Repositorio, Whitelist, Alerta
├── security/       # backup.sh, restore.sh, WireGuard, hardening
├── sql/            # schema.sql
├── docs/           # diário técnico + relatório
├── requirements.txt
└── README.md
```

---

## 5. Fases de construção (ordem de execução)

**Caminho crítico: Fase 1 → Fase 2 → Fase 5.** Sem a rede, a VM não conecta; sem rede e VM, o agente não tem o que monitorar. Se o tempo apertar, essas três são as inegociáveis.

### Fase 0 — Preparar host e repositório
- Atualizar o Mint e instalar: `virtualbox`, `hostapd`, `dnsmasq`, `mysql-server`, `nmap`, `arp-scan`, `python3`, `python3-venv`, `git`.
- Criar o repositório `sentinela_script` com a estrutura de pastas e o primeiro commit.
- Criar `.venv` e `requirements.txt` (mínimo: `mysql-connector-python`, `flask`).

### Fase 1 — Rede controlada (a fundação)
- Subir o AP com `hostapd`, colocar a interface numa bridge `br0`.
- `dnsmasq` entregando DHCP/DNS no segmento (ex.: `192.168.50.0/24`, host = `192.168.50.1`).
- NAT com `nftables` (masquerade) para o segmento alcançar a internet pela conexão do host.
- **Fixar o MAC do celular de teste para esta rede** (ver nota sobre MAC aleatório na Fase 1.5).
- *Pronto quando:* o celular conecta no SSID e pega IP.

### Fase 1.5 — Portal cativo (estende a Fase 1)
Depende do AP/firewall de pé e do banco (Fases 3–4) para gravar. Registro self-service na whitelist. Código completo na **Seção 7**.

### Fase 2 — VM Windows Server automatizada
- Com a `br0` de pé, a VM entra como mais um host do segmento.
- Provisionamento em Python (`provision/`) envelopando `VBoxManage` via `subprocess`:
  `createvm` → `modifyvm` (com `--bridgeadapter1` apontando pra `br0`) → `storagectl`/`storageattach` → `unattended install` com arquivo de resposta (instala o Windows Server sem clique).
- A VM hospeda o serviço da casa e expõe o RDP.
- *Pronto quando:* RDP do celular na VM funciona (conectividade ponta a ponta sem roteador da faculdade).

### Fase 3 — Banco de dados
- Instalar e proteger o MySQL (`mysql_secure_installation`).
- Criar usuário dedicado `sentinela` (nunca usar root no agente/portal).
- Rodar o schema da Fase 4.

### Fase 4 — Schema do banco (idempotente)
Arquivo `sql/schema.sql`. Código completo na **Seção 6**.

### Fase 5 — Agente Sentinela (o núcleo)
Aqui mora o pensamento algorítmico e o OOP exigidos. Classes explícitas:
- `Scanner` — roda `nmap`/`arp-scan` e faz o parse.
- `Repositorio` — fala com o MySQL.
- `Whitelist` — consulta `autorizado`.
- `Alerta` — monta e dispara os avisos.

**Loop de cada ciclo:** abre uma varredura em `TB_VARREDURAS` → grava cada dispositivo visto em `TB_PRESENCAS` (criando o cadastro em `TB_DISPOSITIVOS` se o MAC for novo) → grava as portas em `TB_PORTAS` → compara com o ciclo anterior → dispara alerta para MAC fora da whitelist e para porta nova → persiste em `TB_ALERTAS` e notifica (log + e-mail).

Fecha os requisitos de "logs de segurança", "monitoramento" e uso do Nmap.

### Fase 6 — Segurança e hardening
- **VPN de acesso remoto (WireGuard)** terminando no host — acesso legítimo à "casa" de fora da rede.
- Regras de firewall documentadas, senhas fortes, DNS seguro.
- **Backup automático local + restore testado** (Seção 8).
- **VM Kali/Parrot** na `br0` rodando testes de vulnerabilidade contra a própria rede → material direto pro relatório.

### Fase 7 — Documentação e ensaio
- Diário técnico mantido **desde a Fase 0** (não no fim).
- Ensaio cronometrado da demo: subir rede → ligar VM → RDP → provocar um alerta ao vivo (conectar dispositivo fora da whitelist e mostrar o Sentinela acusando) → mostrar o registro no banco.

---

## 6. Schema do banco (`sql/schema.sql`)

Modelo normalizado. A chave é a **`TB_PRESENCAS`**: dispositivo é o "quem" (cadastro durável, identidade = MAC), varredura é o "quando", presença é "esse quem apareceu nesse quando, com esse IP e essas portas". Com isso o Sentinela responde nativamente: quem é novo, quem sumiu, e que porta abriu em quem.

`IF NOT EXISTS` em tudo → rodar o arquivo de novo não dá erro nem recria nada (só cria o que falta). *Observação:* `IF NOT EXISTS` checa só a existência pelo nome — não compara colunas. Alteração de schema posterior vai por `ALTER TABLE`, não por recriar.

```sql
CREATE DATABASE IF NOT EXISTS vigia_de_rede CHARACTER SET utf8mb4;
USE vigia_de_rede;

-- Catálogo de dispositivos: identidade = MAC. É aqui que mora a whitelist.
CREATE TABLE IF NOT EXISTS TB_DISPOSITIVOS (
    id_dispositivo   INT AUTO_INCREMENT PRIMARY KEY,
    endereco_mac     VARCHAR(17) NOT NULL UNIQUE,
    nome_dispositivo VARCHAR(100),
    tipo_dispositivo VARCHAR(50),
    autorizado       BOOLEAN NOT NULL DEFAULT FALSE,   -- TRUE = na whitelist
    primeiro_visto   DATETIME,
    ultimo_visto     DATETIME,
    status           ENUM('ativo','inativo','desconhecido') DEFAULT 'desconhecido'
) ENGINE=InnoDB;

-- Cada ciclo de varredura
CREATE TABLE IF NOT EXISTS TB_VARREDURAS (
    id_varredura            INT AUTO_INCREMENT PRIMARY KEY,
    data_varredura          DATETIME NOT NULL,
    quantidade_dispositivos INT,
    total_portas            INT,
    total_alertas           INT,
    resultado_geral         VARCHAR(50),
    resumo                  TEXT
) ENGINE=InnoDB;

-- Quais dispositivos apareceram em cada varredura, e com qual IP na hora
CREATE TABLE IF NOT EXISTS TB_PRESENCAS (
    id_presenca    INT AUTO_INCREMENT PRIMARY KEY,
    id_varredura   INT NOT NULL,
    id_dispositivo INT NOT NULL,
    endereco_ip    VARCHAR(45),
    FOREIGN KEY (id_varredura)   REFERENCES TB_VARREDURAS(id_varredura),
    FOREIGN KEY (id_dispositivo) REFERENCES TB_DISPOSITIVOS(id_dispositivo)
) ENGINE=InnoDB;

-- Portas abertas num dispositivo específico, numa varredura específica
CREATE TABLE IF NOT EXISTS TB_PORTAS (
    id_porta      INT AUTO_INCREMENT PRIMARY KEY,
    id_presenca   INT NOT NULL,
    numero_porta  INT,
    protocolo     ENUM('tcp','udp'),
    servico       VARCHAR(100),
    status_porta  VARCHAR(20),
    FOREIGN KEY (id_presenca) REFERENCES TB_PRESENCAS(id_presenca)
) ENGINE=InnoDB;

-- Alertas gerados (ligados à varredura e, quando aplicável, ao dispositivo)
CREATE TABLE IF NOT EXISTS TB_ALERTAS (
    id_alerta      INT AUTO_INCREMENT PRIMARY KEY,
    id_varredura   INT NOT NULL,
    id_dispositivo INT,
    tipo_alerta    VARCHAR(50),
    descricao      TEXT,
    nivel_risco    ENUM('baixo','medio','alto','critico'),
    data_alerta    DATETIME,
    FOREIGN KEY (id_varredura)   REFERENCES TB_VARREDURAS(id_varredura),
    FOREIGN KEY (id_dispositivo) REFERENCES TB_DISPOSITIVOS(id_dispositivo)
) ENGINE=InnoDB;
```

> **Por que `ENGINE=InnoDB`:** o MyISAM aceita a sintaxe de foreign key mas a **ignora silenciosamente** — a integridade referencial vira decorativa. No InnoDB a FK é de fato aplicada (bloqueia registro órfão, impede apagar pai com filhos). Conferir com `SHOW TABLE STATUS FROM vigia_de_rede;` — a coluna `Engine` deve dizer `InnoDB` em todas.

---

## 7. Módulo `captive/` — portal cativo

**Conceito:** o firewall mantém um **conjunto (set) de MACs autorizados** no nftables. Uma única regra diz "quem está no conjunto passa; o resto cai". Liberar alguém = jogar o MAC no conjunto; bloquear = tirar. O conjunto é a whitelist viva; o banco é a fonte da verdade durável.

O portal é o **caminho de escrita** da whitelist: o dispositivo se registra sozinho (senha compartilhada), o portal mostra o MAC capturado, grava em `TB_DISPOSITIVOS` com `autorizado = TRUE` e libera no firewall. Android/iOS abrem a tela de login automaticamente (captive portal detection via HTTP) — a UX simplificada vem de graça do sistema operacional.

> **Nota sobre MAC aleatório:** Android/iOS usam por padrão um MAC **aleatório mas estável por SSID** — consistente naquela rede entre reconexões, então o registro funciona. O único cenário que quebra é a *rotação periódica* do MAC (Android 12+, não é o padrão). No celular de teste, garantir o modo "fixo/estável para esta rede".

### 7.1 Firewall (`captive/firewall.nft`) — roda uma vez, no boot

```nft
#!/usr/sbin/nft -f
# captive/firewall.nft

table inet portal {
    set autorizados {
        type ether_addr          # a whitelist viva
    }

    chain forward {
        type filter hook forward priority filter; policy drop;
        ct state established,related accept
        ether saddr @autorizados accept
        # quem não está no conjunto cai aqui (policy drop)
    }

    chain prerouting {
        type nat hook prerouting priority dstnat; policy accept;
        # HTTP de quem NÃO está autorizado vai pro portal Flask (porta 8080 no host)
        iifname "br0" ether saddr != @autorizados tcp dport 80 redirect to :8080
    }

    chain postrouting {
        type nat hook postrouting priority srcnat; policy accept;
        oifname != "br0" masquerade
    }
}
```

> DNS e DHCP não precisam de regra de liberação: o `dnsmasq` entrega o próprio host como servidor, então essas consultas vão *pro host* (input), não são encaminhadas, e passam mesmo com o `forward` em `drop`. A detecção de portal bate em HTTP (porta 80), capturada pelo `redirect`; HTTPS fica de fora de propósito (evita erro de certificado).

### 7.2 Liberar/revogar (`captive/firewall_ctl.py`)

```python
# captive/firewall_ctl.py
import subprocess

def liberar_mac(mac: str) -> None:
    subprocess.run(["sudo", "nft", "add", "element", "inet", "portal",
                    "autorizados", "{ " + mac + " }"], check=True)

def revogar_mac(mac: str) -> None:
    subprocess.run(["sudo", "nft", "delete", "element", "inet", "portal",
                    "autorizados", "{ " + mac + " }"], check=True)
```

> O Flask **não** roda como root. Criar uma entrada estreita no `sudoers` permitindo ao usuário do portal rodar **só** o `nft` sem senha. Princípio do menor privilégio — bom ponto pro relatório.

### 7.3 Rota do portal (`captive/portal.py`)

```python
# captive/portal.py
import re, subprocess
from datetime import datetime
from flask import Flask, request, render_template_string
import mysql.connector
from firewall_ctl import liberar_mac

app = Flask(__name__)
SENHA_REDE = "troque-esta-senha"   # senha compartilhada do portal

def mac_do_ip(ip: str) -> str | None:
    saida = subprocess.run(["ip", "neigh", "show", ip],
                           capture_output=True, text=True).stdout
    m = re.search(r"lladdr ([0-9a-f:]{17})", saida)
    return m.group(1) if m else None

def conectar():
    return mysql.connector.connect(host="127.0.0.1", user="sentinela",
                                   password="...", database="vigia_de_rede")

PAGINA = """
<h2>Registrar dispositivo na rede</h2>
<p>Seu endereço (MAC): <b>{{ mac }}</b></p>
{% if erro %}<p style="color:red">{{ erro }}</p>{% endif %}
<form method="post" action="/registrar">
  <input name="nome" placeholder="Nome do dispositivo"><br>
  <input name="senha" type="password" placeholder="Senha da rede"><br>
  <button type="submit">Registrar</button>
</form>
"""

@app.route("/", methods=["GET"])
def portal():
    mac = mac_do_ip(request.remote_addr)
    if not mac:
        return "Não consegui identificar seu dispositivo. Reconecte à rede.", 400
    return render_template_string(PAGINA, mac=mac, erro=None)

@app.route("/registrar", methods=["POST"])
def registrar():
    mac = mac_do_ip(request.remote_addr)
    if not mac:
        return "Dispositivo não identificado.", 400
    if request.form.get("senha", "") != SENHA_REDE:
        return render_template_string(PAGINA, mac=mac, erro="Senha incorreta."), 403

    cx = conectar(); cur = cx.cursor()
    cur.execute("""
        INSERT INTO TB_DISPOSITIVOS
            (endereco_mac, nome_dispositivo, autorizado, primeiro_visto, ultimo_visto, status)
        VALUES (%s, %s, TRUE, %s, %s, 'ativo')
        ON DUPLICATE KEY UPDATE
            autorizado = TRUE,
            nome_dispositivo = VALUES(nome_dispositivo),
            ultimo_visto = VALUES(ultimo_visto)
    """, (mac, request.form.get("nome", ""), datetime.now(), datetime.now()))
    cx.commit(); cur.close(); cx.close()

    liberar_mac(mac)   # entra no conjunto nftables; o próximo pacote já passa
    return "Dispositivo registrado! Já pode navegar."
```

> O `ON DUPLICATE KEY UPDATE` só funciona porque `endereco_mac` é `UNIQUE` no schema. O portal escuta na 8080, destino do redirect do firewall.

### 7.4 Ressincronização no boot (`captive/ressync.py`)

```python
# captive/ressync.py — roda no boot, DEPOIS do firewall.nft carregar
import mysql.connector
from firewall_ctl import liberar_mac

cx = mysql.connector.connect(host="127.0.0.1", user="sentinela",
                             password="...", database="vigia_de_rede")
cur = cx.cursor()
cur.execute("SELECT endereco_mac FROM TB_DISPOSITIVOS WHERE autorizado = TRUE")
for (mac,) in cur.fetchall():
    liberar_mac(mac)
cur.close(); cx.close()
```

> **Ordem no boot (amarrar com systemd `After=`):** `firewall.nft` (cria o conjunto vazio) → `ressync.py` (repovoa a partir do banco) → `portal.py` (sobe). *Banco é a fonte da verdade; o conjunto nftables é um espelho reconstruível dele.* Decisão de arquitetura que rende explicação boa na banca.

### 7.5 Vulnerabilidade a documentar (de propósito)
O esquema senha compartilhada + registro de MAC é **fraco por design**: um atacante pode clonar um MAC já registrado e furar a whitelist. Documentar essa limitação como vulnerabilidade conhecida é o tipo de análise madura que a avaliação valoriza.

---

## 8. Backup local + restore (`security/`)

**O restore é a parte que importa** — backup que nunca foi restaurado é só um arquivo que você torce pra funcionar. A banca pergunta "e se der problema, você recupera?".

### 8.1 Backup (`security/backup.sh`)

```bash
#!/usr/bin/env bash
# security/backup.sh
set -euo pipefail

BACKUP_DIR="/var/backups/sentinela"
RETENCAO_DIAS=7
STAMP=$(date +%Y-%m-%d_%H-%M-%S)
ARQUIVO="$BACKUP_DIR/vigia_de_rede_$STAMP.sql.gz"

mkdir -p "$BACKUP_DIR"

# --single-transaction: dump consistente sem travar as tabelas InnoDB
mysqldump --single-transaction --user=sentinela --password="..." \
    vigia_de_rede | gzip > "$ARQUIVO"

# apaga backups com mais de RETENCAO_DIAS
find "$BACKUP_DIR" -name "vigia_de_rede_*.sql.gz" -mtime +$RETENCAO_DIAS -delete

echo "Backup concluído: $ARQUIVO"
```

> `--single-transaction` tira o dump dentro de uma transação → backup consistente **sem travar** o banco (o Sentinela segue gravando). A rotação (`-mtime +7`) transforma "um script que roda" em "uma política de retenção".

### 8.2 Agendamento (cron)

```cron
# crontab -e  →  backup todo dia às 02:00
0 2 * * * /caminho/sentinela_script/security/backup.sh >> /var/log/sentinela_backup.log 2>&1
```

> O log serve duplamente: histórico de execução + evidência pro relatório.

### 8.3 Restore (`security/restore.sh`)

```bash
#!/usr/bin/env bash
# security/restore.sh
set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Uso: $0 <arquivo_de_backup.sql.gz>"
    echo "Disponíveis:"
    ls -1 /var/backups/sentinela/
    exit 1
fi

ARQUIVO="$1"
[ -f "$ARQUIVO" ] || { echo "Arquivo não encontrado: $ARQUIVO"; exit 1; }

echo "ATENÇÃO: isso vai sobrescrever o banco vigia_de_rede com '$ARQUIVO'."
read -p "Confirmar? (digite SIM): " confirma
[ "$confirma" = "SIM" ] || { echo "Cancelado."; exit 0; }

gunzip < "$ARQUIVO" | mysql --user=sentinela --password="..." vigia_de_rede
echo "Restore concluído a partir de: $ARQUIVO"
```

> **Ensaiar um restore de verdade antes da apresentação:** roda o backup, deixa o sistema rodar mais um pouco, restaura um backup anterior e confirma que voltou ao estado esperado. Dá a certeza de que os scripts funcionam ponta a ponta e uma história concreta pro relatório ("simulamos perda de dados e recuperamos a partir do backup das 02:00") — a simulação de incidente que o roteiro pede.

---

## 9. Decisões descartadas (e por quê)

Registrado para não revisitar:

- **Hotspot dentro da VM:** impossível — o VirtualBox não entrega o rádio Wi-Fi físico ao convidado; o AP só existe no host.
- **SGBD na VM "simulando nuvem":** descartado. VM na `br0` não é nuvem (mesmo segmento L2, um salto), e acoplaria o Sentinela ao que ele monitora (se a VM cai, o log para junto). Banco fica no host.
- **Backup em nuvem:** não adotado. Escolhido backup **local** com restore testado — resolve o requisito obrigatório sem peça nova pra falhar na demo. Nuvem permanece extensão futura opcional.

---

## 10. Checklist do ensaio final (Fase 7)

1. Subir a rede (AP + `br0` + `dnsmasq` + firewall).
2. Ligar a VM Windows Server.
3. Conectar o celular, registrar no portal cativo, confirmar liberação.
4. RDP do celular na VM.
5. **Provocar um alerta ao vivo:** conectar um dispositivo fora da whitelist e mostrar o Sentinela acusando.
6. Mostrar o registro no banco (varredura, presença, porta, alerta).
7. Simular incidente: restaurar um backup e confirmar a recuperação.
8. Conferir o diário técnico e os logs como evidência.