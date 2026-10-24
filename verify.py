"""Verifier: a finding is only kept if the evidence it quotes really exists in an
approved source and the text it flags really exists in the draft."""
import re


def norm(x: str) -> str:
    return re.sub(r"\s+", " ", x or "").strip().lower()


def verify(findings, registry, content):
    kept, dropped = [], []
    nc = norm(content)
    for f in findings:
        if f["verdict"] == "unverified":
            ok = norm(f["quote"]) in nc
        else:
            ev = registry.get(f["rule_ref"])
            ok = bool(ev) and bool(norm(f["evidence_quote"])) and norm(f["evidence_quote"]) in norm(ev)
            if ok and f["origin"] != "image" and f["quote"]:
                ok = norm(f["quote"]) in nc
        (kept if ok else dropped).append(f)
    return kept, dropped
