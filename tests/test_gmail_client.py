"""Tests for review/backend/gmail_client.py: MIME construction and the
hard "missing attachment blocks the send" guarantee -- if the draft's own
text says a resume is attached, it actually has to be. See
ARCHITECTURE.md's Stage 7 outreach-send notes and LEARNING_LOG.md
section 19."""

import base64
from email import message_from_bytes, policy
from email.message import EmailMessage
from unittest.mock import patch

import gmail_client


def test_mime_construction_and_base64url_roundtrip():
    message = EmailMessage()
    message.set_content("Hi Jane,\n\nTest body.\n\nWarm regards,\nAlex Rivera")
    message["To"] = "jane@example.com"
    message["Subject"] = "Test Subject"

    encoded = base64.urlsafe_b64encode(message.as_bytes()).decode()
    decoded = base64.urlsafe_b64decode(encoded)
    parsed = message_from_bytes(decoded, policy=policy.default)

    assert parsed["To"] == "jane@example.com"
    assert parsed["Subject"] == "Test Subject"
    assert "Warm regards" in parsed.get_content()
    assert not parsed["From"]  # never set explicitly -- Gmail fills it from the authenticated account


class _FakeSMTP:
    sent_messages: list = []

    def __init__(self, *a, **kw):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass

    def starttls(self):
        pass

    def login(self, *a):
        pass

    def send_message(self, msg):
        _FakeSMTP.sent_messages.append(msg)


def setup_function():
    gmail_client.GMAIL_ADDRESS = "me@example.com"
    gmail_client.GMAIL_APP_PASSWORD = "fakepassword"
    _FakeSMTP.sent_messages = []


def test_both_attachments_present(tmp_path):
    resume_pdf = tmp_path / "resume.pdf"
    cover_pdf = tmp_path / "cover.pdf"
    resume_pdf.write_text("fake resume content")
    cover_pdf.write_text("fake cover letter content")

    with patch("gmail_client.smtplib.SMTP", _FakeSMTP):
        gmail_client.send_email("to@example.com", "Subject", "Body", attachment_paths=[resume_pdf, cover_pdf])

    attachments = list(_FakeSMTP.sent_messages[0].iter_attachments())
    assert {a.get_filename() for a in attachments} == {"resume.pdf", "cover.pdf"}


def test_resume_only_no_cover_letter(tmp_path):
    resume_pdf = tmp_path / "resume.pdf"
    resume_pdf.write_text("fake resume content")

    with patch("gmail_client.smtplib.SMTP", _FakeSMTP):
        gmail_client.send_email("to@example.com", "Subject", "Body", attachment_paths=[resume_pdf])

    attachments = list(_FakeSMTP.sent_messages[0].iter_attachments())
    assert len(attachments) == 1
    assert attachments[0].get_filename() == "resume.pdf"


def test_missing_attachment_blocks_send_entirely(tmp_path):
    missing = tmp_path / "does_not_exist.pdf"
    try:
        with patch("gmail_client.smtplib.SMTP", _FakeSMTP):
            gmail_client.send_email("to@example.com", "Subject", "Body", attachment_paths=[missing])
        assert False, "should have raised RuntimeError"
    except RuntimeError:
        assert _FakeSMTP.sent_messages == [], "nothing should be sent if an attachment is missing"


def test_no_attachments_backward_compatible():
    with patch("gmail_client.smtplib.SMTP", _FakeSMTP):
        gmail_client.send_email("to@example.com", "Subject", "Body")
    assert list(_FakeSMTP.sent_messages[0].iter_attachments()) == []


def test_not_connected_raises_clear_error():
    gmail_client.GMAIL_ADDRESS = None
    gmail_client.GMAIL_APP_PASSWORD = None
    try:
        gmail_client.send_email("to@example.com", "Subject", "Body")
        assert False, "should have raised RuntimeError"
    except RuntimeError as e:
        assert "Gmail not connected" in str(e)
