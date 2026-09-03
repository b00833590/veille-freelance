"""Envoi d'email via SMTP Gmail. Sans identifiants : no-op journalisé."""
from __future__ import annotations

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from settings import env

log = logging.getLogger("veille.mailer")


def send_mail(subject: str, html: str, *, to: str | None = None) -> bool:
    user, pwd = env("GMAIL_USER"), env("GMAIL_APP_PASSWORD")
    if not user or not pwd:
        log.warning("Email non envoyé (GMAIL_USER/APP_PASSWORD manquants) : %s", subject)
        return False
    to = to or user
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = user
    msg["To"] = to
    msg.attach(MIMEText("Version HTML requise.", "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    try:
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
            s.login(user, pwd)
            s.sendmail(user, [to], msg.as_string())
        log.info("Email envoyé : %s", subject)
        return True
    except Exception as e:  # noqa: BLE001
        log.error("Échec envoi email : %s", type(e).__name__)
        return False
