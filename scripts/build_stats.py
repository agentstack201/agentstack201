"""Builds stats.svg — the GitHub numbers card — from the GraphQL API.

Runs in the profile workflow with GITHUB_TOKEN; drawn in the same two colours
and IBM Plex outlines as the rest of the README.

    GITHUB_TOKEN=... python scripts/build_stats.py --user agentstack201 --out dist/stats.svg
    python scripts/build_stats.py --mock --out /tmp/stats.svg      # offline preview
"""
import argparse
import datetime as dt
import json
import os
import random
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_assets import REVEAL, SAND, panel, svg, text  # noqa: E402

QUERY = """
query($login: String!) {
  user(login: $login) {
    followers { totalCount }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes {
        stargazerCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) { edges { size node { name } } }
      }
    }
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}"""


def fetch(login, token):
    req = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps({"query": QUERY, "variables": {"login": login}}).encode(),
        headers={"Authorization": f"bearer {token}", "Content-Type": "application/json", "User-Agent": "build-stats"},
    )
    payload = json.load(urllib.request.urlopen(req, timeout=60))
    if payload.get("errors"):
        raise SystemExit(f"GraphQL error: {payload['errors']}")
    return payload["data"]["user"]


def mock():
    rnd, today = random.Random(7), dt.date.today()
    start = today - dt.timedelta(days=364 + (today.weekday() + 1) % 7)
    days = [{"date": (start + dt.timedelta(d)).isoformat(),
             "contributionCount": rnd.choice([0, 0, 1, 2, 3, 5, 8, 13]) if d % 40 > 6 else 0}
            for d in range((today - start).days + 1)]
    weeks = [{"contributionDays": days[i:i + 7]} for i in range(0, len(days), 7)]
    langs = [("TypeScript", 900), ("JavaScript", 300), ("HTML", 200), ("Python", 120), ("CSS", 90), ("C++", 40)]
    return {"followers": {"totalCount": 12},
            "repositories": {"totalCount": 30, "nodes": [{"stargazerCount": 2, "languages": {"edges": [
                {"size": s, "node": {"name": n}} for n, s in langs]}}]},
            "contributionsCollection": {"contributionCalendar": {
                "totalContributions": sum(d["contributionCount"] for d in days), "weeks": weeks}}}


def streaks(days):
    counts = [d["contributionCount"] for d in days]
    longest = run = 0
    for c in counts:
        run = run + 1 if c else 0
        longest = max(longest, run)
    current, i = 0, len(counts) - 1
    if i >= 0 and counts[i] == 0:  # today may simply not have happened yet
        i -= 1
    while i >= 0 and counts[i]:
        current, i = current + 1, i - 1
    return current, longest


def build(user):
    cal = user["contributionsCollection"]["contributionCalendar"]
    weeks = cal["weeks"]
    days = [d for w in weeks for d in w["contributionDays"]]
    current, longest = streaks(days)
    repos = user["repositories"]
    stars = sum(r["stargazerCount"] for r in repos["nodes"])
    langs = {}
    for r in repos["nodes"]:
        for e in r["languages"]["edges"]:
            langs[e["node"]["name"]] = langs.get(e["node"]["name"], 0) + e["size"]
    total = sum(langs.values()) or 1
    top = sorted(langs.items(), key=lambda kv: -kv[1])[:6]

    W, H = 1200, 470
    body = [panel(W, H)]

    figures = [
        (f"{cal['totalContributions']:,}", "CONTRIBUTIONS", "المساهمات · سنة"),
        (str(current), "CURRENT STREAK", "السلسلة الحالية"),
        (str(longest), "LONGEST STREAK", "أطول سلسلة · سنة"),
        (str(stars), "STARS", "النجوم"),
        (str(repos["totalCount"]), "PUBLIC REPOS", "المستودعات"),
    ]
    col = (W - 80) / len(figures)
    for i, (num, en, ar) in enumerate(figures):
        cx = 40 + col * (i + .5)
        if i:
            body.append(f'<line x1="{40 + col * i}" y1="44" x2="{40 + col * i}" y2="140" stroke="{SAND}" stroke-opacity=".15"/>')
        body.append(f'<g class="reveal" style="animation-delay:{i * .08:.2f}s">'
                    + text(num, 42, cx, 92, f'fill="{SAND}"', family="mono", weight="semibold", anchor="middle")
                    + text(en, 11, cx, 118, f'fill="{SAND}" fill-opacity=".6"', family="mono", weight="semibold", anchor="middle", spacing=2)
                    + text(ar, 13, cx, 140, f'fill="{SAND}" fill-opacity=".5"', anchor="middle") + "</g>")
    body.append(f'<line x1="40" y1="172" x2="{W - 40}" y2="172" stroke="{SAND}" stroke-opacity=".15"/>')

    # Heatmap — opacity of the one sand colour carries the level.
    nonzero = sorted(d["contributionCount"] for d in days if d["contributionCount"])
    q = [nonzero[int(len(nonzero) * f)] for f in (.25, .5, .75)] if nonzero else [1, 1, 1]
    levels = [.07, .3, .5, .75, 1]

    def level(c):
        return 0 if c == 0 else 1 + sum(c > t for t in q)

    cell, gap, hx, hy = 12, 3, 40, 214
    body.append(text("LAST 12 MONTHS", 11, hx, 200, f'fill="{SAND}" fill-opacity=".6"', family="mono", weight="semibold", spacing=2))
    cells = []
    for wi, w in enumerate(weeks):
        for d in w["contributionDays"]:
            di = dt.date.fromisoformat(d["date"]).isoweekday() % 7
            cells.append(f'<rect class="c" style="animation-delay:{.3 + wi * .015:.3f}s" x="{hx + wi * (cell + gap)}" '
                         f'y="{hy + di * (cell + gap)}" width="{cell}" height="{cell}" rx="3" fill="{SAND}" '
                         f'fill-opacity="{levels[level(d["contributionCount"])]}"><title>{d["date"]}: {d["contributionCount"]}</title></rect>')
    body.append("".join(cells))
    ly = hy + 7 * (cell + gap) + 18
    body.append(text("Less", 11, hx, ly + 10, f'fill="{SAND}" fill-opacity=".5"', family="mono"))
    for i, op in enumerate(levels):
        body.append(f'<rect x="{hx + 40 + i * 16}" y="{ly}" width="12" height="12" rx="3" fill="{SAND}" fill-opacity="{op}"/>')
    body.append(text("More", 11, hx + 128, ly + 10, f'fill="{SAND}" fill-opacity=".5"', family="mono"))

    # Languages
    lx, lw = 880, 280
    body.append(text("TOP LANGUAGES", 11, lx, 200, f'fill="{SAND}" fill-opacity=".6"', family="mono", weight="semibold", spacing=2))
    for i, (name, size) in enumerate(top):
        y, pct = 230 + i * 34, size / total
        body.append(f'<g class="reveal" style="animation-delay:{.4 + i * .08:.2f}s">'
                    + text(name, 13, lx, y, f'fill="{SAND}"', family="mono")
                    + text(f"{pct * 100:.1f}%", 13, lx + lw, y, f'fill="{SAND}" fill-opacity=".6"', family="mono", anchor="end")
                    + f'<rect x="{lx}" y="{y + 8}" width="{lw}" height="5" rx="2.5" fill="{SAND}" fill-opacity=".12"/>'
                    + f'<rect class="bar" x="{lx}" y="{y + 8}" width="{max(lw * pct, 3):.1f}" height="5" rx="2.5" fill="{SAND}" fill-opacity="{1 - i * .12:.2f}"/></g>')

    stamp = dt.datetime.now(dt.timezone.utc).strftime("UPDATED %Y-%m-%d")
    body.append(text(f"{stamp} · {user['followers']['totalCount']} FOLLOWERS", 10, W - 40, H - 24,
                     f'fill="{SAND}" fill-opacity=".4"', family="mono", anchor="end", spacing=1.5))

    style = REVEAL + f"""
.c {{ opacity: 0; animation: pop .4s ease-out forwards; }}
.bar {{ transform-box: fill-box; transform-origin: left; animation: grow 1s {'cubic-bezier(.2,.7,.2,1)'} .6s backwards; }}
@keyframes pop {{ to {{ opacity: 1; }} }}
@keyframes grow {{ from {{ transform: scaleX(0); }} }}
@media (prefers-reduced-motion: reduce) {{ .c {{ opacity: 1; }} }}"""
    label = (f"{cal['totalContributions']} contributions in the last year, current streak {current} days, "
             f"longest {longest} days, {stars} stars, {repos['totalCount']} public repositories")
    return svg(W, H, label, "".join(body), style)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER", "agentstack201"))
    ap.add_argument("--out", default="dist/stats.svg")
    ap.add_argument("--mock", action="store_true")
    a = ap.parse_args()
    user = mock() if a.mock else fetch(a.user, os.environ["GITHUB_TOKEN"])
    out = Path(a.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build(user), encoding="utf-8")
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
