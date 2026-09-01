"""Tests for agents/parse_resume.py: id-assignment matching the real
master_resume.yaml convention, links reshaping, and the global
numeric-fabrication check (see module docstring for why it's global
rather than per-bullet). See ARCHITECTURE.md Stage -1 and
LEARNING_LOG.md section 20."""

from unittest.mock import MagicMock, patch

import parse_resume

RAW_TEXT = """
Jane Doe
jane.doe@example.com | 555-123-4567
linkedin.com/in/janedoe

Experience
Software Engineer, Acme Corp, 2022-present
Reduced deploy time by 40% by migrating CI to GitHub Actions.
Led a team of 3 engineers on a payments migration project.

Data Analyst, Beta Inc, 2020-2022
Built dashboards using Tableau and SQL for 12 stakeholders.

Projects
Personal Finance Tracker (2023)
Built with Python and Flask, used by 200+ beta testers.

Skills
Python, SQL, Tableau, GitHub Actions, Flask
"""

GOOD_PARSED = {
    "name": "Jane Doe",
    "email": "jane.doe@example.com",
    "phone": "555-123-4567",
    "location": "",
    "linkedin": "linkedin.com/in/janedoe",
    "github": "",
    "portfolio": "",
    "skills": [
        {"name": "Python", "tags": ["python"]},
        {"name": "SQL", "tags": ["data", "sql"]},
        {"name": "Tableau", "tags": ["data", "visualization"]},
        {"name": "GitHub Actions", "tags": ["devops", "ci-cd"]},
        {"name": "Flask", "tags": ["python", "backend"]},
    ],
    "experience": [
        {
            "company": "Acme Corp", "title": "Software Engineer", "start": "2022", "end": "present",
            "bullets": [
                {"text": "Reduced deploy time by 40% by migrating CI to GitHub Actions.", "tags": ["ci-cd"], "metrics": True},
                {"text": "Led a team of 3 engineers on a payments migration project.", "tags": ["leadership"], "metrics": True},
            ],
        },
        {
            "company": "Beta Inc", "title": "Data Analyst", "start": "2020", "end": "2022",
            "bullets": [
                {"text": "Built dashboards using Tableau and SQL for 12 stakeholders.", "tags": ["data"], "metrics": True},
            ],
        },
    ],
    "projects": [
        {
            "name": "Personal Finance Tracker", "status": "complete", "date": "2023", "tech": ["Python", "Flask"],
            "bullets": [
                {"text": "Built with Python and Flask, used by 200+ beta testers.", "tags": ["python"], "metrics": True},
            ],
        },
    ],
    "education": [],
    "certifications": [],
}


def _mock_response(parsed_dict):
    resp = MagicMock()
    resp.parsed_output = parse_resume.ParsedResumeDraft(**parsed_dict)
    return resp


def _parse(parsed_dict):
    with patch("parse_resume.anthropic.Anthropic") as MockClient:
        MockClient.return_value.messages.parse.return_value = _mock_response(parsed_dict)
        return parse_resume.parse_resume_draft(RAW_TEXT)


def test_ids_assigned_matching_real_convention():
    result = _parse(GOOD_PARSED)
    draft = result["draft"]
    assert [e["id"] for e in draft["experience"]] == ["exp_001", "exp_002"]
    assert [b["id"] for e in draft["experience"] for b in e["bullets"]] == ["b_001", "b_002", "b_003"]
    assert [p["id"] for p in draft["projects"]] == ["proj_001"]
    assert [b["id"] for p in draft["projects"] for b in p["bullets"]] == ["p_001"]


def test_links_reshaped_and_summary_variants_stubbed():
    draft = _parse(GOOD_PARSED)["draft"]
    assert draft["basics"]["name"] == "Jane Doe"
    assert draft["basics"]["links"]["linkedin"] == "linkedin.com/in/janedoe"
    assert draft["basics"]["links"]["github"] == ""
    assert draft["summary_variants"] == []


def test_faithful_transcription_no_false_warnings():
    result = _parse(GOOD_PARSED)
    assert result["validation_log"] == []


def test_fabricated_number_not_in_source_flagged():
    bad = dict(GOOD_PARSED)
    bad["experience"] = [{
        "company": "Acme Corp", "title": "Software Engineer", "start": "2022", "end": "present",
        "bullets": [{"text": "Reduced deploy time by 99% by migrating CI to GitHub Actions.", "tags": [], "metrics": True}],
    }]
    result = _parse(bad)
    assert len(result["validation_log"]) == 1
    assert "99" in result["validation_log"][0]


def test_real_number_elsewhere_in_source_not_flagged():
    """The check is global, not per-bullet -- a number reworded into a
    different bullet than where it originally appeared should still not
    be treated as fabricated, since it IS genuinely present in the raw
    source text somewhere."""
    ok = dict(GOOD_PARSED)
    ok["experience"] = [{
        "company": "Acme Corp", "title": "Software Engineer", "start": "2022", "end": "present",
        "bullets": [{"text": "Cut deployment time 40% via GitHub Actions CI migration.", "tags": [], "metrics": True}],
    }]
    result = _parse(ok)
    assert result["validation_log"] == []
