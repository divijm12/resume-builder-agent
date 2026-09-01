"""Tests for agents/tailor.py's no-fabrication guardrails -- the core
correctness guarantee of the whole project. All mocked, no real API
calls. See ARCHITECTURE.md Stage 2 and LEARNING_LOG.md sections 8-11, 22
for the real bugs each of these checks was built to catch."""

from unittest.mock import MagicMock, patch

import tailor

MASTER_RESUME = {
    "basics": {"name": "Test Person"},
    "skills": [{"name": "PyTorch", "tags": []}, {"name": "TensorFlow", "tags": []}],
    "experience": [
        {
            "id": "exp_001",
            "company": "TestCo",
            "title": "Engineer",
            "start": "2020",
            "end": "present",
            "bullets": [
                {"id": "b_001", "text": "Reduced latency 40% by migrating to Kafka using PyTorch pipelines."},
                {
                    "id": "b_002",
                    "text": (
                        "Improved ML model prediction accuracy 35% for a turfgrass disease outbreak "
                        "research project by cleaning and preparing a 50,000+ entry structured dataset, "
                        "engineering domain-relevant features, training neural networks using PyTorch "
                        "and TensorFlow, and evaluating model outputs across multiple training cycles."
                    ),
                },
            ],
        },
    ],
    "projects": [],
    "education": [],
    "certifications": [],
}
ORIGINAL_B001 = MASTER_RESUME["experience"][0]["bullets"][0]["text"]
ORIGINAL_B002 = MASTER_RESUME["experience"][0]["bullets"][1]["text"]


def _plan(bullet_text_map):
    return {
        "selected_skills": [{"master_skill_name": "PyTorch"}, {"master_skill_name": "TensorFlow"}],
        "experience": [{"id": "exp_001", "bullets": [{"id": bid, "text": txt} for bid, txt in bullet_text_map.items()]}],
        "projects": [],
        "diff_summary": [],
        "unaddressed_hard_gaps": [],
        "unaddressed_red_flags": [],
        "unaddressed_reword_opportunities": [],
        "ats_scan_notes": [],
    }


def _final_text(result, bullet_id):
    for exp in result["tailored_resume"]["experience"]:
        for b in exp["bullets"]:
            if b["id"] == bullet_id:
                return b["text"]
    return None


# --- Phrase-detection heuristic (_distinctive_phrases / _dropped_phrases) ---


def test_turfgrass_case_detected():
    bad_reword = ORIGINAL_B002.replace("a turfgrass disease outbreak research project", "a research project")
    dropped = tailor._dropped_phrases(ORIGINAL_B002, bad_reword)
    assert any("turfgrass" in p.lower() for p in dropped)


def test_legitimate_paraphrase_also_flagged_known_tradeoff():
    """Documents the accepted false-positive tradeoff -- see ARCHITECTURE.md
    Stage 2 and LEARNING_LOG.md section 22. Not a bug."""
    original = "...applying structured data quality validation rules at each transformation stage..."
    paraphrase = "...applying rigorous data checks throughout the pipeline..."
    assert len(tailor._dropped_phrases(original, paraphrase)) > 0


def test_phrase_substantially_preserved_no_false_alarm():
    original = "Built a live submission intake platform for 500+ field agents."
    good_reword = "Built a live intake platform serving 500+ field agents."
    assert tailor._dropped_phrases(original, good_reword) == []


def test_majority_threshold_not_any_single_word():
    """Regression for the bug the first mocked test of this feature caught:
    an 'any single word survives' rule let 'turfgrass disease outbreak'
    disappear because the generic tail 'research project' alone survived."""
    generic_tail_only = ORIGINAL_B002.replace(
        "a turfgrass disease outbreak research project", "a research project"
    )
    dropped = tailor._dropped_phrases(ORIGINAL_B002, generic_tail_only)
    assert dropped, "must flag when only the generic tail of a phrase survives"


# --- Existing guardrails still work after the _check_bullet refactor ---


def test_numeric_fabrication_reverts():
    plan = _plan({"b_001": "Reduced latency 90% by migrating to Kafka using PyTorch pipelines."})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive")
    assert "90%" not in _final_text(result, "b_001")
    assert any("introduced a number" in w for w in result["validation_log"])


def test_dropped_named_tech_term_reverts():
    plan = _plan({"b_001": "Reduced latency 40% by migrating to Kafka."})  # drops "PyTorch"
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive")
    assert _final_text(result, "b_001") == ORIGINAL_B001
    assert any("dropped named" in w for w in result["validation_log"])


def test_appended_clause_reverts():
    orig_core = ORIGINAL_B001.rstrip().rstrip(".").rstrip()
    plan = _plan({"b_001": orig_core + " -- demonstrating strong backend skills"})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive")
    assert _final_text(result, "b_001") == ORIGINAL_B001
    assert any("demonstrating X" in w for w in result["validation_log"])


def test_honest_mode_locks_bullet_text():
    plan = _plan({"b_001": "Something totally different that should be ignored."})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="honest")
    assert _final_text(result, "b_001") == ORIGINAL_B001


def test_distinctive_phrase_drop_no_client_reverts_immediately():
    plan = _plan({
        "b_001": ORIGINAL_B001,
        "b_002": ORIGINAL_B002.replace("a turfgrass disease outbreak research project", "a research project"),
    })
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive")  # no client passed
    assert _final_text(result, "b_002") == ORIGINAL_B002
    assert any("no retry attempted (no client provided)" in w for w in result["validation_log"])


# --- Retry-before-revert mechanism ---


def _retry_response(text):
    resp = MagicMock()
    resp.parsed_output = tailor.BulletRetryResult(text=text)
    return resp


def _generic_b002():
    return ORIGINAL_B002.replace("a turfgrass disease outbreak research project", "a research project")


def test_retry_success_is_accepted():
    fixed = ORIGINAL_B002.replace(
        "a turfgrass disease outbreak research project", "a turfgrass disease outbreak project"
    )
    client = MagicMock()
    client.messages.parse.return_value = _retry_response(fixed)
    plan = _plan({"b_002": _generic_b002()})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive", client=client, retry_model="claude-haiku-4-5")
    assert _final_text(result, "b_002") == fixed
    assert any("correction accepted" in w for w in result["validation_log"])
    assert client.messages.parse.call_count == 1


def test_retry_still_fails_reverts():
    still_bad = _generic_b002() + " using deep learning techniques"
    client = MagicMock()
    client.messages.parse.return_value = _retry_response(still_bad)
    plan = _plan({"b_002": _generic_b002()})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive", client=client, retry_model="claude-haiku-4-5")
    assert _final_text(result, "b_002") == ORIGINAL_B002
    assert any("still had issues, reverted" in w for w in result["validation_log"])


def test_retry_fixes_one_thing_but_introduces_new_fabrication_still_reverts():
    """Proves the retry's output gets the FULL guardrail suite re-run, not
    just the one check that originally fired."""
    new_fabrication = ORIGINAL_B002.replace("35%", "99%")
    client = MagicMock()
    client.messages.parse.return_value = _retry_response(new_fabrication)
    plan = _plan({"b_002": _generic_b002()})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive", client=client, retry_model="claude-haiku-4-5")
    assert _final_text(result, "b_002") == ORIGINAL_B002
    assert "99%" not in _final_text(result, "b_002")


def test_retry_api_failure_treated_as_still_bad():
    client = MagicMock()
    client.messages.parse.side_effect = Exception("network error")
    plan = _plan({"b_002": _generic_b002()})
    result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive", client=client, retry_model="claude-haiku-4-5")
    assert _final_text(result, "b_002") == ORIGINAL_B002


def test_retry_cap_skips_retry_entirely():
    client = MagicMock()
    fixed = ORIGINAL_B002.replace(
        "a turfgrass disease outbreak research project", "a turfgrass disease outbreak project"
    )
    client.messages.parse.return_value = _retry_response(fixed)
    plan = _plan({"b_002": _generic_b002()})
    with patch.object(tailor, "MAX_RETRIES_PER_RUN", 0):
        result = tailor.validate_and_build(plan, MASTER_RESUME, mode="aggressive", client=client, retry_model="claude-haiku-4-5")
    assert _final_text(result, "b_002") == ORIGINAL_B002
    assert client.messages.parse.call_count == 0
    assert any("retry cap reached" in w for w in result["validation_log"])
