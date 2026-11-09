# Sentinela — Especificação de Testes

> O que cada teste precisa validar, e **onde** cada um pode rodar.
> Base para montar o workflow de CI (`.github/workflows/ci.yml`) e o roteiro de teste manual no Mint.

---

## 1. Princípio: três ambientes, três alcances

Cada teste pertence a uma camada, definida pela pergunta "isso depende de hardware físico?".

| Ambiente | Kernel / rede | Serve para |
|---|---|---|
| **WSL (Ubuntu)** | Kernel Microsoft, atrás de NAT | Escrever e iterar; testar só partes "puras" (banco, parser, lógica Flask) |
| **GitHub Actions** (`ubuntu-latest`) | Linux real, kernel real, root via sudo | **CI automatizado** — banco, firewall nftables, rede simulada por namespaces, Sentinela ponta a ponta |
| **Mint bare-metal** | Linux nativo sobre o hardware | AP Wi-Fi, celular real, VM na bridge, teste integrado + demo |

**Regra de corte:** tudo *downstream* de "o cliente já está na `br0`" é testável no Actions. Tudo que é fisicamente preso ao rádio Wi-Fi, ao celular real ou à VM Windows fica só no Mint.

---

## 2. O que o CI (Actions) DEVE testar

### Job 1 — Banco de dados (schema + queries)
Sobe um MySQL real no runner e valida o modelo.

- **Idempotência do schema:** rodar `schema.sql` **duas vezes seguidas** não gera erro (prova o `IF NOT EXISTS`).
- **Engine correta:** após criar, toda tabela retorna `InnoDB` em `SHOW TABLE STATUS`.
- **Integridade referencial de fato aplicada:** inserir uma `TB_PRESENCAS` com `id_varredura` inexistente deve **falhar** (prova que a FK não é decorativa).
- **Unicidade do MAC:** inserir dois dispositivos com o mesmo `endereco_mac` deve falhar; o `ON DUPLICATE KEY UPDATE` do portal deve atualizar em vez de duplicar.
- **Queries do ciclo:** inserir varredura → presença → portas → alerta e reler, confirmando os JOINs que o relatório vai usar.

### Job 2 — Firewall / whitelist (nftables)
A mecânica que o WSL não conseguia validar. Roda com sudo no runner.

- **Carga do ruleset:** `nft -f firewall.nft` carrega sem erro; o conjunto `autorizados` existe e nasce vazio.
- **Liberar:** `liberar_mac()` insere o MAC → consultar o conjunto confirma que ele está lá.
- **Revogar:** `revogar_mac()` remove o MAC → o conjunto volta a não contê-lo.
- **Idempotência/robustez:** liberar um MAC já presente, ou revogar um ausente, não derruba o script.
- **Sincronização banco → firewall:** popular `TB_DISPOSITIVOS` com N autorizados, rodar o `ressync.py`, e confirmar que os N MACs (e só eles) estão no conjunto. É o teste do padrão "banco é a verdade, conjunto é espelho reconstruível".

### Job 3 — Rede simulada + Sentinela ponta a ponta
Usa **network namespaces + veth** para criar "dispositivos falsos" sem hardware.

- **Descoberta de dispositivo:** criar 2–3 namespaces com IPs numa bridge; o `Scanner` (arp-scan/nmap) tem que encontrar todos.
- **Leitura de MAC:** `mac_do_ip()` retorna o MAC correto do namespace a partir do IP (testa o parsing de `ip neigh`).
- **Detecção de porta:** subir um serviço numa porta conhecida dentro de um namespace; o `Scanner` tem que reportar aquela porta como aberta, e o parser do Nmap tem que capturá-la.
- **Alerta de dispositivo fora da whitelist:** um namespace com MAC **não** autorizado deve gerar registro em `TB_ALERTAS` com o tipo correto.
- **Alerta de porta nova:** rodar dois ciclos; na segunda varredura, abrir uma porta que não existia na primeira → o diff tem que gerar alerta de porta nova.
- **Ausência de falso positivo:** dispositivo autorizado e sem porta nova **não** pode gerar alerta.

### Job 4 — Lógica do portal (Flask)
Testa as rotas isoladas, sem rede real.

- **Senha errada:** POST em `/registrar` com senha incorreta retorna 403 e **não** grava no banco nem libera no firewall.
- **Senha certa:** grava o dispositivo com `autorizado = TRUE` e chama a liberação (a chamada ao firewall pode ser *mockada* neste job).
- **MAC não identificado:** se `mac_do_ip()` retorna vazio, a rota responde erro e não grava.

---

## 3. O que o CI NÃO consegue testar (fica no Mint bare-metal)

Listado para o relatório deixar claro o limite do CI e por quê:

- **Associação Wi-Fi (`hostapd`):** não há rádio no runner. O CI testa tudo **depois** que o cliente entrou na rede; a entrada em si é manual no Mint.
- **Captura do portal com celular real:** o redirect da porta 80 e o captive-portal-detection do Android/iOS só se provam com o aparelho de verdade.
- **VM Windows Server na bridge:** provisionar Windows desatendido dentro de CI é inviável (ISO, tempo, licença) — testar no Mint.
- **RDP ponta a ponta (celular → VM):** depende da VM e do Wi-Fi reais.
- **Demo ao vivo:** o Actions é headless; não é superfície de apresentação.

> Estes viram itens do **checklist de ensaio manual** (Fase 7 do planejamento), não do CI.

---

## 4. Formato sugerido de cada caso de teste

Para manter os testes legíveis e defensáveis, descrever cada um no padrão **dado → quando → então**:

```
Dado   um banco vazio com o schema aplicado
Quando  insiro uma presença referenciando uma varredura inexistente
Então   o MySQL rejeita a inserção (erro de foreign key)
```

---

## 5. Por que isso também conta como entrega

Montar este CI não é só contornar a limitação do WSL — ele **satisfaz o bloco Development Tools** do roteiro (Git/GitHub com automação) e vira evidência forte pro relatório: a cada push, o pipeline sobe um MySQL, carrega o `nftables`, cria dispositivos simulados e valida o Sentinela de ponta a ponta num Linux real. É maturidade de engenharia acima do esperado para 2º semestre.