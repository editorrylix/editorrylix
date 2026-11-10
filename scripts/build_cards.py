#!/usr/bin/env python3
"""Render the profile README cards into cards/*.svg.

    python scripts/build_cards.py             animated cards
    STATIC=1 python scripts/build_cards.py    final frame, no animation (for screenshots)

GitHub shows the cards through <img>, where scripts and external files are
blocked. Each SVG is therefore self-contained: one inline <style> with CSS
keyframes, SMIL <animate> elements, and fonts subset with pyftsubset and
embedded as base64 WOFF. Colours and fonts follow lutherclips.app.

Needs fonttools. Pillow is optional and only used to shrink the portrait.
"""
import base64
import datetime as dt
import html
import io
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "cards"
DATA = ROOT / "data" / "contributions.json"
FONTS = ROOT / "fonts"
STATIC = os.environ.get("STATIC") == "1"

# ── Content ──────────────────────────────────────────────────────────────────
NAME = "Harsh Raj"
ABOUT = "I build backends, automation and data systems. CS & Data Analytics at IIT Patna."
PORTRAIT = ROOT / "assets" / "portrait.jpg"  # optional: add the file and it appears in the hero

# (card file, title, small line). The links themselves live in README.md.
TILES = [
    ("luther", "Luther", "lutherclips.app"),
    ("linkedin", "LinkedIn", "Harsh Raj"),
    ("instagram", "Instagram", "@harxsh.py"),
]

# Featured repos, in display order. Stars, language and description come from
# the JSON; the text here is used when a repo has no description on GitHub.
FEATURED = {
    "nexus-ai-lecture-studio": "Local-first lecture and meeting studio: on-device transcription, study guides, Anki decks.",
    "shorts-clipper-bot": "Discord-controlled bot that watches YouTube channels and archives new Shorts to Google Drive.",
    "InstaViewBot": "Pulls view and engagement metrics for Instagram Reels through an API.",
}

# ── Look: taken from lutherclips.app ─────────────────────────────────────────
BG = "#000000"      # page
PANEL = "#111115"   # card surface
LINE = "#242223"    # card border
INK = "#FFFFFF"
SOFT = "#E4E4E7"
MUTED = "#A1A1AA"
DIM = "#8A8A8A"
BRAND = "#615FFF"   # indigo, the contribution colour
BRAND_LIGHT = "#7C86FF"
BRAND_DEEP = "#4F39F6"
PURPLE = "#AD46FF"  # far end of the site's indigo-to-purple gradient
EMPTY = "#1B1B20"   # a day with no contributions

W = 846             # width of a README column on github.com
R = 16              # card corner radius

# face key -> (CSS family, file in fonts/, weight)
FACES = {
    "r": ("Geist", "Geist-Regular.ttf", 400),
    "m": ("Geist", "Geist-Medium.ttf", 500),
    "b": ("Geist", "Geist-Bold.ttf", 700),
    "c": ("Geist Mono", "GeistMono-Medium.ttf", 500),
}
FALLBACK = {"Geist": "Inter,system-ui,sans-serif", "Geist Mono": "ui-monospace,monospace"}

MOTION_CSS = """
@keyframes in{from{opacity:0;transform:translateX(-12px)}}
@keyframes fade{from{opacity:0}}
@keyframes grow{from{transform:scaleY(0)}}
.grow{transform-box:fill-box;transform-origin:50% 100%}
.wipe{clip-path:url(#wipe)}
.st{display:none}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.mo{display:none}.st{display:inline}.wipe{clip-path:none}}
"""
EASE = "cubic-bezier(.2,.7,.2,1)"


# ── Fonts: measuring and subsetting ──────────────────────────────────────────
class Metrics:
    """Advance widths from the full font, so text can be fitted and aligned."""

    def __init__(self, file):
        font = TTFont(FONTS / file)
        self.cmap = font.getBestCmap()
        self.hmtx = font["hmtx"]
        self.upm = font["head"].unitsPerEm

    def width(self, s, size, spacing=0.0):
        units = sum(self.hmtx[self.cmap.get(ord(ch), ".notdef")][0] for ch in s)
        return units * size / self.upm + spacing * len(s)


METRICS = {key: Metrics(file) for key, (_, file, _) in FACES.items()}


def width(s, face, size, spacing=0.0):
    return METRICS[face].width(s, size, spacing)


def fit(s, face, size, max_w):
    """One line, cut with an ellipsis if it would overflow."""
    if width(s, face, size) <= max_w:
        return s
    while s and width(s.rstrip() + "…", face, size) > max_w:
        s = s[:-1]
    return s.rstrip(" ,.;:") + "…"


def balance(s, face, size, max_w):
    """One line if it fits, otherwise two lines of roughly equal length."""
    if width(s, face, size) <= max_w:
        return [s]
    words = s.split()
    splits = [(" ".join(words[:i]), " ".join(words[i:])) for i in range(1, len(words))]
    a, b = min(splits, key=lambda p: max(width(p[0], face, size), width(p[1], face, size)))
    return [fit(a, face, size, max_w), fit(b, face, size, max_w)]


def woff_base64(file, chars):
    """Subset one font to the characters a card uses (pyftsubset), as base64 WOFF."""
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "subset.woff"
        subprocess.run(
            [
                sys.executable, "-m", "fontTools.subset",  # the module behind `pyftsubset`
                str(FONTS / file),
                "--unicodes=" + ",".join(f"U+{ord(ch):04X}" for ch in sorted(chars)),
                "--flavor=woff",
                "--layout-features=kern",
                "--no-hinting",
                "--drop-tables+=meta",
                "--no-recalc-timestamp",  # same input, same bytes: no daily churn
                f"--output-file={out}",
            ],
            check=True,
        )
        return base64.b64encode(out.read_bytes()).decode()


# ── Card builder ─────────────────────────────────────────────────────────────
def anim(name, delay, dur=0.6, ease=EASE):
    """Inline animation style. Elements rest in their final state, so the
    keyframes only describe where they come from."""
    return "" if STATIC else f' style="animation:{name} {dur:g}s {ease} {delay:.2f}s both"'


class Card:
    def __init__(self, w, h, fill=PANEL, gutter=0):
        """gutter: transparent margin left and right of the card surface."""
        self.w, self.h = w, h
        self.defs, self.body, self.used = [], [], {}
        self.add(f'<rect x="{gutter + .5}" y=".5" width="{w - 2 * gutter - 1}" height="{h - 1}" rx="{R}" fill="{fill}" stroke="{LINE}"/>')

    def add(self, svg):
        self.body.append(svg)

    def motion_only(self, svg):
        """Shown while animating; hidden under prefers-reduced-motion and in STATIC."""
        if not STATIC:
            self.add(f'<g class="mo">{svg}</g>')

    def text(self, x, y, s, face="r", size=14, fill=INK, anchor="start", spacing=0.0):
        self.used.setdefault(face, set()).update(s)
        extra = (f' text-anchor="{anchor}"' if anchor != "start" else "") + (
            f' letter-spacing="{spacing:.2f}"' if spacing else ""
        )
        return f'<text class="{face}" x="{x:.1f}" y="{y:.1f}" font-size="{size:g}" fill="{fill}"{extra}>{html.escape(s)}</text>'

    def playhead(self, x0, x1, y0, y1, begin, dur, spline=None):
        """SMIL: a thin gradient line that scrubs across, like a video playhead."""
        if STATIC:
            return
        self.defs.append(
            '<linearGradient id="ph" x1="0" y1="0" x2="0" y2="1">'
            f'<stop offset="0" stop-color="{BRAND_LIGHT}" stop-opacity="0"/><stop offset=".3" stop-color="{BRAND_LIGHT}"/>'
            f'<stop offset=".7" stop-color="{PURPLE}"/><stop offset="1" stop-color="{PURPLE}" stop-opacity="0"/></linearGradient>'
        )
        timing = f'begin="{begin:.2f}s" dur="{dur:g}s" fill="freeze"'
        self.motion_only(
            f'<rect x="{x0:.1f}" y="{y0}" width="2" height="{y1 - y0}" fill="url(#ph)" opacity="0">'
            f'<animate attributeName="x" from="{x0:.1f}" to="{x1:.1f}" {timing}{spline or ""}/>'
            f'<animate attributeName="opacity" values="0;1;1;0" keyTimes="0;.06;.8;1" {timing}/></rect>'
        )

    def render(self):
        faces = []
        for key in sorted(self.used):
            family, file, weight = FACES[key]
            faces.append(
                f"@font-face{{font-family:'{family}';font-weight:{weight};"
                f"src:url(data:font/woff;base64,{woff_base64(file, self.used[key])}) format('woff')}}"
                f".{key}{{font-family:'{family}',{FALLBACK[family]};font-weight:{weight}}}"
            )
        css = "".join(faces) + ("" if STATIC else MOTION_CSS.replace("\n", ""))
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{self.h}" viewBox="0 0 {self.w} {self.h}">'
            f"<style>{css}</style><defs>{''.join(self.defs)}</defs>{''.join(self.body)}</svg>\n"
        )


# ── Data ─────────────────────────────────────────────────────────────────────
LEVELS = ["NONE", "FIRST_QUARTILE", "SECOND_QUARTILE", "THIRD_QUARTILE", "FOURTH_QUARTILE"]


def load():
    """data/contributions.json is the GraphQL response the workflow saves."""
    user = json.loads(DATA.read_text())["data"]["user"]
    calendar = user["contributionsCollection"]["contributionCalendar"]
    weeks = [
        [(dt.date.fromisoformat(d["date"]), d["contributionCount"], LEVELS.index(d["contributionLevel"]))
         for d in week["contributionDays"]]
        for week in calendar["weeks"]
    ]
    repos = {r["name"]: r for r in user["repositories"]["nodes"]}
    return weeks, calendar["totalContributions"], repos


def streaks(days):
    """(current, longest) runs of consecutive days with a contribution."""
    longest = run = 0
    for _, count, _ in days:
        run = run + 1 if count else 0
        longest = max(longest, run)
    counts = [count for _, count, _ in days]
    if counts and counts[-1] == 0:  # today isn't over, so an empty today doesn't break the streak
        counts.pop()
    current = 0
    while current < len(counts) and counts[-1 - current]:
        current += 1
    return current, longest


def short(day):
    return f"{day:%b} {day.day}"


def plural(n, word):
    return f"{n:,} {word}" + ("" if n == 1 else "s")


def mix(a, b, t):
    """Blend hex colour b towards a by t."""
    pa, pb = (int(a[i:i + 2], 16) for i in (1, 3, 5)), (int(b[i:i + 2], 16) for i in (1, 3, 5))
    return "#" + "".join(f"{round(y + (x - y) * t):02X}" for x, y in zip(pa, pb))


# ── Cards ────────────────────────────────────────────────────────────────────
def portrait_uri(size):
    if not PORTRAIT.exists():
        return None
    raw, mime = PORTRAIT.read_bytes(), "image/png" if PORTRAIT.suffix.lower() == ".png" else "image/jpeg"
    try:  # square-crop and shrink to 2x the display size when Pillow is around
        from PIL import Image, ImageOps

        img = ImageOps.fit(ImageOps.exif_transpose(Image.open(PORTRAIT)).convert("RGB"), (size * 2, size * 2))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=86)
        raw, mime = buf.getvalue(), "image/jpeg"
    except ImportError:
        pass
    return f"data:{mime};base64,{base64.b64encode(raw).decode()}"


def hero(t0):
    h, pad, photo = 240, 40, 160
    c = Card(W, h, fill=BG)
    c.defs.append(
        '<radialGradient id="glow" cx=".88" cy="0" r=".9">'
        f'<stop offset="0" stop-color="{BRAND_DEEP}" stop-opacity=".5"/><stop offset=".55" stop-color="{BRAND_DEEP}" stop-opacity=".1"/>'
        f'<stop offset="1" stop-color="{BRAND_DEEP}" stop-opacity="0"/></radialGradient>'
    )
    c.add(f'<rect x="1" y="1" width="{W - 2}" height="{h - 2}" rx="{R - 1}" fill="url(#glow)"/>')

    uri = portrait_uri(photo)
    text_w = W - 2 * pad - (photo + 32 if uri else 0)
    size = min(84, 84 * text_w / width(NAME, "b", 84, -0.05 * 84))  # the site sets headlines at -0.05em
    lines = balance(ABOUT, "m", 18, text_w)
    y = 128 if len(lines) == 1 else 114
    parts = [c.text(pad, y, NAME, "b", size, INK, spacing=-0.05 * size)]
    parts += [c.text(pad, y + 44 + 26 * i, line, "m", 18, MUTED) for i, line in enumerate(lines)]
    if uri:
        x, top = W - pad - photo, (h - photo) / 2
        c.defs.append(f'<clipPath id="photo"><rect x="{x}" y="{top}" width="{photo}" height="{photo}" rx="24"/></clipPath>')
        parts.append(
            f'<image href="{uri}" x="{x}" y="{top}" width="{photo}" height="{photo}" clip-path="url(#photo)" preserveAspectRatio="xMidYMid slice"/>'
            f'<rect x="{x + .5}" y="{top + .5}" width="{photo - 1}" height="{photo - 1}" rx="24" fill="none" stroke="{INK}" stroke-opacity=".12"/>'
        )

    if STATIC:
        c.add("".join(parts))
    else:
        # SMIL widens a clip rectangle in step with the playhead. The rectangle
        # rests at full width, so the text shows even where SMIL doesn't run.
        spline = ' calcMode="spline" keyTimes="0;1" keySplines=".3 0 .1 1"'
        c.defs.append(
            f'<clipPath id="wipe"><rect x="0" y="0" width="{W}" height="{h}">'
            f'<animate attributeName="width" from="0" to="{W}" begin="{t0:.2f}s" dur="1.2s" fill="freeze"{spline}/></rect></clipPath>'
        )
        c.add(f'<g class="wipe">{"".join(parts)}</g>')
        c.playhead(0, W - 2, 1, h - 1, t0, 1.2, spline)
    return c


def tile(title, sub, delay):
    # 32.5% of the column. The README puts the three tiles side by side with no
    # space between the tags (a space would wrap the row on phones), so the gap
    # between them is the gutter drawn into each tile.
    w, h, gutter = 275, 92, 3
    c = Card(w, h, gutter=gutter)
    x = gutter + 21
    c.add(
        f"<g{anim('in', delay)}>" + c.text(x, 43, title, "b", 19, INK, spacing=-0.4) + c.text(x, 66, sub, "m", 13, MUTED)
        + f'<path d="M{w - x - 12} 36 l10 -10 m-7.5 0 h7.5 v7.5" fill="none" stroke="{BRAND_LIGHT}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"/></g>'
    )
    return c


def months(weeks, t0):
    days = [d for week in weeks for d in week]
    h = 292
    c = Card(W, h)
    per_month = {}
    for day, count, _ in days:
        per_month[(day.year, day.month)] = per_month.get((day.year, day.month), 0) + count
    peak = max(per_month.values()) or 1

    x0, x1, base, top, sweep = 32, 548, 232, 86, 0.9
    pitch, bar_w = (x1 - x0) / len(per_month), 24
    c.defs.append(
        f'<linearGradient id="bar" gradientUnits="userSpaceOnUse" x1="0" y1="{top}" x2="0" y2="{base}">'
        f'<stop offset="0" stop-color="{PURPLE}"/><stop offset=".45" stop-color="{BRAND}"/><stop offset="1" stop-color="{BRAND_DEEP}"/></linearGradient>'
    )
    c.add(c.text(x0, 46, "Contributions per month", "m", 14, MUTED))
    c.add(f'<rect x="{x0}" y="{base}" width="{x1 - x0}" height="1" fill="{LINE}"/>')

    for i, ((year, month), n) in enumerate(per_month.items()):
        cx = x0 + pitch * (i + 0.5)
        delay = t0 + sweep * (i + 0.5) / len(per_month)
        label = dt.date(year, month, 1)
        c.add(c.text(cx, base + 21, f"{label:%b}", "m", 11.5, MUTED, "middle"))
        if i == 0 or month == 1:
            c.add(c.text(cx, base + 36, str(year), "r", 10.5, DIM, "middle"))
        if n == 0:
            c.add(f'<rect x="{cx - bar_w / 2:.1f}" y="{base - 3}" width="{bar_w}" height="3" rx="1.5" fill="#2E2E33"/>')
            continue
        bar_h = max(6, (base - top) * n / peak)
        c.add(
            f'<rect class="grow" x="{cx - bar_w / 2:.1f}" y="{base - bar_h:.1f}" width="{bar_w}" height="{bar_h:.1f}" rx="{min(6, bar_h / 2):.1f}" fill="url(#bar)"{anim("grow", delay, 0.7)}/>'
            f"<g{anim('fade', delay + 0.4, 0.4)}>{c.text(cx, base - bar_h - 8, f'{n:,}', 'm', 11.5, SOFT, 'middle')}</g>"
        )
    c.playhead(x0, x1 - 2, 62, base, t0, sweep)

    current, longest = streaks(days)
    busiest = max(days, key=lambda d: d[1])
    active = sum(1 for _, count, _ in days if count)
    stats = [
        ("Current streak", plural(current, "day"), f"longest {longest:,}"),
        ("Active days", f"{active:,}", f"of the last {len(days)}"),
        ("Busiest day", f"{busiest[1]:,}", f"on {short(busiest[0])}"),
    ]
    sx = 612
    c.add(f'<rect x="580" y="32" width="1" height="{h - 64}" fill="{LINE}"/>')
    for i, (label, value, detail) in enumerate(stats):
        y = 62 + 80 * i
        if i:
            c.add(f'<rect x="{sx}" y="{y - 32}" width="{W - 32 - sx}" height="1" fill="{LINE}"/>')
        room = W - 32 - sx - width(value, "b", 26, -0.8) - 10
        c.add(
            f"<g{anim('in', t0 + 0.25 + 0.15 * i)}>" + c.text(sx, y, label, "m", 13, MUTED)
            + c.text(sx, y + 32, value, "b", 26, INK, spacing=-0.8)
            + c.text(sx + width(value, "b", 26, -0.8) + 10, y + 32, fit(detail, "r", 13, room), "r", 13, DIM) + "</g>"
        )
    return c


def repo(name, info, fallback, delay):
    h = 100
    c = Card(W, h)
    right = W - 32
    lang = info.get("primaryLanguage") or {}
    meta, x = [], right
    stars = f"{info.get('stargazerCount', 0):,}"
    x -= width(stars, "m", 13)
    meta.append(c.text(x, 70, stars, "m", 13, MUTED))
    x -= 19
    meta.append(  # star
        f'<path transform="translate({x:.1f} 58.5)" d="M7 1.2l1.8 3.7 4 .6-2.9 2.9.7 4L7 10.5l-3.6 1.9.7-4L1.2 5.5l4-.6z" fill="none" stroke="{MUTED}" stroke-width="1.3" stroke-linejoin="round"/>'
    )
    if lang.get("name"):
        lx = right - width(lang["name"], "m", 13)
        meta.append(c.text(lx, 44, lang["name"], "m", 13, SOFT))
        meta.append(f'<circle cx="{lx - 11:.1f}" cy="39.5" r="4" fill="{lang.get("color") or BRAND}"/>')
    desc = fit(info.get("description") or fallback, "r", 14, x - 32 - 40)
    c.add(f"<g{anim('in', delay)}>" + c.text(32, 44, name, "c", 16, INK, spacing=-0.3) + c.text(32, 70, desc, "r", 14, MUTED) + "</g>")
    c.add(f"<g{anim('fade', delay + 0.2)}>{''.join(meta)}</g>")
    return c


def graph(weeks, total, t0):
    cell, gap = 12, 3
    step = cell + gap
    left = (W - (len(weeks) * step - gap)) / 2
    top, sweep = 84, 1.2
    h = top + 7 * step - gap + 26
    c = Card(W, h)
    fills = [EMPTY] + [mix(BRAND, PANEL, t) for t in (0.3, 0.52, 0.76, 1)]
    right = left + len(weeks) * step - gap

    c.add(c.text(left, 46, f"{plural(total, 'contribution')} in the last year", "m", 14, MUTED))
    x = right - width("More", "r", 12)
    c.add(c.text(x, 46, "More", "r", 12, DIM))
    for i, fill in enumerate(reversed(fills)):
        x_cell = x - 7 - cell - i * step
        c.add(f'<rect x="{x_cell:.1f}" y="35" width="{cell}" height="{cell}" rx="3" fill="{fill}"/>')
    c.add(c.text(x_cell - 7, 46, "Less", "r", 12, DIM, "end"))

    # Month names sit over the first week of each month; drop one that would
    # collide with the next (a clipped first column, usually).
    marks = [i for i, week in enumerate(weeks) if i == 0 or week[0][0].month != weeks[i - 1][0][0].month]
    marks = [i for n, i in enumerate(marks) if n + 1 == len(marks) or marks[n + 1] - i >= 3]
    for i in marks:
        if left + i * step + 24 <= right:
            c.add(c.text(left + i * step, top - 10, f"{weeks[i][0][0]:%b}", "r", 11.5, DIM))

    for i, week in enumerate(weeks):
        x_col = left + i * step
        cells = "".join(
            f'<rect x="{x_col:.1f}" y="{top + ((day.weekday() + 1) % 7) * step}" width="{cell}" height="{cell}" rx="3" fill="{fills[level]}"/>'
            for day, _, level in week
        )
        c.add(f"<g{anim('fade', t0 + sweep * i / len(weeks), 0.35, 'ease-out')}>{cells}</g>")
    c.playhead(left - 2, right, top - 6, h - 20, t0, sweep)
    return c


# ── Build ────────────────────────────────────────────────────────────────────
def main():
    weeks, total, repos = load()
    # Start times, staggered so the page plays from the top card to the bottom one.
    cards = {"hero": hero(0.1)}
    for i, (slug, title, sub) in enumerate(TILES):
        cards[f"tile-{slug}"] = tile(title, sub, 0.9 + 0.12 * i)
    cards["months"] = months(weeks, 1.5)
    for i, (name, fallback) in enumerate(FEATURED.items()):
        cards[f"repo-{name.lower()}"] = repo(name, repos.get(name, {}), fallback, 2.5 + 0.15 * i)
    cards["graph"] = graph(weeks, total, 3.1)

    OUT.mkdir(exist_ok=True)
    for stale in OUT.glob("*.svg"):
        if stale.stem not in cards:
            stale.unlink()
    for name, card in cards.items():
        path = OUT / f"{name}.svg"
        path.write_text(card.render(), encoding="utf-8")
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.1f} kB")
    print("static frame" if STATIC else "animated")


if __name__ == "__main__":
    main()
