#!/usr/bin/env python3
"""Generate self-hosted GitHub profile cards (stats, streak, activity graph) as static SVGs.

Runs inside GitHub Actions (see .github/workflows/profile-stats.yml). Uses only the Python
standard library and GitHub's own GraphQL API, so there is no third-party image service that
can rate-limit or go down. If the API call fails, the script exits without touching the
existing SVG files, so the profile keeps showing the last good version.
"""
import json
import math
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import date, datetime, timedelta, timezone
from xml.sax.saxutils import escape

USER = os.environ.get("GH_USER", "kamalswarnkar")
TOKEN = os.environ.get("GH_TOKEN", "")
OUT_DIR = os.environ.get("OUT_DIR", "assets/stats")
API = "https://api.github.com/graphql"

FONT = "'Segoe UI','Helvetica Neue',Helvetica,Arial,sans-serif"

# --------------------------------------------------------------------------- data

PROFILE_Q = """
query($login: String!, $prQuery: String!) {
  prSearch: search(query: $prQuery, type: ISSUE, first: 1) { issueCount }
  user(login: $login) {
    name
    login
    createdAt
    followers { totalCount }
    repositories(ownerAffiliations: [OWNER], isFork: false, privacy: PUBLIC, first: 100) {
      totalCount
      nodes { languages(first: 10) { nodes { name } } }
    }
    pullRequests { totalCount }
    repositoriesContributedTo(first: 1, contributionTypes: [COMMIT, ISSUE, PULL_REQUEST, REPOSITORY]) {
      totalCount
    }
    contributionsCollection { contributionYears }
  }
}
"""

YEAR_Q = """
query($login: String!, $from: DateTime!, $to: DateTime!) {
  user(login: $login) {
    contributionsCollection(from: $from, to: $to) {
      totalCommitContributions
      contributionCalendar {
        totalContributions
        weeks { contributionDays { date contributionCount } }
      }
    }
  }
}
"""


def gql(query, variables):
    body = json.dumps({"query": query, "variables": variables}).encode()
    headers = {
        "Authorization": f"bearer {TOKEN}",
        "Content-Type": "application/json",
        "User-Agent": "profile-cards-generator",
    }
    payload = None
    for attempt in range(3):
        try:
            req = urllib.request.Request(API, data=body, headers=headers)
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.load(resp)
            break
        except (urllib.error.URLError, TimeoutError) as exc:
            if attempt == 2:
                raise
            print(f"Request failed ({exc}); retrying...", file=sys.stderr)
            time.sleep(3 * (attempt + 1))
    if payload.get("errors"):
        raise RuntimeError(f"GitHub API error: {payload['errors']}")
    return payload["data"]


def fetch():
    """Return everything the cards need."""
    first = gql(PROFILE_Q, {"login": USER, "prQuery": f"author:{USER} type:pr"})
    prof = first["user"]
    pr_count = max(first["prSearch"]["issueCount"], prof["pullRequests"]["totalCount"])
    years = prof["contributionsCollection"]["contributionYears"]
    counts = {}
    commits = 0
    for year in years:
        data = gql(
            YEAR_Q,
            {"login": USER, "from": f"{year}-01-01T00:00:00Z", "to": f"{year}-12-31T23:59:59Z"},
        )["user"]["contributionsCollection"]
        commits += data["totalCommitContributions"]
        for week in data["contributionCalendar"]["weeks"]:
            for day in week["contributionDays"]:
                counts[date.fromisoformat(day["date"])] = day["contributionCount"]
    return {
        "name": prof.get("name") or prof["login"],
        "created": datetime.fromisoformat(prof["createdAt"].replace("Z", "+00:00")).date(),
        "followers": prof["followers"]["totalCount"],
        "repos": prof["repositories"]["totalCount"],
        "prs": pr_count,
        "languages": len(
            {
                lang["name"]
                for repo in prof["repositories"]["nodes"]
                for lang in repo["languages"]["nodes"]
            }
        ),
        "contributed_to": prof["repositoriesContributedTo"]["totalCount"],
        "commits": commits,
        "days": counts,
    }


# ------------------------------------------------------------------------ metrics


def streaks(counts, today):
    """Return (current_len, current_range, longest_len, longest_range)."""
    one = timedelta(days=1)
    d = today if counts.get(today, 0) > 0 else today - one
    cur, end = 0, d
    while counts.get(d, 0) > 0:
        cur += 1
        d -= one
    cur_range = (d + one, end) if cur else None

    best, best_range, run, run_start = 0, None, 0, None
    for day in sorted(counts):
        if day > today:
            break
        if counts[day] > 0:
            if run == 0:
                run_start = day
            run += 1
            if run > best:
                best, best_range = run, (run_start, day)
        else:
            run = 0
    return cur, cur_range, best, best_range


def fmt_day(d, with_year=False):
    s = f"{d.strftime('%b')} {d.day}"
    return f"{s}, {d.year}" if with_year else s


def fmt_range(rng, today):
    if not rng:
        return "No active streak"
    a, b = rng
    show_year = a.year != today.year or b.year != today.year
    if a == b:
        return fmt_day(a, show_year)
    return f"{fmt_day(a, show_year)} – {fmt_day(b, show_year)}"


# ------------------------------------------------------------------------ drawing


def head(w, h, title, desc):
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" role="img" aria-labelledby="t d">
  <title id="t">{escape(title)}</title>
  <desc id="d">{escape(desc)}</desc>
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#0B1120"/><stop offset="0.6" stop-color="#111936"/><stop offset="1" stop-color="#1B1F4B"/>
    </linearGradient>
    <linearGradient id="accent" x1="0" y1="0" x2="1" y2="0">
      <stop offset="0" stop-color="#6366F1"/><stop offset="1" stop-color="#22D3EE"/>
    </linearGradient>
    <linearGradient id="area" x1="0" y1="0" x2="0" y2="1">
      <stop offset="0" stop-color="#6366F1" stop-opacity="0.38"/><stop offset="1" stop-color="#6366F1" stop-opacity="0"/>
    </linearGradient>
    <pattern id="dots" width="24" height="24" patternUnits="userSpaceOnUse"><circle cx="2" cy="2" r="1" fill="#94A3B8" opacity="0.12"/></pattern>
  </defs>
  <rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="url(#bg)" stroke="#26314D"/>
  <rect x="0.5" y="0.5" width="{w - 1}" height="{h - 1}" rx="16" fill="url(#dots)"/>
  <g font-family="{FONT}">
"""


def tail():
    return "  </g>\n</svg>\n"


def card_title(text):
    return (
        f'    <text x="30" y="42" font-size="18" font-weight="700" fill="#F8FAFC">{escape(text)}</text>\n'
        '    <rect x="30" y="52" width="44" height="3" rx="1.5" fill="url(#accent)"/>\n'
    )


def ring(cx, cy, r, fraction, stroke_w=8):
    circ = 2 * math.pi * r
    return (
        f'    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="#1E2A47" stroke-width="{stroke_w}"/>\n'
        f'    <circle cx="{cx}" cy="{cy}" r="{r}" fill="none" stroke="url(#accent)" stroke-width="{stroke_w}" '
        f'stroke-linecap="round" stroke-dasharray="{circ * fraction:.1f} {circ:.1f}" '
        f'transform="rotate(-90 {cx} {cy})"/>\n'
    )


def stats_svg(m, today):
    w, h = 495, 205
    rows = [
        ("Public Repositories", m["repos"]),
        ("Total Commits", m["commits"]),
    ]
    # Only show pull requests when there are some; otherwise show followers instead.
    rows.append(("Pull Requests", m["prs"]) if m["prs"] > 0 else ("Followers", m["followers"]))
    rows += [
        ("Languages Used", m["languages"]),
        ("Contributed To", m["contributed_to"]),
    ]
    out = head(w, h, "GitHub overview", "Repositories, commits, languages and recent activity")
    out += card_title(f"{m['name']}'s GitHub Stats")
    for i, (label, value) in enumerate(rows):
        y = 90 + i * 25
        out += f'    <text x="30" y="{y}" font-size="14" fill="#94A3B8">{label}</text>\n'
        out += f'    <text x="285" y="{y}" font-size="14" font-weight="700" fill="#F8FAFC" text-anchor="end">{value:,}</text>\n'
    active = m["active90"]
    out += ring(395, 112, 44, active / 90)
    out += f'    <text x="395" y="122" font-size="32" font-weight="800" fill="#F8FAFC" text-anchor="middle">{active}</text>\n'
    out += '    <text x="395" y="140" font-size="11" fill="#94A3B8" text-anchor="middle">of 90 days</text>\n'
    out += '    <text x="395" y="180" font-size="11" letter-spacing="1.5" fill="#64748B" text-anchor="middle">ACTIVE DAYS</text>\n'
    return out + tail()


def streak_svg(m, today):
    w, h = 495, 195
    cur, cur_range, best, best_range = m["streaks"]
    total = sum(m["days"].values())
    active = [d for d, c in m["days"].items() if c > 0]
    first = min(active) if active else m["created"]
    out = head(w, h, "Contribution streak", "Total contributions, current streak and longest streak")
    # dividers
    out += '    <line x1="165" y1="34" x2="165" y2="162" stroke="#26314D"/>\n'
    out += '    <line x1="330" y1="34" x2="330" y2="162" stroke="#26314D"/>\n'
    # total
    out += f'    <text x="82" y="96" font-size="34" font-weight="800" fill="#F8FAFC" text-anchor="middle">{total:,}</text>\n'
    out += '    <text x="82" y="130" font-size="14" font-weight="600" fill="#A5B4FC" text-anchor="middle">Total Contributions</text>\n'
    out += f'    <text x="82" y="152" font-size="12" fill="#94A3B8" text-anchor="middle">{fmt_day(first, True)} – Present</text>\n'
    # current streak
    frac = min(1.0, cur / max(best, 1)) if best else 0.0
    out += ring(247, 82, 36, frac)
    out += f'    <text x="247" y="93" font-size="30" font-weight="800" fill="#F8FAFC" text-anchor="middle">{cur}</text>\n'
    out += '    <text x="247" y="144" font-size="14" font-weight="600" fill="#22D3EE" text-anchor="middle">Current Streak</text>\n'
    out += f'    <text x="247" y="164" font-size="12" fill="#94A3B8" text-anchor="middle">{fmt_range(cur_range, today)}</text>\n'
    # longest streak
    out += f'    <text x="412" y="96" font-size="34" font-weight="800" fill="#F8FAFC" text-anchor="middle">{best}</text>\n'
    out += '    <text x="412" y="130" font-size="14" font-weight="600" fill="#A5B4FC" text-anchor="middle">Longest Streak</text>\n'
    out += f'    <text x="412" y="152" font-size="12" fill="#94A3B8" text-anchor="middle">{fmt_range(best_range, today)}</text>\n'
    return out + tail()


def activity_svg(m, today, span=30):
    w, h = 1000, 300
    days = [today - timedelta(days=span - 1 - i) for i in range(span)]
    vals = [m["days"].get(d, 0) for d in days]
    peak = max(vals)
    ymax = max(4, int(math.ceil(peak / 4.0) * 4))
    left, right, top, bottom = 70, 960, 92, 244
    xs = [left + i * (right - left) / (span - 1) for i in range(span)]
    ys = [bottom - v / ymax * (bottom - top) for v in vals]

    out = head(w, h, "Contribution activity", f"Daily contributions over the last {span} days")
    out += card_title(f"Contribution activity · last {span} days")
    out += f'    <text x="970" y="42" font-size="13" fill="#94A3B8" text-anchor="end">{sum(vals):,} contributions</text>\n'
    for i in range(5):
        y = bottom - i * (bottom - top) / 4
        out += f'    <line x1="{left}" y1="{y:.1f}" x2="{right}" y2="{y:.1f}" stroke="#26314D" stroke-dasharray="3 5"/>\n'
        out += f'    <text x="{left - 12}" y="{y + 4:.1f}" font-size="11" fill="#64748B" text-anchor="end">{int(ymax * i / 4)}</text>\n'
    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in zip(xs, ys))
    area = f"{xs[0]:.1f},{bottom} {pts} {xs[-1]:.1f},{bottom}"
    out += f'    <polygon points="{area}" fill="url(#area)"/>\n'
    out += f'    <polyline points="{pts}" fill="none" stroke="url(#accent)" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>\n'
    for x, y, v in zip(xs, ys, vals):
        if v > 0:
            out += f'    <circle cx="{x:.1f}" cy="{y:.1f}" r="3.4" fill="#22D3EE" stroke="#0B1120" stroke-width="1.5"/>\n'
    for i in range(0, span, 5):
        out += f'    <text x="{xs[i]:.1f}" y="{bottom + 24}" font-size="11" fill="#64748B" text-anchor="middle">{fmt_day(days[i])}</text>\n'
    out += f'    <text x="{xs[-1]:.1f}" y="{bottom + 24}" font-size="11" font-weight="600" fill="#94A3B8" text-anchor="middle">Today</text>\n'
    return out + tail()


def build(data, today):
    m = dict(data)
    m["streaks"] = streaks(data["days"], today)
    m["active90"] = sum(1 for i in range(90) if data["days"].get(today - timedelta(days=i), 0) > 0)
    return m


def write_all(m, today, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    files = {
        "stats.svg": stats_svg(m, today),
        "streak.svg": streak_svg(m, today),
        "activity.svg": activity_svg(m, today),
    }
    for name, svg in files.items():
        with open(os.path.join(out_dir, name), "w", encoding="utf-8") as fh:
            fh.write(svg)
        print(f"wrote {os.path.join(out_dir, name)}")


def main():
    if not TOKEN:
        sys.exit("GH_TOKEN is not set")
    today = datetime.now(timezone.utc).date()
    try:
        data = fetch()
    except Exception as exc:  # keep the previous good files if anything goes wrong
        sys.exit(f"Could not fetch GitHub data, leaving existing cards untouched: {exc}")
    write_all(build(data, today), today, OUT_DIR)


if __name__ == "__main__":
    main()
