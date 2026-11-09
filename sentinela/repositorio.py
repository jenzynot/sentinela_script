"""sentinela/repositorio.py — toda a conversa do agente com o MySQL.

Um Repositorio = uma conexão = uma transação por ciclo. O agente abre um por
ciclo e fecha no fim: não há conexão de longa duração para cair por timeout.
"""
from datetime import datetime

import mysql.connector

from .config import mysql_params
from .scanner import Porta


class Repositorio:
    def __init__(self, conexao=None):
        self.cx = conexao or mysql.connector.connect(**mysql_params(), autocommit=False)

    def _cur(self):
        return self.cx.cursor()

    def commit(self):
        self.cx.commit()

    def rollback(self):
        self.cx.rollback()

    def fechar(self):
        self.cx.close()

    # --- varreduras ------------------------------------------------------
    def abrir_varredura(self, quando: datetime) -> int:
        cur = self._cur()
        cur.execute("INSERT INTO TB_VARREDURAS (data_varredura, resultado_geral) "
                    "VALUES (%s, 'em_andamento')", (quando,))
        return cur.lastrowid

    def fechar_varredura(self, id_varredura: int, dispositivos: int, portas: int,
                         alertas: int, resultado: str, resumo: str) -> None:
        self._cur().execute("""
            UPDATE TB_VARREDURAS SET quantidade_dispositivos = %s, total_portas = %s,
                   total_alertas = %s, resultado_geral = %s, resumo = %s
            WHERE id_varredura = %s
        """, (dispositivos, portas, alertas, resultado, resumo, id_varredura))

    def varredura_anterior(self, id_varredura: int) -> int | None:
        cur = self._cur()
        cur.execute("SELECT MAX(id_varredura) FROM TB_VARREDURAS "
                    "WHERE id_varredura < %s AND resultado_geral <> 'em_andamento'",
                    (id_varredura,))
        return cur.fetchone()[0]

    # --- dispositivos ----------------------------------------------------
    def registrar_visto(self, mac: str, quando: datetime) -> tuple[int, bool]:
        """Garante o cadastro do MAC e atualiza o 'último visto'.
        Devolve (id_dispositivo, novo?)."""
        cur = self._cur()
        cur.execute("SELECT id_dispositivo FROM TB_DISPOSITIVOS WHERE endereco_mac = %s", (mac,))
        linha = cur.fetchone()
        if linha:
            cur.execute("UPDATE TB_DISPOSITIVOS SET ultimo_visto = %s, status = 'ativo' "
                        "WHERE id_dispositivo = %s", (quando, linha[0]))
            return linha[0], False
        cur.execute("""
            INSERT INTO TB_DISPOSITIVOS (endereco_mac, autorizado, primeiro_visto, ultimo_visto, status)
            VALUES (%s, FALSE, %s, %s, 'ativo')
        """, (mac, quando, quando))
        return cur.lastrowid, True

    def macs_autorizados(self) -> set[str]:
        cur = self._cur()
        cur.execute("SELECT endereco_mac FROM TB_DISPOSITIVOS WHERE autorizado = TRUE")
        return {mac.lower() for (mac,) in cur.fetchall()}

    def marcar_ausentes(self, presentes: set[int]) -> int:
        """Quem estava ativo e não apareceu nesta varredura vira 'inativo'."""
        cur = self._cur()
        if presentes:
            marcadores = ", ".join(["%s"] * len(presentes))
            cur.execute(f"UPDATE TB_DISPOSITIVOS SET status = 'inativo' "
                        f"WHERE status = 'ativo' AND id_dispositivo NOT IN ({marcadores})",
                        tuple(presentes))
        else:
            cur.execute("UPDATE TB_DISPOSITIVOS SET status = 'inativo' WHERE status = 'ativo'")
        return cur.rowcount

    # --- presenças e portas ----------------------------------------------
    def presentes_em(self, id_varredura: int) -> set[int]:
        cur = self._cur()
        cur.execute("SELECT id_dispositivo FROM TB_PRESENCAS WHERE id_varredura = %s",
                    (id_varredura,))
        return {i for (i,) in cur.fetchall()}

    def registrar_presenca(self, id_varredura: int, id_dispositivo: int, ip: str) -> int:
        cur = self._cur()
        cur.execute("INSERT INTO TB_PRESENCAS (id_varredura, id_dispositivo, endereco_ip) "
                    "VALUES (%s, %s, %s)", (id_varredura, id_dispositivo, ip))
        return cur.lastrowid

    def registrar_portas(self, id_presenca: int, portas: list[Porta]) -> None:
        if portas:
            self._cur().executemany("""
                INSERT INTO TB_PORTAS (id_presenca, numero_porta, protocolo, servico, status_porta)
                VALUES (%s, %s, %s, %s, %s)
            """, [(id_presenca, p.numero, p.protocolo, p.servico[:100], p.estado) for p in portas])

    def portas_da_presenca_anterior(self, id_dispositivo: int,
                                    id_varredura: int) -> set[tuple[int, str]] | None:
        """Portas que o dispositivo tinha na última vez em que foi visto antes
        desta varredura. None = nunca visto antes (sem base para comparar)."""
        cur = self._cur()
        cur.execute("""
            SELECT id_presenca FROM TB_PRESENCAS
            WHERE id_dispositivo = %s AND id_varredura < %s
            ORDER BY id_varredura DESC LIMIT 1
        """, (id_dispositivo, id_varredura))
        linha = cur.fetchone()
        if not linha:
            return None
        cur.execute("SELECT numero_porta, protocolo FROM TB_PORTAS WHERE id_presenca = %s",
                    (linha[0],))
        return {(n, p) for n, p in cur.fetchall()}

    # --- alertas ---------------------------------------------------------
    def registrar_alerta(self, id_varredura: int, id_dispositivo: int | None, tipo: str,
                         descricao: str, nivel: str, quando: datetime) -> int:
        cur = self._cur()
        cur.execute("""
            INSERT INTO TB_ALERTAS (id_varredura, id_dispositivo, tipo_alerta, descricao,
                                    nivel_risco, data_alerta)
            VALUES (%s, %s, %s, %s, %s, %s)
        """, (id_varredura, id_dispositivo, tipo, descricao, nivel, quando))
        return cur.lastrowid
