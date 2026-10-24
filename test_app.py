import json
import os
import re
import tempfile
from pathlib import Path

os.environ["DATABASE_URL"] = "sqlite:///" + os.path.join(tempfile.mkdtemp(), "t.db")
os.environ.pop("ANTHROPIC_API_KEY", None)

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, select
from app.main import app
from app.models import engine, Draft, Finding
from app.engine import verify, llm
from app import services

HERE = Path(__file__).parent


@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c


def login(c, email):
    c.get("/logout")
    r = c.post("/login", data={"email": email, "password": "demo123"}, follow_redirects=True)
    assert r.status_code == 200


def create(c, text, title="T"):
    r = c.post("/drafts/new", data={"title": title, "channel": "Social post", "intent": "promote",
                                    "content": text}, follow_redirects=True)
    assert r.status_code == 200
    return int(str(r.url).rsplit("/", 1)[1])


def quotes(draft_id):
    with Session(engine) as s:
        v = services.latest_version(s, draft_id)
        return [(f.quote.lower(), f.verdict, f.status) for f in services.findings_for(s, v.id)]


def test_planted_violations_recall_and_clean_texts(client):
    login(client, "asha@acme.test")
    cases = json.load(open(HERE / "planted_violations.json"))
    total = hit = 0
    missed = []
    for c in cases:
        d = create(client, c["text"])
        qs = [q for q, v, st in quotes(d) if v != "supported"]
        for e in c["expect"]:
            total += 1
            if any(e.lower() in q or q in e.lower() and q for q in qs):
                hit += 1
            else:
                missed.append((c["text"], e))
    clean = json.load(open(HERE / "clean_texts.json"))
    fp = 0
    for t in clean:
        d = create(client, t)
        fp += sum(1 for q, v, st in quotes(d) if v != "supported")
    print(f"\nRECALL {hit}/{total} = {hit/total:.0%}; false alarms on {len(clean)} clean texts: {fp}")
    for m in missed:
        print("MISSED", m)
    assert hit / total >= 0.9
    assert fp == 0


def test_every_finding_cites_real_evidence(client):
    login(client, "asha@acme.test")
    d = create(client, "Our app is the fastest and 100% secure! Download now.")
    with Session(engine) as s:
        v = services.latest_version(s, d)
        for f in services.findings_for(s, v.id):
            if f.verdict not in ("unverified", "supported"):
                assert f.evidence_quote and f.evidence_title


def test_unverified_claim_is_honest(client):
    login(client, "asha@acme.test")
    d = create(client, "Our platform delivers unmatched performance.")
    assert any(v == "unverified" for q, v, st in quotes(d))


def test_verifier_drops_invented_evidence():
    registry = {"doc:1:0": "Do not use exclamation marks."}
    good = dict(rule_ref="doc:1:0", evidence_quote="Do not use exclamation marks", quote="Hi!", verdict="violation", origin="ai")
    bad = dict(rule_ref="doc:1:0", evidence_quote="Never mention competitors", quote="Hi!", verdict="violation", origin="ai")
    gone = dict(rule_ref="doc:1:0", evidence_quote="Do not use exclamation marks", quote="Not in draft", verdict="violation", origin="ai")
    kept, dropped = verify.verify([good, bad, gone], registry, "Hi! there")
    assert kept == [good] and len(dropped) == 2


def test_ai_judge_findings_are_verified(monkeypatch, client):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    guide_ref = None
    with Session(engine) as s:
        from app.models import GuidelineDoc
        doc = s.exec(select(GuidelineDoc)).first()
        guide_ref = f"doc:{doc.id}:6"
    fake = [
        {"category": "tone", "draft_quote": "just slang here", "evidence_ref": guide_ref,
         "evidence_quote": "avoid slang", "explanation": "Slang.", "suggestion": "plain words"},
        {"category": "tone", "draft_quote": "just slang here", "evidence_ref": guide_ref,
         "evidence_quote": "this sentence is invented", "explanation": "Invented.", "suggestion": ""},
        {"category": "tone", "draft_quote": "just slang here", "evidence_ref": "made-up", "evidence_quote": "x"},
    ]
    monkeypatch.setattr(llm, "judge", lambda *a, **k: fake)
    login(client, "asha@acme.test")
    d = create(client, "This is just slang here for you.")
    with Session(engine) as s:
        v = services.latest_version(s, d)
        ai = [f for f in services.findings_for(s, v.id) if f.origin == "ai"]
        assert len(ai) == 1 and ai[0].evidence_quote.lower() == "avoid slang"


def test_full_workflow_with_roles(client):
    login(client, "asha@acme.test")
    d = create(client, "Our app is the fastest and 100% secure! Download now.", "Workflow test")
    # creator cannot approve
    r = client.post(f"/drafts/{d}/decision", data={"action": "approve"}, follow_redirects=True)
    assert r.status_code == 403
    r = client.post(f"/drafts/{d}/apply-all", follow_redirects=True)
    assert "Applied" in r.text
    with Session(engine) as s:
        v = services.latest_version(s, d)
        assert v.version_no == 2
        assert "built for speed" in v.content and "100%" not in v.content
        assert services.issues(services.findings_for(s, v.id)) == []
    client.post(f"/drafts/{d}/submit")
    login(client, "ravi@acme.test")
    assert "Workflow test" in client.get("/drafts").text
    r = client.post(f"/drafts/{d}/decision", data={"action": "approve", "comment": "Looks good"}, follow_redirects=True)
    assert "Approved" in r.text
    with Session(engine) as s:
        assert s.get(Draft, d).status == "approved"
    assert client.get(f"/drafts/{d}/diff?a=1&b=2").status_code == 200


def test_high_risk_claims_need_reviewer(client):
    login(client, "asha@acme.test")
    d = create(client, "We are 100% secure.", "Risky")
    client.post(f"/drafts/{d}/submit")
    login(client, "ravi@acme.test")
    r = client.post(f"/drafts/{d}/decision", data={"action": "approve"}, follow_redirects=True)
    assert "authorised reviewer" in r.text
    login(client, "meera@acme.test")
    r = client.post(f"/drafts/{d}/decision", data={"action": "approve"}, follow_redirects=True)
    assert "Explain why" in r.text
    r = client.post(f"/drafts/{d}/decision", data={"action": "approve", "comment": "Legal confirmed wording"}, follow_redirects=True)
    assert "override" in r.text


def test_dismiss_needs_reason_and_is_carried_over(client):
    login(client, "asha@acme.test")
    d = create(client, "Wow! This is good.", "Dismiss")
    with Session(engine) as s:
        fid = services.issues(services.findings_for(s, services.latest_version(s, d).id))[0].id
    r = client.post(f"/findings/{fid}/dismiss", data={"reason": ""}, follow_redirects=True)
    assert "short reason" in r.text
    client.post(f"/findings/{fid}/dismiss", data={"reason": "Campaign voice"}, follow_redirects=True)
    client.post(f"/drafts/{d}/recheck")
    with Session(engine) as s:
        fs = services.findings_for(s, services.latest_version(s, d).id)
        assert any(f.status == "dismissed" for f in fs)


def test_creator_cannot_see_others_drafts(client):
    login(client, "asha@acme.test")
    d = create(client, "Private draft text.", "Asha only")
    login(client, "kiran@acme.test")
    assert client.get(f"/drafts/{d}").status_code == 404


def test_insights_and_admin_pages(client):
    login(client, "ravi@acme.test")
    r = client.get("/insights")
    assert r.status_code == 200 and "Guideline health" in r.text and "Hype words" in r.text
    assert client.get("/audit").status_code == 200
    login(client, "asha@acme.test")
    assert client.get("/insights").status_code == 403
    assert client.post("/sources/glossary", data={"banned": "x", "preferred": "y"}).status_code == 403
    login(client, "admin@acme.test")
    assert client.post("/sources/glossary", data={"banned": "synergy", "preferred": "teamwork"}, follow_redirects=True).status_code == 200
    assert client.get("/sources").status_code == 200


def test_image_checks(client):
    import io
    from PIL import Image
    login(client, "asha@acme.test")
    buf = io.BytesIO()
    Image.new("RGB", (400, 300), (230, 30, 30)).save(buf, "PNG")
    r = client.post("/drafts/new", data={"title": "Img", "channel": "Social post", "intent": "x",
                    "content": "A calm launch note.", "alt_text": "image"},
                    files={"image": ("a.png", buf.getvalue(), "image/png")}, follow_redirects=True)
    d = int(str(r.url).rsplit("/", 1)[1])
    refs = [f for f in [q for q in quotes(d)]]
    with Session(engine) as s:
        rr = [f.rule_ref for f in services.findings_for(s, services.latest_version(s, d).id)]
    assert "image:alt" in rr and "image:palette" in rr


def test_health(client):
    assert client.get("/health").json()["status"] == "ok"
