"""Demo organisation 'Acme' with approved sources, demo users and a little history,
so judges can use the product immediately."""
from datetime import date, timedelta, datetime
from sqlmodel import Session, select
from .models import (now, Org, User, GlossaryTerm, ToneRule, ClaimEntry, GuidelineDoc, Draft, Comment,
                     AuditLog, engine, SQLModel)
from .security import hash_pw
from . import services

BRAND_GUIDE = """Voice and tone. Our voice is calm and confident. We explain what the product does and let the facts speak. Do not use exclamation marks in headlines or body copy.

Hype language. Avoid hype words such as revolutionary, game-changing or mind-blowing. Describe the benefit in plain words instead.

Pressure language. Never push readers with urgency such as act now, hurry or last chance. Invite them to get started instead.

Claims. Every promotional claim must be supported by an approved source. Do not use absolute words such as 100% or guaranteed, and do not rank Acme against competitors without an approved benchmark.

Terminology. We call Acme a platform, never an app. We talk about customers, not clients. We say affordable, never cheap.

Accessibility. Every image needs alt text that describes it. Link text must describe the destination, never say click here.

Respect for the reader. Keep sentences short, avoid slang, and write for someone meeting Acme for the first time."""

USERS = [("Asha Rao", "asha@acme.test", "creator"), ("Kiran Patel", "kiran@acme.test", "creator"),
         ("Ravi Menon", "ravi@acme.test", "manager"), ("Meera Iyer", "meera@acme.test", "reviewer"),
         ("Admin", "admin@acme.test", "admin")]

HISTORY = [
    ("asha@acme.test", "Launch teaser", "Social post", "Announce the new dashboard",
     "Meet our revolutionary new dashboard! It is the fastest way to see your data.", ["Hype"]),
    ("asha@acme.test", "Newsletter intro", "Email", "Welcome new subscribers",
     "Our app helps clients plan better! Click here to read more.", []),
    ("kiran@acme.test", "Feature blog", "Blog", "Explain reporting",
     "This game-changing report builder is super easy to use. Our app is guaranteed results for every team!", ["Hype"]),
    ("kiran@acme.test", "Partner post", "Social post", "Thank partners",
     "A revolutionary partnership with our world-class partners! Hurry, join the webinar.", ["Hype"]),
    ("asha@acme.test", "Pricing note", "Email", "Share pricing",
     "Plans start at ₹499 per user per month. Our app is cheap and clients love it!", []),
    ("kiran@acme.test", "Support update", "Blog", "Explain support",
     "Mind-blowing support is available 24/7 by chat and email.", ["Hype"]),
    ("asha@acme.test", "Customer story", "Blog", "Tell a customer story",
     "Acme is used by more than 2,000 teams worldwide. Our app is trusted by clients everywhere!", []),
]


def seed():
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        if s.exec(select(Org)).first():
            return
        org = Org(name="Acme")
        s.add(org)
        s.commit()
        s.refresh(org)
        oid = org.id
        for name, email, role in USERS:
            s.add(User(org_id=oid, name=name, email=email, role=role, password_hash=hash_pw("demo123")))
        for b, p in [("app", "platform"), ("cheap", "affordable"), ("clients", "customers"),
                     ("client", "customer"), ("utilize", "use")]:
            s.add(GlossaryTerm(org_id=oid, banned=b, preferred=p))
        guide = "Acme Brand Guide v3"
        for cat, title, pat, repl, guid in [
            ("tone", "Exclamation marks", r"!+", ".",
             "Our voice is calm and confident. Do not use exclamation marks in headlines or body copy."),
            ("tone", "Hype words", r"\b(?:revolutionary|game[- ]changing|mind[- ]blowing|cutting[- ]edge|world[- ]class)\b", "",
             "Avoid hype words such as revolutionary, game-changing or mind-blowing. Describe the benefit in plain words instead."),
            ("tone", "Slang", r"\b(?:super easy|no-brainer|killer|awesome)\b", None,
             "Keep language professional and avoid slang."),
            ("messaging", "Pressure language", r"\b(?:act now|hurry|last chance|don't miss out)\b", "Get started",
             "Never push readers with urgency such as act now, hurry or last chance. Invite them to get started instead."),
            ("accessibility", "Descriptive link text", r"\bclick here\b", "view details",
             "Link text must describe the destination and must never say click here."),
        ]:
            s.add(ToneRule(org_id=oid, category=cat, title=title, pattern=pat, replacement=repl,
                           guidance=guid, source_title=guide))
        today = date.today()
        for kind, text, pat, kw, alt, exp in [
            ("prohibited", "Do not make absolute security claims. Approved wording: Acme encrypts data in transit and at rest and has completed an independent security audit.",
             r"(?:100\s*%|completely|totally|absolutely)\s+(?:secure|safe)|unhackable|hack-proof", None,
             "encrypted and independently audited", None),
            ("prohibited", "Do not claim to be the fastest. No approved speed benchmark exists in the Claim Ledger.",
             r"(?:the\s+)?fastest", None, "built for speed", None),
            ("prohibited", "Do not rank Acme as number one or best-in-class without an approved benchmark.",
             r"number[- ]one|best[- ]in[- ](?:class|market|world)|market[- ]leading|#1", None, None, None),
            ("prohibited", "Do not promise guaranteed outcomes.",
             r"guarantee[sd]?\s+(?:results|returns|growth|success|savings)|guaranteed\s+(?:results|returns|growth|success|savings)", None, None, None),
            ("approved", "Plans start at ₹499 per user per month.", None,
             "plans,start,per,month,price,pricing", None, today + timedelta(days=200)),
            ("approved", "Acme is used by more than 2,000 teams worldwide.", None,
             "used,trusted,teams,companies,customers,worldwide", None, today + timedelta(days=250)),
            ("approved", "Acme encrypts data in transit and at rest and has completed an independent security audit.", None,
             "encrypted,encrypts,encryption,audit,audited,security,secure,data", None, today + timedelta(days=300)),
            ("approved", "Summer offer: 30% off annual plans.", None,
             "summer,offer,off,annual,plans,discount", None, today - timedelta(days=45)),
            ("approved", "Support is available 24/7 by chat and email.", None,
             "support,available,chat,email,help", None, today + timedelta(days=365)),
        ]:
            s.add(ClaimEntry(org_id=oid, kind=kind, text=text, pattern=pat, keywords=kw, alternative=alt,
                             expires_on=exp, source_title="Acme Claim Ledger"))
        s.add(GuidelineDoc(org_id=oid, title=guide, body=BRAND_GUIDE))
        s.commit()
        by_email = {u.email: u for u in s.exec(select(User)).all()}
        mgr = by_email["ravi@acme.test"]
        for i, (email, title, channel, intent, text, dismiss) in enumerate(HISTORY):
            u = by_email[email]
            d = Draft(org_id=oid, author_id=u.id, title=title, channel=channel, intent=intent,
                      created_at=now() - timedelta(days=12 - i), status="draft")
            s.add(d)
            s.commit()
            s.refresh(d)
            v = services.save_version(s, d, text, "First draft", u.name)
            for f in services.findings_for(s, v.id):
                if any(k.lower() in f.rule_title.lower() for k in dismiss) and f.status == "open":
                    f.status, f.dismiss_reason = "dismissed", "Brand voice allows this in launch posts"
                    s.add(f)
            d.status = "approved"
            s.add(d)
            s.add(Comment(draft_id=d.id, user_name=mgr.name, role=mgr.role, body="Approved for publishing."))
            s.commit()
            services.audit(s, oid, d.id, mgr.name, "Approved")
