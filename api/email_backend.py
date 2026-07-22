"""Pluggable email delivery for WatchDogWeb. (INFRA-1)

Selects an implementation via the EMAIL_BACKEND env var:
    EMAIL_BACKEND=smtp      -> SMTPBackend      (SMTP_HOST/PORT/USERNAME/PASSWORD/USE_TLS, EMAIL_FROM)
    EMAIL_BACKEND=sendgrid  -> SendGridBackend   (SENDGRID_API_KEY, EMAIL_FROM)
    EMAIL_BACKEND=console   -> ConsoleBackend    (default — logs the link, sends nothing;
                                                    dev never hard-blocks on missing config)

No new dependencies: SMTPBackend uses stdlib smtplib/ssl; SendGridBackend uses SendGrid's
v3 HTTP API directly via `requests`, which main.py already imports for SSO.

All call sites in main.py should go through send_templated_email() rather than talking to a
backend directly, so template wording and failure handling stay in one place.
"""

import os
import smtplib
import ssl
from email.message import EmailMessage
import requests


class EmailBackend:
    def send(self, to: str, subject: str, body_text: str) -> bool:
        raise NotImplementedError


class ConsoleBackend(EmailBackend):
    """Dev fallback. Matches the existing '[DEBUG] Send ... link' print pattern that was
    inline in main.py, so local dev never hard-blocks on missing email config."""

    def send(self, to: str, subject: str, body_text: str) -> bool:
        print(f"[DEBUG-EMAIL] To: {to} | Subject: {subject}\n{body_text}")
        return True


class SMTPBackend(EmailBackend):
    """For testing against a personal SMTP account (e.g. Gmail with an app password)."""

    def __init__(self):
        self.host = os.getenv("SMTP_HOST", "")
        self.port = int(os.getenv("SMTP_PORT", "587"))
        self.username = os.getenv("SMTP_USERNAME", "")
        self.password = os.getenv("SMTP_PASSWORD", "")
        self.use_tls = os.getenv("SMTP_USE_TLS", "true").lower() == "true"
        self.from_addr = os.getenv("EMAIL_FROM", self.username)

    def send(self, to: str, subject: str, body_text: str) -> bool:
        if not self.host:
            print(f"[EMAIL-ERROR] SMTP_HOST not configured — dropping email to {to}")
            return False
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = self.from_addr
        msg["To"] = to
        msg.set_content(body_text)
        try:
            if self.use_tls:
                context = ssl.create_default_context()
                with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                    server.starttls(context=context)
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            else:
                with smtplib.SMTP(self.host, self.port, timeout=10) as server:
                    if self.username:
                        server.login(self.username, self.password)
                    server.send_message(msg)
            return True
        except Exception as e:
            print(f"[EMAIL-ERROR] SMTP send to {to} failed: {e}")
            return False


class SendGridBackend(EmailBackend):
    """Uses SendGrid's v3 HTTP API directly (no `sendgrid` package dependency added)."""

    def __init__(self):
        self.api_key = os.getenv("SENDGRID_API_KEY", "")
        self.from_addr = os.getenv("EMAIL_FROM", "")

    def send(self, to: str, subject: str, body_text: str) -> bool:
        if not self.api_key or not self.from_addr:
            print(f"[EMAIL-ERROR] SENDGRID_API_KEY/EMAIL_FROM not configured — dropping email to {to}")
            return False
        payload = {
            "personalizations": [{"to": [{"email": to}]}],
            "from": {"email": self.from_addr},
            "subject": subject,
            "content": [{"type": "text/plain", "value": body_text}],
        }
        try:
            resp = requests.post(
                "https://api.sendgrid.com/v3/mail/send",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
                timeout=10,
            )
            if resp.status_code >= 300:
                print(f"[EMAIL-ERROR] SendGrid send to {to} failed: {resp.status_code} {resp.text}")
                return False
            return True
        except Exception as e:
            print(f"[EMAIL-ERROR] SendGrid send to {to} failed: {e}")
            return False


_BACKEND_INSTANCE = None


def get_email_backend() -> EmailBackend:
    global _BACKEND_INSTANCE
    if _BACKEND_INSTANCE is not None:
        return _BACKEND_INSTANCE
    choice = os.getenv("EMAIL_BACKEND", "console").lower()
    if choice == "smtp":
        _BACKEND_INSTANCE = SMTPBackend()
    elif choice == "sendgrid":
        _BACKEND_INSTANCE = SendGridBackend()
    else:
        _BACKEND_INSTANCE = ConsoleBackend()
    return _BACKEND_INSTANCE


def send_templated_email(to: str, subject: str, body_text: str) -> bool:
    """Single call site for main.py. Never raises — failures are logged and swallowed so
    email delivery problems don't break the underlying request. This matches the existing
    anti-account-enumeration pattern already used across main.py (e.g.
    request_initial_password_setup, request_unlock), which always returns a generic success
    response regardless of whether an email was actually eligible/sent."""
    try:
        return get_email_backend().send(to, subject, body_text)
    except Exception as e:
        print(f"[EMAIL-ERROR] Unexpected error sending to {to}: {e}")
        return False