import hashlib
import secrets
from fastapi import Depends, HTTPException, Request
from sqlmodel import Session
from .models import User, engine


class NeedLogin(Exception):
    pass


def hash_pw(pw: str, salt: str | None = None) -> str:
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 60000).hex()
    return f"{salt}${h}"


def check_pw(pw: str, stored: str) -> bool:
    salt = stored.split("$")[0]
    return secrets.compare_digest(hash_pw(pw, salt), stored)


def get_session():
    with Session(engine) as s:
        yield s


def current_user(request: Request, s: Session = Depends(get_session)) -> User:
    uid = request.session.get("uid")
    user = s.get(User, uid) if uid else None
    if not user:
        raise NeedLogin()
    return user


def require(*roles: str):
    def dep(user: User = Depends(current_user)) -> User:
        if user.role != "admin" and user.role not in roles:
            raise HTTPException(403, "Your role cannot open this page.")
        return user
    return dep
