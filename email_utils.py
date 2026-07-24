import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication
from email.mime.image import MIMEImage
from pathlib import Path
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
PASSWORD_RESET_SENDER = os.getenv("PASSWORD_RESET_SENDER", "support@roweai.ca")
PASSWORD_RESET_BASE_URL = os.getenv("PASSWORD_RESET_BASE_URL", "https://roweai.ca").rstrip("/")
REFERRAL_ADMIN_EMAIL = os.getenv(
    "REFERRAL_ADMIN_EMAIL",
    os.getenv("ADMIN_REGISTRATION_EMAIL", "daryl_rowe@hotmail.com"),
)
REVIEW_EMAIL_SENDER = os.getenv("REVIEW_EMAIL_SENDER", "support@roweai.ca")
GOOGLE_REVIEW_URL = "https://share.google/HIvgRJCoeZ1NLXap0"
REVIEW_EMAIL_SUBJECT = "We'd Love To Hear Your Review"
CLIENT_SERVICE_AGREEMENT_FILENAME = "Client Service Agreement.pdf"


def _get_client_service_agreement_bytes() -> bytes:
    """Load the Client Service Agreement PDF bundled with the backend."""
    candidates = [
        Path(__file__).resolve().parent / "assets" / CLIENT_SERVICE_AGREEMENT_FILENAME,
        Path(__file__).resolve().parent.parent
        / "ai-latform"
        / CLIENT_SERVICE_AGREEMENT_FILENAME,
        Path(__file__).resolve().parent.parent
        / "ai-platform"
        / CLIENT_SERVICE_AGREEMENT_FILENAME,
    ]
    for path in candidates:
        if path.exists():
            return path.read_bytes()
    raise FileNotFoundError(
        f"{CLIENT_SERVICE_AGREEMENT_FILENAME} not found in assets/"
    )


def send_welcome_email_with_attachment(
    *,
    to_email: str,
    subject: str,
    body: str,
    from_email=None,
) -> None:
    """Send a welcome email with the Client Service Agreement attached."""
    agreement_note = (
        "\n----------------------------------------\n"
        "Client Service Agreement\n"
        "----------------------------------------\n"
        "Please find your Client Service Agreement attached to this email.\n"
    )
    if "Client Service Agreement" not in body:
        body = body.rstrip() + "\n" + agreement_note

    send_email_with_attachment(
        to_email,
        subject,
        body,
        _get_client_service_agreement_bytes(),
        CLIENT_SERVICE_AGREEMENT_FILENAME,
        from_email=from_email or PASSWORD_RESET_SENDER,
    )



def send_email(to_email, subject, body, from_email=None):
    sender = from_email or VERIFIED_SENDER
    msg = MIMEText(body)
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.sendmail(sender, to_email, msg.as_string())
    server.quit()


def send_appointment_owner_notification(
    *,
    to_email: str,
    business_name: str,
    appointment: dict,
) -> None:
    when = appointment.get("normalized_datetime") or (
        f"{appointment.get('requested_date')} {appointment.get('requested_time')}"
    )
    body = f"""Hello,

A new appointment request was received for {business_name}.

Customer: {appointment.get('customer_name')}
Contact: {appointment.get('customer_contact')}
Service: {appointment.get('service')}
Requested time: {when} ({appointment.get('timezone')})
Status: {appointment.get('status')}
Notes: {appointment.get('notes') or 'None'}

Sign in to your client dashboard to review and update this request.

Rowe AI
"""
    send_email(
        to_email=to_email,
        subject=f"New appointment request for {business_name}",
        body=body,
    )


def send_appointment_confirmation_email(
    *,
    to_email: str,
    business_name: str,
    appointment: dict,
) -> None:
    when = appointment.get("normalized_datetime") or (
        f"{appointment.get('requested_date')} {appointment.get('requested_time')}"
    )
    body = f"""Hello {appointment.get('customer_name')},

Thank you for your appointment request with {business_name}.

Service: {appointment.get('service')}
Requested time: {when} ({appointment.get('timezone')})
Status: Pending

The business will review your request and confirm soon.

{business_name}
"""
    send_email(
        to_email=to_email,
        subject=f"Appointment request received — {business_name}",
        body=body,
    )


def _get_qr_code_image_bytes() -> bytes:
    from pathlib import Path

    candidates = [
        Path(__file__).resolve().parent / "assets" / "qr-code-google-review.png",
        Path(__file__).resolve().parent.parent
        / "frontend"
        / "images"
        / "loki"
        / "qr code"
        / "qr-code-google-review.png",
    ]
    for path in candidates:
        if path.exists():
            return path.read_bytes()
    raise FileNotFoundError("Google review QR code image not found")


def send_review_request_email(*, to_email: str, business_name: str) -> None:
    """Thank the client after one week and ask for a Google review."""
    plain_body = f"""Hello,

Thank you for subscribing to Rowe AI and for trusting us with {business_name}'s chatbot.

We hope everything is going well so far. If you have any questions or run into any issues, please reach out to us at support@roweai.ca — we're happy to help.

We would also really appreciate it if you could leave us a Google review:
{GOOGLE_REVIEW_URL}

Thank you again for being a Rowe AI customer.

Rowe AI Support
support@roweai.ca
"""

    html_body = f"""<!DOCTYPE html>
<html>
  <body style="font-family: Arial, sans-serif; color: #172033; line-height: 1.6;">
    <p>Hello,</p>
    <p>Thank you for subscribing to Rowe AI and for trusting us with <strong>{business_name}</strong>'s chatbot.</p>
    <p>We hope everything is going well so far. If you have any questions or run into any issues, please reach out to us at
      <a href="mailto:support@roweai.ca">support@roweai.ca</a> — we're happy to help.</p>
    <p><strong>Please leave us a Google review using the QR code below:</strong></p>
    <p style="text-align: center;">
      <img src="cid:google-review-qr" alt="Google review QR code" style="max-width: 220px; width: 100%; height: auto;">
    </p>
    <p>You can also leave a review using this link:<br>
      <a href="{GOOGLE_REVIEW_URL}">{GOOGLE_REVIEW_URL}</a>
    </p>
    <p>Thank you again for being a Rowe AI customer.</p>
    <p>Rowe AI Support<br><a href="mailto:support@roweai.ca">support@roweai.ca</a></p>
  </body>
</html>
"""

    msg = MIMEMultipart("related")
    msg["Subject"] = REVIEW_EMAIL_SUBJECT
    msg["From"] = REVIEW_EMAIL_SENDER
    msg["To"] = to_email

    alternative = MIMEMultipart("alternative")
    alternative.attach(MIMEText(plain_body, "plain"))
    alternative.attach(MIMEText(html_body, "html"))
    msg.attach(alternative)

    qr_bytes = _get_qr_code_image_bytes()
    image = MIMEImage(qr_bytes, _subtype="png")
    image.add_header("Content-ID", "<google-review-qr>")
    image.add_header("Content-Disposition", "inline", filename="qr-code-google-review.png")
    msg.attach(image)

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.sendmail(REVIEW_EMAIL_SENDER, to_email, msg.as_string())
    server.quit()


def send_admin_registration_notification(
    *,
    user_email: str,
    business_name: str,
    billing_status: str,
    business_phone: str | None = None,
    stripe_customer_id: str | None = None,
    registered_at: str | None = None,
    client_ip: str | None = None,
) -> None:
    timestamp = registered_at or "unknown"
    stripe_id = stripe_customer_id or "not available"
    ip_line = f"IP Address: {client_ip}\n" if client_ip else ""
    phone_line = f"Business Phone: {business_phone}\n" if business_phone else ""

    body = f"""A new user has registered on Rowe AI.

Email: {user_email}
Business Name: {business_name}
{phone_line}Billing Status: {billing_status}
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


def get_password_reset_url(reset_token: str) -> str:
    return f"{PASSWORD_RESET_BASE_URL}/reset-password?token={reset_token}"


def send_password_reset_email(*, to_email: str, reset_token: str) -> None:
    reset_url = get_password_reset_url(reset_token)
    body = f"""Hello,

Click the link below to reset your Rowe AI password:

{reset_url}

This link expires in 30 minutes and can only be used once.

If you did not request this, you can ignore this email.

Rowe AI Support
"""

    send_email(
        to_email=to_email,
        subject="Reset Your Rowe AI Password",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_welcome_email_with_referral(
    *,
    to_email: str,
    business_name: str,
    chatbot_link: str,
    dashboard_link: str,
    embed_code: str,
    referral_link: str,
) -> None:
    body = f"""Welcome to Rowe AI, {business_name}!

Your AI chatbot is now live and ready to use.

----------------------------------------
Your Chatbot Link (for testing)
----------------------------------------
{chatbot_link}

----------------------------------------
Your Client Dashboard
----------------------------------------
{dashboard_link}

----------------------------------------
Your Website Embed Code
----------------------------------------
Paste this code before </body> on your website:

{embed_code}

----------------------------------------
Share Rowe AI and Earn Free Months
----------------------------------------
Love Rowe AI? Share your personal referral link with another business.
When they become a paying customer, you earn 1 free month added to your subscription.

Your referral link:
{referral_link}

----------------------------------------
Billing
----------------------------------------
Your 30-day trial and subscription are managed directly on the Rowe AI website.
Use Manage Subscription in your client dashboard to update payment details.

----------------------------------------
Need Help?
----------------------------------------
If you need help installing the chatbot or customizing responses,
just reply to this email and we'll take care of you.

Thanks for choosing Rowe AI!
"""

    send_welcome_email_with_attachment(
        to_email=to_email,
        subject="Welcome to Rowe AI — Here's Your Referral Link",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_voicebot_welcome_email(*, to_email: str, client_name: str) -> None:
    body = f"""Hi {client_name},

Welcome to Rowe AI Voicebot! Your AI phone receptionist is officially active and ready to start handling your calls.

To get started, please visit your Voicebot Dashboard:
https://ai-platform-frontend-uaaa.onrender.com/login.html

Inside your dashboard, you can:
• Enter your Business Phone Number
• Set your Voicebot personality
• Add your business knowledge (hours, pricing, FAQs)
• Configure name spelling
• Follow the Call Forwarding Setup instructions

Once you forward your business phone number to your AI receptionist, the bot will begin answering calls immediately.

If you need help, contact us anytime:
support@roweai.ca
226-343-9977

Welcome aboard — your AI receptionist is ready to work.

Rowe AI Team
"""

    send_welcome_email_with_attachment(
        to_email=to_email,
        subject="Welcome to Rowe AI Voicebot — Your AI Phone Receptionist Is Ready",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_duo_welcome_email(*, to_email: str, client_name: str) -> None:
    body = f"""Hi {client_name},

Welcome to Rowe AI Duo! Both your AI website chatbot and your AI phone receptionist are now active.

You can access your Duo dashboard here:

https://ai-platform-frontend-uaaa.onrender.com/login.html

After login you will be routed to the Duo dashboard with Chatbot and Voicebot side by side.

Please open the Duo dashboard to set up both bots:

VOICEBOT SETUP:
• Enter your Business Phone Number
• Set your Voicebot personality
• Add your business knowledge (hours, pricing, FAQs)
• Configure name spelling
• Follow the Call Forwarding Setup instructions
Once forwarding is enabled, your AI receptionist will begin answering calls immediately.

CHATBOT SETUP:
• Customize your chatbot script
• Add knowledge base content
• Install your widget on your website
• Adjust appearance and behavior

If you need help, contact us anytime:
support@roweai.ca
226-343-9977

Welcome to Rowe AI Duo — your business now has full AI coverage.

Rowe AI Team
"""

    send_welcome_email_with_attachment(
        to_email=to_email,
        subject="Welcome to Rowe AI Duo — Your Chatbot & Voicebot Are Ready",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_referred_user_welcome_email(
    *,
    to_email: str,
    business_name: str,
    referrer_name: str,
) -> None:
    body = f"""Welcome to Rowe AI, {business_name}!

You were referred by {referrer_name}. They earned a free month for helping you join Rowe AI.

Your chatbot is ready to set up in your client dashboard. If you need help getting started, just reply to this email.

Thank you for choosing Rowe AI!
"""

    send_welcome_email_with_attachment(
        to_email=to_email,
        subject="Welcome to Rowe AI",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_referral_reward_email(
    *,
    to_email: str,
    referral_link: str,
    updated_renewal_date: str | None = None,
    successful_referrals: int = 0,
    free_months_earned: int = 0,
) -> None:
    renewal_line = (
        f"Your updated renewal date is {updated_renewal_date}."
        if updated_renewal_date
        else "Your subscription has been extended by 30 days."
    )

    body = f"""Congratulations!

You earned a free month of Rowe AI because a business you referred became a paying customer.

{renewal_line}

Your referral stats:
- Successful referrals: {successful_referrals}
- Free months earned: {free_months_earned}

Keep sharing your referral link to earn more free months:
{referral_link}

Thank you for helping grow the Rowe AI community!

Rowe AI Support
"""

    send_email(
        to_email=to_email,
        subject="You Earned a Free Month of Rowe AI!",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_account_deleted_user_email(*, to_email: str) -> None:
    body = """Hello,

This confirms that your Rowe AI account and subscription have been permanently deleted.

All associated chatbot data, settings, and account information have been removed from our system.

Thank you for trying Rowe AI. We are sorry to see you go, and you are welcome back anytime.

Rowe AI Support
"""

    send_email(
        to_email=to_email,
        subject="Your Rowe AI Account Has Been Deleted",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_account_deleted_admin_email(
    *,
    user_email: str,
    business_names: list[str],
    deleted_at: str,
    subscription_canceled: bool,
    referral_code: str | None = None,
    referral_count: int = 0,
    free_months_earned: int = 0,
) -> None:
    business_line = ", ".join(business_names) if business_names else "None"
    referral_line = referral_code or "None"

    body = f"""A user deleted their Rowe AI account from the client dashboard.

User email: {user_email}
Business name(s): {business_line}
Date/time: {deleted_at}
Stripe subscription canceled: {"Yes" if subscription_canceled else "No"}

Referral data removed:
- Referral code: {referral_line}
- Successful referrals: {referral_count}
- Free months earned: {free_months_earned}

Rowe AI System
"""

    send_email(
        to_email=REFERRAL_ADMIN_EMAIL,
        subject="User Account Deleted",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_admin_referral_conversion_email(
    *,
    referrer_name: str,
    referrer_email: str,
    referred_name: str,
    referred_email: str,
    converted_at: str,
) -> None:
    body = f"""A referral conversion was processed automatically.

Referrer:
- Name: {referrer_name}
- Email: {referrer_email}

New customer:
- Name: {referred_name}
- Email: {referred_email}

Date/time: {converted_at}

Action taken:
- 30-day subscription extension applied to the referrer
- Referral reward emails sent

Rowe AI System
"""

    send_email(
        to_email=REFERRAL_ADMIN_EMAIL,
        subject="New Referral Conversion",
        body=body,
        from_email=PASSWORD_RESET_SENDER,
    )


def send_email_with_attachment(
    to_email,
    subject,
    body,
    attachment_bytes,
    attachment_filename,
    mime_type="application/pdf",
    from_email=None,
):
    sender = from_email or VERIFIED_SENDER
    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = to_email
    msg.attach(MIMEText(body))

    attachment = MIMEApplication(attachment_bytes, _subtype=mime_type.split("/")[-1])
    attachment.add_header("Content-Disposition", "attachment", filename=attachment_filename)
    msg.attach(attachment)

    server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
    server.starttls()
    server.login(SMTP_USER, SMTP_PASSWORD)
    server.sendmail(sender, to_email, msg.as_string())
    server.quit()
