"""
Email digest builder and sender.
Generates HTML email digests for daily/weekly briefings.
Supports SendGrid and SMTP delivery.
"""
from html import escape
import os
from typing import List, Dict, Any
import structlog

logger = structlog.get_logger(__name__)

SENDGRID_API_KEY = os.environ.get("SENDGRID_API_KEY")
SMTP_HOST = os.environ.get("SMTP_HOST")
FROM_EMAIL = os.environ.get("DIGEST_FROM_EMAIL", "bd-intelligence@machomelab.com")


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
    
    return f"""
    <tr style="border-bottom: 1px solid #334155;">
        <td style="padding: 8px 12px; color: #e2e8f0; font-size: 14px;">{deal.get('title', 'N/A')}</td>
        <td style="padding: 8px 12px; color: #94a3b8; font-size: 13px;">{deal.get('principal', '—')} → {deal.get('partner', '—')}</td>
        <td style="padding: 8px 12px; color: #cbd5e1; font-size: 14px; font-weight: 600;">{value}</td>
        <td style="padding: 8px 12px; color: #64748b; font-size: 12px;">{deal.get('date', '—')}</td>
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


def build_digest_html(title: str, sections: List[Dict[str, Any]], app_url: str = "https://cortellis.machomelab.com") -> str:
    """
    Build a complete HTML email digest.
    Dark theme matching the platform UI.
    """
    sections_html = ""

    for section in sections:
        section_html = f"""
        <div style="margin-bottom: 24px;">
            <h2 style="color: #60a5fa; font-size: 14px; text-transform: uppercase; letter-spacing: 1px; margin-bottom: 12px; font-weight: 600;">
                {section.get('title', '')}
            </h2>
        """

        if section.get("content"):
            section_html += f'<p style="color: #cbd5e1; font-size: 14px; line-height: 1.6;">{section["content"]}</p>'

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
                stats_html += f"""
                <div style="background: #1e293b; border: 1px solid #334155; border-radius: 8px; padding: 12px 16px; flex: 1;">
                    <div style="color: #64748b; font-size: 11px;">{stat.get('label', '')}</div>
                    <div style="color: #e2e8f0; font-size: 20px; font-weight: 700; margin-top: 4px;">{stat.get('value', '')}</div>
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
                <h1 style="color: #e2e8f0; font-size: 20px; margin: 0;">📊 {title}</h1>
                <p style="color: #64748b; font-size: 13px; margin-top: 4px;">BD Intelligence Platform</p>
            </div>

            <!-- Content -->
            <div style="padding: 24px 0;">
                {sections_html}
            </div>

            <!-- Footer -->
            <div style="text-align: center; padding: 16px 0; border-top: 1px solid #1e293b;">
                <a href="{app_url}" style="color: #3b82f6; font-size: 13px; text-decoration: none;">
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


def send_digest_email(to_email: str, subject: str, html_content: str) -> bool:
    """
    Send digest email via SendGrid or SMTP.
    Returns True if sent successfully.
    """
    if SENDGRID_API_KEY:
        return _send_via_sendgrid(to_email, subject, html_content)
    elif SMTP_HOST:
        return _send_via_smtp(to_email, subject, html_content)
    else:
        logger.warning("No email delivery configured (set SENDGRID_API_KEY or SMTP_HOST)")
        # Log the email for development
        logger.info("Email digest generated (not sent)", to=to_email, subject=subject, html_length=len(html_content))
        return False


def _send_via_sendgrid(to_email: str, subject: str, html_content: str) -> bool:
    """Send via SendGrid API."""
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail, Email, To, Content

        sg = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(
            from_email=Email(FROM_EMAIL, "BD Intelligence"),
            to_emails=To(to_email),
            subject=subject,
            html_content=Content("text/html", html_content),
        )
        response = sg.send(message)
        logger.info("SendGrid email sent", to=to_email, status=response.status_code)
        return response.status_code in (200, 201, 202)
    except Exception as e:
        logger.error("SendGrid send failed", error=str(e))
        return False


def _send_via_smtp(to_email: str, subject: str, html_content: str) -> bool:
    """Send via SMTP."""
    try:
        import smtplib
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText

        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "")
        smtp_pass = os.environ.get("SMTP_PASS", "")

        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = FROM_EMAIL
        msg["To"] = to_email
        msg.attach(MIMEText(html_content, "html"))

        with smtplib.SMTP(SMTP_HOST, smtp_port) as server:
            server.starttls()
            if smtp_user:
                server.login(smtp_user, smtp_pass)
            server.sendmail(FROM_EMAIL, to_email, msg.as_string())

        logger.info("SMTP email sent", to=to_email)
        return True
    except Exception as e:
        logger.error("SMTP send failed", error=str(e))
        return False
