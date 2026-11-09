# Fase 5 — Agente Sentinela

O núcleo do projeto: um agente em Python orientado a objetos que, a cada ciclo, descobre quem está na rede, varre as portas, compara com o que viu antes e alerta.

## Classes

| Classe | Arquivo | Responsabilidade |
|---|---|---|
| `Scanner` | `sentinela/scanner.py` | `arp-scan` (quem está na rede, inclusive quem bloqueia ping) e `nmap` (portas abertas, saída XML); parsers das duas saídas |
| `Repositorio` | `sentinela/repositorio.py` | Toda a conversa com o MySQL; uma conexão e uma transação por ciclo |
| `Whitelist` | `sentinela/whitelist.py` | Carrega os MACs com `autorizado = TRUE` (gravados pelo portal) |
| `Alerta` | `sentinela/alerta.py` | Grava em `TB_ALERTAS`, escreve no log e (opcional) manda **um** e-mail por ciclo |
| `Sentinela` | `sentinela/agente.py` | Orquestra o ciclo |

## O ciclo

```
arp-scan br0 ──► [ (ip, mac), ... ]
nmap -sS --top-ports 1000 (todos os IPs de uma vez) ──► { ip: [portas] }
                              │
            ┌─────────────────▼──────────────────┐   uma transação
            │ TB_VARREDURAS  ← abre a varredura   │
            │ para cada dispositivo:              │
            │   TB_DISPOSITIVOS ← cadastra/atualiza (MAC novo = cadastro novo)
            │   TB_PRESENCAS    ← "este MAC, neste IP, nesta varredura"
            │   TB_PORTAS       ← portas abertas
            │   fora da whitelist e acabou de chegar? → ALERTA alto
            │   porta que não existia na última vez?  → ALERTA (alto se 21/23/445/3306/3389/5900)
            │ quem sumiu → status 'inativo'       │
            │ TB_VARREDURAS  ← totais + resumo    │
            └─────────────────┬──────────────────┘   commit (ou rollback total)
                              ▼
                  e-mail com os alertas do ciclo
```

### Regras de alerta (e por quê)

- **Dispositivo não autorizado alerta quando chega**, não a cada ciclo em que continua na rede. Um intruso parado não gera uma enxurrada; se ele sair e voltar, alerta de novo.
- **Porta nova compara com a última vez em que aquele dispositivo foi visto** (não só com o ciclo anterior): um notebook que some por uma hora e volta com o RDP aberto é pego.
- **Primeira aparição não gera "porta nova"**: não há base de comparação. O alerta de não autorizado cobre o dispositivo desconhecido.
- **Varredura antes da transação:** o `nmap` pode levar minutos; o banco só é tocado com os dados prontos.
- **Notificação depois do commit:** nada é avisado sem estar gravado. Falha no e-mail não derruba o agente.

## Instalação

```bash
sudo ./instalar.sh agente
```

Roda um ciclo de teste em primeiro plano (se falhar, mostra o motivo e não instala) e depois sobe o `sentinela-agente.service`, como root, porque `arp-scan` e `nmap -sS` usam pacotes crus.

Uso manual:

```bash
sudo /opt/sentinela/.venv/bin/python -m sentinela --uma-vez      # um ciclo (demo)
sudo /opt/sentinela/.venv/bin/python -m sentinela --intervalo 30
```

Configuração no `.env`: `SENTINELA_INTERVALO`, `SENTINELA_PORTAS`, `SENTINELA_LOG` e o bloco `SMTP_*`.

## Critério de pronto (e demo ao vivo)

1. `journalctl -fu sentinela-agente` aberto no telão.
2. Conectar um aparelho **não registrado** no Wi-Fi.
3. No próximo ciclo: `[ALTO] dispositivo_nao_autorizado: MAC aa:bb:… (192.168.50.1xx) fora da whitelist — nunca visto antes`.
4. Mostrar no banco:
   ```sql
   SELECT v.data_varredura, a.nivel_risco, a.tipo_alerta, a.descricao
   FROM TB_ALERTAS a JOIN TB_VARREDURAS v USING (id_varredura)
   ORDER BY a.id_alerta DESC LIMIT 5;
   ```
5. Bônus: abrir uma porta nova na VM (ex.: compartilhamento de arquivos → 445) e mostrar o `porta_nova` de risco alto.

## O que o CI prova

- **Job 3 (Linux real, namespaces + veth):** o `Scanner` acha os 3 dispositivos falsos com o MAC certo e a porta 80 aberta; dois ciclos reais do agente geram `dispositivo_nao_autorizado` para o intruso, `porta_nova` quando a porta abre, e **nenhum** alerta para o autorizado sem mudança; presenças e portas ficam gravadas.
- **Job 0 (unidade):** parsers (`arp-scan` com duplicatas, `nmap` com vários hosts), alerta só na chegada e de novo na volta, porta nova contra a última aparição, rollback total quando o banco falha no meio, um e-mail por ciclo mesmo com notificador quebrado.
