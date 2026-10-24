import os
from datetime import datetime, date, timezone
from typing import Optional
from sqlalchemy import Column, LargeBinary
from sqlmodel import SQLModel, Field, create_engine

def _db_url() -> str:
    url = os.getenv("DATABASE_URL") or os.getenv("POSTGRES_URL") or ""
    if not url:
        # serverless hosts only allow writing to /tmp
        return "sqlite:////tmp/brandlens.db" if os.getenv("VERCEL") else "sqlite:///./brandlens.db"
    if url.startswith("postgres://"):
        url = "postgresql+psycopg2://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg2://" + url[len("postgresql://"):]
    return url


DB_URL = _db_url()
if DB_URL.startswith("sqlite"):
    engine = create_engine(DB_URL, connect_args={"check_same_thread": False})
else:
    engine = create_engine(DB_URL, pool_pre_ping=True, pool_size=2, max_overflow=2, pool_recycle=240)


def now() -> datetime:
    return datetime.now(timezone.utc)


class Org(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    name: str
    palette: str = "#1F2A44,#0E9F8E,#FFFFFF,#F4F6FA"


class User(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    name: str
    email: str = Field(index=True, unique=True)
    role: str  # creator | manager | reviewer | admin
    password_hash: str


# ---- Source library (the approved truth) ----
class GlossaryTerm(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    banned: str
    preferred: str


class ToneRule(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    category: str  # tone | messaging | accessibility
    title: str
    pattern: str
    replacement: Optional[str] = None  # None = no auto-fix, "" = delete
    guidance: str  # the human-readable rule; used as evidence
    source_title: str = "Brand guide"


class ClaimEntry(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    kind: str  # approved | prohibited
    text: str  # approved wording, or the reason a pattern is prohibited
    pattern: Optional[str] = None  # regex for prohibited claims
    keywords: Optional[str] = None  # comma separated, for approved claims
    alternative: Optional[str] = None
    expires_on: Optional[date] = None
    source_title: str = "Claim ledger"


class GuidelineDoc(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    title: str
    body: str


# ---- Workflow ----
class Draft(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    author_id: int = Field(index=True)
    title: str
    channel: str = "Social post"
    intent: str = ""
    status: str = "draft"  # draft | in_review | changes_requested | approved
    image_path: Optional[str] = None  # "db" when an image is stored
    image_data: Optional[bytes] = Field(default=None, sa_column=Column(LargeBinary))
    alt_text: str = ""
    ai_note: str = ""
    created_at: datetime = Field(default_factory=now)
    updated_at: datetime = Field(default_factory=now)


class DraftVersion(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(index=True)
    version_no: int
    content: str
    note: str = ""
    created_by: str = ""
    created_at: datetime = Field(default_factory=now)


class Finding(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(index=True)
    version_id: int = Field(index=True)
    category: str  # terminology | tone | messaging | claims | accessibility | visual
    severity: str  # high | medium | low | info
    verdict: str  # violation | contradicted | outdated | unverified | supported
    origin: str  # rule | claim | ai | image
    rule_ref: str = ""
    rule_title: str = ""
    quote: str = ""
    evidence_quote: str = ""
    evidence_title: str = ""
    explanation: str = ""
    suggestion: Optional[str] = None
    status: str = "open"  # open | dismissed | ok
    dismiss_reason: str = ""


class Comment(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    draft_id: int = Field(index=True)
    user_name: str
    role: str = ""
    body: str
    created_at: datetime = Field(default_factory=now)


class AuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    org_id: int = Field(index=True)
    draft_id: Optional[int] = Field(default=None, index=True)
    user_name: str
    action: str
    created_at: datetime = Field(default_factory=now)
