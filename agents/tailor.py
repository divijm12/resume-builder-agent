#!/usr/bin/env python3
"""Stage 2 -- Tailoring agent.

Pure function: jd_parsed.json + score.json + master_resume.yaml in,
{tailored_resume, diff_summary, unaddressed_hard_gaps, unaddressed_red_flags,
ats_scan_notes} JSON out. No file writes, no DB writes -- orchestration/
persistence happens one layer up.

Hard rule (CLAUDE.md): may only select, reorder, and lightly reword bullets
that already exist in master_resume.yaml -- never invent a bullet, metric, or
skill. This is enforced here, not just prompted: every selected id is checked
against the master resume, every selected skill must resolve to a real
master_skill_name (a JD-matching display_as relabel of that same skill is
allowed -- e.g. "LLM agent development" shown as "Agentic AI solutions" --
but the underlying skill must be real), and reworded bullet text is rejected
(reverted to the original) if it introduces a number that wasn't in the
source bullet, drops a named technology/vendor term (from that project's
`tech` list) that was present in the original bullet, or adds a technology/
skill name from anywhere in the master resume's vocabulary that wasn't
already in that specific bullet -- unless it's a textual expansion of
something already there (e.g. "Claude API" -> "Anthropic Claude API" is
fine; "Python" appearing out of nowhere is not).
"""

import argparse
import json
import re
from pathlib import Path
from typing import List, Optional

import anthropic
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

SYSTEM_PROMPT = (
    "You tailor a resume to a specific job by selecting, reordering, and lightly "
    "rewording bullets that already exist in the candidate's master resume -- you "
    "may NEVER invent a bullet, metric, skill, or claim that isn't already there. "
    "A 'light reword' means rephrasing for emphasis or matching the JD's "
    "terminology -- it must preserve every number, percentage, and factual claim "
    "in the original bullet exactly, AND it must never delete, generalize, or "
    "genericize a domain-specific detail from the original -- the specific "
    "subject, domain, or context the work was actually about. For example, "
    "rewording 'a turfgrass disease outbreak research project' down to just 'a "
    "research project' is NOT a light reword -- it deletes the exact detail "
    "that makes the work distinctive and credible, even though no number "
    "changed. The same applies to named technologies, tools, vendors, and "
    "products: 'Sarvam AI for STT/TTS' must not become generic 'speech-to-text/"
    "text-to-speech', and 'a Supabase backend' must not become just 'a "
    "backend' -- keep the actual name. If a domain-specific detail or named "
    "technology doesn't obviously match the JD, keep it in anyway rather than "
    "cutting it; you can still add JD-matching language elsewhere in the same "
    "bullet without removing what was already there. When rewording, prefer "
    "the formula 'Accomplished [X], as measured "
    "by [Y], by doing [Z]' -- built only from the X, Y, and Z already present "
    "in that original bullet, never inventing a metric just to complete the "
    "formula, and never dropping domain-specific words to make it fit. This "
    "cuts both ways -- do not ADD a claim either. Never append a rhetorical "
    "qualifier that asserts a competency the bullet doesn't already describe: "
    "phrases like 'demonstrating X', 'showcasing Y', or 'highlighting Z' "
    "tacked onto the end of a bullet are exactly this mistake. Never name a "
    "technology, tool, or skill in the reworded text unless it was already "
    "part of what that specific bullet described -- e.g. don't add 'using "
    "Python' to a bullet that never mentioned Python, even if Python is "
    "elsewhere on the resume. Expanding something already named to its fuller "
    "form (e.g. 'Claude API' to 'Anthropic Claude API') is fine; naming a "
    "different technology that bullet never mentioned is not. If a bullet "
    "can't honestly fit that formula or be reworded to fit the JD without "
    "changing, deleting, or adding to its facts, use the original text "
    "unchanged.\n\n"
    "Select and order skills and bullets to foreground what matches this JD. "
    "Prioritize bullets/skills the score input flagged as matched or as a "
    "reword_opportunity. Then specifically check top_missing_keywords and "
    "red_flags from the score input, in that priority order: for each one, if "
    "the master resume genuinely covers it somewhere (even under different "
    "wording), make sure a selected/reworded bullet surfaces it in this JD's "
    "terminology; if the resume has no real coverage for it, do not fake "
    "coverage -- list that keyword/red flag back out in unaddressed_hard_gaps "
    "or unaddressed_red_flags instead of hiding it.\n\n"
    "Each selected skill must be anchored to a real master_skill_name from the "
    "master resume -- you cannot invent a skill from nothing. But you MAY set "
    "display_as to a JD-matching relabel of that same skill when it's "
    "genuinely the same underlying capability, just named differently -- e.g. "
    "master_skill_name 'LLM agent development' with display_as 'Agentic AI "
    "solutions' is fine when the resume's own projects (an agent-based system) "
    "back it up; that's the skill-level equivalent of a light bullet reword, "
    "not fabrication. It would NOT be fine to relabel 'SQL (PostgreSQL, "
    "MySQL)' as 'NoSQL databases' -- that's a different, unsupported "
    "capability, not a rename of the same one.\n\n"
    "Finally, self-review your own selection like an ATS filter and a hiring "
    "manager skimming 200 resumes in one sitting: which of your selected "
    "bullets would get skipped -- too generic, too vague, buried lede, no "
    "keyword signal? For each one you flag, actually change that bullet's text "
    "field so it would stop the scroll instead of blending in -- don't leave "
    "the text field unchanged and only describe the fix in ats_scan_notes. Only "
    "describe an edit in ats_scan_notes/diff_summary if you actually changed "
    "that bullet's text field to something different from the original; if you "
    "kept it verbatim, don't claim you reworded it.\n\n"
    "Don't over-correct into inaction. All of the constraints above are about "
    "*what a change must look like* if you make one -- they are not a reason "
    "to avoid making changes. A resume that comes out identical to the master "
    "resume, especially against a JD with a low match score or several "
    "top_missing_keywords/red_flags, is a sign you were too cautious, not "
    "appropriately careful -- score.json's reword_opportunities exist "
    "precisely because there ARE safe, grounded ways to better surface what's "
    "already there. Skill relabeling (display_as) and bullet/project selection "
    "and ordering are always safe -- use them assertively. Reach for bullet "
    "rewording too wherever it can honestly follow the rules above; only fall "
    "back to a bullet's original text when THAT bullet specifically can't be "
    "reworded without breaking a rule, not as a default posture for the whole "
    "resume."
)

NUMERIC_TOKEN_RE = re.compile(r"\d[\d,]*\.?\d*%?\+?x?", re.IGNORECASE)


class SelectedBullet(BaseModel):
    id: str
    text: str


class SelectedExperience(BaseModel):
    id: str
    bullets: List[SelectedBullet]


class SelectedProject(BaseModel):
    id: str
    bullets: List[SelectedBullet]


class SelectedSkill(BaseModel):
    master_skill_name: str
    display_as: Optional[str] = None


class TailoringPlan(BaseModel):
    selected_skills: List[SelectedSkill]
    experience: List[SelectedExperience]
    projects: List[SelectedProject]
    diff_summary: List[str]
    unaddressed_hard_gaps: List[str]
    unaddressed_red_flags: List[str]
    ats_scan_notes: List[str]


def _numeric_tokens(text: str) -> set:
    return set(NUMERIC_TOKEN_RE.findall(text))


def _contains_term(text: str, term: str) -> bool:
    """Whole-word/phrase, case-insensitive containment check."""
    prefix = r"\b" if term[0].isalnum() else ""
    suffix = r"\b" if term[-1].isalnum() else ""
    return re.search(prefix + re.escape(term) + suffix, text, re.IGNORECASE) is not None


def _is_expansion(term: str, original_text: str) -> bool:
    """True if `term` (new to the bullet) textually extends something already in
    the original -- e.g. 'Anthropic Claude API' extends an original mention of
    'Claude API'. False means it's a genuinely new, unsupported addition."""
    words = re.findall(r"\w{4,}", term.lower())
    original_lower = original_text.lower()
    return any(w in original_lower for w in words)


def _known_terms(master_resume: dict) -> set:
    """All skill names and project tech names -- the vocabulary a reworded bullet
    is allowed to newly mention, and only when it's an expansion of something
    already in that bullet (see _is_expansion)."""
    terms = {s["name"] for s in master_resume.get("skills", [])}
    for proj in master_resume.get("projects", []):
        terms.update(proj.get("tech", []))
    return terms


def _bullet_lookup(master_resume: dict) -> dict:
    """bullet id -> original bullet text, across experience and projects."""
    lookup = {}
    for exp in master_resume.get("experience", []):
        for b in exp.get("bullets", []):
            lookup[b["id"]] = b["text"]
    for proj in master_resume.get("projects", []):
        for b in proj.get("bullets", []):
            lookup[b["id"]] = b["text"]
    return lookup


def validate_and_build(plan: dict, master_resume: dict) -> dict:
    """Enforce the no-fabrication hard rule and assemble the final tailored resume.

    An unknown bullet/skill/experience id is dropped; a reworded bullet that
    introduces a number not present in the original is reverted to the
    original text. Every rejection is recorded in diff_summary so it's visible
    in review, not silently swallowed.
    """
    bullet_text = _bullet_lookup(master_resume)
    valid_skills = {s["name"] for s in master_resume.get("skills", [])}
    known_terms = _known_terms(master_resume)
    exp_by_id = {e["id"]: e for e in master_resume.get("experience", [])}
    proj_by_id = {p["id"]: p for p in master_resume.get("projects", [])}
    master_exp_order = [e["id"] for e in master_resume.get("experience", [])]

    warnings = []
    actually_reworded_ids = []

    def resolve_bullets(selected_bullets, valid_ids_for_parent, protected_terms=frozenset()):
        resolved = []
        for sb in selected_bullets:
            if sb["id"] not in bullet_text or sb["id"] not in valid_ids_for_parent:
                warnings.append(f"Dropped unknown bullet id '{sb['id']}' -- not in master resume.")
                continue
            original = bullet_text[sb["id"]]
            new_text = sb["text"]
            dropped_terms = [
                t for t in protected_terms
                if t.lower() in original.lower() and t.lower() not in new_text.lower()
            ]
            added_terms = [
                t for t in known_terms
                if _contains_term(new_text, t) and not _contains_term(original, t)
                and not _is_expansion(t, original)
            ]
            if _numeric_tokens(new_text) - _numeric_tokens(original):
                warnings.append(
                    f"Reworded text for bullet '{sb['id']}' introduced a number not in "
                    f"the original -- reverted to original text."
                )
                resolved.append({"id": sb["id"], "text": original})
            elif dropped_terms:
                warnings.append(
                    f"Reworded text for bullet '{sb['id']}' dropped named "
                    f"technology/vendor term(s) {dropped_terms} present in the original -- "
                    f"reverted to original text."
                )
                resolved.append({"id": sb["id"], "text": original})
            elif added_terms:
                warnings.append(
                    f"Reworded text for bullet '{sb['id']}' added named "
                    f"technology/skill term(s) {added_terms} not present (or expanded) in "
                    f"the original -- reverted to original text."
                )
                resolved.append({"id": sb["id"], "text": original})
            else:
                if new_text != original:
                    actually_reworded_ids.append(sb["id"])
                resolved.append({"id": sb["id"], "text": new_text})
        return resolved

    tailored_experience_by_id = {}
    for se in plan["experience"]:
        exp = exp_by_id.get(se["id"])
        if exp is None:
            warnings.append(f"Dropped unknown experience id '{se['id']}'.")
            continue
        valid_ids = {b["id"] for b in exp["bullets"]}
        tailored_experience_by_id[se["id"]] = {
            **{k: v for k, v in exp.items() if k != "bullets"},
            "bullets": resolve_bullets(se["bullets"], valid_ids),
        }
    # Keep original chronological order regardless of what order the model returned.
    tailored_experience = [tailored_experience_by_id[eid] for eid in master_exp_order if eid in tailored_experience_by_id]

    tailored_projects = []
    for sp in plan["projects"]:
        proj = proj_by_id.get(sp["id"])
        if proj is None:
            warnings.append(f"Dropped unknown project id '{sp['id']}'.")
            continue
        valid_ids = {b["id"] for b in proj["bullets"]}
        protected_terms = set(proj.get("tech", []))
        tailored_projects.append({
            **{k: v for k, v in proj.items() if k != "bullets"},
            "bullets": resolve_bullets(sp["bullets"], valid_ids, protected_terms=protected_terms),
        })
    # Projects keep the model's relevance-ranked order (unlike experience, not chronological).

    selected_skills = []
    relabeled_skills = []
    for s in plan["selected_skills"]:
        if s["master_skill_name"] not in valid_skills:
            warnings.append(
                f"Dropped unknown skill '{s['master_skill_name']}' -- not in master resume "
                f"(display_as relabeling only works when master_skill_name is a real skill)."
            )
            continue
        label = s.get("display_as") or s["master_skill_name"]
        selected_skills.append(label)
        if label != s["master_skill_name"]:
            relabeled_skills.append(f"{s['master_skill_name']} -> {label}")

    # Ground truth, computed from the actual output -- not the model's self-report.
    # ats_scan_notes/diff_summary above are the model's own rationale and can describe
    # an edit it didn't actually make; this line is always accurate.
    if actually_reworded_ids:
        warnings.append(f"Bullets with text actually changed from the master resume: {actually_reworded_ids}")
    else:
        warnings.append("No bullet text was changed from the master resume -- all selected bullets kept verbatim.")
    if relabeled_skills:
        warnings.append(f"Skills relabeled from their master resume name: {relabeled_skills}")

    tailored_resume = {
        "basics": master_resume["basics"],
        "skills": selected_skills,
        "experience": tailored_experience,
        "projects": tailored_projects,
        "education": master_resume.get("education", []),
        "certifications": master_resume.get("certifications", []),
    }

    return {
        "tailored_resume": tailored_resume,
        "diff_summary": plan["diff_summary"] + warnings,
        "unaddressed_hard_gaps": plan["unaddressed_hard_gaps"],
        "unaddressed_red_flags": plan["unaddressed_red_flags"],
        "ats_scan_notes": plan["ats_scan_notes"],
    }


def tailor_resume(jd_parsed: dict, score: dict, master_resume: dict, model: str = DEFAULT_MODEL) -> dict:
    """Produce a tailored resume from the JD, score output, and master resume."""
    client = anthropic.Anthropic()
    user_content = (
        f"Job description (parsed):\n{json.dumps(jd_parsed, indent=2)}\n\n"
        f"Score/gap analysis:\n{json.dumps(score, indent=2)}\n\n"
        f"Candidate's master resume (only reference ids/text from here):\n"
        f"{yaml.dump(master_resume, sort_keys=False)}"
    )
    response = client.messages.parse(
        model=model,
        max_tokens=8000,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_content}],
        output_format=TailoringPlan,
    )
    plan = response.parsed_output.model_dump()
    return validate_and_build(plan, master_resume)


def main():
    parser = argparse.ArgumentParser(description="Tailor the master resume to a scored JD.")
    parser.add_argument("--jd-json", required=True, help="Path to jd_parsed.json")
    parser.add_argument("--score-json", required=True, help="Path to score.json (output of score.py)")
    parser.add_argument("--resume", type=Path, default=Path("data/master_resume.yaml"), help="Path to master_resume.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    args = parser.parse_args()

    jd_parsed = json.loads(Path(args.jd_json).read_text())
    score = json.loads(Path(args.score_json).read_text())
    master_resume = yaml.safe_load(args.resume.read_text())

    result = tailor_resume(jd_parsed, score, master_resume, model=args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
