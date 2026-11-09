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

---

## 2026-11-09 — Fase 1: rede controlada

### O que foi feito
- `network/gerar_configs.py`: gera `hostapd.conf`, `dnsmasq.conf` e o drop-in do NetworkManager a partir do `.env`, validando tudo antes (SSID, tamanho da senha WPA, gateway dentro do segmento, faixa DHCP).
- `network/rede.sh subir|descer|status`: cria a `br0` com o IP do gateway, liga `ip_forward` e tira a placa Wi-Fi do NetworkManager.
- Units systemd (`systemd/`) agrupadas em `sentinela.target`: bridge → firewall → AP (`hostapd`) → DHCP/DNS (`dnsmasq`).
- `instalar.sh rede`: implanta o código em `/opt/sentinela`, copia o `.env` para `/etc/sentinela/sentinela.env`, gera as configs e sobe os serviços. `instalar.sh verificar` mostra o estado.
- CI ganhou o **Job 0** (unidade + `shellcheck` dos scripts) e as actions foram atualizadas (Node 24, runner `ubuntu-24.04` = base do Mint 22).
- Guia em `docs/fase1_rede.md`.

### Decisões e por quê
- **Instâncias próprias de `hostapd`/`dnsmasq`** (`sentinela-ap`, `sentinela-dhcp`) em vez dos serviços da distro: config isolada em `/etc/sentinela`, sem depender de `/etc/default/hostapd` nem do `/etc/dnsmasq.conf` global.
- **`dnsmasq` com `bind-interfaces` só na `br0`**: não disputa a porta 53 com o `systemd-resolved` do host.
- **DNS upstream fixo (`no-resolv` + `server=`)**: o segmento não herda o DNS da rede da faculdade/casa; escolha explícita (Cloudflare + Quad9 por padrão).
- **`ap_isolate=1`**: clientes Wi-Fi não se falam direto pelo rádio; tudo passa pela `br0`.
- **Código em `/opt/sentinela`**: o usuário de serviço `sentinela` (portal) não consegue ler `/home/<usuário>`; a cópia em `/opt` resolve e separa "repositório de trabalho" de "instalação".
- **Geração de config em Python, não `envsubst`**: precisa de lógica (rede aberta × WPA2, reserva da VM) e de validação — e assim é testável no CI.
- **Recusa de quebra de linha no SSID/senha**: sem isso, `WIFI_SSID="x\nwpa=0"` injetaria diretivas no `hostapd.conf`.

### Problemas encontrados
- Nada testável em hardware ainda: a validação real (celular pega IP) depende do Mint com a placa em modo AP.

### Próximos passos
- [ ] No Mint: preencher o `.env`, `sudo ./instalar.sh rede` e confirmar o celular pegando IP.

---

## 2026-11-09 — Fase 1.5: portal cativo

### O que foi feito
- Portal responde a **qualquer caminho em GET** com a página de registro: é o que faz Android (`/generate_204`), iOS (`/hotspot-detect.html`) e Windows (`/connecttest.txt`) abrirem a tela do portal sozinhos.
- Página adaptada ao celular (viewport, campos grandes) e tela de sucesso mostrando o MAC liberado.
- Nome do dispositivo cortado em 100 caracteres (tamanho da coluna — o MySQL em modo estrito recusaria).
- `captive/sudoers.sentinela` + etapa `instalar.sh portal`: valida o sudoers com `visudo -c`, confere o acesso ao banco como o usuário de serviço e sobe `sentinela-ressync` + `sentinela-portal`.
- Guia em `docs/fase1_5_portal.md`; testes novos no Job 4 (detecção de portal, nome longo).

### Decisões e por quê
- **Responder a página em vez de redirecionar (302):** um passo a menos; o POST para `/registrar` também passa pelo redirect do firewall e funciona.
- **Etapa `portal` exige o banco:** o portal grava em `TB_DISPOSITIVOS`; sem banco ele subiria e quebraria no primeiro registro. Falhar cedo, na instalação, com a instrução `sudo ./instalar.sh banco`.

### Próximos passos
- [ ] No Mint (depois da Fase 3): `sudo ./instalar.sh portal` e registrar o celular de teste.

---

## 2026-11-09 — Fase 2: VM Windows Server automatizada

### O que foi feito
- `provision/vbox.py`: envelope do `VBoxManage` com executor injetável (nos testes, um falso grava os comandos).
- `provision/vm.py`: `criar → instalar → aguardar → configurar → autorizar` (e `status`, `iniciar`, `parar`, `destruir`, `imagens`), tudo a partir do bloco `VM_*` do `.env`.
- A VM entra na `br0` com **MAC fixo**: o `dnsmasq` dá sempre o mesmo IP (`VM_IP`) e o MAC vai direto para a whitelist.
- Configuração interna da VM por `guestcontrol` + PowerShell: RDP com NLA, regra de firewall do Windows e IIS com o "Painel da Casa".
- 14 testes de unidade (Job 0) e guia em `docs/fase2_vm.md`.

### Decisões e por quê
- **Executor injetável:** VirtualBox não roda no runner do CI, mas a lógica (sequência de comandos, flags, idempotência, re-tentativas) é testável assim.
- **Senha por arquivo temporário 600** (`--password-file` / `--passwordfile`): na linha de comando ela apareceria no `ps` para qualquer usuário do host.
- **Validação da senha antes de instalar:** a política do Windows recusa senha fraca e a instalação desatendida trava sem mensagem — melhor falhar na hora com o motivo.
- **`aguardar` exige 3 leituras estáveis:** a instalação reinicia o Windows algumas vezes; uma leitura isolada pode cair no meio de um reboot.
- **PowerShell via `-EncodedCommand`:** evita escapar aspas e acentos entre Python → VBoxManage → Windows.
- **Regra de RDP pelo ID neutro (`@FirewallAPI.dll,-28752`):** o nome "Remote Desktop" muda conforme o idioma da ISO.
- **Rodar como usuário comum (recusa root):** VMs do VirtualBox pertencem ao usuário que as cria; como root, a VM some da interface do usuário.
- **Painel da casa = página no IIS (placeholder):** o roteiro deixa a escolha (painel, app ou jogo) para a equipe; o caminho para trocar está na própria página.

### Problemas encontrados
- Instalação real do Windows não é testável no CI (ISO, tempo, licença) — fica no roteiro manual do Mint.

### Próximos passos
- [ ] No Mint: baixar a ISO de avaliação, preencher `VM_*` e rodar `python -m provision.vm tudo`.
- [ ] Testar RDP do celular em `192.168.50.10`.

---

## 2026-11-09 — Fases 3 e 4: banco de dados

### O que foi feito
- `sql/setup_banco.sh`: versão automática do `mysql_secure_installation` (remove anônimos, root remoto e o banco `test`), aplica o `schema.sql`, cria/sincroniza o usuário `sentinela` e confere que tudo é InnoDB.
- Etapa `instalar.sh banco`, que ainda confirma o login do usuário de serviço com as credenciais do `.env`.
- O schema (Fase 4) já existia desde o CI; agora tem guia em `docs/fase3_banco.md`.
- Job 1 ganhou testes que rodam o `setup_banco.sh` de verdade contra o MySQL do CI.

### Decisões e por quê
- **Só DML para o usuário `sentinela`** (`SELECT/INSERT/UPDATE/DELETE`): portal e agente não precisam criar nem apagar tabela. O teste prova que `DROP TABLE` é negado.
- **Root do MySQL pelo socket:** no Mint, o `root` do MySQL autentica pelo usuário do sistema; não há senha de root para guardar nem vazar.
- **Senha pela entrada padrão do `mysql`**, nunca como argumento (`ps` mostraria). Escape de `\` e `'` testado com uma senha que tem os dois.
- **Recusa de config perigosa:** `MYSQL_USER=root`, senha curta ou a senha de exemplo do `.env.example`.
- **Variáveis para o CI** (`HOSTS_SENTINELA`, `MANTER_ROOT_REMOTO`): no container do CI as conexões chegam do IP da bridge do Docker, não de `localhost`. No host os padrões seguros valem.

### Próximos passos
- [ ] No Mint: `sudo ./instalar.sh banco`, depois `sudo ./instalar.sh portal`.

---

## 2026-11-09 — Fase 5: agente Sentinela

### O que foi feito
- Pacote `sentinela/` com as classes do planejamento: `Scanner`, `Repositorio`, `Whitelist`, `Alerta`, mais o orquestrador `Sentinela` e o `python -m sentinela` (loop, `--uma-vez`, log em arquivo + journald, encerra limpo no SIGTERM).
- O contrato que os testes do Job 3 definiram antes do agente existir foi cumprido: os testes que estavam pulados agora rodam contra namespaces reais no CI.
- Etapa `instalar.sh agente`: confere `arp-scan`/`nmap` e o banco, roda **um ciclo de teste** e só então sobe o serviço.
- Testes de unidade das regras (Job 0) com dublês de banco e scanner; guia em `docs/fase5_agente.md`.

### Decisões e por quê
- **arp-scan para descoberta, nmap para portas:** ARP enxerga quem bloqueia ping (Windows bloqueia por padrão); o nmap roda uma vez com todos os IPs.
- **Alerta de intruso na chegada, não a cada ciclo:** evita enxurrada de alertas iguais; sair e voltar alerta de novo.
- **Porta nova contra a última aparição do dispositivo**, não só o ciclo anterior: pega quem some e volta diferente.
- **Varredura fora da transação, notificação depois do commit:** banco não fica travado esperando o nmap; ninguém é avisado de algo que não ficou gravado.
- **Uma conexão por ciclo:** sem conexão longa para cair por `wait_timeout` do MySQL.
- **E-mail opcional e agrupado:** um e-mail por ciclo; sem SMTP configurado, só log + banco.

### Próximos passos
- [ ] No Mint: `sudo ./instalar.sh agente` e provocar um alerta com um aparelho não registrado.

---

## 2026-11-09 — Fase 6: segurança e hardening

### O que foi feito
- Firewall endurecido: chain `input` com `policy drop` (o segmento só alcança DNS, DHCP e o portal no host; MySQL/SSH inacessíveis de fora), regra `wg0 → br0` para a VPN e masquerade só do segmento.
- `security/backup.sh` + `restore.sh` (do planejamento, com melhorias) e cron diário às 02:00 (`instalar.sh seguranca`).
- `security/wireguard.sh`: servidor + peers com QR code, túnel dividido e chave pré-compartilhada (`instalar.sh vpn`).
- `docs/seguranca.md`: firewall regra por regra, contas e privilégios, DNS seguro, VPN, backup, roteiro de testes com a Kali e tabela de vulnerabilidades conhecidas.
- CI: Job 1 ensaia o incidente (backup → estrago → restore → estado igual ao backup) a cada push; Job 2 confere a chain `input`.

### Decisões e por quê
- **Restore tira backup do estado atual antes de sobrescrever:** restore errado também precisa ter volta.
- **Backup só vale depois do `gzip -t`** (arquivo `.tmp` → `mv`): um dump interrompido nunca vira "o último backup".
- **Nome do backup com milissegundos:** sem isso, o backup de segurança do restore podia sobrescrever, no mesmo segundo, o arquivo sendo restaurado (achado ao escrever o teste).
- **Backup/restore como root pelo socket:** sem senha de banco em script nem em crontab.
- **VPN com túnel dividido:** o celular só desvia o tráfego da casa; não vira um proxy de toda a navegação.
- **Vulnerabilidades documentadas, não escondidas:** clonagem de MAC, senha compartilhada e o tráfego L2 dentro da `br0` (a tabela `inet` filtra o que é roteado, não o que é comutado na bridge) — com impacto e mitigação.

### Próximos passos
- [ ] No Mint: `sudo ./instalar.sh seguranca`, ensaiar um restore e guardar a saída como evidência.
- [ ] Rodar o roteiro da Kali e registrar os resultados no relatório.
