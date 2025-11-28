import os
import logging
import smtplib
from dotenv import load_dotenv
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

load_dotenv()

# SMTP‑настройки из окружения
SMTP_SERVER = os.getenv("SMTP_SERVER", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", 587))
SMTP_USERNAME = os.getenv("SMTP_USERNAME")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")
SENDER_EMAIL = os.getenv("SENDER_EMAIL", SMTP_USERNAME)


def send_recovery_email(recipient_email: str, recovery_link: str, subject, text, html):
    """Отправляет письмо для восстановления пароля с HTML и текстовой версией"""
    # subject = "Восстановление пароля"
    # text = (
    #     "Для восстановления пароля перейдите по ссылке:\n"
    #     f"{recovery_link}\n\n"
    #     "Если вы не запрашивали восстановление, проигнорируйте это письмо."
    # )
    # html = f"""
    #     <html>
    #         <body>
    #             <p>Здравствуйте!</p>
    #             <p>Чтобы <b>сбросить пароль</b>, перейдите по ссылке ниже:</p>
    #             <p><a href="{recovery_link}">Сбросить пароль</a></p>
    #             <p>Ссылка действительна 1 час. Если вы не запрашивали сброс - просто проигнорируйте это письмо.</p>
    #         </body>
    #     </html>
    # """

    # Собираем мультипарт
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = SENDER_EMAIL
    msg["To"] = recipient_email

    # Добавляем версии письма
    msg.attach(MIMEText(text, "plain"))
    msg.attach(MIMEText(html, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.ehlo()
            server.starttls()
            server.login(SMTP_USERNAME, SMTP_PASSWORD)
            server.send_message(msg)
        logging.info(f"Recovery email sent to {recipient_email}")
    except Exception as e:
        logging.error(f"Failed to send recovery email to {recipient_email}: {e}")