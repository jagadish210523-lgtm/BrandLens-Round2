import re

_SENT = re.compile(r"(?:[^.!?\n]|\.(?=\d))+(?:[.!?]+|(?=\n)|$)")


def sentences(text: str):
    """Return (start, end, sentence) for every sentence in the text."""
    out = []
    for m in _SENT.finditer(text):
        s = m.group(0)
        if s.strip():
            out.append((m.start(), m.end(), s))
    return out


def paragraphs(body: str):
    return [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
