# Fase 7 — Roteiro do ensaio e da demo

Ensaiar **cronometrado**, pelo menos duas vezes, no Mint de verdade. Meta: **≤ 12 minutos** de demo.

## Antes de começar (checklist de bancada)

- [ ] Host ligado no uplink (cabo ou USB tethering) — **não** na placa do AP.
- [ ] `sudo ./instalar.sh verificar` → todos os serviços `active`.
- [ ] VM ligada e com IP: `.venv/bin/python -m provision.vm status` → `running · IP 192.168.50.10`.
- [ ] Celular de teste **já registrado** no portal (MAC fixo para a rede *Sentinela*).
- [ ] Segundo aparelho **não registrado** à mão (outro celular, notebook ou a VM Kali desligada).
- [ ] Terminais abertos no telão:
  1. `journalctl -fu sentinela-agente`
  2. `sudo mysql vigia_de_rede`
  3. livre (comandos)
- [ ] Um backup recente: `ls -lt /var/backups/sentinela | head -3`.
- [ ] Bateria dos celulares carregada; Wi-Fi do celular de teste **esquecendo** outras redes conhecidas da sala.

## Roteiro (com tempo)

| # | Min | Passo | O que mostrar / dizer |
|---|---|---|---|
| 1 | 0–1 | **Arquitetura** | "O host é o gateway; a VM é um cliente protegido." Diagrama do README. |
| 2 | 1–2 | **Subir a rede** | `sudo systemctl restart sentinela.target` → `sudo ./instalar.sh verificar`. Bridge, AP, DHCP e firewall `active`. |
| 3 | 2–3 | **VM ligada** | `python -m provision.vm status`. Abrir `http://192.168.50.10` no celular: Painel da Casa. |
| 4 | 3–5 | **Portal cativo** | Celular *novo* (ou o de teste após revogar) conecta → tela do portal abre sozinha → senha errada (403) → senha certa → navega. `sudo nft list set inet portal autorizados`. |
| 5 | 5–6 | **RDP celular → VM** | App Remote Desktop → `192.168.50.10`. Mostrar a área de trabalho do Windows Server. |
| 6 | 6–8 | **Alerta ao vivo** | Conectar o aparelho **não registrado**. No terminal 1, no próximo ciclo: `[ALTO] dispositivo_nao_autorizado …`. Ele não navega (forward em drop). |
| 7 | 8–9 | **Registro no banco** | Consultas abaixo: varredura → presença → porta → alerta. |
| 8 | 9–11 | **Incidente + restore** | Apagar os alertas → restaurar o backup → alertas de volta. |
| 9 | 11–12 | **Evidências** | CI verde no GitHub (cada push sobe MySQL, nftables e rede simulada), diário técnico, `docs/seguranca.md` (vulnerabilidades conhecidas). |

### Passo 7 — consultas prontas

```sql
-- última varredura
SELECT id_varredura, data_varredura, quantidade_dispositivos, total_portas, total_alertas, resumo
FROM TB_VARREDURAS ORDER BY id_varredura DESC LIMIT 1;

-- quem estava presente e com quais portas
SELECT d.endereco_mac, d.nome_dispositivo, d.autorizado, p.endereco_ip,
       GROUP_CONCAT(po.numero_porta ORDER BY po.numero_porta) AS portas
FROM TB_PRESENCAS p
JOIN TB_DISPOSITIVOS d  ON d.id_dispositivo = p.id_dispositivo
LEFT JOIN TB_PORTAS po  ON po.id_presenca = p.id_presenca
WHERE p.id_varredura = (SELECT MAX(id_varredura) FROM TB_VARREDURAS)
GROUP BY p.id_presenca;

-- alertas recentes
SELECT data_alerta, nivel_risco, tipo_alerta, descricao
FROM TB_ALERTAS ORDER BY id_alerta DESC LIMIT 5;
```

### Passo 8 — incidente simulado

```bash
sudo /opt/sentinela/security/backup.sh                     # anote o arquivo
sudo mysql vigia_de_rede -e "DELETE FROM TB_ALERTAS"       # "perdemos os logs de segurança"
sudo mysql vigia_de_rede -e "SELECT COUNT(*) FROM TB_ALERTAS"
sudo /opt/sentinela/security/restore.sh /var/backups/sentinela/<arquivo>   # digite SIM
sudo mysql vigia_de_rede -e "SELECT COUNT(*) FROM TB_ALERTAS"             # voltaram
```

## Plano B (se algo falhar ao vivo)

| Falhou | Plano B |
|---|---|
| Wi-Fi não sobe | `journalctl -u sentinela-ap -n 30`; trocar `WIFI_CANAL`; em último caso mostrar o CI (Job 3 prova o agente numa rede simulada). |
| Portal não abre sozinho | Abrir `http://neverssl.com` no celular (HTTP puro) — o redirect leva ao portal. |
| RDP lento/sem conexão | Mostrar o Painel da Casa no navegador (prova a conectividade) e o `nmap -p 3389 192.168.50.10`. |
| Alerta demora | `sudo /opt/sentinela/.venv/bin/python -m sentinela --uma-vez` força um ciclo na hora. |
| Banco inacessível | `sudo systemctl status mysql`; os logs em `/var/log/sentinela/sentinela.log` também têm os alertas. |

## Depois de cada ensaio

- Anotar o tempo de cada passo e o que travou no **diário técnico**.
- Guardar prints/saídas (portal no celular, alerta no terminal, consultas, restore) para o relatório.
