"""Image creative checks: alt text and brand palette."""
import io
from PIL import Image
from .rules import finding

ALT_RULE = "Every image must have meaningful alt text that describes what it shows."
GENERIC_ALT = {"image", "picture", "photo", "banner", "graphic", "img", "creative"}


def palette_rule(palette: str) -> str:
    return f"Images must mainly use the approved brand colours: {palette}."


def registry(palette: str) -> dict:
    return {"image:alt": ALT_RULE, "image:palette": palette_rule(palette)}


def _hex(h: str):
    h = h.strip().lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def check(data: bytes | None, alt_text: str, palette: str):
    out = []
    alt = (alt_text or "").strip()
    if len(alt) < 12 or alt.lower() in GENERIC_ALT:
        out.append(finding(
            "accessibility", "medium", "violation", "image:alt", "Image needs meaningful alt text",
            "", ALT_RULE, "Accessibility guidelines",
            "Screen-reader users cannot tell what this image shows. Describe the image in a full phrase.",
            None, "image"))
    if data:
        try:
            img = Image.open(io.BytesIO(data)).convert("RGB").resize((80, 80))
            colours = [_hex(c) for c in palette.split(",") if c.strip()]
            near = 0
            for px in img.getdata():
                if min(sum((a - b) ** 2 for a, b in zip(px, c)) ** 0.5 for c in colours) <= 70:
                    near += 1
            share = near / (80 * 80)
            if share < 0.35:
                out.append(finding(
                    "visual", "medium", "violation", "image:palette", "Image is off-palette",
                    "", palette_rule(palette), "Visual identity guide",
                    f"Only {share:.0%} of this image uses approved brand colours (at least 35% expected).",
                    None, "image"))
        except Exception:
            pass
    return out
