"""Claim Ledger check. Every promotional claim ends in one of four outcomes:
supported, contradicted, outdated or unverified."""
import re
from datetime import date
from .rules import finding
from .segment import sentences

TRIGGERS = re.compile(
    r"\d+(?:\.\d+)?\s*%|[₹$€£]\s?\d|\b\d[\d,]*\+?\s+(?:teams|customers|users|companies|clients)\b"
    r"|\b(?:guarantee[sd]?|always|never|zero|risk-free|instant(?:ly)?|best|fastest|number[- ]one|leading|"
    r"unmatched|unbeatable|secure|certified|compliant|encrypt\w*|audited|24/7)\b|#1",
    re.I)
NUM = re.compile(r"\d[\d,]*(?:\.\d+)?")


def _tokens(s: str) -> set:
    toks = set(re.findall(r"[a-z0-9]+", s.lower()))
    return toks | {t[:-1] for t in toks if len(t) > 3 and t.endswith("s")}


def _nums(s: str) -> set:
    return {n.replace(",", "") for n in NUM.findall(s)}


def check_claims(text, entries, today: date | None = None):
    today = today or date.today()
    prohibited = [e for e in entries if e.kind == "prohibited" and e.pattern]
    approved = [e for e in entries if e.kind == "approved"]
    out = []
    for _, _, sent in sentences(text):
        s = sent.strip()
        handled = False
        for e in prohibited:
            try:
                pat = re.compile(e.pattern, re.I)
            except re.error:
                continue
            for m in pat.finditer(s):
                handled = True
                out.append(finding(
                    "claims", "high", "contradicted", f"claim:{e.id}",
                    "Claim not allowed by approved material", m.group(0), e.text,
                    e.source_title, e.text, e.alternative, "claim"))
        if handled:
            continue
        trig = TRIGGERS.search(s)
        if not trig:
            continue
        toks = _tokens(s)
        best, best_score = None, 0
        for e in approved:
            kws = {k.strip().lower() for k in (e.keywords or "").split(",") if k.strip()}
            score = len(kws & toks)
            if score > best_score:
                best, best_score = e, score
        if best and best_score >= 2:
            if best.expires_on and best.expires_on < today:
                out.append(finding(
                    "claims", "high", "outdated", f"claim:{best.id}",
                    "Claim uses expired approval", s, best.text, best.source_title,
                    f"This claim was only approved until {best.expires_on:%d %b %Y}. Remove it or get it re-approved.",
                    None, "claim"))
            elif _nums(s) - _nums(best.text):
                out.append(finding(
                    "claims", "high", "contradicted", f"claim:{best.id}",
                    "Figure differs from approved claim", s, best.text, best.source_title,
                    "The numbers in this sentence do not match the approved claim.",
                    best.text, "claim"))
            else:
                out.append(finding(
                    "claims", "info", "supported", f"claim:{best.id}",
                    "Matches an approved claim", s, best.text, best.source_title,
                    "This statement matches an approved claim.", None, "claim"))
        else:
            seen = set()
            for tm in TRIGGERS.finditer(s):
                key = tm.group(0).lower()
                if key in seen:
                    continue
                seen.add(key)
                out.append(finding(
                    "claims", "medium", "unverified", "claim:none",
                    "Claim has no approved source", tm.group(0), "", "",
                    f'"{tm.group(0)}" is a promotional claim, but nothing in the approved material supports it. '
                    "Remove it, soften it, or add an approved source to the Claim Ledger.",
                    None, "claim"))
    return out
