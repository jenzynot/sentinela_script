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


PAGINA = """
<h2>Registrar dispositivo na rede</h2>
<p>Seu endereço (MAC): <b>{{ mac }}</b></p>
{% if erro %}<p style="color:red">{{ erro }}</p>{% endif %}
<form method="post" action="/registrar">
  <input name="nome" placeholder="Nome do dispositivo"><br>
  <input name="senha" type="password" placeholder="Senha da rede"><br>
  <button type="submit">Registrar</button>
</form>
"""


@app.route("/", methods=["GET"])
def portal():
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

    registrar_autorizado(mac, request.form.get("nome", ""))
    liberar_mac(mac)   # entra no conjunto nftables; o próximo pacote já passa
    return "Dispositivo registrado! Já pode navegar."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8080)
