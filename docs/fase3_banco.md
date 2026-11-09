# Fases 3 e 4 — Banco de dados

O MySQL fica **no host**, junto de quem escreve nele (portal e agente). O banco `vigia_de_rede` é a fonte da verdade da whitelist e o histórico de tudo o que o Sentinela viu.

## Instalação

```bash
nano .env                     # MYSQL_PASSWORD com 12+ caracteres
sudo ./instalar.sh banco
```

O `sql/setup_banco.sh` (chamado pela etapa) faz, de forma idempotente:

| Passo | Equivale a |
|---|---|
| Remove usuários anônimos, `root` remoto e o banco `test` | `mysql_secure_installation` (sem perguntas) |
| Avisa se o MySQL não estiver ouvindo só em `127.0.0.1` | — |
| Aplica `sql/schema.sql` | Fase 4 |
| Cria/sincroniza o usuário `sentinela` em `localhost` e `127.0.0.1` | — |
| `GRANT SELECT, INSERT, UPDATE, DELETE ON vigia_de_rede.*` | menor privilégio |
| Confere que todas as tabelas são InnoDB | FKs aplicadas de fato |

O `root` do MySQL continua autenticando **pelo socket** (`sudo mysql`): não existe senha de root para vazar. A senha do `sentinela` vai para o MySQL pela entrada padrão, nunca pela linha de comando.

## Modelo (Fase 4)

```
TB_DISPOSITIVOS (quem)  1 ──< TB_PRESENCAS >── 1  TB_VARREDURAS (quando)
   endereco_mac UNIQUE          endereco_ip                │
   autorizado = whitelist       │                          │
        │                       └──< TB_PORTAS             │
        └──────────────< TB_ALERTAS >──────────────────────┘
```

- Rodar `schema.sql` de novo não dá erro nem apaga nada (`IF NOT EXISTS`). Mudanças posteriores vão por `ALTER TABLE`.
- `ENGINE=InnoDB` em tudo: no MyISAM as FKs seriam aceitas e ignoradas.

## O que o CI prova (Job 1)

- Schema aplicado duas vezes sem erro, dados preservados.
- Todas as tabelas em InnoDB.
- FK recusa presença de varredura inexistente; MAC duplicado é recusado.
- Upsert do portal atualiza em vez de duplicar.
- JOINs do relatório (portas por dispositivo, alertas por varredura).
- `setup_banco.sh` roda duas vezes; o usuário criado lê/grava, mas **não** consegue `DROP TABLE` nem ler `mysql.user`; config perigosa (usuário root, senha curta/padrão, nome com aspas) é recusada.

## Consultas úteis

```bash
sudo mysql vigia_de_rede
```

```sql
-- whitelist
SELECT endereco_mac, nome_dispositivo, status, ultimo_visto FROM TB_DISPOSITIVOS WHERE autorizado;

-- últimos alertas
SELECT a.data_alerta, a.nivel_risco, a.tipo_alerta, a.descricao
FROM TB_ALERTAS a ORDER BY a.id_alerta DESC LIMIT 20;

-- portas abertas na última varredura
SELECT d.endereco_mac, p.endereco_ip, po.numero_porta, po.protocolo, po.servico
FROM TB_PORTAS po
JOIN TB_PRESENCAS p    ON p.id_presenca = po.id_presenca
JOIN TB_DISPOSITIVOS d ON d.id_dispositivo = p.id_dispositivo
WHERE p.id_varredura = (SELECT MAX(id_varredura) FROM TB_VARREDURAS);
```
