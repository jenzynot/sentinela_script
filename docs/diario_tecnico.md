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
