import smtplib
from email.message import EmailMessage
import logging
from typing import Optional
from app.config import settings

logger = logging.getLogger("email_service")

def send_alert_email(
    alert_id: str,
    source: str,
    detected_at: str,
    latitude: Optional[float] = None,
    longitude: Optional[float] = None,
    speed_kmh: Optional[float] = None,
) -> bool:
    """
    Dispatches an emergency alert email via SMTP to the designated recipient
    with telemetry data and an interactive Google Maps location link.
    """
    if not settings.ALERT_EMAIL_ENABLED:
        logger.info("Alert email notifications are disabled (ALERT_EMAIL_ENABLED=False).")
        return False

    if not settings.SMTP_PASSWORD:
        logger.warning("SMTP_PASSWORD is not configured; skipping email dispatch.")
        return False

    try:
        msg = EmailMessage()
        trigger_label = "MANUAL SOS" if source.lower() == "manual" else "AUTOMATIC IMPACT"
        msg["Subject"] = f"🚨 EMERGENCY ALERT: Road Incident ({trigger_label}) Detected"
        msg["From"] = settings.SMTP_USER
        msg["To"] = settings.ALERT_RECIPIENT_EMAIL

        # Build Google Maps link
        has_location = latitude is not None and longitude is not None
        maps_link = (
            f"https://www.google.com/maps?q={latitude},{longitude}"
            if has_location
            else "Location unavailable"
        )

        plain_text = f"""EMERGENCY ALERT NOTIFICATION
========================================
An emergency alert was triggered from the Road-Events mobile client.

- Trigger Source: {trigger_label}
- Detected At:    {detected_at}
- Coordinates:    {f"{latitude:.6f}, {longitude:.6f}" if has_location else "Unavailable"}
- Speed:          {f"{speed_kmh:.1f} km/h" if speed_kmh is not None else "N/A"}
- Alert ID:       {alert_id}

Google Maps Location:
{maps_link}

Please check on the rider immediately.
========================================
"""

        html_content = f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <style>
    body {{
      font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;
      background-color: #0f172a;
      margin: 0;
      padding: 24px 12px;
    }}
    .card {{
      max-width: 580px;
      margin: 0 auto;
      background: #ffffff;
      border-radius: 16px;
      overflow: hidden;
      box-shadow: 0 10px 25px -5px rgba(0, 0, 0, 0.3);
      border-top: 6px solid #dc2626;
    }}
    .header {{
      background: linear-gradient(135deg, #fef2f2 0%, #fee2e2 100%);
      padding: 28px 24px;
      text-align: center;
      border-bottom: 1px solid #fecaca;
    }}
    .header h1 {{
      margin: 0;
      color: #991b1b;
      font-size: 24px;
      font-weight: 800;
      letter-spacing: -0.5px;
    }}
    .header p {{
      margin: 6px 0 0 0;
      color: #b91c1c;
      font-size: 14px;
      font-weight: 500;
    }}
    .content {{
      padding: 28px 24px;
      color: #334155;
      font-size: 15px;
      line-height: 1.6;
    }}
    .badge {{
      display: inline-block;
      padding: 4px 12px;
      border-radius: 9999px;
      font-size: 13px;
      font-weight: 700;
      background-color: #fee2e2;
      color: #991b1b;
      text-transform: uppercase;
    }}
    .table {{
      width: 100%;
      border-collapse: collapse;
      margin: 20px 0;
      background: #f8fafc;
      border-radius: 10px;
      overflow: hidden;
    }}
    .table td {{
      padding: 12px 16px;
      border-bottom: 1px solid #e2e8f0;
      font-size: 14px;
    }}
    .table tr:last-child td {{
      border-bottom: none;
    }}
    .table td.label {{
      font-weight: 600;
      color: #64748b;
      width: 35%;
    }}
    .table td.value {{
      font-weight: 500;
      color: #0f172a;
    }}
    .btn {{
      display: block;
      text-align: center;
      background-color: #dc2626;
      color: #ffffff !important;
      padding: 14px 24px;
      text-decoration: none;
      border-radius: 10px;
      font-weight: 700;
      font-size: 16px;
      margin: 24px 0 8px 0;
      box-shadow: 0 4px 6px -1px rgba(220, 38, 38, 0.3);
    }}
    .footer {{
      padding: 16px 24px;
      background-color: #f1f5f9;
      font-size: 12px;
      color: #94a3b8;
      text-align: center;
      border-top: 1px solid #e2e8f0;
    }}
  </style>
</head>
<body>
  <div class="card">
    <div class="header">
      <h1>🚨 EMERGENCY ALERT</h1>
      <p>Road-Events Incident Response System</p>
    </div>
    <div class="content">
      <p style="margin-top: 0;">An urgent incident alert was just triggered with the following telemetry details:</p>
      
      <table class="table">
        <tr>
          <td class="label">Trigger Source</td>
          <td class="value"><span class="badge">{trigger_label}</span></td>
        </tr>
        <tr>
          <td class="label">Detected At (UTC)</td>
          <td class="value">{detected_at}</td>
        </tr>
        <tr>
          <td class="label">Coordinates</td>
          <td class="value"><strong>{f"{latitude:.6f}, {longitude:.6f}" if has_location else "Unavailable"}</strong></td>
        </tr>
        <tr>
          <td class="label">Current Speed</td>
          <td class="value">{f"{speed_kmh:.1f} km/h" if speed_kmh is not None else "N/A"}</td>
        </tr>
        <tr>
          <td class="label">Alert ID</td>
          <td class="value" style="font-family: monospace; font-size: 12px; color: #64748b;">{alert_id}</td>
        </tr>
      </table>

      {f'<a href="{maps_link}" class="btn" target="_blank">📍 Open Location in Google Maps</a>' if has_location else ''}
    </div>
    <div class="footer">
      Automated safety notification generated by the Road-Events backend.
    </div>
  </div>
</body>
</html>
"""

        msg.set_content(plain_text)
        msg.add_alternative(html_content, subtype="html")

        logger.info(f"Connecting to SMTP server {settings.SMTP_HOST}:{settings.SMTP_PORT} to send alert email...")
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT, timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
            server.send_message(msg)

        logger.info(f"Successfully delivered alert email to {settings.ALERT_RECIPIENT_EMAIL} for alert {alert_id}")
        return True

    except Exception as e:
        logger.error(f"Failed to dispatch alert email to {settings.ALERT_RECIPIENT_EMAIL}: {e}", exc_info=True)
        return False
