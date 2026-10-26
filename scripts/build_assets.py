"""Builds every README graphic in assets/ from code.

Two colours only — ink black and the sand of the avatar — and IBM Plex for all
text. Text is shaped with HarfBuzz and converted to vector outlines, so Arabic
and Latin render identically on every device (GitHub serves README images
without web fonts) and the Arabic can be "written" right-to-left.

    pip install fonttools uharfbuzz
    python scripts/build_assets.py            # fonts and icons are downloaded to .cache/
"""
import functools
import math
import re
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


def wrap(s, size, max_width, **kw):
    lines, line = [], ""
    for word in s.split():
        trial = f"{line} {word}".strip()
        if line and measure(trial, size, **kw) > max_width:
            lines.append(line)
            line = word
        else:
            line = trial
    return lines + [line] if line else lines


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
            f'<style>{style}\n@media (prefers-reduced-motion: reduce) {{ * {{ animation: none !important; }} '
            f'.reveal {{ opacity: 1 !important; transform: none !important; }} }}</style>\n{body}\n</svg>\n')


REVEAL = f"""
.reveal {{ opacity: 0; animation: rise .7s {EASE} forwards; }}
@keyframes rise {{ from {{ opacity: 0; transform: translateY(8px); }} to {{ opacity: 1; transform: none; }} }}"""


def panel(w, h, r=16):
    return f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="{r}" fill="{INK}" stroke="{SAND}" stroke-opacity=".35" stroke-width="1.5"/>'


def pill(x, y, label, filled=False, size=11, pad=12, h=26, anchor="start"):
    w = measure(label, size, family="mono", weight="semibold", spacing=1) + pad * 2
    if anchor == "end":
        x -= w
    elif anchor == "middle":
        x -= w / 2
    fill, ink = (SAND, INK) if filled else (INK, SAND)
    stroke = "" if filled else f'stroke="{SAND}" stroke-opacity=".6"'
    return (f'<rect x="{x:.1f}" y="{y}" width="{w:.1f}" height="{h}" rx="{h / 2}" fill="{fill}" {stroke}/>'
            + text(label, size, x + w / 2, y + h / 2 + size * 0.36, f'fill="{ink}"', family="mono",
                   weight="semibold", anchor="middle", spacing=1)), w


def pills(labels, cx, y, gap=10, **kw):
    widths = [pill(0, 0, l, **kw)[1] for l in labels]
    x = cx - (sum(widths) + gap * (len(labels) - 1)) / 2
    out = []
    for label, w in zip(labels, widths):
        out.append(pill(x, y, label, **kw)[0])
        x += w + gap
    return "".join(out)


def bilingual(en, ar, cx, y, size_en, size_ar, ink, star_r=7):
    """`ENGLISH ✦ عربي` centred on cx."""
    return (text(en, size_en, cx - star_r - 14, y, f'fill="{ink}"', family="mono", weight="semibold",
                 anchor="end", spacing=2)
            + f'<path d="{star(cx, y - size_en * 0.36, star_r)}" fill="{ink}"/>'
            + text(ar, size_ar, cx + star_r + 14, y + 1, f'fill="{ink}"', weight="semibold"))


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


# ── section headers ─────────────────────────────────────────────────────────

SECTIONS = {
    "whoami": ("WHO AM I", "نبذة عنّي"),
    "status": ("STATUS & CURRENT WORK", "الحالة والعمل الحالي"),
    "stack": ("TECH STACK", "الأدوات"),
    "projects": ("FEATURED PROJECTS", "مشاريع مختارة"),
    "words": ("WORDS THE WORLD BORROWED", "هل تعلم؟"),
    "stats": ("GITHUB IN NUMBERS", "بالأرقام"),
    "snake": ("CONTRIBUTION SNAKE", "المساهمات"),
}


def build_section(en, ar):
    W, H = 840, 60
    body = (panel(W, H, 14)
            + f'<rect class="sweep" x="-200" y="2" width="200" height="{H - 4}" fill="url(#sw)"/>'
            + bilingual(en, ar, W / 2, 37, 17, 22, SAND, 8))
    defs = (f'<defs><linearGradient id="sw" x1="0" x2="1"><stop offset="0" stop-color="{SAND}" stop-opacity="0"/>'
            f'<stop offset=".5" stop-color="{SAND}" stop-opacity=".12"/><stop offset="1" stop-color="{SAND}" stop-opacity="0"/></linearGradient>'
            f'<clipPath id="c"><rect width="{W}" height="{H}" rx="14"/></clipPath></defs>')
    body = defs + body.replace('<rect class="sweep"', '<rect clip-path="url(#c)" class="sweep"')
    style = f".sweep {{ animation: sweep 6s ease-in-out infinite; }} @keyframes sweep {{ to {{ transform: translateX({W + 200}px); }} }}"
    return svg(W, H, f"{en} · {ar}", body, style)


# ── tech stack ──────────────────────────────────────────────────────────────

STACK = {
    "languages": ("LANGUAGES", "اللغات", [
        ("typescript", "TypeScript"), ("javascript", "JavaScript"), ("python", "Python"), ("html5", "HTML"),
        ("css", "CSS"), ("cplusplus", "C++"), ("gnubash", "Bash")], []),
    "frontend": ("FRONTEND", "الواجهات", [
        ("nextdotjs", "Next.js"), ("react", "React"), ("vite", "Vite"), ("tailwindcss", "Tailwind")],
        ["RTL & ARABIC UI", "PWA · OFFLINE-FIRST", "RESPONSIVE"]),
    "backend": ("BACKEND & DATA", "الخوادم والبيانات", [
        ("nodedotjs", "Node.js"), ("express", "Express"), ("postgresql", "PostgreSQL"), ("prisma", "Prisma"),
        ("supabase", "Supabase"), ("neon", "Neon"), ("zod", "Zod")],
        ["REST APIS", "AUTH & RLS", "REALTIME"]),
    "ai": ("AI & AGENTS", "الذكاء الاصطناعي", [
        ("claude", "Claude"), ("googlegemini", "Gemini"), ("openrouter", "OpenRouter"), ("deepseek", "DeepSeek")],
        ["MULTI-AGENT SYSTEMS", "LLM ORCHESTRATION", "TOOL CALLING", "PROMPT ENGINEERING"]),
    "cloud": ("CLOUD, DEVOPS & QUALITY", "السحابة والجودة", [
        ("docker", "Docker"), ("vercel", "Vercel"), ("render", "Render"), ("githubactions", "Actions"),
        ("git", "Git"), ("linux", "Linux"), ("vitest", "Vitest")],
        ["PLAYWRIGHT E2E", "TYPESCRIPT STRICT", "WEB SECURITY"]),
}


def icon_path(slug):
    src = fetch(f"https://cdn.simpleicons.org/{slug}", CACHE / "icons" / f"{slug}.svg").read_text()
    return re.search(r'<path[^>]* d="([^"]+)"', src).group(1)


def build_stack(en, ar, icons, chips):
    W, tile, gap = 840, 56, 104
    H = 208 if chips else 166
    body = [panel(W, H),
            f'<rect x="14" y="14" width="{W - 28}" height="44" rx="10" fill="{SAND}"/>',
            bilingual(en, ar, W / 2, 42, 15, 19, INK, 7)]
    x0 = W / 2 - gap * (len(icons) - 1) / 2
    for i, (slug, label) in enumerate(icons):
        cx = x0 + gap * i
        body.append(
            f'<g class="reveal" style="animation-delay:{.15 + i * .08:.2f}s">'
            f'<rect x="{cx - tile / 2}" y="74" width="{tile}" height="{tile}" rx="14" fill="{INK}" stroke="{SAND}" stroke-opacity=".45" stroke-width="1.5"/>'
            f'<path transform="translate({cx - 15} 87) scale(1.25)" fill="{SAND}" d="{icon_path(slug)}"/>'
            + text(label, 12, cx, 150, f'fill="{SAND}" fill-opacity=".8"', family="mono", anchor="middle") + "</g>")
    if chips:
        body.append(f'<g class="reveal" style="animation-delay:.7s">{pills(chips, W / 2, 166)}</g>')
    return svg(W, H, f"{en.title()} · {ar}: " + ", ".join(l for _, l in icons), "".join(body), REVEAL)


# ── cards ───────────────────────────────────────────────────────────────────

def build_heritage():
    W, H = 1200, 262
    lines = [
        [("Twelve centuries ago, a scholar in Baghdad's House of Wisdom wrote a book on calculation in Arabic.", {})],
        [("His name, ", {}), ("al-Khwārizmī", {"weight": "bold"}), (", became the word ", {}), ("algorithm", {"weight": "bold"}),
         ("; his book's title, ", {}), ("al-jabr", {"weight": "bold"}), (", became ", {}), ("algebra", {"weight": "bold"}), (".", {})],
        [("I'm simply trying to keep that thread going — one well-built system at a time.", {})],
    ]
    body = [panel(W, H),
            f'<g class="reveal">{bilingual("HERITAGE & PHILOSOPHY", "إرثٌ ورسالة", W / 2, 48, 13, 17, SAND, 6)}</g>',
            f'<g class="reveal" style="animation-delay:.25s">'
            + text("« نبني بإتقان، ونتعلّم بشغف، ونسعى أن يترك كلُّ سطرٍ نكتبه أثرًا ينفع الناس »", 27, W / 2, 112,
                   f'fill="{SAND}"', weight="semibold", anchor="middle") + "</g>"]
    for i, parts in enumerate(lines):
        styled = [(t, 19, f'fill="{SAND}" fill-opacity="{1 if kw else .72}"', kw) for t, kw in parts]
        body.append(f'<g class="reveal" style="animation-delay:{.5 + i * .15:.2f}s">{compose(styled, W / 2, 164 + i * 30, "middle")}</g>')
    return svg(W, H, "Heritage & philosophy · إرث ورسالة", "".join(body), REVEAL)


CODE = '''class AhmadHisham:
    """Arabic roots, modern stack."""

    def __init__(self):
        self.name      = {"en": "Ahmad Hisham", "ar": "أحمد هشام"}
        self.username  = "@agentstack201"
        self.role      = "Full-Stack Developer & AI Systems Architect"
        self.languages = {
            "Arabic":  "Native — لغة الضاد",
            "English": "Professional",
        }
        self.passion   = {
            "en": "Turning ideas into systems, and systems into products",
            "ar": "تحويل الأفكار إلى أنظمة ذكية تخدم الإنسان",
        }
        self.skills = {
            "ai_agents":  ["Multi-Agent Systems", "LLM Orchestration", "Claude", "Gemini"],
            "full_stack": ["Next.js", "React", "Node.js", "TypeScript", "Python"],
            "cloud_data": ["PostgreSQL", "Prisma", "Supabase", "Docker", "Vercel"],
        }

    def say_welcome(self, guest: str = "friend") -> str:
        # In Arab hospitality, coffee comes before conversation.
        coffee = "قهوة عربية بالهيل"  # Arabic coffee with cardamom
        return "\\n".join([
            f"{coffee} — أهلاً وسهلاً",
            f"Welcome, {guest}! Coffee's on me — let's build something meaningful.",
        ])


print(AhmadHisham().say_welcome())'''

KEYWORDS = r"\b(class|def|return|print|self|str)\b"


def code_tokens(line):
    """Two-colour highlighting: comments dim, strings mid, keywords bold."""
    out, i = [], 0
    pattern = re.compile(r'(#.*$)|((?:f)?"(?:[^"\\]|\\.)*")|' + KEYWORDS)
    for m in pattern.finditer(line):
        if m.start() > i:
            out.append((line[i:m.start()], 1, "regular"))
        if m.group(1):
            out.append((m.group(1), .45, "regular"))
        elif m.group(2):
            out.append((m.group(2), .72, "regular"))
        else:
            out.append((m.group(0), 1, "semibold"))
        i = m.end()
    if i < len(line):
        out.append((line[i:], 1, "regular"))
    return out


def build_code():
    lines = CODE.split("\n")
    W, lh, top = 1000, 23, 78
    H = top + lh * len(lines) + 34
    body = [panel(W, H),
            f'<line x1="1" y1="50" x2="{W - 1}" y2="50" stroke="{SAND}" stroke-opacity=".25"/>']
    for i in range(3):
        body.append(f'<circle cx="{30 + i * 22}" cy="26" r="6" fill="{SAND if i == 0 else INK}" stroke="{SAND}" stroke-opacity=".7"/>')
    body.append(text("ahmad_hisham.py", 13, W / 2, 31, f'fill="{SAND}" fill-opacity=".6"', family="mono", anchor="middle"))
    for n, line in enumerate(lines):
        y = top + n * lh
        row = [text(f"{n + 1:>2}", 13, 46, y, f'fill="{SAND}" fill-opacity=".28"', family="mono", anchor="end")]
        x = 70
        for chunk, op, weight in code_tokens(line):
            glyphs, w = layout(chunk, 14.5, x, y, family="mono", weight=weight, rtl=False)
            if glyphs:
                row.append(f'<path fill="{SAND}" fill-opacity="{op}" d="{"".join(d for _, d in glyphs)}"/>')
            x += w
        body.append(f'<g class="reveal" style="animation-delay:{.2 + n * .045:.2f}s">{"".join(row)}</g>')
    return svg(W, H, "class AhmadHisham — Python profile", "".join(body), REVEAL)


def card_row(x, y, w, en_title, ar, chip=None, filled=False):
    out = text(en_title, 15, x, y, f'fill="{SAND}"', weight="semibold", rtl=False)
    if ar:
        out += text(ar, 15, x + w, y, f'fill="{SAND}" fill-opacity=".62"', anchor="end")
    if chip:
        out += pill(x + w, y - 18, chip, filled=filled, size=10, pad=10, h=24, anchor="end")[0]
    return out


def build_status():
    W, H, half = 840, 290, 410
    body = [panel(half, H), f'<g transform="translate({W - half} 0)">{panel(half, H)}</g>']
    # Open for
    body.append(text("OPEN FOR", 13, 28, 44, f'fill="{SAND}"', family="mono", weight="semibold", spacing=2)
                + text("منفتح على", 17, half - 28, 45, f'fill="{SAND}"', weight="semibold", anchor="end"))
    body.append(pill(28, 66, "AVAILABLE · متاح", filled=True)[0])
    rows = [("AI agent projects", "الوكلاء الذكية"), ("Full-stack products", "منتجات متكاملة"),
            ("Open source", "مفتوح المصدر"), ("Arabic-first software", "برمجيات عربية")]
    for i, (en, ar) in enumerate(rows):
        y = 140 + i * 38
        body.append(f'<g class="reveal" style="animation-delay:{.2 + i * .1:.2f}s"><path d="{star(34, y - 5, 5)}" fill="{SAND}"/>'
                    + card_row(50, y, half - 78, en, ar) + "</g>")
    # Currently building
    ox = W - half
    body.append(text("CURRENTLY BUILDING", 13, ox + 28, 44, f'fill="{SAND}"', family="mono", weight="semibold", spacing=2)
                + text("أعمل حاليًا على", 17, ox + half - 28, 45, f'fill="{SAND}"', weight="semibold", anchor="end"))
    builds = [("HISN · حِصن", "WEB SECURITY"), ("Multi-agent workflows", "AI AGENTS"),
              ("Nabd Hospital · نبض", "HEALTHCARE"), ("Tilawa · تلاوة", "OFFLINE PWA")]
    for i, (name, chip) in enumerate(builds):
        y = 100 + i * 46
        body.append(f'<g class="reveal" style="animation-delay:{.3 + i * .1:.2f}s">'
                    f'<line x1="{ox + 28}" y1="{y + 18}" x2="{ox + half - 28}" y2="{y + 18}" stroke="{SAND}" stroke-opacity=".12"/>'
                    + card_row(ox + 28, y, half - 56, name, None, chip, filled=(i == 0)) + "</g>")
    return svg(W, H, "Status: available — currently building HISN, multi-agent workflows, Nabd Hospital, Tilawa", "".join(body), REVEAL)


PROJECTS = {
    "hisn": ("HISN · حِصن", "WEB SECURITY · DIPLOMA PROJECT",
             "Web-app security assessment platform. Checks TLS, security headers, cookie flags and common "
             "misconfigurations — and shows the evidence behind every finding. Non-intrusive by design.",
             ["NEXT.JS 15", "TYPESCRIPT", "SUPABASE"]),
    "nabd": ("Nabd Hospital · نبض", "HEALTHCARE · GRADUATION PROJECT",
             "Hospital platform with an Arabic RTL site, three-step appointment booking with double-booking "
             "blocked at the database level, a patient portal and an admin dashboard.",
             ["NEXT.JS 15", "PRISMA", "POSTGRESQL"]),
    "tilawa": ("Tilawa · تلاوة", "QURAN · OFFLINE-FIRST PWA",
               "An elegant Quran reader: the full Mus'haf in Uthmani script, instant search that ignores "
               "diacritics, tafsir, recitation audio, bookmarks and night mode.",
               ["TYPESCRIPT", "PWA", "OFFLINE"]),
    "raseed": ("Raseed · رصيد", "PERSONAL FINANCE · ARABIC",
               "Arabic personal budgeting and savings app. Your data never leaves your browser — "
               "privacy by design.",
               ["TYPESCRIPT", "LOCAL-FIRST"]),
}


def build_project(title, tag, desc, chips):
    W, H = 410, 252
    body = [panel(W, H),
            text(title, 22, 26, 50, f'fill="{SAND}"', weight="bold", rtl=False),
            f'<path d="M{W - 40} 34 L{W - 28} 22 M{W - 38} 22 L{W - 28} 22 L{W - 28} 32" fill="none" stroke="{SAND}" stroke-width="2" stroke-linecap="round"/>',
            text(tag, 10.5, 26, 74, f'fill="{SAND}" fill-opacity=".55"', family="mono", weight="semibold", spacing=1.5)]
    for i, line in enumerate(wrap(desc, 14, W - 52)):
        body.append(text(line, 14, 26, 106 + i * 22, f'fill="{SAND}" fill-opacity=".82"'))
    x = 26
    for chip in chips:
        p, w = pill(x, H - 46, chip, size=10, pad=10, h=24)
        body.append(p)
        x += w + 8
    return svg(W, H, f"{title} — {desc}", f'<g class="reveal">{"".join(body)}</g>', REVEAL)


WORDS = [
    ("Algorithm", "الخوارزمي", "From Algoritmi, the Latin form of al-Khwārizmī's name"),
    ("Algebra", "الجَبْر", "From the title of his 9th-century book al-Jabr wa'l-Muqābala"),
    ("Zero · Cipher", "صِفْر", "sifr — \"empty\": the digit that made positional numbers work"),
    ("Coffee", "قَهْوَة", "qahwa — which is why say_welcome() serves it"),
]


def build_words():
    W, row, top = 840, 76, 30
    H = top + row * len(WORDS) + 14
    body = [panel(W, H)]
    for i, (en, ar, story) in enumerate(WORDS):
        y = top + i * row
        sep = f'<line x1="28" y1="{y + row - 4}" x2="{W - 28}" y2="{y + row - 4}" stroke="{SAND}" stroke-opacity=".12"/>' if i < len(WORDS) - 1 else ""
        body.append(
            f'<g class="reveal" style="animation-delay:{.15 + i * .12:.2f}s">'
            + text(en, 22, 32, y + 32, f'fill="{SAND}"', family="mono", weight="semibold")
            + text(story, 13, 32, y + 56, f'fill="{SAND}" fill-opacity=".6"', rtl=False)
            + f'<path d="M{W - 210} {y + 24} L{W - 250} {y + 24} M{W - 242} {y + 17} L{W - 250} {y + 24} L{W - 242} {y + 31}" fill="none" stroke="{SAND}" stroke-opacity=".55" stroke-width="1.5"/>'
            + text(ar, 30, W - 32, y + 36, f'fill="{SAND}"', weight="bold", anchor="end")
            + sep + "</g>")
    return svg(W, H, "Words the world borrowed from Arabic: algorithm, algebra, zero, coffee", "".join(body), REVEAL)


def build_closing():
    W, H = 1200, 330
    js = "const best = people.sort((a, b) => b.benefitToOthers - a.benefitToOthers)[0];"
    jw = measure(js, 14, family="mono")
    body = [f'<rect width="{W}" height="{H}" fill="{INK}"/>',
            f'<g class="reveal">{text("« خَيْرُ النَّاسِ أَنْفَعُهُمْ لِلنَّاسِ »", 40, W / 2, 78, f"fill=\"{SAND}\"", weight="bold", anchor="middle")}</g>',
            f'<g class="reveal" style="animation-delay:.25s">'
            + text("“The best of people are those most beneficial to others.”", 21, W / 2, 120, f'fill="{SAND}" fill-opacity=".8"', anchor="middle", rtl=False)
            + text("— PROPHET MUHAMMAD ﷺ", 12, W / 2, 148, f'fill="{SAND}" fill-opacity=".5"', family="mono", anchor="middle", spacing=2, rtl=False) + "</g>",
            f'<g class="reveal" style="animation-delay:.5s"><rect x="{W / 2 - jw / 2 - 20}" y="172" width="{jw + 40}" height="40" rx="10" fill="{INK}" stroke="{SAND}" stroke-opacity=".4"/>'
            + text(js, 14, W / 2, 197, f'fill="{SAND}"', family="mono", anchor="middle") + "</g>",
            f'<path class="wave" fill="{SAND}" d="M-60 270 C200 240 400 300 600 272 C800 244 1000 300 1260 268 L1260 {H} L-60 {H} Z"/>',
            f'<path class="wave w2" fill="{SAND}" fill-opacity=".35" d="M-60 258 C220 290 380 236 600 262 C820 288 980 236 1260 256 L1260 {H} L-60 {H} Z"/>']
    style = REVEAL + '''
.wave { animation: drift 9s ease-in-out infinite alternate; } .w2 { animation-duration: 12s; }
@keyframes drift { from { transform: translateX(-30px); } to { transform: translateX(30px); } }'''
    return svg(W, H, "خير الناس أنفعهم للناس — The best of people are those most beneficial to others", "".join(body), style)


def write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main():
    write(ASSETS / "hero.svg", build_hero())
    write(ASSETS / "heritage.svg", build_heritage())
    write(ASSETS / "code.svg", build_code())
    write(ASSETS / "status.svg", build_status())
    write(ASSETS / "words.svg", build_words())
    write(ASSETS / "closing.svg", build_closing())
    for key, (en, ar) in SECTIONS.items():
        write(ASSETS / "sections" / f"{key}.svg", build_section(en, ar))
    for key, spec in STACK.items():
        write(ASSETS / "stack" / f"{key}.svg", build_stack(*spec))
    for key, spec in PROJECTS.items():
        write(ASSETS / "projects" / f"{key}.svg", build_project(*spec))
    print(f"assets written to {ASSETS}")


if __name__ == "__main__":
    main()
