"""
Email digest builder and sender.
Generates HTML email digests for daily/weekly briefings.
Supports SendGrid and SMTP delivery.
"""
from dataclasses import dataclass
from html import escape
import os
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)

DEFAULT_APP_URL = "https://onebd.pchomelab.com"
DEFAULT_FROM_EMAIL = "bd-intelligence@pchomelab.com"


@dataclass(frozen=True)
class EmailDeliveryResult:
    success: bool
    provider: Optional[str]
    status_code: Optional[int] = None
    error: Optional[str] = None


def _setting(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def get_email_delivery_status() -> Dict[str, Any]:
    """Report delivery readiness without exposing credentials."""
    sendgrid = bool(_setting("SENDGRID_API_KEY"))
    smtp = bool(_setting("SMTP_HOST"))
    provider = "sendgrid" if sendgrid else "smtp" if smtp else None
    status = {
        "configured": provider is not None,
        "provider": provider,
        "from_email": _setting("DIGEST_FROM_EMAIL", DEFAULT_FROM_EMAIL),
        "app_url": _setting("APP_URL", DEFAULT_APP_URL),
    }
    if provider == "smtp":
        status["smtp_security"] = _setting("SMTP_SECURITY", "starttls").lower()
    if provider is None:
        status["configuration_hint"] = (
            "Set SENDGRID_API_KEY, or SMTP_HOST with optional SMTP_USER/SMTP_PASS"
        )
    return status


def format_deal_row(deal: Dict[str, Any]) -> str:
    """Format a single deal as an HTML table row."""
    # Handle value as either number or string
    raw_value = deal.get('value')
    if isinstance(raw_value, (int, float)):
        value = f"${raw_value:,.0f}M"
    elif isinstance(raw_value, str):
        value = raw_value
    elif raw_value is None:
        value = "—"
    else:
        value = str(raw_value)
    
    title = escape(str(deal.get("title") or "N/A"))
    principal = escape(str(deal.get("principal") or "—"))
    partner = escape(str(deal.get("partner") or "—"))
    value = escape(value)
    deal_date = escape(str(deal.get("date") or "—"))
    return f"""
    <tr style="border-bottom: 1px solid #334155;">
        <td style="padding: 8px 12px; color: #e2e8f0; font-size: 14px;">{title}</td>
        <td style="padding: 8px 12px; color: #94a3b8; font-size: 13px;">{principal} → {partner}</td>
        <td style="padding: 8px 12px; color: #cbd5e1; font-size: 14px; font-weight: 600;">{value}</td>
        <td style="padding: 8px 12px; color: #64748b; font-size: 12px;">{deal_date}</td>
    </tr>
    """


def format_catalyst_row(catalyst: Dict[str, Any]) -> str:
    """Format a sourced clinical-trial catalyst as an HTML table row."""
    title = escape(str(catalyst.get("title") or catalyst.get("nct_id") or "N/A"))
    nct_id = escape(str(catalyst.get("nct_id") or ""))
    phase = escape(str(catalyst.get("phase") or "Phase not reported"))
    sponsor = escape(str(catalyst.get("sponsor") or "Sponsor not reported"))
    companies = escape(str(catalyst.get("companies") or "No exact company link"))
    catalyst_date = escape(str(catalyst.get("date") or "—"))
    source_url = escape(str(catalyst.get("source_url") or ""), quote=True)
    title_cell = title
    if source_url:
        title_cell = (
            f'<a href="{source_url}" style="color: #93c5fd; '
            f'text-decoration: none;">{title}</a>'
        )
    return f"""
    <tr style="border-bottom: 1px solid #334155;">
        <td style="padding: 8px 12px; color: #cbd5e1; font-size: 13px; white-space: nowrap;">{catalyst_date}</td>
        <td style="padding: 8px 12px; color: #e2e8f0; font-size: 14px;">{title_cell}<br><span style="color: #64748b; font-size: 11px;">{nct_id}</span></td>
        <td style="padding: 8px 12px; color: #94a3b8; font-size: 12px;">{phase}<br>{sponsor}</td>
        <td style="padding: 8px 12px; color: #94a3b8; font-size: 12px;">{companies}</td>
    </tr>
    """


def build_digest_html(
    title: str,
    sections: List[Dict[str, Any]],
    app_url: Optional[str] = None,
) -> str:
    """
    Build a complete HTML email digest.
    Dark theme matching the platform UI.
    """
    sections_html = ""
    safe_title = escape(title)
    safe_app_url = escape(
        app_url or _setting("APP_URL", DEFAULT_APP_URL), quote=True
    )

    for section in sections:
        section_title = escape(str(section.get("title") or ""))
        section_html = f"""
        <div style="margin-bottom: 24px;">
            <h2 style="color: #60a5fa; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; font-weight: 600;">
                {section_title}
            </h2>
        """

        if section.get("content"):
            section_html += (
                '<p style="color: #cbd5e1; font-size: 14px; line-height: 1.6;">'
                f'{escape(str(section["content"]))}</p>'
            )

        if section.get("type") == "catalysts" and section.get("items"):
            section_html += """
            <table style="width: 100%; border-collapse: collapse; margin-top: 8px;">
                <thead>
                    <tr style="border-bottom: 2px solid #334155;">
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Date</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Trial</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Phase / Sponsor</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Exact-linked companies</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in section["items"]:
                section_html += format_catalyst_row(item)
            section_html += "</tbody></table>"
        elif section.get("items"):
            section_html += """
            <table style="width: 100%; border-collapse: collapse; margin-top: 8px;">
                <thead>
                    <tr style="border-bottom: 2px solid #334155;">
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Deal</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Parties</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Value</th>
                        <th style="padding: 6px 12px; color: #64748b; font-size: 12px; text-align: left;">Date</th>
                    </tr>
                </thead>
                <tbody>
            """
            for item in section["items"]:
                section_html += format_deal_row(item)
            section_html += "</tbody></table>"

        if section.get("stats"):
            stats_html = '<div style="display: flex; gap: 16px; margin-top: 8px;">'
            for stat in section["stats"]:
                stat_label = escape(str(stat.get("label") or ""))
                stat_value = escape(str(stat.get("value") or ""))
                stats_html += f"""
                <div style="background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; flex: 1;">
                    <div style="color: #64748b; font-size: 11px;">{stat_label}</div>
                    <div style="color: #e2e8f0; font-size: 20px; font-weight: 700; margin-top: 4px;">{stat_value}</div>
                </div>
                """
            stats_html += '</div>'
            section_html += stats_html

        section_html += "</div>"
        sections_html += section_html

    html = f"""
    <!DOCTYPE html>
    <html>
    <head><meta charset="utf-8"></head>
    <body style="margin: 0; padding: 0; background-color: #0f172a; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;">
        <div style="max-width: 640px; margin: 0 auto; padding: 24px;">
            <!-- Header -->
            <div style="text-align: center; padding: 24px 0; border-bottom: 1px solid #1e293b;">
                <h1 style="color: #e2e8f0; font-size: 20px; margin: 0;">📊 {safe_title}</h1>
                <p style="color: #64748b; font-size: 13px; margin-top: 4px;">BD Intelligence Platform</p>
            </div>

            <!-- Content -->
            <div style="padding: 24px 0;">
                {sections_html}
            </div>

            <!-- Footer -->
            <div style="text-align: center; padding: 16px 0; border-top: 1px solid #1e293b;">
                <a href="{safe_app_url}" style="color: #3b82f6; font-size: 13px; text-decoration: none;">
                    Open BD Intelligence Platform →
                </a>
                <p style="color: #475569; font-size: 11px; margin-top: 8px;">
                    You're receiving this because you're subscribed to deal intelligence digests.
                </p>
            </div>
        </div>
    </body>
    </html>
    """

    return html


def build_password_reset_email(reset_url: str) -> str:
    """Build a minimal password-reset email without logging the secret token."""
    safe_url = escape(reset_url, quote=True)
    return f"""
    <!DOCTYPE html><html><body style="font-family: sans-serif; color: #1e293b;">
      <h2>Reset your OneBD password</h2>
      <p>This link expires in one hour and can be used once.</p>
      <p><a href="{safe_url}" style="background:#2563eb;color:white;padding:10px 16px;text-decoration:none;border-radius:6px;">Reset password</a></p>
      <p>If you did not request this, you can ignore this email.</p>
    </body></html>
    """


def deliver_email(to_email: str, subject: str, html_content: str) -> EmailDeliveryResult:
    """Send through the owner-configured provider and return diagnostic status."""
    if _setting("SENDGRID_API_KEY"):
        return _send_via_sendgrid(to_email, subject, html_content)
    if _setting("SMTP_HOST"):
        return _send_via_smtp(to_email, subject, html_content)
    logger.warning("No email delivery configured")
    return EmailDeliveryResult(
        success=False,
        provider=None,
        error="No email provider is configured",
    )


def send_digest_email(to_email: str, subject: str, html_content: str) -> bool:
    """Backward-compatible boolean wrapper used by scheduled tasks."""
    return deliver_email(to_email, subject, html_content).success


def _send_via_sendgrid(
    to_email: str,
    subject: str,
    html_content: str,
) -> EmailDeliveryResult:
    """Send directly through SendGrid's v3 API without an extra SDK."""
    try:
        import httpx

        response = httpx.post(
            "https://api.sendgrid.com/v3/mail/send",
            headers={
                "Authorization": f"Bearer {_setting('SENDGRID_API_KEY')}",
                "Content-Type": "application/json",
            },
            json={
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {
                    "email": _setting("DIGEST_FROM_EMAIL", DEFAULT_FROM_EMAIL),
                    "name": _setting("DIGEST_FROM_NAME", "BD Intelligence"),
                },
                "subject": subject,
                "content": [{"type": "text/html", "value": html_content}],
            },
            timeout=float(_setting("EMAIL_TIMEOUT_SECONDS", "20")),
        )
        logger.info("SendGrid email sent", to=to_email, status=response.status_code)
        success = 200 <= response.status_code < 300
        return EmailDeliveryResult(
            success=success,
            provider="sendgrid",
            status_code=response.status_code,
            error=None if success else f"SendGrid returned HTTP {response.status_code}",
        )
    except Exception as e:
        logger.error("SendGrid send failed", error=str(e))
        return EmailDeliveryResult(False, "sendgrid", error=str(e))


def _send_via_smtp(
    to_email: str,
    subject: str,
    html_content: str,
) -> EmailDeliveryResult:
    """Send via SMTP."""
    try:
        import smtplib
        import ssl
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        smtp_host = _setting("SMTP_HOST")
        security = _setting("SMTP_SECURITY", "starttls").lower()
        default_port = "465" if security == "ssl" else "587"
        smtp_port = int(_setting("SMTP_PORT", default_port))
        smtp_user = _setting("SMTP_USER")
        smtp_pass = _setting("SMTP_PASS")
        from_email = _setting("DIGEST_FROM_EMAIL", DEFAULT_FROM_EMAIL)
        timeout = float(_setting("EMAIL_TIMEOUT_SECONDS", "20"))

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = from_email
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        connection = (
            smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout)
            if security == "ssl"
            else smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
        )
        with connection as server:
            if security == "starttls":
                server.starttls(context=ssl.create_default_context())
            elif security not in {"ssl", "none"}:
                raise ValueError("SMTP_SECURITY must be starttls, ssl, or none")
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(from_email, to_email, msg.as_string())

        logger.info("SMTP email sent", to=to_email)
        return EmailDeliveryResult(True, "smtp", status_code=250)
    except Exception as e:
        logger.error("SMTP send failed", error=str(e))
        return EmailDeliveryResult(False, "smtp", error=str(e))
