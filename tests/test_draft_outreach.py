"""Tests for agents/draft_outreach.py: cold/referral email types, the
deterministic sign-off and job-link insertion, the length-budget and
formatting soft-flags, and the JD-relevance check. See ARCHITECTURE.md
Stage 6 and LEARNING_LOG.md sections 17-18."""

from unittest.mock import MagicMock, patch

import draft_outreach

TAILORED_RESUME = {
    "basics": {"name": "Jane Candidate", "email": "jane@example.com"},
    "experience": [{"bullets": [{"id": "b_001", "text": "Reduced pipeline latency by 40% using Kafka."}]}],
    "projects": [],
}

JD_PARSED = {
    "role": "Software Engineer",
    "company": "Acme Corp",
    "must_have_skills": ["Kafka", "Python", "distributed systems"],
    "nice_to_have": [],
    "keywords": ["streaming", "backend"],
    "responsibilities": ["Build backend data pipelines"],
}


def _mock_response(subject, paragraphs):
    resp = MagicMock()
    resp.parsed_output = draft_outreach.OutreachDraftSchema(subject=subject, paragraphs=paragraphs)
    return resp


def _generate(paragraphs, subject="Subject", **kwargs):
    with patch("draft_outreach.anthropic.Anthropic") as MockClient:
        mock = MockClient.return_value
        mock.messages.parse.return_value = _mock_response(subject, paragraphs)
        result = draft_outreach.generate_outreach_draft(JD_PARSED, TAILORED_RESUME, "Acme Corp", **kwargs)
        return result, mock


# --- Cold email, core validation reuse ---


def test_normal_claim_survives_with_sign_off_and_paragraph_break():
    paragraphs = [
        [{"text": "Hi Jane Doe,", "source_bullet_ids": []}],
        [{"text": "I reduced pipeline latency by 40% using Kafka.", "source_bullet_ids": ["b_001"]}],
    ]
    result, mock = _generate(paragraphs, subject="Applying -- quick note", contact_name="Jane Doe")
    assert "--" not in result["subject"] and "—" not in result["subject"]
    assert "40%" in result["body_text"]
    assert result["body_text"].endswith("Warm regards,\nJane Candidate\njane@example.com")
    assert "\n\n" in result["body_text"]
    assert result["validation_log"] == []
    mock.messages.parse.assert_called_once()
    assert mock.messages.parse.call_args.kwargs["system"] == draft_outreach.SYSTEM_PROMPT_COLD


def test_fabricated_number_dropped():
    paragraphs = [
        [{"text": "Hi Jane Doe,", "source_bullet_ids": []}],
        [{"text": "I reduced pipeline latency by 90% using Kafka.", "source_bullet_ids": ["b_001"]}],
    ]
    result, _ = _generate(paragraphs)
    assert "90%" not in result["body_text"]
    assert len(result["validation_log"]) > 0


def test_paragraph_losing_all_claims_leaves_body_empty_no_signoff_leak():
    paragraphs = [[{"text": "I reduced latency by 999% somehow.", "source_bullet_ids": ["b_001"]}]]
    result, _ = _generate(paragraphs)
    assert result["body_text"] == ""


def test_merged_greeting_triggers_formatting_flag():
    paragraphs = [[
        {"text": "Hi Jane Doe,", "source_bullet_ids": []},
        {"text": "I reduced pipeline latency by 40% using Kafka.", "source_bullet_ids": ["b_001"]},
    ]]
    result, _ = _generate(paragraphs)
    assert any("separate lines" in w for w in result["validation_log"])


# --- JD-relevance check ---


def test_relevant_hook_no_flag():
    paragraphs = [
        [{"text": "Hi Jane Doe,", "source_bullet_ids": []}],
        [{"text": "I reduced pipeline latency by 40% using Kafka.", "source_bullet_ids": ["b_001"]}],
    ]
    result, _ = _generate(paragraphs)  # Kafka overlaps JD's must_have_skills
    assert not any("recognizable skill" in w for w in result["validation_log"])


def test_irrelevant_hook_flagged():
    tailored_resume_irrelevant = {
        **TAILORED_RESUME,
        "experience": [{"bullets": [{"id": "b_002", "text": "Organized 3 company offsite events for 50 attendees."}]}],
    }
    paragraphs = [
        [{"text": "Hi Jane Doe,", "source_bullet_ids": []}],
        [{"text": "I organized 3 offsite events for 50 attendees.", "source_bullet_ids": ["b_002"]}],
    ]
    with patch("draft_outreach.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.parse.return_value = _mock_response("Subject", paragraphs)
        result = draft_outreach.generate_outreach_draft(JD_PARSED, tailored_resume_irrelevant, "Acme Corp")
    assert any("recognizable skill" in w for w in result["validation_log"])


# --- Referral email type ---


def test_referral_without_job_link_raises():
    try:
        draft_outreach.generate_outreach_draft(JD_PARSED, TAILORED_RESUME, "Acme Corp", email_type="referral")
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_invalid_email_type_raises():
    try:
        draft_outreach.generate_outreach_draft(JD_PARSED, TAILORED_RESUME, "Acme Corp", email_type="bogus")
        assert False, "should have raised ValueError"
    except ValueError:
        pass


def test_referral_uses_referral_prompt_and_inserts_link_deterministically():
    job_link = "https://acme.com/careers/software-engineer-123"
    paragraphs = [
        [{"text": "Hi Jane Doe,", "source_bullet_ids": []}],
        [{"text": "I'm interested in the Software Engineer role and would love a referral. No worries if not.", "source_bullet_ids": []}],
    ]
    result, mock = _generate(paragraphs, subject="Referral ask", email_type="referral", job_link=job_link)
    assert mock.messages.parse.call_args.kwargs["system"] == draft_outreach.SYSTEM_PROMPT_REFERRAL
    assert f"Job posting: {job_link}" in result["body_text"]


def test_referral_link_survives_even_if_model_writes_url_and_trips_numeric_guardrail():
    """The bug this design fixes: a URL's job-id number ('.../123') looks
    like an unverified metric to the numeric-fabrication check, dropping
    the whole claim -- but the deterministic link line doesn't depend on
    that claim surviving."""
    job_link = "https://acme.com/careers/software-engineer-123"
    paragraphs = [
        [{"text": "Hi Jane Doe,", "source_bullet_ids": []}],
        [{"text": f"I saw the posting ({job_link}) and would love a referral.", "source_bullet_ids": []}],
    ]
    result, _ = _generate(paragraphs, email_type="referral", job_link=job_link)
    assert result["body_text"].strip() != ""
    assert job_link in result["body_text"]


def test_neither_prompt_calls_it_tailored_to_the_recipient():
    assert "never 'my tailored resume'" in draft_outreach.SYSTEM_PROMPT_COLD
    assert "never 'my tailored resume'" in draft_outreach.SYSTEM_PROMPT_REFERRAL
