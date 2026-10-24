"""Optional AI layer. Works only when ANTHROPIC_API_KEY is set. Every AI finding
still has to pass the verifier before a person sees it."""
import json
import os
import re
import httpx

MODEL = os.getenv("LLM_MODEL", "claude-sonnet-5-5")


def enabled() -> bool:
    return bool(os.getenv("ANTHROPIC_API_KEY"))


def _call(system: str, user: str, max_tokens: int = 1200) -> str:
    r = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={"x-api-key": os.environ["ANTHROPIC_API_KEY"],
                 "anthropic-version": "2023-06-01", "content-type": "application/json"},
        json={"model": MODEL, "max_tokens": max_tokens, "system": system,
              "messages": [{"role": "user", "content": user}]},
        timeout=45)
    r.raise_for_status()
    return "".join(b.get("text", "") for b in r.json()["content"] if b.get("type") == "text")


def parse_json(text: str) -> dict:
    text = re.sub(r"```(?:json)?", "", text)
    i, j = text.find("{"), text.rfind("}")
    return json.loads(text[i:j + 1])


JUDGE_SYSTEM = (
    "You are a brand reviewer. Use ONLY the guideline excerpts provided. Report only tone or "
    "messaging problems that an excerpt clearly forbids. Never invent a rule. "
    'Return JSON only: {"findings":[{"category":"tone|messaging","draft_quote":"exact text copied from the draft",'
    '"evidence_ref":"id of the excerpt","evidence_quote":"exact words copied from that excerpt",'
    '"explanation":"one sentence","suggestion":"replacement text for draft_quote, or empty"}]}. '
    'If there are no problems return {"findings":[]}.')


def judge(content: str, chunks, known_quotes) -> list:
    excerpts = "\n\n".join(f"[{ref}] {text}" for ref, _, text in chunks)
    user = (f"DRAFT:\n{content}\n\nGUIDELINE EXCERPTS:\n{excerpts}\n\n"
            f"ALREADY REPORTED (do not repeat): {json.dumps(known_quotes)}")
    return parse_json(_call(JUDGE_SYSTEM, user)).get("findings", [])


REWRITE_SYSTEM = (
    "You edit marketing copy so it follows brand rules. Keep the writer's intent, meaning and "
    "structure. Fix only the listed issues. Do not add new claims, numbers or promises. "
    "Return only the rewritten text.")


def rewrite(content: str, intent: str, issues: list) -> str:
    lines = "\n".join(f'- "{i["quote"]}": {i["explanation"]}' for i in issues)
    user = f"INTENT: {intent or 'not stated'}\n\nISSUES:\n{lines}\n\nTEXT:\n{content}"
    return _call(REWRITE_SYSTEM, user, 1500).strip()
