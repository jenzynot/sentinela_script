"""captive/dados.py — acesso ao MySQL usado pelo portal e pelo ressync.

Credenciais vêm do ambiente (ver .env.example); nunca ficam no código.
No host, o systemd carrega o .env com `EnvironmentFile=`.
"""
import os
from datetime import datetime

import mysql.connector


def conectar():
    return mysql.connector.connect(
        host=os.environ.get("MYSQL_HOST", "127.0.0.1"),
        port=int(os.environ.get("MYSQL_PORT", "3306")),
        user=os.environ.get("MYSQL_USER", "sentinela"),
        password=os.environ.get("MYSQL_PASSWORD", ""),
        database=os.environ.get("MYSQL_DATABASE", "vigia_de_rede"),
    )


def registrar_autorizado(mac: str, nome: str) -> None:
    """Grava (ou atualiza) o dispositivo como autorizado.

    O ON DUPLICATE KEY UPDATE só funciona porque endereco_mac é UNIQUE.
    """
    agora = datetime.now()
    cx = conectar()
    try:
        cur = cx.cursor()
        cur.execute("""
            INSERT INTO TB_DISPOSITIVOS
                (endereco_mac, nome_dispositivo, autorizado, primeiro_visto, ultimo_visto, status)
            VALUES (%s, %s, TRUE, %s, %s, 'ativo')
            ON DUPLICATE KEY UPDATE
                autorizado = TRUE,
                nome_dispositivo = VALUES(nome_dispositivo),
                ultimo_visto = VALUES(ultimo_visto)
        """, (mac, nome, agora, agora))
        cx.commit()
        cur.close()
    finally:
        cx.close()


def macs_autorizados() -> list[str]:
    cx = conectar()
    try:
        cur = cx.cursor()
        cur.execute("SELECT endereco_mac FROM TB_DISPOSITIVOS WHERE autorizado = TRUE")
        macs = [mac for (mac,) in cur.fetchall()]
        cur.close()
        return macs
    finally:
        cx.close()
