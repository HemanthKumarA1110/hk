"""Alert delivery via Telegram and SMTP."""

from __future__ import annotations

import logging
import smtplib
from email.message import EmailMessage

import httpx

from trading_shared.config import get_settings

logger = logging.getLogger(__name__)


class AlertSender:
    def __init__(self):
        self.settings = get_settings()

    @property
    def enabled(self) -> bool:
        return bool(
            (self.settings.TELEGRAM_BOT_TOKEN and self.settings.TELEGRAM_CHAT_ID)
            or (self.settings.SMTP_HOST and self.settings.ALERT_EMAIL_TO)
        )

    def send(self, subject: str, body: str, severity: str = "info") -> dict:
        results = {"telegram": False, "email": False}
        message = f"[{severity.upper()}] {subject}\n\n{body}"

        if self.settings.TELEGRAM_BOT_TOKEN and self.settings.TELEGRAM_CHAT_ID:
            try:
                url = f"https://api.telegram.org/bot{self.settings.TELEGRAM_BOT_TOKEN}/sendMessage"
                httpx.post(
                    url,
                    json={"chat_id": self.settings.TELEGRAM_CHAT_ID, "text": message[:4000]},
                    timeout=10.0,
                ).raise_for_status()
                results["telegram"] = True
            except Exception:
                logger.exception("Telegram alert failed")

        if self.settings.SMTP_HOST and self.settings.ALERT_EMAIL_TO:
            try:
                msg = EmailMessage()
                msg["Subject"] = subject
                msg["From"] = self.settings.SMTP_USER or "alerts@trading-bot"
                msg["To"] = self.settings.ALERT_EMAIL_TO
                msg.set_content(body)
                with smtplib.SMTP(self.settings.SMTP_HOST, self.settings.SMTP_PORT, timeout=10) as server:
                    if self.settings.SMTP_USER and self.settings.SMTP_PASSWORD:
                        server.starttls()
                        server.login(self.settings.SMTP_USER, self.settings.SMTP_PASSWORD)
                    server.send_message(msg)
                results["email"] = True
            except Exception:
                logger.exception("Email alert failed")

        return results
