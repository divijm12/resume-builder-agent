#!/usr/bin/env python3
"""Gmail send integration -- the only place in this codebase allowed to
send email. Uses plain SMTP with a Gmail "App Password" (myaccount.google.com/apppasswords,
requires 2-Step Verification on the account) rather than OAuth2 + the
Gmail API -- deliberately simpler setup for a single-user local tool
(no Google Cloud project, no OAuth consent screen, no browser flow),
same pattern already used in this user's other project (Teleworld
Mobile Tracker's GMAIL_APP_PASSWORD). Tradeoff, stated plainly: an App
Password is a broader, account-level credential (SMTP/IMAP access) than
an OAuth token scoped to `gmail.send` only -- acceptable here since it
lives only in `.env` (gitignored) on the user's own machine, same trust
boundary as HUNTER_API_KEY/ANTHROPIC_API_KEY already have.

Never imported by apply.py or any agents/*.py -- this is called from
exactly one place, review/backend/main.py's /send-outreach endpoint,
which itself only fires on an explicit, confirmed frontend click (see
that endpoint's docstring). No pipeline stage can trigger a send.

Setup (one-time, per user -- nothing here is hardcoded to any specific
account): enable 2-Step Verification on your Google account, generate an
App Password at myaccount.google.com/apppasswords, then add to .env:
    GMAIL_ADDRESS=you@gmail.com
    GMAIL_APP_PASSWORD=xxxxxxxxxxxxxxxx
"""

import os
import smtplib
from email.message import EmailMessage

from dotenv import load_dotenv

load_dotenv()

GMAIL_ADDRESS = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587


def send_email(to_email: str, subject: str, body_text: str) -> dict:
    """Send one email via Gmail's SMTP server. Raises a clear, actionable
    RuntimeError if the account isn't configured -- never a bare
    connection/auth stack trace."""
    if not GMAIL_ADDRESS or not GMAIL_APP_PASSWORD:
        raise RuntimeError(
            "Gmail not connected -- set GMAIL_ADDRESS and GMAIL_APP_PASSWORD in .env "
            "(generate an App Password at myaccount.google.com/apppasswords, requires "
            "2-Step Verification to be enabled on the account first)."
        )

    message = EmailMessage()
    message.set_content(body_text)
    message["To"] = to_email
    message["From"] = GMAIL_ADDRESS
    message["Subject"] = subject

    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.starttls()
        server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
        server.send_message(message)

    return {"sent": True}
