import re
from datetime import date
from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse, Response
from PIL import Image
from sqlmodel import Session, select, desc
from .models import (User, Draft, DraftVersion, Finding, Comment, AuditLog, GlossaryTerm, ToneRule,
                     ClaimEntry, GuidelineDoc, Org, now)
from .security import get_session, current_user, require, check_pw
from .ui import render, flash, word_diff
from .engine import llm
from . import services

router = APIRouter()

SAMPLES = {
    "1": ("Product launch post", "Social post", "Promote the app's speed and security to new customers",
          "Our app is the fastest and 100% secure! Download now."),
    "2": ("Summer pricing email", "Email", "Tell subscribers about pricing and the summer discount",
          "Hi there, plans start at ₹299 per user per month. Enjoy our Summer offer: 30% off annual plans! "
          "Act now and click here to see pricing."),
    "3": ("Customer proof blog", "Blog", "Show that many teams trust Acme",
          "Acme is trusted by 5,000 teams worldwide. This revolutionary platform is a game-changing choice, "
          "and it is guaranteed results for your clients."),
}
ROLE_NOTE = {"creator": "Creators write drafts and fix findings.",
             "manager": "Managers review submitted drafts and approve them.",
             "reviewer": "Reviewers can approve claims that still carry high-risk findings.",
             "admin": "Admins manage the approved sources."}


def go(url):
    return RedirectResponse(url, status_code=303)


def load_draft(s, user, draft_id) -> Draft:
    d = s.get(Draft, draft_id)
    if not d or d.org_id != user.org_id or (user.role == "creator" and d.author_id != user.id):
        raise HTTPException(404, "Draft not found")
    return d


def counts(s, draft):
    v = services.latest_version(s, draft.id)
    return len(services.issues(services.findings_for(s, v.id))) if v else 0


# ---------------- auth ----------------
@router.get("/login")
def login_page(request: Request, s: Session = Depends(get_session)):
    users = s.exec(select(User).order_by(User.id)).all()
    return render(request, "login.html", None, users=users, notes=ROLE_NOTE)


@router.post("/login")
def login(request: Request, email: str = Form(...), password: str = Form(...), s: Session = Depends(get_session)):
    u = s.exec(select(User).where(User.email == email.strip().lower())).first()
    if not u or not check_pw(password, u.password_hash):
        flash(request, "err", "Email or password is incorrect.")
        return go("/login")
    request.session["uid"] = u.id
    return go("/drafts")


@router.get("/logout")
def logout(request: Request):
    request.session.clear()
    return go("/login")


@router.get("/")
def home():
    return go("/drafts")


# ---------------- drafts ----------------
@router.get("/drafts")
def drafts(request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    q = select(Draft).where(Draft.org_id == user.org_id).order_by(desc(Draft.updated_at))
    if user.role == "creator":
        q = q.where(Draft.author_id == user.id)
    rows = s.exec(q).all()
    authors = {u.id: u.name for u in s.exec(select(User).where(User.org_id == user.org_id)).all()}
    items = [dict(d=d, author=authors.get(d.author_id, "?"), n=counts(s, d)) for d in rows]
    queue = [i for i in items if i["d"].status == "in_review"]
    return render(request, "drafts.html", user, items=items, queue=queue)


@router.get("/drafts/new")
def new_draft_page(request: Request, sample: str = "", user: User = Depends(require("creator", "manager", "reviewer"))):
    t = SAMPLES.get(sample, ("", "Social post", "", ""))
    return render(request, "new_draft.html", user, sample=t, samples=SAMPLES)


@router.post("/drafts/new")
async def new_draft(request: Request, title: str = Form(...), channel: str = Form("Social post"),
                    intent: str = Form(""), content: str = Form(...), alt_text: str = Form(""),
                    image: UploadFile | None = File(None),
                    user: User = Depends(require("creator", "manager", "reviewer")),
                    s: Session = Depends(get_session)):
    if not content.strip():
        flash(request, "err", "Write or paste the draft text first.")
        return go("/drafts/new")
    d = Draft(org_id=user.org_id, author_id=user.id, title=title.strip() or "Untitled", channel=channel,
              intent=intent.strip(), alt_text=alt_text.strip())
    if image is not None and image.filename:
        data = await image.read()
        try:
            import io
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((1400, 1400))
            buf = io.BytesIO()
            img.save(buf, "PNG", optimize=True)
            d.image_data, d.image_path = buf.getvalue(), "db"
        except Exception:
            flash(request, "err", "That file is not a valid image. Use PNG or JPG under 4 MB.")
            return go("/drafts/new")
    s.add(d)
    s.commit()
    s.refresh(d)
    services.save_version(s, d, content.strip(), "First draft", user.name)
    services.audit(s, user.org_id, d.id, user.name, "Created draft and ran review")
    return go(f"/drafts/{d.id}")


@router.get("/drafts/{draft_id}")
def draft_page(draft_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    v = services.latest_version(s, d.id)
    fs = services.findings_for(s, v.id)
    versions = s.exec(select(DraftVersion).where(DraftVersion.draft_id == d.id).order_by(DraftVersion.version_no)).all()
    comments = s.exec(select(Comment).where(Comment.draft_id == d.id).order_by(Comment.id)).all()
    logs = s.exec(select(AuditLog).where(AuditLog.draft_id == d.id).order_by(desc(AuditLog.id))).all()
    author = s.get(User, d.author_id)
    is_author = user.id == d.author_id
    can_edit = is_author and d.status in ("draft", "changes_requested")
    can_triage = can_edit or (user.role in ("manager", "reviewer", "admin") and d.status == "in_review")
    can_decide = user.role in ("manager", "reviewer", "admin") and d.status == "in_review"
    open_issues = services.issues(fs)
    high_claims = [f for f in open_issues if f.severity == "high" and f.category == "claims"]
    return render(request, "draft.html", user, d=d, v=v, versions=versions, comments=comments, logs=logs,
                  author=author, open_issues=open_issues,
                  verified=[f for f in fs if f.verdict == "supported"],
                  dismissed=[f for f in fs if f.status == "dismissed"], all_findings=fs,
                  can_edit=can_edit, can_triage=can_triage, can_decide=can_decide,
                  fixable=len(services.fixable(fs)), ai_on=llm.enabled(), high_claims=high_claims,
                  needs_reviewer=bool(high_claims) and user.role not in ("reviewer", "admin"))


@router.get("/drafts/{draft_id}/image")
def draft_image(draft_id: int, user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    if not d.image_data:
        raise HTTPException(404)
    return Response(d.image_data, media_type="image/png")


def editable(d, user):
    if user.id != d.author_id or d.status not in ("draft", "changes_requested"):
        raise HTTPException(403, "Only the author can change a draft that is not under review.")


@router.post("/drafts/{draft_id}/edit")
def edit(draft_id: int, request: Request, content: str = Form(...), alt_text: str = Form(""),
         user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    editable(d, user)
    d.alt_text = alt_text.strip()
    s.add(d)
    s.commit()
    services.save_version(s, d, content.strip(), "Edited by author", user.name)
    services.audit(s, d.org_id, d.id, user.name, "Edited text and re-ran review")
    flash(request, "ok", "Saved as a new version and checked again.")
    return go(f"/drafts/{d.id}")


@router.post("/drafts/{draft_id}/recheck")
def recheck(draft_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    editable(d, user)
    v = services.latest_version(s, d.id)
    services.save_version(s, d, v.content, "Re-checked, no text change", user.name)
    flash(request, "ok", "Checked again against the current approved sources.")
    return go(f"/drafts/{d.id}")


@router.post("/findings/{fid}/apply")
def apply_one(fid: int, request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    f = s.get(Finding, fid)
    d = load_draft(s, user, f.draft_id) if f else None
    if not f:
        raise HTTPException(404)
    editable(d, user)
    v = services.latest_version(s, d.id)
    if f.version_id != v.id or f.suggestion is None:
        flash(request, "err", "This suggestion is out of date. Check the draft again.")
        return go(f"/drafts/{d.id}")
    before = len(services.issues(services.findings_for(s, v.id)))
    new = services.apply_fixes(v.content, [(f.quote, f.suggestion)])
    nv = services.save_version(s, d, new, f"Applied suggestion: {f.rule_title}", user.name)
    after = len(services.issues(services.findings_for(s, nv.id)))
    services.audit(s, d.org_id, d.id, user.name, f"Applied suggestion: {f.rule_title}")
    flash(request, "ok", f"Applied. Open issues: {before} before, {after} after the re-check.")
    return go(f"/drafts/{d.id}")


@router.post("/findings/{fid}/dismiss")
def dismiss(fid: int, request: Request, reason: str = Form(""), user: User = Depends(current_user),
            s: Session = Depends(get_session)):
    f = s.get(Finding, fid)
    if not f:
        raise HTTPException(404)
    d = load_draft(s, user, f.draft_id)
    can = (user.id == d.author_id and d.status in ("draft", "changes_requested")) or \
          (user.role in ("manager", "reviewer", "admin") and d.status == "in_review")
    if not can:
        raise HTTPException(403, "You cannot dismiss findings right now.")
    if len(reason.strip()) < 3:
        flash(request, "err", "Add a short reason before dismissing a finding.")
        return go(f"/drafts/{d.id}")
    f.status, f.dismiss_reason = "dismissed", reason.strip()
    s.add(f)
    s.commit()
    services.audit(s, d.org_id, d.id, user.name, f"Dismissed finding ({f.rule_title}): {reason.strip()}")
    flash(request, "ok", "Finding dismissed and the reason was recorded.")
    return go(f"/drafts/{d.id}")


@router.post("/drafts/{draft_id}/apply-all")
def apply_all(draft_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    editable(d, user)
    v = services.latest_version(s, d.id)
    fs = services.findings_for(s, v.id)
    fixes = [(f.quote, f.suggestion) for f in services.fixable(fs) if f.quote]
    if not fixes:
        flash(request, "err", "No automatic fixes are available. Edit the text or dismiss with a reason.")
        return go(f"/drafts/{d.id}")
    before = len(services.issues(fs))
    nv = services.save_version(s, d, services.apply_fixes(v.content, fixes), f"Applied {len(fixes)} suggestions", user.name)
    after = len(services.issues(services.findings_for(s, nv.id)))
    services.audit(s, d.org_id, d.id, user.name, f"Applied {len(fixes)} suggestions")
    flash(request, "ok", f"Applied {len(fixes)} fixes. The re-check shows {after} open issue(s), down from {before}.")
    return go(f"/drafts/{d.id}")


@router.post("/drafts/{draft_id}/ai-rewrite")
def ai_rewrite(draft_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    editable(d, user)
    if not llm.enabled():
        flash(request, "err", "AI rewrite needs an ANTHROPIC_API_KEY on the server.")
        return go(f"/drafts/{d.id}")
    v = services.latest_version(s, d.id)
    fs = services.findings_for(s, v.id)
    before = len(services.issues(fs))
    try:
        text = services.ai_rewrite(v.content, d.intent, fs)
    except Exception as e:
        flash(request, "err", f"AI rewrite failed: {str(e)[:100]}")
        return go(f"/drafts/{d.id}")
    nv = services.save_version(s, d, text, "AI rewrite (intent kept), then re-checked", user.name)
    after = len(services.issues(services.findings_for(s, nv.id)))
    services.audit(s, d.org_id, d.id, user.name, "AI rewrite with intent kept")
    flash(request, "ok", f"AI rewrite saved as a new version. Re-check: {before} issue(s) before, {after} after.")
    return go(f"/drafts/{d.id}")


@router.post("/drafts/{draft_id}/submit")
def submit(draft_id: int, request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    editable(d, user)
    d.status = "in_review"
    d.updated_at = now()
    s.add(d)
    s.commit()
    services.audit(s, d.org_id, d.id, user.name, "Submitted for approval")
    flash(request, "ok", "Submitted. A manager will review it.")
    return go(f"/drafts/{d.id}")


@router.post("/drafts/{draft_id}/decision")
def decision(draft_id: int, request: Request, action: str = Form(...), comment: str = Form(""),
             user: User = Depends(require("manager", "reviewer")), s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    if d.status != "in_review":
        raise HTTPException(400, "This draft is not waiting for review.")
    v = services.latest_version(s, d.id)
    open_issues = services.issues(services.findings_for(s, v.id))
    high_claims = [f for f in open_issues if f.severity == "high" and f.category == "claims"]
    if action == "approve":
        if high_claims and user.role not in ("reviewer", "admin"):
            flash(request, "err", "This draft still has high-risk claim findings. An authorised reviewer must approve it.")
            return go(f"/drafts/{d.id}")
        if high_claims and len(comment.strip()) < 5:
            flash(request, "err", "Explain why you are approving with open claim findings.")
            return go(f"/drafts/{d.id}")
        d.status = "approved"
        label = "Approved" + (" with open claim findings (override)" if high_claims else "")
    else:
        if len(comment.strip()) < 3:
            flash(request, "err", "Say what needs to change so the creator knows what to fix.")
            return go(f"/drafts/{d.id}")
        d.status = "changes_requested"
        label = "Requested changes"
    d.updated_at = now()
    s.add(d)
    if comment.strip():
        s.add(Comment(draft_id=d.id, user_name=user.name, role=user.role, body=comment.strip()))
    s.commit()
    services.audit(s, d.org_id, d.id, user.name, label)
    flash(request, "ok", label + ".")
    return go(f"/drafts/{d.id}")


@router.post("/drafts/{draft_id}/comment")
def comment(draft_id: int, request: Request, body: str = Form(...), user: User = Depends(current_user),
            s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    if body.strip():
        s.add(Comment(draft_id=d.id, user_name=user.name, role=user.role, body=body.strip()))
        s.commit()
        services.audit(s, d.org_id, d.id, user.name, "Added a comment")
    return go(f"/drafts/{d.id}")


@router.get("/drafts/{draft_id}/diff")
def diff(draft_id: int, request: Request, a: int = 1, b: int = 0, user: User = Depends(current_user),
         s: Session = Depends(get_session)):
    d = load_draft(s, user, draft_id)
    versions = s.exec(select(DraftVersion).where(DraftVersion.draft_id == d.id).order_by(DraftVersion.version_no)).all()
    by = {v.version_no: v for v in versions}
    b = b or versions[-1].version_no
    if a not in by or b not in by:
        raise HTTPException(404, "Version not found")
    return render(request, "diff.html", user, d=d, versions=versions, a=by[a], b=by[b],
                  html=word_diff(by[a].content, by[b].content))


# ---------------- source library ----------------
@router.get("/sources")
def sources(request: Request, user: User = Depends(current_user), s: Session = Depends(get_session)):
    oid = user.org_id
    claims = s.exec(select(ClaimEntry).where(ClaimEntry.org_id == oid).order_by(ClaimEntry.kind, ClaimEntry.id)).all()
    return render(request, "sources.html", user,
                  org=s.get(Org, oid), today=date.today(),
                  terms=s.exec(select(GlossaryTerm).where(GlossaryTerm.org_id == oid)).all(),
                  rules=s.exec(select(ToneRule).where(ToneRule.org_id == oid)).all(),
                  claims=claims,
                  docs=s.exec(select(GuidelineDoc).where(GuidelineDoc.org_id == oid)).all())


def _valid_regex(request, pattern):
    try:
        re.compile(pattern)
        return True
    except re.error:
        flash(request, "err", "That pattern is not a valid regular expression.")
        return False


@router.post("/sources/glossary")
def add_term(request: Request, banned: str = Form(...), preferred: str = Form(...),
             user: User = Depends(require("admin")), s: Session = Depends(get_session)):
    s.add(GlossaryTerm(org_id=user.org_id, banned=banned.strip(), preferred=preferred.strip()))
    s.commit()
    services.audit(s, user.org_id, None, user.name, f"Added glossary term {banned.strip()} -> {preferred.strip()}")
    return go("/sources")


@router.post("/sources/rule")
def add_rule(request: Request, category: str = Form(...), title: str = Form(...), pattern: str = Form(...),
             replacement: str = Form(""), guidance: str = Form(...), user: User = Depends(require("admin")),
             s: Session = Depends(get_session)):
    if not _valid_regex(request, pattern):
        return go("/sources")
    s.add(ToneRule(org_id=user.org_id, category=category, title=title.strip(), pattern=pattern,
                   replacement=(replacement if replacement.strip() else None), guidance=guidance.strip(),
                   source_title="Custom rule"))
    s.commit()
    services.audit(s, user.org_id, None, user.name, f"Added rule {title.strip()}")
    return go("/sources")


@router.post("/sources/claim")
def add_claim(request: Request, kind: str = Form(...), text: str = Form(...), pattern: str = Form(""),
              keywords: str = Form(""), alternative: str = Form(""), expires_on: str = Form(""),
              user: User = Depends(require("admin")), s: Session = Depends(get_session)):
    if kind == "prohibited" and (not pattern.strip() or not _valid_regex(request, pattern)):
        flash(request, "err", "A prohibited claim needs a valid pattern.")
        return go("/sources")
    exp = date.fromisoformat(expires_on) if expires_on.strip() else None
    s.add(ClaimEntry(org_id=user.org_id, kind=kind, text=text.strip(), pattern=pattern.strip() or None,
                     keywords=keywords.strip() or None, alternative=alternative.strip() or None,
                     expires_on=exp, source_title="Acme Claim Ledger"))
    s.commit()
    services.audit(s, user.org_id, None, user.name, f"Added {kind} claim")
    return go("/sources")


@router.post("/sources/doc")
def add_doc(title: str = Form(...), body: str = Form(...), user: User = Depends(require("admin")),
            s: Session = Depends(get_session)):
    s.add(GuidelineDoc(org_id=user.org_id, title=title.strip(), body=body.strip()))
    s.commit()
    services.audit(s, user.org_id, None, user.name, f"Added guideline document {title.strip()}")
    return go("/sources")


@router.post("/sources/{kind}/{item_id}/delete")
def delete_source(kind: str, item_id: int, user: User = Depends(require("admin")), s: Session = Depends(get_session)):
    model = {"glossary": GlossaryTerm, "rule": ToneRule, "claim": ClaimEntry, "doc": GuidelineDoc}.get(kind)
    if not model:
        raise HTTPException(404)
    row = s.get(model, item_id)
    if row and row.org_id == user.org_id:
        s.delete(row)
        s.commit()
        services.audit(s, user.org_id, None, user.name, f"Removed {kind} #{item_id}")
    return go("/sources")


# ---------------- insights and audit ----------------
@router.get("/insights")
def insights_page(request: Request, user: User = Depends(require("manager", "reviewer")),
                  s: Session = Depends(get_session)):
    return render(request, "insights.html", user, data=services.insights(s, user.org_id))


@router.get("/audit")
def audit_page(request: Request, user: User = Depends(require("manager", "reviewer")),
               s: Session = Depends(get_session)):
    logs = s.exec(select(AuditLog).where(AuditLog.org_id == user.org_id).order_by(desc(AuditLog.id)).limit(150)).all()
    return render(request, "audit.html", user, logs=logs)
