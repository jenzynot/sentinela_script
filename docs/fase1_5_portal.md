# Fase 1.5 — Portal cativo

Registro self-service na whitelist: o aparelho conecta, o sistema operacional abre a tela do portal, a pessoa digita a senha compartilhada e o MAC do aparelho é liberado no firewall.

## Como funciona

```
celular (MAC fora da whitelist)
  │  HTTP :80 (teste de conectividade do Android/iOS/Windows)
  ▼
nftables prerouting: ether saddr != @autorizados → redirect :8080
  ▼
portal.py (Flask, usuário "sentinela")
  │  mac_do_ip(IP) ← tabela ARP do host (`ip neigh`)
  │  senha confere? (hmac.compare_digest)
  ├─► TB_DISPOSITIVOS: autorizado = TRUE   (banco = fonte da verdade)
  └─► sudo nft add element … autorizados    (conjunto = espelho)
```

- **Detecção de portal:** Android (`/generate_204`), iOS (`/hotspot-detect.html`) e Windows (`/connecttest.txt`) testam a conexão por HTTP. Qualquer caminho em GET devolve a página de registro; como a resposta não é a esperada (204 / "Success"), o aparelho abre a tela do portal sozinho.
- **HTTPS fica de fora de propósito:** interceptar 443 geraria erro de certificado.
- **Boot:** `sentinela-firewall` (conjunto vazio) → `sentinela-ressync` (repovoa do banco) → `sentinela-portal`. Se o firewall for recarregado, o ressync roda de novo (`PartOf=`).

## Instalação

Precisa do banco (Fase 3) de pé:

```bash
sudo ./instalar.sh banco     # se ainda não rodou
sudo ./instalar.sh portal
```

O que a etapa faz:

1. Instala `/etc/sudoers.d/sentinela` (validado com `visudo -c`): o usuário `sentinela` só pode rodar `/usr/sbin/nft` como root.
2. Confere que o usuário `sentinela` consegue logar no MySQL com o `.env`.
3. Sobe `sentinela-ressync` e `sentinela-portal` (porta 8080).

## Critério de pronto

1. Celular conecta no SSID → aparece "Fazer login na rede" (Android) / a folha do portal (iOS).
2. A página mostra o MAC do aparelho. Senha errada → "Senha incorreta" (nada gravado).
3. Senha certa → "Dispositivo registrado!" e o celular navega.
4. Evidência:
   ```bash
   sudo nft list set inet portal autorizados
   sudo mysql vigia_de_rede -e "SELECT endereco_mac, nome_dispositivo, autorizado FROM TB_DISPOSITIVOS"
   ```
5. Reinicie o host: o celular continua liberado (ressync a partir do banco).

## Revogar um aparelho

```bash
sudo mysql vigia_de_rede -e "UPDATE TB_DISPOSITIVOS SET autorizado = FALSE WHERE endereco_mac = 'aa:bb:cc:dd:ee:ff'"
sudo systemctl restart sentinela-ressync    # o conjunto passa a espelhar o banco de novo
```

## Limitações conhecidas (para o relatório)

- **Clonagem de MAC:** quem copiar o MAC de um aparelho registrado passa pela whitelist. A senha compartilhada + MAC é fraca por design.
- **Senha compartilhada:** quem sabe a senha registra quantos aparelhos quiser.
- **Servidor de desenvolvimento do Flask:** suficiente para a demo (poucos clientes), não para produção.

Detalhes e mitigação em `docs/seguranca.md` (Fase 6).
