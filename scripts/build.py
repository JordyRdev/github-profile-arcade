#!/usr/bin/env python3
"""
GitHub Profile Arcade: builds a neofetch-style profile from profile.yml.

  python scripts/build.py            # render with cached stats (assets/stats.json)
  GH_TOKEN=xxx python scripts/build.py --fetch   # fetch fresh GitHub stats, then render

Outputs SVGs in assets/ and fills the <!-- arcade:... --> blocks in README.md.
The workflow in .github/workflows/arcade.yml runs this daily.
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.request
from html import escape
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from race import render_race  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
ASSETS = ROOT / "assets"

# --------------------------------------------------------------------------- #
#  CONFIG: everything personal lives in profile.yml                            #
# --------------------------------------------------------------------------- #
import yaml  # noqa: E402

CONFIG = yaml.safe_load((ROOT / "profile.yml").read_text(encoding="utf-8")) or {}


def _owner():
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    return repo.split("/")[0] if "/" in repo else ""


USER = (CONFIG.get("username") or _owner() or "octocat").strip()
PROMPT = CONFIG.get("prompt") or f"{USER.lower()}@github"
_since = (CONFIG.get("card") or {}).get("uptime_since") or dt.date.today()
CAREER_START = _since if isinstance(_since, dt.date) else dt.date.fromisoformat(str(_since))


def _info_items(raw):
    items = []
    for it in raw or []:
        if it in (None, "", "-"):
            items.append(None)
        elif isinstance(it, str) and it.strip().lower() == "stats":
            items.append("STATS")
        elif isinstance(it, dict) and "section" in it:
            items.append(str(it["section"]))
        elif isinstance(it, dict) and len(it) == 1:
            k, v = next(iter(it.items()))
            items.append((str(k), str(v)))
        else:
            raise SystemExit(f"profile.yml: can't read card line {it!r}")
    return items


INFO = _info_items((CONFIG.get("card") or {}).get("lines"))
TAGLINES = [str(t) for t in (CONFIG.get("header") or {}).get("taglines") or [f"Hi, I'm {USER}"]]
BUTTONS = [(b.get("icon", "globe"), str(b["label"]).upper(), str(b["url"]).replace("YOUR-USERNAME", USER))
           for b in CONFIG.get("buttons") or []]
FEATURES = {"header": True, "card": True, "buttons": True, "tests": True, "race": True}
FEATURES.update(CONFIG.get("show") or {})
PLATE = str((CONFIG.get("race") or {}).get("plate") or USER[:6]).upper()[:7]
PORTRAIT = CONFIG.get("portrait") or {}

def _needed_width():
    need = len(PROMPT) + 12
    for it in INFO:
        if isinstance(it, tuple):
            need = max(need, 2 + len(it[0]) + 1 + len(it[1]) + 6)
    return need


WIDTH = max(58, _needed_width())   # characters in each info line
FONT_SIZE = 16
CHAR_W = 9.63       # approx. advance of a 16px monospace glyph
LINE_H = 20
ART_FONT = 11       # portrait uses a smaller font for more detail
ART_CHAR_W = 6.62
ART_LINE_H = 13.4

# density ramp used by the portrait (dark -> bright on a dark background).
# In light mode the ramp is reversed so the portrait isn't a photo-negative.
RAMP = " .'`^,:;-~=+*xjk%#&$@"

THEMES = {
    "dark": dict(bg="#161b22", border="#30363d", text="#c9d1d9", key="#ffa657",
                 value="#a5d6ff", dots="#616e7f", add="#3fb950", dele="#f85149",
                 art="#c9d1d9", accent="#ffa657", typing="#c9d1d9",
                 btn_bg="#161b22", btn_border="#30363d", btn_icon="#ffa657", btn_text="#c9d1d9", btn_bar="#ffa657"),
    "light": dict(bg="#f6f8fa", border="#d0d7de", text="#24292f", key="#e8590c",
                  value="#0a3069", dots="#c2cfde", add="#1a7f37", dele="#cf222e",
                  art="#24292f", accent="#e8590c", typing="#ffa657",
                  btn_bg="#ffffff", btn_border="#ffa657", btn_icon="#e8590c", btn_text="#24292f", btn_bar="#ffa657"),
}

# --------------------------------------------------------------------------- #
#  Stats                                                                       #
# --------------------------------------------------------------------------- #
STATS_FILE = ASSETS / "stats.json"
API = "https://api.github.com"


def _req(url, token, payload=None):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, headers={
        "Authorization": f"bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": f"{USER}-profile-card",
    })
    with urllib.request.urlopen(req, timeout=60) as r:
        body = r.read()
        return r.status, (json.loads(body) if body else None)


def gql(token, query, variables):
    _, res = _req(f"{API}/graphql", token, {"query": query, "variables": variables})
    if res.get("errors"):
        raise RuntimeError(res["errors"])
    return res["data"]


def fetch_stats(token):
    d = gql(token, """query($login:String!){ user(login:$login){
        id followers{totalCount}
        contributionsCollection{ contributionCalendar{ totalContributions
          weeks{ contributionDays{ date weekday contributionCount contributionLevel } } } }
        repositoriesContributedTo(includeUserRepositories:false,
          contributionTypes:[COMMIT,PULL_REQUEST,REPOSITORY,PULL_REQUEST_REVIEW]){totalCount}
    }}""", {"login": USER})["user"]
    uid = d["id"]
    levels = {"NONE": 0, "FIRST_QUARTILE": 1, "SECOND_QUARTILE": 2, "THIRD_QUARTILE": 3, "FOURTH_QUARTILE": 4}
    cal = d["contributionsCollection"]["contributionCalendar"]
    calendar = {"total": cal["totalContributions"],
                "start": cal["weeks"][0]["contributionDays"][0]["date"],
                "weeks": [[[x["weekday"], x["contributionCount"], levels.get(x["contributionLevel"], 0)]
                           for x in w["contributionDays"]] for w in cal["weeks"]]}
    stats = {"followers": d["followers"]["totalCount"],
             "contributed": d["repositoriesContributedTo"]["totalCount"],
             "repos": 0, "stars": 0, "commits": 0, "additions": 0, "deletions": 0}

    repos, cursor = [], None
    while True:
        page = gql(token, """query($login:String!,$id:ID!,$after:String){ user(login:$login){
            repositories(ownerAffiliations:OWNER, first:50, after:$after){
              totalCount pageInfo{hasNextPage endCursor}
              nodes{ name isFork isPrivate stargazerCount
                defaultBranchRef{ name target{ ... on Commit { history(author:{id:$id}){totalCount} } } } }
        }}}""", {"login": USER, "id": uid, "after": cursor})["user"]["repositories"]
        stats["repos"] = page["totalCount"]
        repos += page["nodes"]
        if not page["pageInfo"]["hasNextPage"]:
            break
        cursor = page["pageInfo"]["endCursor"]

    for r in repos:
        if not r["isFork"]:
            stats["stars"] += r["stargazerCount"]
        ref = r.get("defaultBranchRef")
        n = (ref or {}).get("target", {}).get("history", {}).get("totalCount", 0) if ref else 0
        stats["commits"] += n
        if n == 0:
            continue
        # lines of code: per-author weekly additions/deletions (202 = still computing)
        for _ in range(8):
            status, body = _req(f"{API}/repos/{USER}/{r['name']}/stats/contributors", token)
            if status == 200 and isinstance(body, list):
                for c in body:
                    if (c.get("author") or {}).get("login", "").lower() == USER.lower():
                        stats["additions"] += sum(w["a"] for w in c["weeks"])
                        stats["deletions"] += sum(w["d"] for w in c["weeks"])
                break
            time.sleep(4)
    stats["tests"] = fetch_tests(token, repos)
    stats["calendar"] = calendar
    stats["updated"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    return stats


def _ts(s):
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))


def fetch_tests(token, repos):
    """Latest completed run of each workflow on the default branch of every
    public, non-fork repo (the profile repo itself is skipped)."""
    results = []
    for r in sorted(repos, key=lambda r: r["name"].lower()):
        if r["isFork"] or r.get("isPrivate") or r["name"].lower() == USER.lower():
            continue
        branch = (r.get("defaultBranchRef") or {}).get("name")
        if not branch:
            continue
        try:
            _, body = _req(f"{API}/repos/{USER}/{r['name']}/actions/runs?per_page=30"
                           f"&branch={branch}&status=completed&exclude_pull_requests=true", token)
        except Exception as e:  # one broken repo shouldn't break the card
            print("skip", r["name"], e)
            continue
        seen = set()
        for run in (body or {}).get("workflow_runs", []):
            if run.get("event") == "pull_request" or run["name"] in seen:
                continue
            seen.add(run["name"])
            secs = max(0, int((_ts(run["updated_at"]) - _ts(run["run_started_at"])).total_seconds()))
            results.append({"repo": r["name"], "workflow": run["name"],
                            "conclusion": run.get("conclusion") or "skipped",
                            "seconds": secs, "finished": run["updated_at"]})
    return results


def load_stats():
    if STATS_FILE.exists():
        return json.loads(STATS_FILE.read_text())
    return {"repos": 0, "contributed": 0, "stars": 0, "commits": 0,
            "followers": 0, "additions": 0, "deletions": 0}


# --------------------------------------------------------------------------- #
#  Rendering                                                                   #
# --------------------------------------------------------------------------- #
def uptime(start, today=None):
    today = today or dt.date.today()
    y, m, d = today.year - start.year, today.month - start.month, today.day - start.day
    if d < 0:
        m -= 1
        prev = (today.replace(day=1) - dt.timedelta(days=1))
        d += prev.day
    if m < 0:
        y -= 1
        m += 12
    pl = lambda n, w: f"{n} {w}{'' if n == 1 else 's'}"
    return f"{pl(y, 'year')}, {pl(m, 'month')}, {pl(d, 'day')}"


def seg(text, cls):
    return (text, cls)


def kv_line(key, value):
    """'. Key: ......... value' padded to WIDTH."""
    head = [seg(". ", "dots")]
    parts = key.split(".")
    for i, p in enumerate(parts):
        if i:
            head.append(seg(".", "text"))
        head.append(seg(p, "key"))
    head.append(seg(":", "text"))
    used = 2 + len(key) + 1
    fill = WIDTH - used - len(value) - 2
    return head + [seg(" " + "." * max(fill, 1) + " ", "dots"), seg(value, "value")]


def section_line(title):
    left = f"- {title} "
    return [seg(left, "text"), seg("—" * (WIDTH - len(left)), "text")]


def stat_pair(lk, lv, rk, rv, lwidth):
    """'. Repos: .... 12 {..} | Stars: ..... 5'"""
    out = [seg(". ", "dots"), seg(lk, "key"), seg(":", "text")]
    lfill = lwidth - (2 + len(lk) + 1) - len(lv) - 2
    out += [seg(" " + "." * max(lfill, 1) + " ", "dots")] + lv_segs(lv)
    out += [seg(" | ", "text"), seg(rk, "key"), seg(":", "text")]
    rfill = WIDTH - lwidth - 3 - len(rk) - 1 - len(rv) - 2
    out += [seg(" " + "." * max(rfill, 1) + " ", "dots"), seg(rv, "value")]
    return out


def lv_segs(lv):
    if "{" in lv:  # '12 {Contributed: 3}'
        num, rest = lv.split(" ", 1)
        inner = rest.strip("{}")
        k, v = inner.split(": ")
        return [seg(num, "value"), seg(" {", "text"), seg(k, "key"),
                seg(": ", "text"), seg(v, "value"), seg("}", "text")]
    return [seg(lv, "value")]


def stats_lines(s):
    f = lambda n: f"{n:,}"
    lw = 33
    lines = [
        stat_pair("Repos", f"{f(s['repos'])} {{Contributed: {f(s['contributed'])}}}",
                  "Stars", f(s["stars"]), lw),
        stat_pair("Commits", f(s["commits"]), "Followers", f(s["followers"]), lw),
    ]
    loc = s["additions"] - s["deletions"]
    add, dele = f"{f(s['additions'])}++", f"{f(s['deletions'])}--"
    key = "Lines of Code on GitHub"
    tail_len = len(f(loc)) + 3 + len(add) + 2 + len(dele) + 2
    fill = WIDTH - (2 + len(key) + 1) - tail_len - 2
    lines.append([seg(". ", "dots"), seg(key, "key"), seg(":", "text"),
                  seg(" " + "." * max(fill, 1) + " ", "dots"),
                  seg(f(loc), "value"), seg(" ( ", "text"), seg(add, "add"),
                  seg(", ", "text"), seg(dele, "dele"), seg(" )", "text")])
    return lines


def build_info(stats):
    up = uptime(CAREER_START)
    lines = [[seg(PROMPT, "accent"), seg(" " + "—" * (WIDTH - len(PROMPT) - 1), "text")]]
    for item in INFO:
        if item is None:
            lines.append([seg(".", "dots")])
        elif item == "STATS":
            lines += stats_lines(stats)
        elif isinstance(item, str):
            lines.append(section_line(item))
        else:
            k, v = item
            lines.append(kv_line(k, v.format(uptime=up)))
    return lines


def render_card(theme, stats):
    t = THEMES[theme]
    art = [a.rstrip() for a in (ASSETS / "ascii.txt").read_text().split("\n")]
    while art and not art[0]:
        art.pop(0)
    while art and not art[-1]:
        art.pop()
    if theme == "light":
        rev = {c: RAMP[len(RAMP) - i] for i, c in enumerate(RAMP) if i}
        art = ["".join(rev.get(c, c) for c in a) for a in art]
    info = build_info(stats)
    art_cols = max(len(a) for a in art)
    pad = 20
    info_x = pad + art_cols * ART_CHAR_W + 28
    info_h = (len(info) + 2) * LINE_H
    art_h = len(art) * ART_LINE_H
    w = int(info_x + WIDTH * CHAR_W + pad + 14)
    h = int(pad * 2 + max(info_h, art_h))

    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" font-family="ConsolasFallback,Consolas,'
           f'\'DejaVu Sans Mono\',monospace" width="{w}px" height="{h}px" font-size="{FONT_SIZE}px">',
           "<style>",
           "@font-face{src:local('Consolas'),local('Consolas Bold');font-family:'ConsolasFallback';"
           "font-display:swap;-webkit-size-adjust:109%;size-adjust:109%;}",
           *[f".{c}{{fill:{t[c]};}}" for c in ("text", "key", "value", "dots", "add", "dele", "accent")],
           f".art{{fill:{t['art']};}}",
           ".cursor{animation:blink 1.1s steps(1) infinite;}",
           "@keyframes blink{50%{opacity:0;}}",
           "text,tspan{white-space:pre;}",
           "</style>",
           f'<rect width="{w}px" height="{h}px" fill="{t["bg"]}" rx="15"/>']
    art_top = pad + 10 + max(0, (h - 2 * pad - art_h) / 2)  # vertically centred
    out.append(f'<text x="{pad}" y="{art_top:.1f}" class="art" font-size="{ART_FONT}px">')
    for i, line in enumerate(art):
        out.append(f'<tspan x="{pad}" y="{art_top + i * ART_LINE_H:.1f}">{escape(line)}</tspan>')
    out.append("</text>")
    out.append(f'<text x="{info_x:.0f}" y="{pad + 10}" class="text">')
    for i, line in enumerate(info):
        spans = "".join(f'<tspan class="{c}">{escape(s)}</tspan>' for s, c in line)
        out.append(f'<tspan x="{info_x:.0f}" y="{pad + 10 + i * LINE_H}">{spans}</tspan>')
    y = pad + 10 + (len(info) + 1) * LINE_H
    out.append(f'<tspan x="{info_x:.0f}" y="{y}"><tspan class="accent">&gt;</tspan>'
               f' <tspan class="accent cursor">█</tspan></tspan>')
    out.append("</text></svg>")
    return "\n".join(out)


ICONS = {
    # 24x24 stroke icons (generic, no brand logos)
    "mail": '<rect x="2" y="5" width="20" height="14" rx="2"/><path d="M2 7l10 7 10-7"/>',
    "briefcase": '<rect x="3" y="7" width="18" height="13" rx="2"/><path d="M8 7V5a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/>'
                 '<path d="M3 13h18"/>',
    "folder": '<path d="M3 6a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>'
              '<path d="M9 13l2 2 4-4"/>',
    "globe": '<circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/>',
    "file": '<path d="M6 2h8l5 5v15H6z"/><path d="M14 2v5h5M9 13h7M9 17h7"/>',
    "pen": '<path d="M4 20l4-1 11-11-3-3L5 16z"/><path d="M14 6l3 3"/>',
    "chat": '<path d="M4 5h16v11H9l-5 4z"/>',
    "code": '<path d="M8 7l-5 5 5 5M16 7l5 5-5 5M14 4l-4 16"/>',
}
ICONS.update({"email": ICONS["mail"], "linkedin": ICONS["briefcase"], "projects": ICONS["folder"],
              "website": ICONS["globe"], "cv": ICONS["file"], "blog": ICONS["pen"]})


def render_button(theme, icon, label):
    t = THEMES[theme]
    n = max(len(BUTTONS), 1)
    w, h = int(940 / n), 56
    text_w = len(label) * 10.8
    gx = (w - (28 + 14 + text_w)) / 2
    return (f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
            f'font-family="Consolas,\'DejaVu Sans Mono\',monospace">'
            f'<rect x="1" y="1" width="{w - 2}" height="{h - 2}" rx="6" fill="{t["btn_bg"]}" '
            f'stroke="{t["btn_border"]}" stroke-width="2"/>'
            f'<rect x="1" y="{h - 5}" width="{w - 2}" height="4" fill="{t["btn_bar"]}"/>'
            f'<g transform="translate({gx:.0f},{(h - 28) / 2 - 1:.0f}) scale(1.17)" fill="none" '
            f'stroke="{t["btn_icon"]}" stroke-width="2" stroke-linecap="round" '
            f'stroke-linejoin="round">{ICONS.get(icon, ICONS["globe"])}</g>'
            f'<text x="{gx + 42:.0f}" y="{h / 2 + 5:.0f}" font-size="18" letter-spacing="1" '
            f'fill="{t["btn_text"]}" font-weight="bold">{label}</text></svg>')


def card_width():
    art = [a.rstrip() for a in (ASSETS / "ascii.txt").read_text().split("\n")]
    cols = max(len(a) for a in art)
    return int(20 + cols * ART_CHAR_W + 28 + WIDTH * CHAR_W + 34)


def _dur(secs):
    m, s_ = divmod(int(secs), 60)
    return f"{m}m {s_:02d}s" if m else f"{s_}s"


def render_tests(theme, stats):
    """Playwright-style test report of the latest CI runs across your repos."""
    t = THEMES[theme]
    w = card_width()
    pad = 20
    cols = int((w - 2 * pad) / CHAR_W)
    tests = stats.get("tests") or []
    passed = sum(x["conclusion"] == "success" for x in tests)
    failed = sum(x["conclusion"] in ("failure", "timed_out", "startup_failure") for x in tests)
    skipped = len(tests) - passed - failed
    repos = len({x["repo"] for x in tests})
    total = sum(x["seconds"] for x in tests)
    upd = stats.get("updated", "")[:16].replace("T", " ")

    lines = []  # list of (symbol, symbol_class, segments)
    head = "$ run-tests --owner " + USER
    right = f"{upd} UTC" if upd else ""
    lines.append((None, None, [(head, "accent"), (" " * max(1, cols - len(head) - len(right)), "text"),
                               (right, "dots")]))
    lines.append((None, None, [(f"Running {len(tests)} checks across {repos} repositories", "text")]))
    lines.append((None, None, []))
    status_w = 15
    for x in tests:
        ok = x["conclusion"] == "success"
        bad = x["conclusion"] in ("failure", "timed_out", "startup_failure")
        sym, cls = ("✓", "add") if ok else ("✘", "dele") if bad else ("-", "dots")
        word = "passed" if ok else "failed" if bad else x["conclusion"].replace("_", " ")
        name = f"{x['repo']} › {x['workflow']}"
        tail = f"{word:>7}  {_dur(x['seconds']):>7}"
        room = cols - 4 - len(tail) - 2
        if len(name) > room - 4:
            name = name[: room - 5] + "…"
        dots = " " + "." * max(1, room - len(name) - 1) + " "
        rp, sep, wf = name.partition(" › ")
        lines.append((sym, cls, [(rp, "value"), (sep, "dots"), (wf, "text"),
                                 (dots, "dots"), (f"{word:>7}", cls), (f"  {_dur(x['seconds']):>7}", "dots")]))
    if not tests:
        lines.append((None, None, [("  no CI runs found yet", "dots")]))
    lines.append((None, None, []))
    summary = [(f"{passed} passed", "add"), (" · ", "dots"), (f"{failed} failed", "dele" if failed else "dots"),
               (" · ", "dots"), (f"{skipped} skipped", "dots")]
    stext = sum(len(a) for a, _ in summary)
    dur = f"Total: {_dur(total)}"
    lines.append((None, None, summary + [(" " * max(1, cols - 2 - stext - len(dur)), "text"), (dur, "dots")]))

    h = int(pad * 2 + len(lines) * LINE_H)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" xml:space="preserve" font-family="ConsolasFallback,Consolas,'
           f'\'DejaVu Sans Mono\',monospace" width="{w}px" height="{h}px" font-size="{FONT_SIZE}px">',
           "<style>",
           "@font-face{src:local('Consolas'),local('Consolas Bold');font-family:'ConsolasFallback';"
           "font-display:swap;-webkit-size-adjust:109%;size-adjust:109%;}",
           *[f".{c}{{fill:{t[c]};}}" for c in ("text", "key", "value", "dots", "add", "dele", "accent")],
           "</style>",
           f'<rect width="{w}px" height="{h}px" fill="{t["bg"]}" rx="15"/>']
    for i, (sym, scls, segs) in enumerate(lines):
        y = pad + 15 + i * LINE_H
        indent = 0
        if sym:
            out.append(f'<text x="{pad + 2 * CHAR_W:.1f}" y="{y}" class="{scls}">{sym}</text>')
            indent = 4
        spans = "".join(f'<tspan class="{c}">{escape(a)}</tspan>' for a, c in segs if a)
        if spans:
            out.append(f'<text x="{pad + indent * CHAR_W:.1f}" y="{y}" class="text">{spans}</text>')
    out.append("</svg>")
    return "\n".join(out)


def render_typing(theme):
    """Terminal-style typing header that cycles through TAGLINES."""
    t = THEMES[theme]
    size, cw = 22, 13.24           # font size and forced advance per character
    w, h = card_width(), 44
    x0 = 20 + 2 * cw              # room for the '> ' prompt
    type_t, hold_t, erase_t, gap_t = 0.055, 2.2, 0.025, 0.4   # seconds
    spans = []
    for ln in TAGLINES:
        n = len(ln)
        spans.append((ln, n, n * type_t, n * erase_t))
    cycle = sum(a + hold_t + b + gap_t for _, _, a, b in spans)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" viewBox="0 0 {w} {h}" '
           f'font-family="Consolas,\'DejaVu Sans Mono\',monospace" font-size="{size}">',
           f'<text x="20" y="30" fill="{t["accent"]}">&gt;</text>']
    start = 0.0
    for i, (ln, n, a, b) in enumerate(spans):
        # stepped clip width: 0 -> full (typing) -> hold -> full -> 0 (erasing) -> hidden
        times, widths = [0.0], [0.0]
        if start > 0:
            times.append(start / cycle); widths.append(0.0)
        for k in range(1, n + 1):
            times.append((start + k * (a / n)) / cycle); widths.append(k * cw)
        t_hold_end = start + a + hold_t
        times.append(t_hold_end / cycle); widths.append(n * cw)
        for k in range(n - 1, -1, -1):
            times.append((t_hold_end + (n - k) * (b / n)) / cycle); widths.append(k * cw)
        times.append(1.0); widths.append(0.0)
        kt = ";".join(f"{v:.4f}" for v in times)
        vals = ";".join(f"{v:.1f}" for v in widths)
        out.append(f'<clipPath id="c{i}"><rect x="{x0:.1f}" y="0" height="{h}" width="0">'
                   f'<animate attributeName="width" dur="{cycle:.2f}s" repeatCount="indefinite" '
                   f'calcMode="discrete" keyTimes="{kt}" values="{vals}"/></rect></clipPath>')
        out.append(f'<text x="{x0:.1f}" y="30" fill="{t["typing"]}" font-weight="{'bold' if theme == 'light' else 'normal'}" textLength="{n * cw:.1f}" '
                   f'lengthAdjust="spacingAndGlyphs" clip-path="url(#c{i})" xml:space="preserve">{escape(ln)}</text>')
        # cursor follows the active line and is only visible while it's active
        end = start + a + hold_t + b + gap_t
        ot, ov = [0.0], [1 if start == 0 else 0]
        if start > 0:
            ot.append(start / cycle); ov.append(1)
        if end < cycle - 1e-6:
            ot.append(end / cycle); ov.append(0)
        okt = ";".join(f"{v:.4f}" for v in ot)
        ovals = ";".join(str(v) for v in ov)
        cx = ";".join(f"{x0 + v:.1f}" for v in widths)
        out.append(f'<rect y="10" width="{cw * 0.6:.1f}" height="26" fill="{t["accent"]}" x="{x0:.1f}" opacity="0">'
                   f'<animate attributeName="x" dur="{cycle:.2f}s" repeatCount="indefinite" calcMode="discrete" '
                   f'keyTimes="{kt}" values="{cx}"/>'
                   f'<animate attributeName="opacity" dur="{cycle:.2f}s" repeatCount="indefinite" calcMode="discrete" '
                   f'keyTimes="{okt}" values="{ovals}"/></rect>')
        start += a + hold_t + b + gap_t
    out.append("</svg>")
    return "\n".join(out)


def _picture(name, alt, width="100%"):
    return (f'<picture><source media="(prefers-color-scheme: dark)" srcset="assets/{name}-dark.svg">'
            f'<source media="(prefers-color-scheme: light)" srcset="assets/{name}-light.svg">'
            f'<img alt="{escape(alt)}" src="assets/{name}-dark.svg" width="{width}"></picture>')


def readme_blocks():
    head = []
    if FEATURES["header"]:
        head.append(_picture("typing", " · ".join(TAGLINES)))
    if FEATURES["card"]:
        head.append(f'<a href="https://github.com/{USER}">{_picture("card", f"{USER} profile card")}</a>')
    if FEATURES["buttons"] and BUTTONS:
        pct = f"{int(97 / len(BUTTONS))}%"
        head.append("<p>\n" + "\n".join(
            f'  <a href="{escape(url)}">{_picture(f"btn-{i}", label, pct)}</a>'
            for i, (_, label, url) in enumerate(BUTTONS)) + "\n</p>")
    if FEATURES["tests"]:
        head.append(f'<a href="https://github.com/{USER}?tab=repositories">'
                    f'{_picture("tests", "Latest CI results across my repositories")}</a>')
    race = []
    if FEATURES["race"]:
        race.append("### 🏁 Contribution Grand Prix\n\n" +
                    _picture("race", "Arcade race through my contribution graph"))
    return {"header": "\n\n".join(head), "race": "\n\n".join(race)}


def update_readme():
    readme = ROOT / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else ""
    # First run in a profile repo (owner/owner): swap the template docs for a profile README
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    is_profile_repo = "/" in repo and repo.split("/")[0].lower() == repo.split("/")[1].lower()
    if "<!-- arcade:template-docs -->" in text and is_profile_repo:
        text = (ROOT / "README.profile.md").read_text(encoding="utf-8").replace("YOUR-USERNAME", USER)
        print("first run: README.md replaced with README.profile.md")
    for key, body in readme_blocks().items():
        start, end = f"<!-- arcade:{key}:start -->", f"<!-- arcade:{key}:end -->"
        if start in text and end in text:
            a = text.index(start) + len(start)
            b = text.index(end)
            text = text[:a] + "\n" + body + "\n" + text[b:]
    readme.write_text(text, encoding="utf-8")


def main():
    ASSETS.mkdir(exist_ok=True)
    from portrait import update as update_portrait
    update_portrait(ROOT, PORTRAIT)
    signs = (CONFIG.get("race") or {}).get("signs")
    if signs:
        import race
        race.VEGAS_WORDS = [str(w).upper()[:8] for w in signs]
    stats = load_stats()
    if "--fetch" in sys.argv:
        token = os.environ.get("GH_TOKEN")
        if not token:
            sys.exit("GH_TOKEN not set")
        stats = fetch_stats(token)
        STATS_FILE.write_text(json.dumps(stats, indent=2) + "\n")
        print("stats:", {k: v for k, v in stats.items() if k not in ("calendar", "tests")})
    for old in ASSETS.glob("btn-*.svg"):
        old.unlink()
    for theme in THEMES:
        (ASSETS / f"card-{theme}.svg").write_text(render_card(theme, stats))
        (ASSETS / f"tests-{theme}.svg").write_text(render_tests(theme, stats))
        (ASSETS / f"typing-{theme}.svg").write_text(render_typing(theme))
        (ASSETS / f"race-{theme}.svg").write_text(render_race(theme, stats, card_width(), USER, PLATE))
        for i, (icon, label, _) in enumerate(BUTTONS):
            (ASSETS / f"btn-{i}-{theme}.svg").write_text(render_button(theme, icon, label))
    update_readme()
    print("rendered", ", ".join(sorted(p.name for p in ASSETS.glob("*.svg"))))


if __name__ == "__main__":
    main()
