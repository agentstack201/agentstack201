"""Builds assets/hero.svg — the profile banner.

Two colours only — ink black and the sand of the avatar — and IBM Plex for all
text. Text is shaped with HarfBuzz and converted to vector outlines, so Arabic
and Latin render identically on every device (GitHub serves README images
without web fonts) and the Arabic can be "written" right-to-left.

    pip install fonttools uharfbuzz
    python scripts/build_assets.py            # fonts are downloaded to .cache/
"""
import functools
import math
import urllib.request
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

INK, SAND = "#000000", "#E2C3A7"
ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / ".cache"
ASSETS = ROOT / "assets"

GOOGLE_FONTS = "https://raw.githubusercontent.com/google/fonts/main/ofl"
FONT_FILES = {
    ("sans", "regular"): "ibmplexsansarabic/IBMPlexSansArabic-Regular.ttf",
    ("sans", "semibold"): "ibmplexsansarabic/IBMPlexSansArabic-SemiBold.ttf",
    ("sans", "bold"): "ibmplexsansarabic/IBMPlexSansArabic-Bold.ttf",
    ("mono", "regular"): "ibmplexmono/IBMPlexMono-Regular.ttf",
    ("mono", "semibold"): "ibmplexmono/IBMPlexMono-SemiBold.ttf",
}
EASE = "cubic-bezier(.2,.7,.2,1)"


def fetch(url, dest):
    if not dest.exists():
        dest.parent.mkdir(parents=True, exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "build-assets"})
        dest.write_bytes(urllib.request.urlopen(req, timeout=60).read())
    return dest


# ── text → outlines ─────────────────────────────────────────────────────────

class Font:
    def __init__(self, path):
        self.hb = hb.Font(hb.Face(path.read_bytes()))
        tt = TTFont(path)
        self.order, self.glyphs, self.upem = tt.getGlyphOrder(), tt.getGlyphSet(), tt["head"].unitsPerEm


@functools.lru_cache(None)
def font(family, weight):
    # Plex Mono has no Arabic; Arabic runs inside mono text fall back to Plex Sans Arabic.
    rel = FONT_FILES[(family, weight)]
    return Font(fetch(f"{GOOGLE_FONTS}/{rel}", CACHE / "fonts" / Path(rel).name))


def is_arabic(ch):
    o = ord(ch)
    return 0x0600 <= o <= 0x06FF or 0x0750 <= o <= 0x077F or 0x08A0 <= o <= 0x08FF or 0xFB50 <= o <= 0xFEFF


def bidi_runs(text, rtl):
    """Split into Arabic / Latin runs; neutrals follow their neighbours (a small UBA)."""
    strong = ["ar" if is_arabic(c) else "lat" if c.isalnum() else None for c in text]
    base = "ar" if rtl else "lat"
    kinds, i = list(strong), 0
    while i < len(text):
        if kinds[i] is None:
            j = i
            while j < len(text) and strong[j] is None:
                j += 1
            prev = kinds[i - 1] if i else base
            nxt = strong[j] if j < len(text) else base
            for k in range(i, j):
                kinds[k] = prev if prev == nxt else base
            i = j
        else:
            i += 1
    runs = []
    for ch, kind in zip(text, kinds):
        if runs and runs[-1][1] == kind:
            runs[-1][0] += ch
        else:
            runs.append([ch, kind])
    return runs


def layout(text, size, x=0, y=0, family="sans", weight="regular", anchor="start", spacing=0, rtl=None):
    """Return ([(x, d), ...] one outline per glyph, advance width)."""
    if rtl is None:
        first = next((c for c in text if c.isalpha()), "a")
        rtl = is_arabic(first)
    shaped = []
    for chunk, kind in bidi_runs(text, rtl):
        f = font("sans", weight) if kind == "ar" else font(family, weight)
        buf = hb.Buffer()
        buf.add_str(chunk)
        buf.guess_segment_properties()
        buf.direction = "rtl" if kind == "ar" else "ltr"
        hb.shape(f.hb, buf, {"kern": True, "liga": True})
        scale = size / f.upem
        glyphs, adv = [], 0.0
        for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
            if info.codepoint == 0:
                raise ValueError(f"missing glyph in {text!r}")
            glyphs.append((adv + pos.x_offset * scale, -pos.y_offset * scale, f.order[info.codepoint], f))
            adv += pos.x_advance * scale + (spacing if kind == "lat" else 0)
        shaped.append((glyphs, adv, scale))
    if rtl:
        shaped.reverse()
    width = sum(a for _, a, _ in shaped) - (spacing if text and not rtl else 0)
    cur = x - width * {"start": 0, "middle": 0.5, "end": 1}[anchor]
    out = []
    for glyphs, adv, scale in shaped:
        for gx, gy, name, f in glyphs:
            pen = SVGPathPen(f.glyphs, ntos=lambda v: f"{v:.1f}".rstrip("0").rstrip("."))
            f.glyphs[name].draw(TransformPen(pen, (scale, 0, 0, -scale, cur + gx, y + gy)))
            d = pen.getCommands()
            if d:
                out.append((cur + gx, d))
        cur += adv
    return out, width


def measure(text, size, **kw):
    return layout(text, size, **kw)[1]


def text(s, size, x, y, attrs="", **kw):
    glyphs, _ = layout(s, size, x, y, **kw)
    return f'<path {attrs} d="{"".join(d for _, d in glyphs)}"/>' if glyphs else ""


def compose(parts, x, y, anchor="start"):
    """Lay several differently styled pieces on one LTR line: [(text, size, attrs, kw)]."""
    widths = [measure(t, s, **kw) for t, s, _, kw in parts]
    cur = x - sum(widths) * {"start": 0, "middle": 0.5, "end": 1}[anchor]
    out = []
    for (t, s, attrs, kw), w in zip(parts, widths):
        out.append(text(t, s, cur, y, attrs, **kw))
        cur += w
    return "".join(out)


# ── shared pieces ───────────────────────────────────────────────────────────

def star(cx, cy, r):
    """Eight-pointed star (khatim / rub el hizb)."""
    pts = []
    for i in range(16):
        rad = r if i % 2 == 0 else r * 0.7654
        a = math.pi / 8 * i - math.pi / 2
        pts.append(f"{cx + rad * math.cos(a):.2f},{cy + rad * math.sin(a):.2f}")
    return "M" + " L".join(pts) + " Z"


def svg(w, h, label, body, style=""):
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w} {h}" width="{w}" height="{h}" '
            f'role="img" aria-label="{label.replace("&", "&amp;")}">\n'
            f'<style>{style}\n@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} }}'
            f'</style>\n{body}\n</svg>\n')



# ── hero ────────────────────────────────────────────────────────────────────

TYPED = [
    "I turn ideas into systems, and systems into products",
    "Multi-agent systems · LLM orchestration · Full-stack web",
    "Arabic roots, global standards",
]


def build_hero():
    W, H, cx = 1200, 470, 600
    salam, _ = layout("سَلَامٌ عَلَيْكُمْ", 30, cx, 74, anchor="middle")
    name, _ = layout("أحمد هشام", 112, cx, 212, weight="bold", anchor="middle")

    def pen(glyphs, cls, start, step):
        ordered = sorted(glyphs, key=lambda g: -g[0])  # right-to-left, as Arabic is written
        return "\n".join(f'<path class="{cls}" pathLength="1" style="animation-delay:{start + i * step:.2f}s" d="{d}"/>'
                         for i, (_, d) in enumerate(ordered))

    # Typed lines: each revealed left-to-right by a growing clip, with a caret.
    cycle, begin = 4.5 * len(TYPED), 5.0
    typed = []
    for i, line in enumerate(TYPED):
        w = measure(line, 21, family="mono")
        x0 = cx - w / 2
        a, b = i / len(TYPED), (i + 1) / len(TYPED)
        k = lambda f: f"{a + (b - a) * f:.4f}"
        kt = f"0;{a:.4f};{k(.4)};{k(.82)};{k(.95)};{b:.4f};1" if 0 < a else f"0;{k(.4)};{k(.82)};{k(.95)};{b:.4f};1"
        wv = f"0;0;{w:.1f};{w:.1f};0;0;0" if 0 < a else f"0;{w:.1f};{w:.1f};0;0;0"
        if b == 1:
            kt, wv = kt.rsplit(";", 1)[0], wv.rsplit(";", 1)[0]
        typed.append(
            f'<clipPath id="ty{i}"><rect x="{x0:.1f}" y="404" height="34" width="0">'
            f'<animate attributeName="width" values="{wv}" keyTimes="{kt}" dur="{cycle}s" begin="{begin}s" repeatCount="indefinite"/>'
            f'</rect></clipPath>'
            f'<g clip-path="url(#ty{i})">{text(line, 21, x0, 428, f"fill=\"{SAND}\"", family="mono")}</g>'
            f'<rect x="{x0:.1f}" y="410" width="2" height="22" fill="{SAND}" opacity="0">'
            f'<animate attributeName="x" values="{";".join(str(round(x0 + float(v), 1)) for v in wv.split(";"))}" keyTimes="{kt}" dur="{cycle}s" begin="{begin}s" repeatCount="indefinite"/>'
            f'<animate attributeName="opacity" values="{";".join("1" if a <= float(t) < b else "0" for t in kt.split(";"))}" keyTimes="{kt}" calcMode="discrete" dur="{cycle}s" begin="{begin}s" repeatCount="indefinite"/>'
            f'</rect>')

    tagline = compose([
        ("From the language that gave the world ", 20, f'fill="{SAND}" fill-opacity=".7"', {}),
        ("Algorithm", 20, f'fill="{SAND}"', {"weight": "bold"}),
        (" & ", 20, f'fill="{SAND}" fill-opacity=".7"', {}),
        ("Algebra", 20, f'fill="{SAND}"', {"weight": "bold"}),
        (" — building AI agents & web systems", 20, f'fill="{SAND}" fill-opacity=".7"', {}),
    ], cx, 352, "middle")

    body = f'''<defs>
  <radialGradient id="fade" cx=".5" cy=".42" r=".62">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".5" stop-color="#fff" stop-opacity=".3"/><stop offset="1" stop-color="#fff" stop-opacity="1"/>
  </radialGradient>
  <mask id="edges"><rect width="{W}" height="{H}" fill="url(#fade)"/></mask>
  <pattern id="girih" width="80" height="80" patternUnits="userSpaceOnUse">
    <path d="{star(40, 40, 28)}" fill="none" stroke="{SAND}" stroke-width="1"/>
    <path d="M0 0 L12 12 M80 0 L68 12 M0 80 L12 68 M80 80 L68 68" stroke="{SAND}" stroke-width="1"/>
    <circle cx="40" cy="40" r="5" fill="none" stroke="{SAND}" stroke-width=".8"/>
  </pattern>
</defs>
<rect width="{W}" height="{H}" fill="{INK}"/>
<rect class="pattern" width="{W}" height="{H}" fill="url(#girih)" mask="url(#edges)"/>
<path class="khatim" pathLength="1" d="{star(cx, 180, 158)}"/>
<path class="khatim k2" pathLength="1" d="{star(cx, 180, 134)}"/>
<g>{pen(salam, "salam", .3, .1)}</g>
<g>{pen(name, "ink", 1.1, .2)}</g>
<line class="rule" x1="430" y1="256" x2="770" y2="256"/>
<g class="en name">{text("AHMAD HISHAM", 28, cx, 302, f'fill="{SAND}"', family="mono", weight="semibold", anchor="middle", spacing=13)}</g>
<g class="en tag">{tagline}</g>
<g class="en typed">{"".join(typed)}</g>'''

    style = f'''
.pattern {{ opacity: 0; animation: fade 2.5s ease-out .2s forwards; }}
.khatim {{ fill: none; stroke: {SAND}; stroke-width: 1.3; stroke-dasharray: 1; stroke-dashoffset: 1; opacity: .3;
  transform-origin: {cx}px 180px; animation: draw 3s ease-in-out forwards, spin 100s linear 3s infinite; }}
.k2 {{ opacity: .18; animation-duration: 3.4s, 130s; animation-direction: normal, reverse; }}
.ink, .salam {{ fill: {SAND}; fill-opacity: 0; stroke: {SAND}; stroke-width: 1.4; stroke-dasharray: 1; stroke-dashoffset: 1;
  animation: draw .9s ease-in-out forwards, ink .8s ease-out forwards; }}
.salam {{ stroke-width: .8; animation-duration: .6s, .6s; }}
.en {{ opacity: 0; animation: rise 1.2s {EASE} forwards; }}
.name {{ animation-delay: 3.4s; }} .tag {{ animation-delay: 4s; }} .typed {{ animation-delay: 4.6s; }}
.rule {{ stroke: {SAND}; stroke-opacity: .6; stroke-width: 1; transform-origin: {cx}px 0; transform: scaleX(0); animation: grow 1.4s ease-out 3.2s forwards; }}
@keyframes draw {{ to {{ stroke-dashoffset: 0; }} }}
@keyframes ink {{ to {{ fill-opacity: 1; stroke-width: .2; }} }}
@keyframes fade {{ to {{ opacity: .1; }} }}
@keyframes spin {{ to {{ transform: rotate(360deg); }} }}
@keyframes rise {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
@keyframes grow {{ to {{ transform: scaleX(1); }} }}
@media (prefers-reduced-motion: reduce) {{ .pattern {{ opacity: .1; }} .khatim {{ stroke-dashoffset: 0; }}
  .ink, .salam {{ fill-opacity: 1; stroke-dashoffset: 0; }} .en {{ opacity: 1; }} .rule {{ transform: none; }} }}'''
    return svg(W, H, "سلام عليكم — Ahmad Hisham | أحمد هشام", body, style)


def main():
    out = ASSETS / "hero.svg"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_hero(), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
