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


def get_client_dashboard_url() -> str:
    frontend_url = (
        os.getenv("FRONTEND_PUBLIC_URL")
        or os.getenv("PUBLIC_FRONTEND_URL")
        or "https://ai-platform-frontend-uaaa.onrender.com"
    ).rstrip("/")
    return f"{frontend_url}/client-dashboard.html"


def send_service_suspension_email(
    *,
    to_email: str,
    business_name: str,
    dashboard_url: str | None = None,
) -> None:
    manage_url = dashboard_url or get_client_dashboard_url()
    body = f"""Hello,

We were unable to confirm payment for your Rowe AI subscription, so the chatbot for {business_name} has been temporarily suspended.

While your account is suspended:
- Your website chatbot will not respond to visitors
- Your chatbot service is offline until billing is updated

To reactivate your chatbot, sign in to your client dashboard and update your payment details using Manage Subscription:

{manage_url}

Once your payment is up to date, your chatbot will be restored.

If you believe this is an error or need help, reply to this email and our team will assist you.

Thank you,
Rowe AI Support
"""

    send_email(
        to_email=to_email,
        subject="Your Rowe AI Chatbot Has Been Suspended",
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
