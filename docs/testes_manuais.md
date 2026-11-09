# Testes manuais no Mint (o que o CI não alcança)

O CI (GitHub Actions) testa tudo **depois** de "o cliente já está na `br0`". O que depende de rádio, celular real ou VM Windows fica aqui. Cada item no formato **dado → quando → então**; registrar data e resultado no diário técnico.

| # | Dado | Quando | Então | Resultado |
|---|---|---|---|---|
| M1 | `instalar.sh rede` feito | o celular procura redes | o SSID aparece e o celular conecta e pega IP `192.168.50.1xx` | |
| M2 | celular conectado, fora da whitelist | ele testa a conexão | a tela "Fazer login na rede" abre sozinha com o MAC dele | |
| M3 | tela do portal aberta | senha errada | "Senha incorreta" e nada em `TB_DISPOSITIVOS` | |
| M4 | tela do portal aberta | senha certa | "Dispositivo registrado!" e o celular navega | |
| M5 | celular registrado | o host reinicia | depois do boot ele continua navegando (ressync) | |
| M6 | VM criada com `provision.vm tudo` | `status` | `running` com IP `192.168.50.10` | |
| M7 | celular registrado | app Remote Desktop → `192.168.50.10` | sessão RDP com NLA abre na VM | |
| M8 | celular registrado | navegador → `http://192.168.50.10` | Painel da Casa | |
| M9 | agente rodando | aparelho **não** registrado conecta | `dispositivo_nao_autorizado` no log e em `TB_ALERTAS` | |
| M10 | agente rodando | abre uma porta nova na VM (ex.: compartilhamento → 445) | `porta_nova` de risco **alto** | |
| M11 | VPN configurada, celular no 4G | túnel WireGuard ligado → RDP `192.168.50.10` | conecta de fora da rede | |
| M12 | Kali na `br0` | `nmap -sS -p- 192.168.50.1` | só 53, 67/udp e 8080 | |
| M13 | Kali com o MAC de um aparelho registrado (`macchanger`) | tenta navegar | **consegue** — vulnerabilidade conhecida, registrar | |
| M14 | backup recente | apaga `TB_ALERTAS` e restaura | contagem de alertas volta ao valor do backup | |

## Por que estes ficam fora do CI

- **Associação Wi-Fi (`hostapd`):** não há rádio no runner.
- **Detecção de portal do celular:** só o Android/iOS real prova o comportamento do sistema.
- **VM Windows:** instalar Windows no CI é inviável (ISO, tempo, licença).
- **RDP ponta a ponta:** depende da VM e do Wi-Fi reais.
- **Demo:** o Actions é headless.
