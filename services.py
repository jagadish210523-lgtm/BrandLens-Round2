import re
from collections import Counter, defaultdict
from sqlmodel import Session, select, desc
from .models import (Draft, DraftVersion, Finding, AuditLog, User, now)
from .engine import review, llm

def audit(s: Session, org_id, draft_id, user_name, action):
    s.add(AuditLog(org_id=org_id, draft_id=draft_id, user_name=user_name, action=action))
    s.commit()


def latest_version(s, draft_id):
    return s.exec(select(DraftVersion).where(DraftVersion.draft_id == draft_id)
                  .order_by(desc(DraftVersion.version_no))).first()


def findings_for(s, version_id):
    return s.exec(select(Finding).where(Finding.version_id == version_id).order_by(Finding.id)).all()


def issues(findings):
    return [f for f in findings if f.status == "open" and f.verdict != "supported"]


def tidy(text: str) -> str:
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+([.,;:!?])", r"\1", text)
    return "\n".join(ln.strip() for ln in text.split("\n")).strip()


def replace_quote(text: str, quote: str, repl: str) -> str:
    pre = r"(?<!\w)" if quote[:1].isalnum() else ""
    suf = r"(?!\w)" if quote[-1:].isalnum() else ""
    return re.sub(pre + re.escape(quote) + suf, lambda m: repl, text)


def apply_fixes(content: str, fixes):
    new = content
    for quote, repl in sorted(set(fixes), key=lambda x: -len(x[0])):
        if quote:
            new = replace_quote(new, quote, repl)
    new = tidy(new)
    if content[:1].isupper() and new[:1].islower():
        new = new[:1].upper() + new[1:]
    return new


def run_and_store(s: Session, draft: Draft, version: DraftVersion):
    prev = s.exec(select(DraftVersion).where(DraftVersion.draft_id == draft.id,
                                             DraftVersion.version_no < version.version_no)
                  .order_by(desc(DraftVersion.version_no))).first()
    carried = {}
    if prev:
        for f in findings_for(s, prev.id):
            if f.status == "dismissed":
                carried[(f.rule_ref, f.quote.lower())] = f.dismiss_reason
    found, ai = review.run(s, draft, version.content)
    for f in found:
        key = (f["rule_ref"], f["quote"].lower())
        status = "ok" if f["verdict"] == "supported" else "open"
        reason = ""
        if key in carried and status == "open":
            status, reason = "dismissed", carried[key]
        s.add(Finding(draft_id=draft.id, version_id=version.id, status=status, dismiss_reason=reason, **f))
    if ai["enabled"]:
        draft.ai_note = ("AI judge on" + (f", {ai['dropped']} unverifiable AI finding(s) dropped" if ai["dropped"] else "")
                         + (f" (AI unavailable: {ai['error']})" if ai["error"] else ""))
    else:
        draft.ai_note = "AI judge off: rule and claim checks only"
    draft.updated_at = now()
    s.add(draft)
    s.commit()
    return ai


def save_version(s: Session, draft: Draft, content: str, note: str, user_name: str):
    last = latest_version(s, draft.id)
    v = DraftVersion(draft_id=draft.id, version_no=(last.version_no + 1) if last else 1,
                     content=content, note=note, created_by=user_name)
    s.add(v)
    s.commit()
    s.refresh(v)
    run_and_store(s, draft, v)
    return v


def fixable(findings):
    return [f for f in issues(findings) if f.suggestion is not None]


def ai_rewrite(content: str, intent: str, findings):
    return llm.rewrite(content, intent, [{"quote": f.quote, "explanation": f.explanation}
                                         for f in issues(findings) if f.quote])


def insights(s: Session, org_id: int):
    drafts = s.exec(select(Draft).where(Draft.org_id == org_id)).all()
    by_cat, by_rule, by_author = Counter(), Counter(), Counter()
    titles, shown, dismissed = {}, Counter(), Counter()
    first_total = 0
    users = {u.id: u.name for u in s.exec(select(User).where(User.org_id == org_id)).all()}
    for d in drafts:
        versions = s.exec(select(DraftVersion).where(DraftVersion.draft_id == d.id)
                          .order_by(DraftVersion.version_no)).all()
        if not versions:
            continue
        for f in findings_for(s, versions[0].id):
            if f.verdict == "supported":
                continue
            by_cat[f.category] += 1
            by_rule[f.rule_ref] += 1
            by_author[users.get(d.author_id, "?")] += 1
            titles[f.rule_ref] = f.rule_title
            first_total += 1
        for v in versions:
            for f in findings_for(s, v.id):
                if f.verdict != "supported" and f.status in ("open", "dismissed"):
                    shown[f.rule_ref] += 1
                    if f.status == "dismissed":
                        dismissed[f.rule_ref] += 1
                        titles.setdefault(f.rule_ref, f.rule_title)
    health = []
    for ref, n in shown.items():
        d = dismissed[ref]
        rate = d / n
        if n >= 3 and rate >= 0.4:
            health.append({"ref": ref, "title": titles.get(ref, ref), "shown": n, "dismissed": d,
                           "rate": round(rate * 100)})
    health.sort(key=lambda h: -h["rate"])
    return {
        "drafts": len(drafts),
        "approved": sum(1 for d in drafts if d.status == "approved"),
        "first_total": first_total,
        "by_cat": by_cat.most_common(),
        "top_rules": [(titles.get(r, r), n) for r, n in by_rule.most_common(6)],
        "by_author": by_author.most_common(),
        "health": health,
    }
