# Diário técnico — Projeto Sentinela

Registro cronológico das decisões, problemas e evidências do projeto. Mantido desde a Fase 0 (não escrito no fim).

Formato de cada entrada: **o que foi feito**, **decisões e por quê**, **problemas encontrados**, **próximos passos**.

---

## 2026-11-09 — Fase 0: preparar host e repositório

### O que foi feito
- Criada a estrutura de pastas do repositório `sentinela_script` (`network/`, `provision/`, `captive/`, `sentinela/`, `security/`, `sql/`, `docs/`).
- `requirements.txt` com o mínimo: `mysql-connector-python` e `flask`.
- `setup_host.sh`: script idempotente que prepara o host Mint (atualização, pacotes, `.venv`, verificação).
- `.env.example`: modelo das credenciais (MySQL, senha do portal, segmento de rede). O `.env` real fica fora do Git.
- `.gitignore` e `.gitattributes` (fim de linha LF forçado).
- Primeiro commit.

### Decisões e por quê
- **Pacotes além da lista do planejamento:** `nftables` (garantir o firewall da Fase 1 mesmo em instalação mínima), `iw` (verificar se a placa Wi-Fi suporta modo AP) e `python3-pip`.
- **`hostapd` e `dnsmasq` desabilitados após a instalação:** o `dnsmasq` padrão tenta ouvir na porta 53 em todas as interfaces e entra em conflito com o `systemd-resolved`. Os dois só sobem na Fase 1, já configurados para a `br0`.
- **Usuário comum no grupo `vboxusers`:** necessário para o `VBoxManage` da Fase 2 sem root.
- **`.venv` criado como usuário comum, não root:** o portal e o agente não rodam como root (menor privilégio).
- **Senhas fora do código:** os trechos do planejamento usam `password="..."` direto no código; o projeto vai ler do `.env`, que não é versionado.
- **LF forçado via `.gitattributes`:** o repositório também é editado pelo Windows (via `\\wsl.localhost`), e um `.sh` com CRLF quebra no Linux.

### Problemas encontrados
- O desenvolvimento acontece no WSL (Ubuntu), não no host Mint. A instalação dos pacotes de sistema foi empacotada em `setup_host.sh` para rodar no Mint real.
- O WSL não tem `python3-venv` instalado (`ensurepip` indisponível), então o `.venv` ainda não foi criado aqui. Para desenvolver no WSL: `sudo apt install python3-venv` e depois `python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`. No Mint, o `setup_host.sh` já cuida disso.

### Próximos passos
- [ ] Rodar `sudo ./setup_host.sh` no host Mint e registrar a saída aqui (principalmente o teste de modo AP).
- [ ] Criar o repositório remoto no GitHub e dar o primeiro push.
- [ ] Iniciar a Fase 1: `hostapd` + `br0` + `dnsmasq` + NAT com `nftables`.

---

## 2026-11-09 — CI de testes no GitHub Actions

### O que foi feito
- `python3-venv` instalado no WSL e `.venv` criado (pendência da Fase 0 resolvida).
- Montado o CI descrito em `planejamento_testes.md`: `.github/workflows/ci.yml` com 4 jobs (banco, firewall, rede simulada, portal) e a action local `.github/actions/preparar` (Python 3.12, `.venv`, pacotes apt, usuário `sentinela` no MySQL).
- Para os testes terem o que testar, o código que o planejamento já trazia pronto virou arquivo: `sql/schema.sql`, `captive/firewall.nft`, `captive/firewall_ctl.py`, `captive/portal.py`, `captive/ressync.py` e `captive/dados.py` (acesso ao banco).
- Suíte pytest em `tests/`, um marker por job, casos no formato dado → quando → então.

### Decisões e por quê
- **Pulado localmente, falha no CI:** sem MySQL, `nft` ou root o teste é pulado (WSL), mas com `CI=true` ele falha. Um pipeline verde precisa significar "testado", não "não rodou".
- **MySQL 8.0 como service container**, com healthcheck via TCP (`-h 127.0.0.1`): o ping pelo socket responde ainda durante a inicialização temporária do container.
- **Schema aplicado pelo cliente `mysql`**, igual se faz no host, e não pelo conector Python.
- **Código usa o usuário `sentinela`** (só SELECT/INSERT/UPDATE/DELETE); o root só é usado pelos testes para recriar o banco.
- **`firewall.nft` idempotente** (`table` + `delete table` antes da definição): recarregar não duplica regras. O conjunto renasce vazio e o `ressync` o repovoa.
- **`firewall_ctl` endurecido:** valida o formato do MAC (impede injetar sintaxe nft, ex. `"aa:..., bb:..."` liberaria dois de uma vez), revogar MAC ausente não é erro, e `sincronizar()` faz `flush` + `add` numa única transação nft (ressync deixa o conjunto *exatamente* igual ao banco).
- **Portal:** senha vem de `PORTAL_SENHA`; sem ela configurada ninguém se registra (falha fechada); comparação com `hmac.compare_digest` (tempo constante).
- **Credenciais pelo ambiente** (`MYSQL_*`), não no código.
- **Agente (Fase 5) como contrato:** os testes do Scanner e dos alertas já existem e ficam pulados até `sentinela/` ser criado. A interface esperada está no topo de `tests/test_rede.py`.

### Problemas encontrados
- O WSL não tem MySQL, `nft`, `nmap` nem `arp-scan`: localmente só deu para validar coleta, sintaxe e a lógica de pular/falhar (36 testes pulados). A execução real acontece no primeiro push.

### Próximos passos
- [ ] Criar o repositório no GitHub, dar push e acompanhar a primeira execução do CI.
- [ ] Fase 1: `hostapd` + `br0` + `dnsmasq` no Mint.
