"""Tests for agents/find_contact.py: the verified-status mapping (hard
rule 3), the department/HR relevance boost, and the named-in-JD targeted
Email Finder lookup + dedup. See ARCHITECTURE.md Stage 5."""

from unittest.mock import MagicMock, patch

import find_contact

DOMAIN_SEARCH_DATA = {
    "data": {
        "emails": [
            {
                "first_name": "Alice", "last_name": "Eng", "position": "Software Engineer",
                "value": "alice@x.com", "confidence": 70, "department": "it",
                "verification": {"status": "valid"}, "seniority": "junior", "sources": [1],
            },
            {
                "first_name": "Bob", "last_name": "Recruit", "position": "Technical Recruiter",
                "value": "bob@x.com", "confidence": 60, "department": "hr",
                "verification": {"status": "accept_all"}, "seniority": "junior", "sources": [1],
            },
            {
                "first_name": "Cara", "last_name": "Sales", "position": "Account Executive",
                "value": "cara@x.com", "confidence": 95, "department": "sales",
                "verification": {"status": "valid"}, "seniority": "senior", "sources": [1, 2],
            },
            {
                "first_name": "Dan", "last_name": "NoTitle", "position": None,
                "value": "dan@x.com", "confidence": 50, "department": None,
                "verification": {"status": "unknown"}, "seniority": None, "sources": [],
            },
        ]
    }
}


def _fake_domain_search_response():
    resp = MagicMock()
    resp.status_code = 200
    resp.json.return_value = DOMAIN_SEARCH_DATA
    return resp


def test_hr_and_department_boost_to_top():
    with patch("find_contact.requests.get", return_value=_fake_domain_search_response()):
        result = find_contact.find_contacts("TestCo", role_title="Backend Software Engineer", api_key="fake")

    names = [c["name"] for c in result["contacts"]]
    assert names[0] == "Bob Recruit"  # HR boost
    assert names[1] == "Alice Eng"  # IT department match
    assert set(names) == {"Bob Recruit", "Alice Eng", "Cara Sales", "Dan NoTitle"}  # nothing hidden


def test_verified_status_mapping_hard_rule_3():
    with patch("find_contact.requests.get", return_value=_fake_domain_search_response()):
        result = find_contact.find_contacts("TestCo", api_key="fake")

    by_name = {c["name"]: c for c in result["contacts"]}
    assert by_name["Alice Eng"]["verified"] is True  # status == "valid"
    assert by_name["Bob Recruit"]["verified"] is False  # status == "accept_all"
    assert by_name["Dan NoTitle"]["verified"] is False  # status == "unknown"


def test_relevance_labels_correct():
    with patch("find_contact.requests.get", return_value=_fake_domain_search_response()):
        result = find_contact.find_contacts("TestCo", role_title="Backend Software Engineer", api_key="fake")
    by_name = {c["name"]: c for c in result["contacts"]}
    assert by_name["Bob Recruit"]["relevance_label"] == "Recruiting"
    assert by_name["Alice Eng"]["relevance_label"] == "Engineering/IT"
    assert by_name["Cara Sales"]["relevance_label"] is None  # not hidden, just unlabeled


def test_no_role_title_no_department_boost_hr_boost_still_applies():
    with patch("find_contact.requests.get", return_value=_fake_domain_search_response()):
        result = find_contact.find_contacts("TestCo", api_key="fake")
    assert result["contacts"][0]["name"] == "Bob Recruit"
    alice = next(c for c in result["contacts"] if c["name"] == "Alice Eng")
    assert alice["relevance_label"] is None


# --- Named-in-JD targeted Email Finder lookup ---

_NAMED_LOOKUP_DATA = {
    "data": {
        "emails": [
            {
                "first_name": "Alice", "last_name": "Eng", "position": "Software Engineer",
                "value": "alice@x.com", "confidence": 70, "department": "it",
                "verification": {"status": "valid"}, "seniority": "junior", "sources": [1],
            },
            {
                "first_name": "Cara", "last_name": "Sales", "position": "Account Executive",
                "value": "cara@x.com", "confidence": 95, "department": "sales",
                "verification": {"status": "valid"}, "seniority": "senior", "sources": [1, 2],
            },
        ]
    }
}


def _fake_named_lookup_get(url, params=None, timeout=None):
    resp = MagicMock()
    if url == find_contact.HUNTER_DOMAIN_SEARCH_URL:
        resp.status_code = 200
        resp.json.return_value = _NAMED_LOOKUP_DATA
    elif url == find_contact.HUNTER_EMAIL_FINDER_URL:
        resp.status_code = 200
        name = params["full_name"]
        if name == "Maria Chen":
            resp.json.return_value = {"data": {"email": None}}  # not found, no credit charged
        elif name == "Cara Sales":
            resp.json.return_value = {"data": {
                "first_name": "Cara", "last_name": "Sales", "email": "cara@x.com",
                "score": 95, "position": "Account Executive", "department": "sales",
                "verification": {"status": "valid"}, "seniority": "senior", "sources": [1, 2],
            }}
        elif name == "Bob NewPerson":
            resp.json.return_value = {"data": {
                "first_name": "Bob", "last_name": "NewPerson", "email": "bob@x.com",
                "score": 80, "position": "Engineering Manager", "department": "it",
                "verification": {"status": "accept_all"}, "seniority": "senior", "sources": [1],
            }}
    return resp


def test_named_lookup_not_found_leaves_list_unaffected():
    with patch("find_contact.requests.get", side_effect=_fake_named_lookup_get):
        result = find_contact.find_contacts("TestCo", hiring_manager_name="Maria Chen", api_key="fake")
    assert len(result["contacts"]) == 2
    assert all(c["relevance_label"] is None for c in result["contacts"])


def test_named_lookup_dedups_against_existing_entry():
    with patch("find_contact.requests.get", side_effect=_fake_named_lookup_get):
        result = find_contact.find_contacts("TestCo", hiring_manager_name="Cara Sales", api_key="fake")
    assert len(result["contacts"]) == 2, "must not duplicate -- same email already present"
    cara = next(c for c in result["contacts"] if c["email"] == "cara@x.com")
    assert cara["relevance_label"] == "Named in JD"
    assert result["contacts"][0]["email"] == "cara@x.com"  # sorted to the very top


def test_named_lookup_adds_new_person_without_shrinking_list():
    with patch("find_contact.requests.get", side_effect=_fake_named_lookup_get):
        result = find_contact.find_contacts("TestCo", hiring_manager_name="Bob NewPerson", api_key="fake")
    assert len(result["contacts"]) == 3, "must ADD, never replace the original 2"
    assert result["contacts"][0]["name"] == "Bob NewPerson"
    assert result["contacts"][0]["relevance_label"] == "Named in JD"
    assert result["contacts"][0]["verified"] is False  # accept_all, even for a named hit
    names = {c["name"] for c in result["contacts"]}
    assert names == {"Bob NewPerson", "Alice Eng", "Cara Sales"}


def test_no_hiring_manager_name_unaffected():
    with patch("find_contact.requests.get", side_effect=_fake_named_lookup_get):
        result = find_contact.find_contacts("TestCo", api_key="fake")
    assert len(result["contacts"]) == 2
