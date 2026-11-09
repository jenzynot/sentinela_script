"""sentinela/alerta.py — monta, grava e avisa.

Cada alerta vai para TB_ALERTAS e para o log na hora. Avisos externos
(e-mail) saem uma vez por ciclo, DEPOIS do commit, com todos os alertas
juntos — um intruso não gera dez e-mails, e nada é avisado sem estar gravado.
"""
import logging
import os
import smtplib
from dataclasses import dataclass
from datetime import datetime
from email.message import EmailMessage

log = logging.getLogger("sentinela.alerta")

NAO_AUTORIZADO = "dispositivo_nao_autorizado"
PORTA_NOVA = "porta_nova"

# Portas cuja abertura inesperada é mais grave (acesso remoto / compartilhamento / banco)
PORTAS_SENSIVEIS = {21: "ftp", 23: "telnet", 445: "smb", 3306: "mysql",
                    3389: "rdp", 5900: "vnc"}


def nivel_porta_nova(numero: int) -> str:
    return "alto" if numero in PORTAS_SENSIVEIS else "medio"


@dataclass(frozen=True)
class Emitido:
    id_alerta: int
    tipo: str
    nivel: str
    descricao: str


class Alerta:
    def __init__(self, repositorio, notificadores=()):
        self._repo = repositorio
        self._notificadores = list(notificadores)
        self.emitidos: list[Emitido] = []

    def disparar(self, id_varredura: int, id_dispositivo: int | None, tipo: str,
                 descricao: str, nivel: str, quando: datetime) -> int:
        id_alerta = self._repo.registrar_alerta(id_varredura, id_dispositivo, tipo,
                                                descricao, nivel, quando)
        self.emitidos.append(Emitido(id_alerta, tipo, nivel, descricao))
        log.warning("[%s] %s: %s", nivel.upper(), tipo, descricao)
        return id_alerta

    def notificar(self, id_varredura: int) -> None:
        if not self.emitidos or not self._notificadores:
            return
        assunto = f"[Sentinela] {len(self.emitidos)} alerta(s) na varredura {id_varredura}"
        corpo = "\n".join(f"- [{a.nivel.upper()}] {a.tipo}: {a.descricao}" for a in self.emitidos)
        for notificar in self._notificadores:
            try:
                notificar(assunto, corpo)
            except Exception:   # aviso que falha não pode derrubar o agente
                log.exception("falha ao enviar notificação")


class NotificadorEmail:
    def __init__(self, host: str, porta: int, usuario: str, senha: str,
                 remetente: str, destinatarios: list[str]):
        self.host, self.porta = host, porta
        self.usuario, self.senha = usuario, senha
        self.remetente, self.destinatarios = remetente, destinatarios

    def __call__(self, assunto: str, corpo: str) -> None:
        msg = EmailMessage()
        msg["Subject"], msg["From"] = assunto, self.remetente
        msg["To"] = ", ".join(self.destinatarios)
        msg.set_content(corpo)
        with smtplib.SMTP(self.host, self.porta, timeout=20) as smtp:
            smtp.starttls()
            if self.usuario:
                smtp.login(self.usuario, self.senha)
            smtp.send_message(msg)


def notificadores_do_ambiente(env=os.environ) -> list:
    """E-mail só liga se SMTP_HOST e ALERTA_EMAIL_PARA estiverem no .env."""
    if not (env.get("SMTP_HOST") and env.get("ALERTA_EMAIL_PARA")):
        return []
    return [NotificadorEmail(
        host=env["SMTP_HOST"], porta=int(env.get("SMTP_PORTA", "587")),
        usuario=env.get("SMTP_USUARIO", ""), senha=env.get("SMTP_SENHA", ""),
        remetente=env.get("ALERTA_EMAIL_DE") or env.get("SMTP_USUARIO", "sentinela@localhost"),
        destinatarios=[e.strip() for e in env["ALERTA_EMAIL_PARA"].split(",") if e.strip()],
    )]
