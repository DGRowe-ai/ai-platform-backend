import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from dotenv import load_dotenv
import os

# Load environment variables
load_dotenv()

SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
VERIFIED_SENDER = os.getenv("VERIFIED_SENDER")
REPORT_RECIPIENT = os.getenv("REPORT_RECIPIENT", "rowe-ai@outlook.com")
ADMIN_REGISTRATION_EMAIL = os.getenv(
    "ADMIN_REGISTRATION_EMAIL",
    os.getenv("REPORT_RECIPIENT", "daryl_rowe@hotmail.com"),
)


def send_email(to_email, subject, body):
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = VERIFIED_SENDER
    msg["To"] = to_email

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.sendmail(VERIFIED_SENDER, to_email, msg.as_string())
    server.quit()


def send_admin_registration_notification(
    *,
    user_email: str,
    business_name: str,
    billing_status: str,
    stripe_customer_id: str | None = None,
    registered_at: str | None = None,
    client_ip: str | None = None,
) -> None:
    timestamp = registered_at or "unknown"
    stripe_id = stripe_customer_id or "not available"
    ip_line = f"IP Address: {client_ip}\n" if client_ip else ""

    body = f"""A new user has registered on Rowe AI.

Email: {user_email}
Business Name: {business_name}
Billing Status: {billing_status}
Stripe Customer ID: {stripe_id}
Registered At: {timestamp}
{ip_line}
– Rowe AI System
"""

    send_email(
        to_email=ADMIN_REGISTRATION_EMAIL,
        subject="New Rowe AI Registration",
        body=body,
    )


def send_email_with_attachment(to_email, subject, body, attachment_bytes, attachment_filename, mime_type="application/pdf"):
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = VERIFIED_SENDER
    msg["To"] = to_email
    msg.attach(MIMEText(body))

    attachment = MIMEApplication(attachment_bytes, _subtype=mime_type.split("/")[-1])
    attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    msg.attach(attachment)

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.sendmail(VERIFIED_SENDER, to_email, msg.as_string())
    server.quit()
