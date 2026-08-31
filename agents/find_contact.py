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
"""

import argparse
import json
import os
from typing import List, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

HUNTER_DOMAIN_SEARCH_URL = "https://api.hunter.io/v2/domain-search"


def find_contacts(company: str, api_key: Optional[str] = None) -> dict:
    """Look up candidate hiring contacts at `company` via Hunter.io.

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

    contacts = []
    for e in emails:
        verification = e.get("verification") or {}
        status = verification.get("status")
        name = " ".join(filter(None, [e.get("first_name"), e.get("last_name")])).strip()
        contacts.append(
            {
                "name": name or None,
                "title": e.get("position"),
                "email": e.get("value"),
                "confidence": e.get("confidence"),
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
            }
        )

    contacts.sort(key=lambda c: c["confidence"] or 0, reverse=True)

    message = None if contacts else f"No contact found via Hunter.io for '{company}'."
    return {"contacts": contacts, "message": message, "error": None}


def main():
    parser = argparse.ArgumentParser(description="Find candidate hiring contacts for a company via Hunter.io.")
    parser.add_argument("--company", required=True, help="Company name to search")
    args = parser.parse_args()

    result = find_contacts(args.company)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
