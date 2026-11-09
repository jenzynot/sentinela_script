"""captive/portal.py — portal cativo (Fase 1.5).

Escuta na 8080, destino do redirect HTTP do firewall.nft.
O dispositivo se registra com a senha compartilhada; o portal grava em
TB_DISPOSITIVOS (autorizado = TRUE) e libera o MAC no nftables.
"""
import hmac
import os
import re
import subprocess

from flask import Flask, render_template_string, request

from dados import registrar_autorizado
from firewall_ctl import liberar_mac

app = Flask(__name__)

# Senha compartilhada da rede. Sem PORTAL_SENHA configurada, ninguém se registra.
SENHA_REDE = os.environ.get("PORTAL_SENHA")


def mac_do_ip(ip: str) -> str | None:
    saida = subprocess.run(["ip", "neigh", "show", ip],
                           capture_output=True, text=True).stdout
    m = re.search(r"lladdr ([0-9a-f:]{17})", saida)
    return m.group(1) if m else None


def senha_confere(digitada: str) -> bool:
    if not SENHA_REDE:
        return False
    # compare_digest: tempo constante, não vaza a senha por timing
    return hmac.compare_digest(digitada.encode(), SENHA_REDE.encode())


TAMANHO_MAX_NOME = 100   # TB_DISPOSITIVOS.nome_dispositivo é VARCHAR(100)

BASE = """<!doctype html>
<html lang="pt-BR"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sentinela — registro na rede</title>
<style>
  body{font-family:system-ui,sans-serif;max-width:26rem;margin:2rem auto;padding:0 1rem;color:#1d2433}
  h2{margin-bottom:.25rem} .mac{font-family:monospace;background:#eef1f6;padding:.1rem .4rem;border-radius:.25rem}
  input,button{display:block;width:100%;box-sizing:border-box;margin:.5rem 0;padding:.7rem;font-size:1rem;border-radius:.4rem;border:1px solid #b8c0cc}
  button{background:#1f5eff;color:#fff;border:0} .erro{color:#b3261e} .ok{color:#146c2e}
</style></head><body>{% block corpo %}{% endblock %}</body></html>"""

PAGINA = BASE.replace("{% block corpo %}{% endblock %}", """
<h2>Registrar dispositivo na rede</h2>
<p>Seu endereço (MAC): <span class="mac">{{ mac }}</span></p>
{% if erro %}<p class="erro">{{ erro }}</p>{% endif %}
<form method="post" action="/registrar">
  <input name="nome" maxlength="100" placeholder="Nome do dispositivo (ex.: Celular da Ana)">
  <input name="senha" type="password" placeholder="Senha da rede" required>
  <button type="submit">Registrar</button>
</form>""")

SUCESSO = BASE.replace("{% block corpo %}{% endblock %}", """
<h2 class="ok">Dispositivo registrado!</h2>
<p>O MAC <span class="mac">{{ mac }}</span> entrou na whitelist. Já pode navegar.</p>""")


# Android (/generate_204), iOS (/hotspot-detect.html), Windows (/connecttest.txt)...
# testam a conexão por HTTP. O firewall redireciona esse HTTP para cá; responder
# com a página (em vez do que o sistema espera) faz o aparelho abrir o portal.
@app.route("/", methods=["GET"])
@app.route("/<path:_caminho>", methods=["GET"])
def portal(_caminho=None):
    mac = mac_do_ip(request.remote_addr)
    if not mac:
        return "Não consegui identificar seu dispositivo. Reconecte à rede.", 400
    return render_template_string(PAGINA, mac=mac, erro=None)


@app.route("/registrar", methods=["POST"])
def registrar():
    mac = mac_do_ip(request.remote_addr)
    if not mac:
        return "Dispositivo não identificado.", 400
    if not senha_confere(request.form.get("senha", "")):
        return render_template_string(PAGINA, mac=mac, erro="Senha incorreta."), 403

    nome = request.form.get("nome", "").strip()[:TAMANHO_MAX_NOME]
    registrar_autorizado(mac, nome)
    liberar_mac(mac)   # entra no conjunto nftables; o próximo pacote já passa
    return render_template_string(SUCESSO, mac=mac)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
