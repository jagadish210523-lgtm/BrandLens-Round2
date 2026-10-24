"""Review pipeline: segment -> rule checks -> claim ledger -> (retrieve + AI judge) -> verifier."""
import re
from datetime import date
from sqlmodel import Session, select
from ..models import (Org, GlossaryTerm, ToneRule, ClaimEntry, GuidelineDoc)
from . import rules, claims, images, llm, verify
from .segment import paragraphs


def _toks(s):
    return set(re.findall(r"[a-z]{3,}", s.lower()))


def retrieve(content, chunks, k=6):
    q = _toks(content)
    scored = sorted(chunks, key=lambda c: len(q & _toks(c[2])), reverse=True)
    return scored[:k]


def run(s: Session, draft, content: str):
    oid = draft.org_id
    org = s.get(Org, oid)
    terms = s.exec(select(GlossaryTerm).where(GlossaryTerm.org_id == oid)).all()
    trules = s.exec(select(ToneRule).where(ToneRule.org_id == oid)).all()
    centries = s.exec(select(ClaimEntry).where(ClaimEntry.org_id == oid)).all()
    docs = s.exec(select(GuidelineDoc).where(GuidelineDoc.org_id == oid)).all()

    registry = {f"glossary:{t.id}": rules.gloss_text(t) for t in terms}
    registry.update({f"tone:{r.id}": r.guidance for r in trules})
    registry.update({f"claim:{c.id}": c.text for c in centries})
    chunks = []
    for d in docs:
        for i, p in enumerate(paragraphs(d.body)):
            ref = f"doc:{d.id}:{i}"
            registry[ref] = p
            chunks.append((ref, d.title, p))
    registry.update(images.registry(org.palette))

    found = rules.check_glossary(content, terms) + rules.check_rules(content, trules)
    found += claims.check_claims(content, centries, date.today())

    ai = {"enabled": llm.enabled(), "used": False, "dropped": 0, "error": ""}
    if ai["enabled"] and chunks:
        try:
            titles = {c[0]: c[1] for c in chunks}
            raw = llm.judge(content, retrieve(content, chunks), [f["quote"] for f in found])
            for it in raw:
                ref = str(it.get("evidence_ref", ""))
                if not ref.startswith("doc:") or ref not in registry or not it.get("draft_quote"):
                    ai["dropped"] += 1
                    continue
                cat = it.get("category") if it.get("category") in ("tone", "messaging") else "tone"
                found.append(rules.finding(
                    cat, "medium", "violation", ref, "AI review: " + cat, it["draft_quote"],
                    it.get("evidence_quote", ""), titles.get(ref, "Brand guide"),
                    it.get("explanation", ""), (it.get("suggestion") or None), "ai"))
            ai["used"] = True
        except Exception as e:  # AI is optional: rule checks still stand
            ai["error"] = str(e)[:120]

    if draft.image_path:
        found += images.check(draft.image_data, draft.alt_text, org.palette)

    kept, dropped = verify.verify(found, registry, content)
    ai["dropped"] += sum(1 for f in dropped if f["origin"] == "ai")

    seen, unique = set(), []
    for f in kept:
        key = (f["rule_ref"], f["quote"].lower())
        if key not in seen:
            seen.add(key)
            unique.append(f)
    low = content.lower()
    unique.sort(key=lambda f: low.find(f["quote"].lower()) if f["quote"] and low.find(f["quote"].lower()) >= 0 else 10**6)
    return unique, ai
