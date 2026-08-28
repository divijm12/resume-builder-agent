#!/usr/bin/env python3
"""Stage 2 -- Tailoring agent.

Pure function: jd_parsed.json + score.json + master_resume.yaml in,
{tailored_resume, diff_summary, validation_log, unaddressed_hard_gaps,
unaddressed_red_flags, unaddressed_reword_opportunities, ats_scan_notes,
score_before, score_after, overall_score_delta} JSON out. No file writes, no
DB writes -- orchestration/persistence happens one layer up.

diff_summary is the model's own narrative of its selection/ordering/skill
choices (plain language, no internal ids) plus code-generated lines noting
which sections had bullets actually reworded (only bullets that survived
every guardrail below -- the model is explicitly barred from narrating
specific bullet-wording changes itself, since it can't know pre-validation
whether a given reword will be reverted) -- safe to show a user directly.
validation_log is the code-computed ground
truth and guardrail actions (references master_resume.yaml bullet ids like
"b_004", raw rejection messages) -- an audit trail, not written for
end-user display; a UI should hide/collapse it rather than show it inline.

Two modes (mode="aggressive"|"honest", see MODES), same no-fabrication
guarantee underneath both. "aggressive" (default) selects/reorders/relabels
AND rewords bullets -- the original, heavily tested behavior. "honest" only
selects/reorders/relabels; bullet text is locked to the master resume's
original wording in code (not just prompted) so that guarantee can't drift.
Naming follows Tsenta's (a real product in this space) client-side copy:
"Honest: reorders and highlights"; "Aggressive: rewrites and tailors the
content" -- neither mode ever fabricates, per that product's own AI
disclosure ("applications use only true facts from the resume you
uploaded"); "aggressive" there means reword intensity, not license to invent.

Rescores the tailored resume with score.py's own scoring function (same
recruiter-persona prompt) so the impact of tailoring is visible, not assumed
-- this means every run makes two model calls, not one.

Hard rule (CLAUDE.md): may only select, reorder, and lightly reword bullets
that already exist in master_resume.yaml -- never invent a bullet, metric, or
skill. This is enforced here, not just prompted: every selected id is checked
against the master resume, every selected skill must resolve to a real
master_skill_name (a JD-matching display_as relabel of that same skill is
allowed -- e.g. "LLM agent development" shown as "Agentic AI solutions" --
but the underlying skill must be real), and reworded bullet text is rejected
(reverted to the original) if it introduces a number that wasn't in the
source bullet, drops a named technology/skill term (from the master
resume's full vocabulary -- all skill names plus every project's `tech`
list, not just that bullet's own project) that was present in the original
bullet, or adds a technology/skill name from that same vocabulary that
wasn't already in that specific bullet -- unless it's a textual expansion of
something already there (e.g. "Claude API" -> "Anthropic Claude API" is
fine; "Python" appearing out of nowhere is not). Also rejected: stapling a
"-- demonstrating X" / "-- applying Y" clause onto the end of the original
text instead of actually rewording it -- prompt-only enforcement of this
didn't hold reliably across runs, so it's now caught structurally (new text
== original text + a trailing --/em-dash clause).
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

from score import score_jd

load_dotenv()

DEFAULT_MODEL = "claude-haiku-4-5"

# Two modes, same no-fabrication guarantee underneath both -- this mirrors
# how Tsenta (a real product in this space) names theirs: "Honest" only
# reorders/highlights/relabels, never touches bullet text; "Aggressive"
# additionally rewords bullets, still bound by every guardrail below. Honest
# mode's "never touches bullet text" half of that guarantee is enforced in
# code (see resolve_bullets), not just prompted -- consistent with this
# project's whole approach of not trusting prompt-only behavior for anything
# structurally checkable.
MODES = ("honest", "aggressive")

_SHARED_CORE_PROMPT = (
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
    "Every single item in the score input's reword_opportunities list MUST be "
    "addressed in this pass -- via a skill relabel, a reworded bullet, or "
    "reordering that surfaces it. These are called reword_opportunities and not "
    "hard_gaps specifically because score.py already determined the master "
    "resume genuinely covers each one -- so there is always a safe, grounded "
    "way to surface it, and skipping one without a documented reason is a "
    "miss, not caution. Go through the list one item at a time; for each, make "
    "the change, then note it in diff_summary. If -- and only if -- you "
    "inspect one closely and it genuinely cannot be surfaced without breaking "
    "a rule above, put it in unaddressed_reword_opportunities with the "
    "specific reason; this field should normally end up empty. Then "
    "separately check top_missing_keywords and red_flags from the score "
    "input, in that priority order: for each one, if the master resume "
    "genuinely covers it somewhere (even under different wording), make sure "
    "a selected/reworded bullet surfaces it in this JD's terminology; if the "
    "resume has no real coverage for it, do not fake coverage -- list that "
    "keyword/red flag back out in unaddressed_hard_gaps or "
    "unaddressed_red_flags instead of hiding it.\n\n"
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
    "When deciding which skills to select, distinguish two categories. "
    "General-purpose/foundational skills -- widely-applicable languages, "
    "tools, and practices not tied to one specific domain (e.g. Python, Git, "
    "SQL, unit testing, cross-functional collaboration) -- should almost "
    "always stay selected regardless of what the JD asks for. They never "
    "read as a distraction, and dropping one only makes the resume less "
    "differentiated, not more focused -- do not remove a general-purpose "
    "skill just because the JD doesn't happen to mention it. Narrow/"
    "specialist skills tied to one specific domain (e.g. a particular AI "
    "framework, a specific vendor API, niche ML tooling) MAY be trimmed down "
    "when the JD has no footprint in that domain at all -- a long list of "
    "niche framework names reads as keyword-stuffing to a recruiter skimming "
    "in seconds. But never trim a domain down to zero if the master resume "
    "shows genuine depth there (multiple real skills and/or bullets in that "
    "area) -- keep a small representative subset (roughly 2-3 of the "
    "strongest, most recognizable ones) instead of removing the domain "
    "entirely. The goal is proportion, not erasure: a recruiter should come "
    "away thinking 'this candidate also has real depth in X, secondary to "
    "this role' -- never a wall of niche names, but never zero trace of it "
    "either.\n\n"
    "diff_summary is shown directly to the candidate, so it has two hard "
    "rules. First: never write a bullet's internal id (like 'b_003' or "
    "'p_008') anywhere in diff_summary, ats_scan_notes, or the "
    "unaddressed_* fields -- refer to bullets by their company/project name "
    "instead (e.g. 'the GeoVerify liveness-detection bullet'), never by id. "
    "Second, and more important: do NOT describe a specific bullet-wording "
    "change in diff_summary at all (no 'reworded X to Y' lines) -- you "
    "cannot know from inside this response whether a given reword will "
    "survive the accuracy check that runs after you respond, so any claim "
    "you make about *what* changed in a bullet's wording may end up "
    "describing an edit that gets reverted, which is worse than not "
    "claiming it. The system separately and accurately documents which "
    "bullets' wording actually changed once that check has run -- you do "
    "not need to and should not do this yourself. In diff_summary, only "
    "describe: which skills you selected or relabeled and why, which "
    "experience/projects you chose to include and how you ordered them, "
    "and how that selection surfaces this JD's reword_opportunities/"
    "missing keywords -- never the specific before/after text of a reworded "
    "bullet."
)

_AGGRESSIVE_MODE_PROMPT = (
    "\n\nYou are running in AGGRESSIVE mode: reword bullet text, not just "
    "select/reorder/relabel. Self-review your own selection like an ATS "
    "filter and a hiring manager skimming 200 resumes in one sitting: which "
    "of your selected bullets would get skipped -- too generic, too vague, "
    "buried lede, no keyword signal? For each one you flag, actually change "
    "that bullet's text field so it would stop the scroll instead of "
    "blending in -- don't leave the text field unchanged and only describe "
    "the fix in ats_scan_notes. Only describe an edit in "
    "ats_scan_notes/diff_summary if you actually changed that bullet's text "
    "field to something different from the original; if you kept it "
    "verbatim, don't claim you reworded it.\n\n"
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

_HONEST_MODE_PROMPT = (
    "\n\nYou are running in HONEST mode: you may ONLY select which bullets "
    "and projects to include and their order, and relabel skills "
    "(display_as) to JD-matching terminology when it's genuinely the same "
    "underlying capability. You do NOT reword bullet text in this mode -- "
    "whatever you put in a bullet's 'text' field is discarded and the "
    "original master resume wording is used instead, so don't spend effort "
    "trying to reword bullets; just repeat each selected bullet's original "
    "text back in the 'text' field unchanged. Address reword_opportunities "
    "and top_missing_keywords/red_flags only through selection, ordering, "
    "and skill relabeling -- if one genuinely can't be surfaced that way, "
    "put it in unaddressed_reword_opportunities/unaddressed_hard_gaps/"
    "unaddressed_red_flags rather than pretending a bullet reword will fix "
    "it. Still self-review as an ATS/hiring-manager would, but express that "
    "through what you select and how you order it, not through rewriting."
)


def _system_prompt(mode: str) -> str:
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    addendum = _AGGRESSIVE_MODE_PROMPT if mode == "aggressive" else _HONEST_MODE_PROMPT
    return _SHARED_CORE_PROMPT + addendum


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
    unaddressed_reword_opportunities: List[str]
    ats_scan_notes: List[str]


def _numeric_tokens(text: str) -> set:
    return set(NUMERIC_TOKEN_RE.findall(text))


def _date_rank(date_str) -> float:
    """Higher = more recent. 'present'/'Present' ranks above any fixed date
    (still ongoing now); 'YYYY' or 'YYYY-MM' parses to a comparable numeric
    value; empty/unparseable sorts last. Used to sort every dated section
    (experience, projects, education, certifications) deterministically in
    code rather than trusting the model's selection order for chronology."""
    if not date_str:
        return float("-inf")
    s = str(date_str).strip().lower()
    if s == "present":
        return float("inf")
    m = re.match(r"^(\d{4})(?:-(\d{1,2}))?$", s)
    if m:
        year = int(m.group(1))
        month = int(m.group(2)) if m.group(2) else 1
        return year * 12 + month
    return float("-inf")


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


def _has_appended_clause(original: str, new_text: str) -> bool:
    """True if new_text is exactly the original with a trailing --/em-dash clause
    stapled onto the end -- the structural signature of the 'demonstrating X'
    antipattern (asserting an unearned capability instead of actually rewording
    the sentence). Prompt-only enforcement of this didn't hold reliably across
    runs, but the shape is mechanical enough to catch deterministically."""
    orig_core = original.rstrip().rstrip(".").rstrip()
    if not new_text.startswith(orig_core):
        return False
    remainder = new_text[len(orig_core):].lstrip()
    return remainder.startswith("--") or remainder.startswith("—") or remainder.startswith("-")


def _known_terms(master_resume: dict) -> set:
    """All skill names and every project's tech names, globally (not scoped to a
    single project or bullet) -- protects a term from being dropped out of any
    bullet that already mentions it, and gates what a reworded bullet is allowed
    to newly mention (only as an expansion of something already there -- see
    _is_expansion)."""
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


def validate_and_build(plan: dict, master_resume: dict, mode: str = "aggressive") -> dict:
    """Enforce the no-fabrication hard rule and assemble the final tailored resume.

    An unknown bullet/skill/experience id is dropped; a reworded bullet that
    introduces a number not present in the original is reverted to the
    original text. Every rejection is recorded in validation_log so it's
    visible in review, not silently swallowed.

    In "honest" mode, bullet text is locked to the master resume's original
    wording in code -- not just prompted -- so that guarantee holds
    regardless of what the model returns in a bullet's 'text' field.
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

    bullet_text = _bullet_lookup(master_resume)
    valid_skills = {s["name"] for s in master_resume.get("skills", [])}
    known_terms = _known_terms(master_resume)
    exp_by_id = {e["id"]: e for e in master_resume.get("experience", [])}
    proj_by_id = {p["id"]: p for p in master_resume.get("projects", [])}

    warnings = []
    actually_reworded_ids = []
    # parent display name (e.g. "GeoVerify", "Forestallers") -> count of bullets
    # actually reworded there, computed only from bullets that survived every
    # guardrail below -- this is what diff_summary's reword narration is built
    # from, instead of the model's own pre-validation claim (see resolve_bullets;
    # the model's claim can describe an edit that gets reverted two lines later).
    reworded_by_parent: dict = {}
    # parent display names with at least one reword ATTEMPT that got reverted --
    # used below to catch the model narrating that attempt in diff_summary even
    # when it obeys the "no ids" rule (e.g. "reworded the GeoVerify bullet to
    # emphasize X" -- true it tried, false that it survived). Prompt-only
    # enforcement of "don't narrate this" didn't hold in production even after
    # the id-specific fix, the same lesson as _has_appended_clause: catch the
    # shape in code, don't just ask nicely.
    reverted_parents: set = set()

    def resolve_bullets(selected_bullets, valid_ids_for_parent, parent_label):
        resolved = []
        for sb in selected_bullets:
            if sb["id"] not in bullet_text or sb["id"] not in valid_ids_for_parent:
                warnings.append(f"Dropped unknown bullet id '{sb['id']}' -- not in master resume.")
                continue
            original = bullet_text[sb["id"]]
            new_text = original if mode == "honest" else sb["text"]
            # Same global vocabulary (all skill names + all projects' tech) protects
            # against both directions, for every bullet -- experience included, not
            # just project bullets. A term only "counts" as dropped if it's an exact
            # word/phrase match in the original, so unrelated prose can't false-positive.
            dropped_terms = [
                t for t in known_terms
                if _contains_term(original, t) and not _contains_term(new_text, t)
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
                reverted_parents.add(parent_label)
                resolved.append({"id": sb["id"], "text": original})
            elif _has_appended_clause(original, new_text):
                warnings.append(
                    f"Reworded text for bullet '{sb['id']}' stapled a 'demonstrating X' "
                    f"style clause onto the end instead of actually rewording -- reverted "
                    f"to original text."
                )
                reverted_parents.add(parent_label)
                resolved.append({"id": sb["id"], "text": original})
            elif dropped_terms:
                warnings.append(
                    f"Reworded text for bullet '{sb['id']}' dropped named "
                    f"technology/vendor term(s) {dropped_terms} present in the original -- "
                    f"reverted to original text."
                )
                reverted_parents.add(parent_label)
                resolved.append({"id": sb["id"], "text": original})
            elif added_terms:
                warnings.append(
                    f"Reworded text for bullet '{sb['id']}' added named "
                    f"technology/skill term(s) {added_terms} not present (or expanded) in "
                    f"the original -- reverted to original text."
                )
                reverted_parents.add(parent_label)
                resolved.append({"id": sb["id"], "text": original})
            else:
                if new_text != original:
                    actually_reworded_ids.append(sb["id"])
                    reworded_by_parent[parent_label] = reworded_by_parent.get(parent_label, 0) + 1
                resolved.append({"id": sb["id"], "text": new_text})
        return resolved

    tailored_experience = []
    for se in plan["experience"]:
        exp = exp_by_id.get(se["id"])
        if exp is None:
            warnings.append(f"Dropped unknown experience id '{se['id']}'.")
            continue
        valid_ids = {b["id"] for b in exp["bullets"]}
        tailored_experience.append({
            **{k: v for k, v in exp.items() if k != "bullets"},
            "bullets": resolve_bullets(se["bullets"], valid_ids, exp.get("company", exp["id"])),
        })
    # Reverse-chronological order, by end date (or start if ongoing/no end) --
    # enforced in code regardless of what order the model returned, per user
    # instruction that every section is strictly chronological.
    tailored_experience.sort(key=lambda e: _date_rank(e.get("end") or e.get("start")), reverse=True)

    tailored_projects = []
    for sp in plan["projects"]:
        proj = proj_by_id.get(sp["id"])
        if proj is None:
            warnings.append(f"Dropped unknown project id '{sp['id']}'.")
            continue
        valid_ids = {b["id"] for b in proj["bullets"]}
        tailored_projects.append({
            **{k: v for k, v in proj.items() if k != "bullets"},
            "bullets": resolve_bullets(sp["bullets"], valid_ids, proj.get("name", proj["id"])),
        })
    # Reverse-chronological by the project's single `date` field.
    tailored_projects.sort(key=lambda p: _date_rank(p.get("date")), reverse=True)

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
    if plan["unaddressed_reword_opportunities"]:
        warnings.append(
            f"reword_opportunities NOT addressed this pass (should normally be empty): "
            f"{plan['unaddressed_reword_opportunities']}"
        )
    else:
        warnings.append("All reword_opportunities from the score input were addressed this pass.")

    tailored_education = sorted(
        master_resume.get("education", []),
        key=lambda e: _date_rank(e.get("end") or e.get("start")),
        reverse=True,
    )
    tailored_certifications = sorted(
        master_resume.get("certifications", []),
        key=lambda c: _date_rank(c.get("year")),
        reverse=True,
    )

    tailored_resume = {
        "basics": master_resume["basics"],
        "skills": selected_skills,
        "experience": tailored_experience,
        "projects": tailored_projects,
        "education": tailored_education,
        "certifications": tailored_certifications,
    }

    # Backstop for the "never write an internal id in diff_summary" prompt rule
    # above -- prompt-only enforcement of a structurally-checkable rule hasn't
    # held reliably elsewhere in this file (see _has_appended_clause), so don't
    # just trust it here either. Strip a parenthetical made entirely of known
    # ids (the exact shape seen in production: "(b_001, b_002, b_003)"). If an
    # id still appears after that, drop the whole line rather than show the
    # user a partially-scrubbed fragment -- a line that still names an id is,
    # by definition, exactly the specific-bullet-wording narration the prompt
    # rule above already says not to write, so dropping it is consistent, not
    # just a formatting fix. Always logged in validation_log so the slip is
    # visible in the audit trail rather than silently swallowed.
    all_ids = set(bullet_text.keys()) | set(exp_by_id.keys()) | set(proj_by_id.keys())
    cleaned_model_diff_summary = []
    if all_ids:
        id_alt = "|".join(re.escape(i) for i in sorted(all_ids, key=len, reverse=True))
        paren_ids_re = re.compile(rf"\s*\((?:{id_alt})(?:,\s*(?:{id_alt}))*\)")
        id_word_re = re.compile(rf"\b(?:{id_alt})\b")
        for line in plan["diff_summary"]:
            cleaned = paren_ids_re.sub("", line)
            if id_word_re.search(cleaned):
                warnings.append(
                    f"diff_summary line referenced an internal id despite the "
                    f"prompt rule against it -- dropped from the user-facing "
                    f"summary rather than shown: {line!r}"
                )
                continue
            cleaned_model_diff_summary.append(cleaned)
    else:
        cleaned_model_diff_summary = list(plan["diff_summary"])

    # Second backstop, for the substantive rule ("do NOT describe a specific
    # bullet-wording change") rather than just the id-syntax rule above.
    # Verified in production that a model can obey "don't use ids" while still
    # violating the actual rule -- e.g. "reworded the GeoVerify bullet to
    # emphasize data validation..." names no id, but still claims a specific
    # reword happened, and that exact bullet had been reverted by the
    # dropped-terms guardrail two lines earlier. Prompt-only enforcement of
    # this didn't hold even after the narrower id-only fix, so: any line that
    # both (a) names a project/company that had a reword attempt reverted and
    # (b) uses a reword-claiming verb ("reworded", "rewrote", "rewriting") is
    # dropped -- deliberately narrow verb list so this doesn't also eat
    # legitimate selection/ordering rationale that happens to mention the same
    # project name (e.g. "selected GeoVerify to emphasize backend work" is
    # fine and should survive; only an explicit reword claim is the target).
    if reverted_parents:
        # Match on significant words from the parent name, not the full string --
        # a project's full label ("GeoVerify -- Data Integration and Verification
        # Platform") rarely appears verbatim in a diff_summary line; the model
        # naturally refers to it by its short name ("GeoVerify") instead.
        parent_words = {
            (p, word) for p in reverted_parents for word in re.findall(r"\w{4,}", p)
        }
        reword_verb_re = re.compile(r"\breword|\brewrot|\brewrit", re.IGNORECASE)
        filtered = []
        for line in cleaned_model_diff_summary:
            line_lower = line.lower()
            flagged_parent = next((p for p, word in parent_words if word.lower() in line_lower), None)
            if flagged_parent and reword_verb_re.search(line):
                warnings.append(
                    f"diff_summary line claimed a specific bullet-wording change in "
                    f"{flagged_parent!r}, which had a reword attempt reverted this pass "
                    f"-- dropped from the user-facing summary rather than shown: {line!r}"
                )
                continue
            filtered.append(line)
        cleaned_model_diff_summary = filtered

    # Code-generated, ground-truth reword lines -- built only from bullets that
    # actually survived every guardrail above, unlike the model's own diff_summary
    # (which is written before validation runs and can describe an edit that gets
    # reverted two lines later -- exactly what happened with a real GeoVerify/
    # TensorFlow bullet in production: the model's summary claimed a rewording
    # that the guardrail had already blocked). No ids, just a plain count per
    # section, so it can never mismatch what's actually in tailored_resume.
    reword_summary_lines = [
        f"Reworded {count} bullet{'s' if count != 1 else ''} in {parent} to better match the JD."
        for parent, count in reworded_by_parent.items()
    ]

    return {
        "tailored_resume": tailored_resume,
        # Model's own narrative (selection/ordering/skill rationale, in plain
        # language, no internal ids -- safe to show a user directly), plus the
        # code-generated reword lines above appended after it. The model is
        # explicitly instructed not to narrate specific bullet-wording changes
        # itself (see _SHARED_CORE_PROMPT) precisely so this list can't disagree
        # with what actually shipped in tailored_resume.
        "diff_summary": cleaned_model_diff_summary + reword_summary_lines,
        # Code-computed ground truth and guardrail actions (references bullet ids
        # like "b_004" from master_resume.yaml's tagging scheme, and raw rejection
        # messages) -- an audit trail for verifying the no-fabrication rule held,
        # not written for end-user display. Keep separate so a UI can choose to
        # hide/collapse it instead of exposing internal ids in the main view.
        "validation_log": warnings,
        "unaddressed_hard_gaps": plan["unaddressed_hard_gaps"],
        "unaddressed_red_flags": plan["unaddressed_red_flags"],
        "unaddressed_reword_opportunities": plan["unaddressed_reword_opportunities"],
        "ats_scan_notes": plan["ats_scan_notes"],
    }


def tailor_resume(
    jd_parsed: dict, score: dict, master_resume: dict, model: str = DEFAULT_MODEL, mode: str = "aggressive"
) -> dict:
    """Produce a tailored resume from the JD, score output, and master resume.

    mode: "aggressive" (default) rewords bullets in addition to selecting,
    reordering, and relabeling skills -- this is the original, heavily
    tested behavior. "honest" only selects/reorders/relabels; bullet text is
    never touched (enforced in validate_and_build, not just prompted).
    """
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")

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
        system=_system_prompt(mode),
        messages=[{"role": "user", "content": user_content}],
        output_format=TailoringPlan,
    )
    plan = response.parsed_output.model_dump()
    result = validate_and_build(plan, master_resume, mode=mode)

    # Rescore the tailored resume with score.py's own scoring logic so the impact
    # of tailoring (or lack of it) is measured, not assumed.
    score_after = score_jd(jd_parsed, result["tailored_resume"], model=model)
    result["score_before"] = score
    result["score_after"] = score_after
    result["overall_score_delta"] = score_after["overall_score"] - score["overall_score"]
    return result


def main():
    parser = argparse.ArgumentParser(description="Tailor the master resume to a scored JD.")
    parser.add_argument("--jd-json", required=True, help="Path to jd_parsed.json")
    parser.add_argument("--score-json", required=True, help="Path to score.json (output of score.py)")
    parser.add_argument("--resume", type=Path, default=Path("data/master_resume.yaml"), help="Path to master_resume.yaml")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Claude model to use (default: {DEFAULT_MODEL})")
    parser.add_argument(
        "--mode", choices=MODES, default="aggressive",
        help="'aggressive' (default) rewords bullets; 'honest' only selects/reorders/relabels, never touches bullet text",
    )
    args = parser.parse_args()

    jd_parsed = json.loads(Path(args.jd_json).read_text())
    score = json.loads(Path(args.score_json).read_text())
    master_resume = yaml.safe_load(args.resume.read_text())

    result = tailor_resume(jd_parsed, score, master_resume, model=args.model, mode=args.mode)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
