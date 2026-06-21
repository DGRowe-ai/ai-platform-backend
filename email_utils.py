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
PASSWORD_RESET_SENDER = os.getenv("PASSWORD_RESET_SENDER", "support@roweai.ca")
PASSWORD_RESET_BASE_URL = os.getenv("PASSWORD_RESET_BASE_URL", "https://roweai.ca").rstrip("/")
REFERRAL_ADMIN_EMAIL = os.getenv(
    "REFERRAL_ADMIN_EMAIL",
    os.getenv("ADMIN_REGISTRATION_EMAIL", "daryl_rowe@hotmail.com"),
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

    send_email(
        to_email=to_email,
        subject="Welcome to Rowe AI — Here's Your Referral Link",
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

    send_email(
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
