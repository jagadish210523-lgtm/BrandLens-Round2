"""Deterministic checks: glossary and tone/messaging/accessibility rules."""
import re


def finding(category, severity, verdict, rule_ref, rule_title, quote, evidence_quote,
            evidence_title, explanation, suggestion, origin):
    return dict(category=category, severity=severity, verdict=verdict, rule_ref=rule_ref,
                rule_title=rule_title, quote=quote, evidence_quote=evidence_quote,
                evidence_title=evidence_title, explanation=explanation,
                suggestion=suggestion, origin=origin)


def gloss_text(t) -> str:
    return f'Always say "{t.preferred}" instead of "{t.banned}".'


def _match_case(src: str, repl: str) -> str:
    return repl[:1].upper() + repl[1:] if src[:1].isupper() else repl


def check_glossary(text, terms):
    out = []
    for t in terms:
        pat = re.compile(rf"(?<!\w){re.escape(t.banned)}(s)?(?!\w)", re.I)
        for m in pat.finditer(text):
            repl = _match_case(m.group(0), t.preferred) + ("s" if m.group(1) else "")
            out.append(finding(
                "terminology", "low", "violation", f"glossary:{t.id}",
                f'Terminology: "{t.banned}" should be "{t.preferred}"',
                m.group(0), gloss_text(t), "Approved glossary",
                f'The approved term is "{t.preferred}", not "{m.group(0)}".',
                repl, "rule"))
    return out


_SEVERITY = {"tone": "medium", "messaging": "medium", "accessibility": "medium"}


def check_rules(text, rules):
    out = []
    for r in rules:
        try:
            pat = re.compile(r.pattern, re.I)
        except re.error:
            continue
        for m in pat.finditer(text):
            if not m.group(0).strip():
                continue
            sev = "low" if r.title.lower().startswith("exclamation") else _SEVERITY.get(r.category, "medium")
            out.append(finding(
                r.category, sev, "violation", f"tone:{r.id}", r.title,
                m.group(0), r.guidance, r.source_title,
                r.guidance, r.replacement, "rule"))
    return out
