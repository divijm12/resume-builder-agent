"""Tests for agents/cover_letter.py's citation-verification guardrail.
No 'known-good original' exists for free-form prose the way a resume
bullet has, so every claim must cite which real bullet grounds it, and
code verifies every number in a claim against its cited bullet's actual
text. See ARCHITECTURE.md Stage 4 and LEARNING_LOG.md section 12."""

import cover_letter

TAILORED_RESUME = {
    "experience": [
        {"bullets": [{"id": "b_001", "text": "Reduced latency 40% using Kafka."}]},
    ],
    "projects": [
        {"bullets": [{"id": "p_001", "text": "Built a dashboard used by 200+ users."}]},
    ],
}


def test_valid_claim_survives():
    draft = {"paragraphs": [[{"text": "I reduced latency 40% using Kafka.", "source_bullet_ids": ["b_001"]}]]}
    result = cover_letter.validate_and_build(draft, TAILORED_RESUME)
    assert "40%" in result["cover_letter_text"]
    assert result["validation_log"] == []


def test_fabricated_number_dropped():
    draft = {"paragraphs": [[{"text": "I reduced latency 90% using Kafka.", "source_bullet_ids": ["b_001"]}]]}
    result = cover_letter.validate_and_build(draft, TAILORED_RESUME)
    assert "90%" not in result["cover_letter_text"]
    assert len(result["validation_log"]) > 0


def test_unknown_bullet_id_stripped_from_citation_but_number_still_checked():
    # cited id doesn't exist -> cited_text is empty -> any number in the
    # claim is "not present in its cited bullets" and gets dropped
    draft = {"paragraphs": [[{"text": "I reduced latency 40% somehow.", "source_bullet_ids": ["b_999"]}]]}
    result = cover_letter.validate_and_build(draft, TAILORED_RESUME)
    assert "40%" not in result["cover_letter_text"]
    assert any("unknown bullet id" in w for w in result["validation_log"])


def test_claim_with_no_citation_and_no_number_survives():
    # generic connective sentences (greeting, closing) legitimately have no citation
    draft = {"paragraphs": [[{"text": "I'm excited to apply for this role.", "source_bullet_ids": []}]]}
    result = cover_letter.validate_and_build(draft, TAILORED_RESUME)
    assert "excited to apply" in result["cover_letter_text"]
    assert result["validation_log"] == []


def test_paragraph_losing_every_claim_is_dropped_not_left_blank():
    draft = {
        "paragraphs": [
            [{"text": "I reduced latency 40% using Kafka.", "source_bullet_ids": ["b_001"]}],
            [{"text": "I reduced latency 999% somehow.", "source_bullet_ids": ["b_001"]}],
        ]
    }
    result = cover_letter.validate_and_build(draft, TAILORED_RESUME)
    assert "999%" not in result["cover_letter_text"]
    assert "40%" in result["cover_letter_text"]
    # only one paragraph survives -- no stray blank line where the bad one was
    assert result["cover_letter_text"].count("\n\n") == 0


def test_em_dash_stripped():
    text = "I built systems -- and scaled them well."
    cleaned = cover_letter._strip_em_dashes(text)
    assert "--" not in cleaned
    assert "—" not in cleaned


def test_em_dash_stripped_in_full_validation():
    draft = {"paragraphs": [[{"text": "I reduced latency 40% -- using Kafka.", "source_bullet_ids": ["b_001"]}]]}
    result = cover_letter.validate_and_build(draft, TAILORED_RESUME)
    assert "--" not in result["cover_letter_text"]
    assert any("Stripped an em dash" in w for w in result["validation_log"])


def test_bullet_lookup_covers_experience_and_projects():
    lookup = cover_letter._bullet_lookup(TAILORED_RESUME)
    assert lookup["b_001"] == "Reduced latency 40% using Kafka."
    assert lookup["p_001"] == "Built a dashboard used by 200+ users."
