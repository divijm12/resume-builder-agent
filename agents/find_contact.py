#!/usr/bin/env python3
"""Stage 5 -- Contact discovery agent.

Pure function: company name in, a ranked list of candidate hiring contacts
out. No file writes, no DB writes -- orchestration/persistence happens one
layer up (the review backend writes a chosen contact onto an application
row only once a human picks one, see review/backend/main.py).

Hunter.io only, not Apollo.io, despite CLAUDE.md's original plan naming
both: verified directly against both providers' pricing pages before
building anything -- Apollo's free plan has no API access at all (gated
behind a "Custom"/enterprise plan), while Hunter's free plan does (50
credits/month, no expiration). CLAUDE.md hard rule 3 still stands
regardless of provider: no LinkedIn scraping, ever.

Uses Hunter's Domain Search endpoint (https://api.hunter.io/v2/domain-search),
which accepts a plain company name directly (`company=` param) -- no
separate domain-lookup step needed. Each person in the response already
carries Hunter's own verification status and a confidence score, so one
call is enough; this does not make a second call to Hunter's separate
Email Verifier endpoint for the initial candidate list.

Hard rule 3's "flag unverified contacts clearly, don't silently treat them
as equal to verified ones" is enforced here, not left to a UI convention:
`verified` is True only when Hunter's own `verification.status == "valid"`.
`accept_all` (the domain accepts mail to any address, so a hit there
doesn't actually confirm this specific person's email) and `unknown` both
map to False -- there is no code path that can produce `verified: True`
for anything Hunter itself hasn't confirmed.

No fallback to scraping a company's team/about page when Hunter finds
nothing (CLAUDE.md's original plan named this as an option) -- deliberately
out of scope for v1, since every company site is structured differently
and a generic scraper would be fragile and often silently wrong. When
Hunter finds nothing, that's reported plainly, not papered over.

Relevance boost (added 2026-08-31): Hunter's response already tags each
person with a `department` from a fixed, documented vocabulary (`hr`,
`it`, `product`, `sales`, ... -- see DEPARTMENT_DISPLAY_NAMES for the
full list) -- this is real structured data, not a guess. `role_title`
(optional) is matched against a small, explicit keyword table onto that
same fixed vocabulary to guess which department the hiring team likely
sits in. Contacts in `hr` (recruiters) or the inferred target department
get boosted to the top of the list and labeled -- nothing is filtered out
or hidden, every candidate Hunter returned is still present; this only
changes ranking and adds a label, per explicit user preference over a
hard filter that could make the list look emptier than it really is when
a company's Hunter data doesn't happen to cover a matching department.

Named-in-JD targeted lookup (added 2026-08-31): when the JD text itself
names a real hiring manager (see agents/ingest_jd.py's `hiring_manager_name`),
that name is looked up specifically via Hunter's Email Finder endpoint
(`https://api.hunter.io/v2/email-finder`, `company` + `full_name`) --
Hunter's own docs confirm no credit is charged when it finds nothing, so
this is safe to always attempt when a name is available. If found, it's
merged into the SAME list the Domain Search already returns (deduped by
email if that person also showed up there) and boosted above every other
signal, labeled "Named in JD". This never replaces or shrinks the regular
list -- every candidate Domain Search would have returned on its own is
still present either way; the targeted lookup can only add or re-label,
never remove.
"""

import argparse
import json
import os
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"
HUNTER_EMAIL_FINDER_URL = "https://api.hunter.io/v2/email-finder"

# Higher than any combination of the department/HR boosts below (max 3) --
# a name stated directly in the JD is a stronger signal than an inferred
# department match, so it always sorts to the very top when both apply.
NAMED_IN_JD_BOOST = 10

# Hunter's own fixed department vocabulary (documented in their API reference),
# with a display label for each -- used only for the two departments that
# actually get boosted (hr, and whichever one a role title maps to), but kept
# complete here so any department can be labeled if useful later.
DEPARTMENT_DISPLAY_NAMES = {
    "executive": "Executive",
    "it": "Engineering/IT",
    "finance": "Finance",
    "management": "Management",
    "sales": "Sales",
    "legal": "Legal",
    "support": "Support",
    "hr": "HR/Recruiting",
    "marketing": "Marketing",
    "communication": "Communications",
    "education": "Education",
    "design": "Design",
    "health": "Health",
    "operations": "Operations",
    "product": "Product",
    "research": "Research",
    "consulting": "Consulting",
    "administrative": "Administrative",
    "procurement": "Procurement",
}

# A small, explicit keyword -> department mapping, deliberately bounded to
# Hunter's own 19 known department values rather than an open-ended guess.
# Order matters only in that more specific keywords are listed before any
# broader ones that could otherwise shadow them.
_ROLE_KEYWORDS_TO_DEPARTMENT = [
    (("engineer", "developer", "programmer", "software", "backend", "frontend",
      "full stack", "fullstack", "devops", "sre", "site reliability", "qa",
      "quality assurance", "data scientist", "machine learning", "ml engineer",
      "security engineer", "infrastructure", "platform engineer"), "it"),
    (("product manager", "product owner", "product analyst"), "product"),
    (("sales", "account executive", "business development", "bdr", "sdr"), "sales"),
    (("marketing", "growth marketer", "seo", "content strategist"), "marketing"),
    (("finance", "accountant", "accounting", "financial analyst", "controller"), "finance"),
    (("legal", "counsel", "attorney", "paralegal"), "legal"),
    (("recruiter", "recruiting", "talent acquisition", "human resources", "hr ",
      "people operations", "people ops"), "hr"),
    (("operations manager", "logistics"), "operations"),
    (("research scientist", "researcher", "research engineer"), "research"),
    (("designer", "ux", "ui designer", "graphic design"), "design"),
    (("customer success", "customer support", "support engineer", "help desk"), "support"),
    (("consultant", "consulting"), "consulting"),
    (("communications", "public relations",), "communication"),
    (("nurse", "physician", "clinical", "healthcare", "medical"), "health"),
    (("teacher", "instructor", "professor", "curriculum"), "education"),
    (("administrative assistant", "office manager", "executive assistant"), "administrative"),
    (("procurement", "purchasing", "sourcing manager"), "procurement"),
]


def _infer_target_department(role_title: Optional[str]) -> Optional[str]:
    """Best-guess Hunter department for a job role title, via the small
    explicit table above -- a bounded mapping onto 19 known values, not an
    open-ended guess. Returns None if nothing matches, which is a normal,
    honest outcome: no boost applied for team-relevance, nothing hidden."""
    if not role_title:
        return None
    title_lower = role_title.lower()
    for keywords, department in _ROLE_KEYWORDS_TO_DEPARTMENT:
        if any(kw in title_lower for kw in keywords):
            return department
    return None


def _find_named_contact(company: str, full_name: str, key: str) -> Optional[dict]:
    """Targeted lookup for one specific named person via Hunter's Email
    Finder. Returns a contact dict shaped like find_contacts()'s regular
    entries (minus _relevance_boost, set by the caller), or None if Hunter
    found nothing or the request failed -- both are silent, expected
    outcomes here, never raised, since a miss on this targeted lookup
    should never break the regular candidate list."""
    try:
        response = requests.get(
            HUNTER_EMAIL_FINDER_URL,
            params={"company": company, "full_name": full_name, "api_key": key},
            timeout=15,
        )
    except requests.RequestException:
        return None

    if response.status_code != 200:
        return None

    data = response.json().get("data") or {}
    email = data.get("email")
    if not email:
        return None

    verification = data.get("verification") or {}
    status = verification.get("status")
    name = " ".join(filter(None, [data.get("first_name"), data.get("last_name")])).strip()

    return {
        "name": name or full_name,
        "title": data.get("position"),
        "email": email,
        "confidence": data.get("score"),
        "department": data.get("department"),
        "relevance_label": "Named in JD",
        "verified": status == "valid",
        "verification_status": status,
        "decision_maker": data.get("seniority") in ("senior", "executive"),
        "sources_count": len(data.get("sources") or []),
        "source": "hunter.io",
    }


def find_contacts(
    company: str,
    role_title: Optional[str] = None,
    hiring_manager_name: Optional[str] = None,
    api_key: Optional[str] = None,
) -> dict:
    """Look up candidate hiring contacts at `company` via Hunter.io.

    `role_title`, if given, only affects ranking/labeling (see module
    docstring) -- it is never sent to Hunter as a filter, so the full,
    unfiltered candidate list Hunter returns is always what's available.

    `hiring_manager_name`, if given (from a JD that named one explicitly --
    see agents/ingest_jd.py), triggers one additional targeted lookup via
    Hunter's Email Finder for that specific person. A hit is merged into
    the same list and boosted to the top labeled "Named in JD"; a miss
    costs nothing (Hunter doesn't charge a credit for an unfound Email
    Finder lookup) and changes nothing about the regular list.

    Returns {"contacts": [...], "message": str | None, "error": str | None}.
    Never raises for an expected failure mode (no results, bad key, rate
    limit, network error) -- always returns a dict describing what happened,
    so a caller can show something sensible instead of a stack trace.
    """
    key = api_key or os.getenv("HUNTER_API_KEY")
    if not key:
        return {
            "contacts": [],
            "message": None,
            "error": "No HUNTER_API_KEY configured -- add one to .env to use contact discovery.",
        }

    try:
        response = requests.get(
            HUNTER_DOMAIN_SEARCH_URL,
            params={"company": company, "api_key": key},
            timeout=15,
        )
    except requests.RequestException as e:
        return {"contacts": [], "message": None, "error": f"Network error calling Hunter.io: {e}"}

    if response.status_code != 200:
        detail = None
        try:
            detail = response.json().get("errors", [{}])[0].get("details")
        except Exception:
            pass
        return {
            "contacts": [],
            "message": None,
            "error": f"Hunter.io returned {response.status_code}" + (f": {detail}" if detail else ""),
        }

    data = response.json().get("data", {})
    emails = data.get("emails", []) or []
    target_department = _infer_target_department(role_title)

    contacts = []
    for e in emails:
        verification = e.get("verification") or {}
        status = verification.get("status")
        name = " ".join(filter(None, [e.get("first_name"), e.get("last_name")])).strip()
        department = e.get("department")

        is_recruiting = department == "hr"
        is_team_match = target_department is not None and department == target_department
        relevance_label = "Recruiting" if is_recruiting else (
            DEPARTMENT_DISPLAY_NAMES.get(department, department) if is_team_match else None
        )
        # HR ranks above a team-department match when both would apply (e.g.
        # searching an HR role itself) -- a real recruiter is the more useful
        # first contact for an application either way.
        relevance_boost = (2 if is_recruiting else 0) + (1 if is_team_match else 0)

        contacts.append(
            {
                "name": name or None,
                "title": e.get("position"),
                "email": e.get("value"),
                "confidence": e.get("confidence"),
                "department": department,
                # None for most contacts -- only set for an actual HR or
                # team-department match, never fabricated for display.
                "relevance_label": relevance_label,
                # Only Hunter's own "valid" status counts as verified -- "accept_all"
                # (the domain accepts mail to any address, so this doesn't confirm
                # this specific person) and "unknown" both stay unverified. See the
                # module docstring: this is the one hard-rule-3 guarantee, enforced
                # in code, not left to a UI label to get right.
                "verified": status == "valid",
                "verification_status": status,
                "decision_maker": e.get("seniority") in ("senior", "executive"),
                "sources_count": len(e.get("sources") or []),
                "source": "hunter.io",
                "_relevance_boost": relevance_boost,
            }
        )

    if hiring_manager_name:
        named = _find_named_contact(company, hiring_manager_name, key)
        if named:
            existing = next(
                (c for c in contacts if c.get("email") and c["email"].lower() == named["email"].lower()),
                None,
            )
            if existing:
                existing["relevance_label"] = "Named in JD"
                existing["_relevance_boost"] = NAMED_IN_JD_BOOST
            else:
                named["_relevance_boost"] = NAMED_IN_JD_BOOST
                contacts.append(named)

    # Relevant contacts (named in the JD, HR/recruiting, or the inferred team
    # department) sort to the top; confidence breaks ties within each group.
    # Nothing is dropped -- every contact Hunter's Domain Search returned is
    # still in this list either way.
    contacts.sort(key=lambda c: (c["_relevance_boost"], c["confidence"] or 0), reverse=True)
    for c in contacts:
        del c["_relevance_boost"]

    message = None if contacts else f"No contact found via Hunter.io for '{company}'."
    return {"contacts": contacts, "message": message, "error": None}


def main():
    parser = argparse.ArgumentParser(description="Find candidate hiring contacts for a company via Hunter.io.")
    parser.add_argument("--company", required=True, help="Company name to search")
    parser.add_argument("--role-title", default=None, help="Optional job title, used only to rank/label results")
    parser.add_argument(
        "--hiring-manager-name",
        default=None,
        help="Optional name (from a JD that stated one) to look up specifically via Email Finder",
    )
    args = parser.parse_args()

    result = find_contacts(args.company, role_title=args.role_title, hiring_manager_name=args.hiring_manager_name)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
