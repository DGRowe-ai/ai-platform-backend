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
