"""Builds assets/hero.svg — the animated profile banner.

Arabic text is shaped with HarfBuzz and converted to vector outlines, so the
calligraphy renders identically on every device (GitHub serves README images
without web fonts) and can be "written" with a right-to-left pen animation.

    pip install fonttools uharfbuzz
    curl -LO https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Bold.ttf
    curl -LO https://raw.githubusercontent.com/google/fonts/main/ofl/amiri/Amiri-Regular.ttf
    python scripts/build_hero.py --fonts . --out assets/hero.svg
"""
import argparse
import math
from pathlib import Path

import uharfbuzz as hb
from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

W, H = 1200, 420


def shape(font_path, text, size, cx, baseline):
    """Return [(x, d)] glyph outlines for `text`, centred on cx."""
    data = Path(font_path).read_bytes()
    hb_font = hb.Font(hb.Face(data))
    buf = hb.Buffer()
    buf.add_str(text)
    buf.guess_segment_properties()
    hb.shape(hb_font, buf, {"kern": True, "liga": True})

    tt = TTFont(font_path)
    order, glyphs = tt.getGlyphOrder(), tt.getGlyphSet()
    scale = size / tt["head"].unitsPerEm
    width = sum(p.x_advance for p in buf.glyph_positions) * scale
    x = cx - width / 2

    out = []
    for info, pos in zip(buf.glyph_infos, buf.glyph_positions):
        gx, gy = x + pos.x_offset * scale, baseline - pos.y_offset * scale
        pen = SVGPathPen(glyphs)
        glyphs[order[info.codepoint]].draw(TransformPen(pen, (scale, 0, 0, -scale, gx, gy)))
        d = pen.getCommands()
        if d:
            out.append((gx, d))
        x += pos.x_advance * scale
    return out


def star(cx, cy, r):
    """Eight-pointed star (two overlapping squares), the khatim / rub el hizb."""
    pts = []
    for i in range(16):
        rad = r if i % 2 == 0 else r * 0.7654  # inner radius of an {8/2} star
        a = math.pi / 8 * i - math.pi / 2
        pts.append(f"{cx + rad * math.cos(a):.2f},{cy + rad * math.sin(a):.2f}")
    return "M" + " L".join(pts) + " Z"


def glyph_paths(glyphs, cls, start, step):
    # Pen moves right-to-left, the way Arabic is actually written.
    ordered = sorted(glyphs, key=lambda g: -g[0])
    return "\n".join(
        f'<path class="{cls}" pathLength="1" style="animation-delay:{start + i * step:.2f}s" d="{d}"/>'
        for i, (_, d) in enumerate(ordered)
    )


def build(fonts, out):
    bold, regular = Path(fonts, "Amiri-Bold.ttf"), Path(fonts, "Amiri-Regular.ttf")
    salam = shape(regular, "سَلَامٌ عَلَيْكُمْ", 40, W / 2, 78)
    name = shape(bold, "أَحْمَد هِشَام", 124, W / 2, 222)

    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" aria-labelledby="t d">
<title id="t">سلام عليكم — Ahmad Hisham | أحمد هشام</title>
<desc id="d">From the language that gave the world the words Algorithm and Algebra — building AI agents and web systems.</desc>
<defs>
  <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="#0d1117"/><stop offset=".55" stop-color="#0b1f29"/><stop offset="1" stop-color="#0f4c5c"/>
  </linearGradient>
  <linearGradient id="gold" x1="0" y1="0" x2="1" y2="0">
    <stop offset="0" stop-color="#b8892b"/><stop offset=".45" stop-color="#f5d27a"/>
    <stop offset=".55" stop-color="#fff3c4"/><stop offset="1" stop-color="#b8892b"/>
    <animateTransform attributeName="gradientTransform" type="translate" values="-1 0;1 0" dur="6s" begin="4s" repeatCount="indefinite"/>
  </linearGradient>
  <radialGradient id="glow" cx=".5" cy=".45" r=".5">
    <stop offset="0" stop-color="#00b4d8" stop-opacity=".22"/><stop offset="1" stop-color="#00b4d8" stop-opacity="0"/>
  </radialGradient>
  <radialGradient id="fade" cx=".5" cy=".45" r=".65">
    <stop offset="0" stop-color="#fff" stop-opacity="0"/><stop offset=".55" stop-color="#fff" stop-opacity=".35"/><stop offset="1" stop-color="#fff" stop-opacity="1"/>
  </radialGradient>
  <mask id="edges"><rect width="{W}" height="{H}" fill="url(#fade)"/></mask>
  <pattern id="girih" width="80" height="80" patternUnits="userSpaceOnUse">
    <path d="{star(40, 40, 30)}" fill="none" stroke="#00b4d8" stroke-width="1"/>
    <path d="M0 0 L10 10 M80 0 L70 10 M0 80 L10 70 M80 80 L70 70" stroke="#00b4d8" stroke-width="1"/>
    <circle cx="40" cy="40" r="6" fill="none" stroke="#e3b341" stroke-width=".8"/>
  </pattern>
</defs>
<style>
  .pattern {{ opacity: 0; animation: fadeIn 2.5s ease-out .2s forwards; }}
  .khatim  {{ fill: none; stroke: #e3b341; stroke-width: 1.4; stroke-dasharray: 1; stroke-dashoffset: 1; opacity: .35;
             transform-origin: 600px 190px; animation: draw 3s ease-in-out forwards, spin 90s linear 3s infinite; }}
  .k2      {{ stroke: #00b4d8; animation-direction: normal, reverse; animation-duration: 3.4s, 120s; }}
  .ink     {{ fill: url(#gold); fill-opacity: 0; stroke: #f5d27a; stroke-width: 1.6; stroke-dasharray: 1; stroke-dashoffset: 1;
             animation: draw .9s ease-in-out forwards, ink .8s ease-out forwards; }}
  .salam   {{ fill: #8fd9e8; fill-opacity: 0; stroke: #8fd9e8; stroke-width: 1; stroke-dasharray: 1; stroke-dashoffset: 1;
             animation: draw .6s ease-in-out forwards, ink .6s ease-out forwards; }}
  .en      {{ font-family: 'Segoe UI', 'Helvetica Neue', Helvetica, Arial, sans-serif; fill: #e6edf3; text-anchor: middle; opacity: 0;
             animation: rise 1.2s cubic-bezier(.2,.7,.2,1) forwards; }}
  .name    {{ font-size: 30px; font-weight: 600; letter-spacing: 14px; animation-delay: 3.6s; }}
  .tag     {{ font-size: 17px; fill: #9fb3c8; letter-spacing: .5px; animation-delay: 4.3s; }}
  .tag tspan.hl {{ fill: #e3b341; font-weight: 600; }}
  .rule    {{ stroke: #e3b341; stroke-width: 1.2; transform-origin: 600px 0; transform: scaleX(0); animation: grow 1.4s ease-out 3.4s forwards; }}
  @keyframes draw  {{ to {{ stroke-dashoffset: 0; }} }}
  @keyframes ink   {{ 0% {{ fill-opacity: 0; }} 100% {{ fill-opacity: 1; stroke-width: .3; }} }}
  @keyframes fadeIn {{ to {{ opacity: .09; }} }}
  @keyframes spin  {{ to {{ transform: rotate(360deg); }} }}
  @keyframes rise  {{ from {{ opacity: 0; transform: translateY(10px); }} to {{ opacity: 1; transform: none; }} }}
  @keyframes grow  {{ to {{ transform: scaleX(1); }} }}
  @media (prefers-reduced-motion: reduce) {{
    * {{ animation: none !important; }}
    .pattern {{ opacity: .09; }} .khatim {{ stroke-dashoffset: 0; }}
    .ink, .salam {{ fill-opacity: 1; stroke-dashoffset: 0; }} .en {{ opacity: 1; }} .rule {{ transform: none; }}
  }}
</style>
<rect width="{W}" height="{H}" fill="url(#bg)"/>
<rect class="pattern" width="{W}" height="{H}" fill="url(#girih)" mask="url(#edges)"/>
<rect width="{W}" height="{H}" fill="url(#glow)"/>
<path class="khatim" pathLength="1" d="{star(600, 190, 165)}"/>
<path class="khatim k2" pathLength="1" d="{star(600, 190, 140)}"/>
<g>
{glyph_paths(salam, "salam", 0.3, 0.12)}
</g>
<g>
{glyph_paths(name, "ink", 1.2, 0.22)}
</g>
<line class="rule" x1="420" y1="268" x2="780" y2="268"/>
<text class="en name" x="600" y="312">AHMAD HISHAM</text>
<text class="en tag" x="600" y="352">From the language that gave the world <tspan class="hl">Algorithm</tspan> &amp; <tspan class="hl">Algebra</tspan> — building AI agents &amp; web systems</text>
</svg>
'''
    Path(out).write_text(svg, encoding="utf-8")
    print(f"wrote {out} ({len(svg) / 1024:.1f} KB)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--fonts", default=".")
    ap.add_argument("--out", default="assets/hero.svg")
    a = ap.parse_args()
    build(a.fonts, a.out)
