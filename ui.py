import difflib
import re
from pathlib import Path
from fastapi import Request
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))


def highlight(content, findings):
    spans, low = [], content.lower()
    for f in findings:
        q = (f.quote or "").strip()
        if not q or f.status != "open" or f.verdict == "supported":
            continue
        i = low.find(q.lower())
        if i >= 0:
            spans.append((i, i + len(q), f))
    spans.sort(key=lambda x: (x[0], -(x[1] - x[0])))
    out, pos = [], 0
    for a, b, f in spans:
        if a < pos:
            continue
        out.append(escape(content[pos:a]))
        out.append(Markup('<mark class="m-%s" data-f="%s" title="%s">') % (f.severity, f.id, f.explanation))
        out.append(escape(content[a:b]))
        out.append(Markup("</mark>"))
        pos = b
    out.append(escape(content[pos:]))
    return Markup("").join(out)


def word_diff(a, b):
    aw, bw = re.findall(r"\s+|\S+", a), re.findall(r"\s+|\S+", b)
    out = []
    for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, aw, bw).get_opcodes():
        if op == "equal":
            out.append(escape("".join(aw[i1:i2])))
        else:
            if i2 > i1:
                out.append(Markup('<del>%s</del>') % "".join(aw[i1:i2]))
            if j2 > j1:
                out.append(Markup('<ins>%s</ins>') % "".join(bw[j1:j2]))
    return Markup("").join(out)


templates.env.globals["css"] = (BASE / "static" / "style.css").read_text()
templates.env.filters["highlight"] = highlight
templates.env.filters["dt"] = lambda d: d.strftime("%d %b %Y, %H:%M") if d else ""
templates.env.filters["d"] = lambda d: d.strftime("%d %b %Y") if d else ""


def render(request: Request, name: str, user=None, **ctx):
    flash = request.session.pop("flash", None)
    ctx.update(user=user, flash=flash, path=request.url.path)
    return templates.TemplateResponse(request, name, ctx)


def flash(request: Request, kind: str, msg: str):
    request.session["flash"] = [kind, msg]
