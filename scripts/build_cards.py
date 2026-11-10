#!/usr/bin/env python3
"""Render the profile README cards into cards/*.svg.

    python scripts/build_cards.py             animated cards
    STATIC=1 python scripts/build_cards.py    final frame, no animation (for screenshots)

The profile is drawn as a rack of hardware modules: aluminium faceplates,
black display glass, amber LEDs. The name is a dot-matrix display, the
contribution graph is the same matrix one year wide, the monthly counts are
level meters and the numbers are seven-segment readouts.

GitHub shows the cards through <img>, where scripts and external files are
blocked. Each SVG is therefore self-contained: one inline <style> with CSS
keyframes, SMIL <animate> elements, and fonts subset with pyftsubset and
embedded as base64 WOFF.

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
ABOUT = ("I build backends, automation and data systems.", "CS & Data Analytics at IIT Patna")
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
    "Pouchy": "Shake your mouse, park anything, drop it anywhere. A drop shelf for Windows 10 and 11.",
    "nexus-ai-lecture-studio": "Local-first lecture and meeting studio: on-device transcription, study guides, Anki decks.",
    "shorts-clipper-bot": "Discord-controlled bot that watches YouTube channels and archives new Shorts to Google Drive.",
    "InstaViewBot": "Pulls view and engagement metrics for Instagram Reels through an API.",
}

# ── Look ─────────────────────────────────────────────────────────────────────
PLATE_HI = "#E6E7E2"   # faceplate, top of the sheet
PLATE_LO = "#CFD0CA"   # faceplate, bottom
EDGE = "#9C9D97"       # faceplate outline, recess edges
INK = "#171816"        # silk-screened text
INK_SOFT = "#575953"
GLASS = "#0A0B0A"      # display window
LED_OFF = "#1E201D"    # an unlit LED
AMBER = "#FF9A1F"      # a lit LED
HOT = "#FFD79A"        # the brightest LEDs, and the flash as one switches on
RED = "#FF4A2E"        # top of the level meters
# Contribution levels 0-4, off to brightest.
LEVEL_LED = [LED_OFF, "#6B3C0A", "#B25E0A", "#F4890C", "#FFCB73"]
# Key caps and repo stripes: (face, skirt, text on it).
CAPS = [("#FF5A1F", "#B83A0A", INK), ("#FFC42E", "#BD8B00", INK), ("#2B66DD", "#17409A", "#FFFFFF")]

W = 846             # width of a README column on github.com
R = 14              # faceplate corner radius
PAD = 28            # faceplate edge to content
PITCH = 14          # LED spacing in the two matrix displays

# face key -> (CSS family, file in fonts/, weight)
FACES = {
    "r": ("Barlow Semi Condensed", "BarlowSemiCondensed-Regular.ttf", 400),
    "m": ("Barlow Semi Condensed", "BarlowSemiCondensed-Medium.ttf", 500),
    "s": ("Barlow Semi Condensed", "BarlowSemiCondensed-SemiBold.ttf", 600),
    "b": ("Barlow Semi Condensed", "BarlowSemiCondensed-Bold.ttf", 700),
}
FALLBACK = "'Arial Narrow',system-ui,sans-serif"

MOTION_CSS = """
@keyframes fade{from{opacity:0}}
@keyframes lit{0%{opacity:0}35%{opacity:1;stroke:#FFF;fill:#FFF}}
@keyframes press{0%,100%{transform:translateY(0)}45%{transform:translateY(7px)}}
@keyframes pulse{50%{opacity:.35}}
.st{display:none}
@media (prefers-reduced-motion:reduce){*{animation:none!important}.mo{display:none}.st{display:inline}}
"""
EASE = "cubic-bezier(.2,.7,.2,1)"

# 5x7 dot-matrix alphabet, one string per row.
FONT_5X7 = {
    "A": ".###. #...# #...# ##### #...# #...# #...#",
    "B": "####. #...# #...# ####. #...# #...# ####.",
    "C": ".###. #...# #.... #.... #.... #...# .###.",
    "D": "####. #...# #...# #...# #...# #...# ####.",
    "E": "##### #.... #.... ####. #.... #.... #####",
    "F": "##### #.... #.... ####. #.... #.... #....",
    "G": ".###. #...# #.... #.### #...# #...# .###.",
    "H": "#...# #...# #...# ##### #...# #...# #...#",
    "I": ".###. ..#.. ..#.. ..#.. ..#.. ..#.. .###.",
    "J": "..### ...#. ...#. ...#. ...#. #..#. .##..",
    "K": "#...# #..#. #.#.. ##... #.#.. #..#. #...#",
    "L": "#.... #.... #.... #.... #.... #.... #####",
    "M": "#...# ##.## #.#.# #.#.# #...# #...# #...#",
    "N": "#...# ##..# #.#.# #..## #...# #...# #...#",
    "O": ".###. #...# #...# #...# #...# #...# .###.",
    "P": "####. #...# #...# ####. #.... #.... #....",
    "Q": ".###. #...# #...# #...# #.#.# #..#. .##.#",
    "R": "####. #...# #...# ####. #.#.. #..#. #...#",
    "S": ".#### #.... #.... .###. ....# ....# ####.",
    "T": "##### ..#.. ..#.. ..#.. ..#.. ..#.. ..#..",
    "U": "#...# #...# #...# #...# #...# #...# .###.",
    "V": "#...# #...# #...# #...# #...# .#.#. ..#..",
    "W": "#...# #...# #...# #.#.# #.#.# ##.## #...#",
    "X": "#...# #...# .#.#. ..#.. .#.#. #...# #...#",
    "Y": "#...# #...# .#.#. ..#.. ..#.. ..#.. ..#..",
    "Z": "##### ....# ...#. ..#.. .#... #.... #####",
    "0": ".###. #...# #..## #.#.# ##..# #...# .###.",
    "1": "..#.. .##.. ..#.. ..#.. ..#.. ..#.. .###.",
    "2": ".###. #...# ....# ...#. ..#.. .#... #####",
    "3": "##### ...#. ..#.. ...#. ....# #...# .###.",
    "4": "...#. ..##. .#.#. #..#. ##### ...#. ...#.",
    "5": "##### #.... ####. ....# ....# #...# .###.",
    "6": "..##. .#... #.... ####. #...# #...# .###.",
    "7": "##### ....# ...#. ..#.. .#... .#... .#...",
    "8": ".###. #...# #...# .###. #...# #...# .###.",
    "9": ".###. #...# #...# .#### ....# ...#. .##..",
    "-": "..... ..... ..... ##### ..... ..... .....",
    ".": "..... ..... ..... ..... ..... .##.. .##..",
    "'": "..#.. ..#.. ..... ..... ..... ..... .....",
}

# Seven-segment digits: which of segments a-g are lit.
SEGMENTS = {"0": "abcdef", "1": "bc", "2": "abged", "3": "abgcd", "4": "fgbc",
            "5": "afgcd", "6": "afgedc", "7": "abc", "8": "abcdefg", "9": "abcdfg"}


def n(x):
    """A number as short as SVG allows."""
    return f"{x:.1f}".rstrip("0").rstrip(".")


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


def printable(s, face):
    """Drop characters the font can't draw (emoji, mostly) and tidy the spaces left behind."""
    return " ".join("".join(ch for ch in s if ch == " " or ord(ch) in METRICS[face].cmap).split())


def fit(s, face, size, max_w):
    """One line, cut with an ellipsis if it would overflow."""
    if width(s, face, size) <= max_w:
        return s
    while s and width(s.rstrip() + "…", face, size) > max_w:
        s = s[:-1]
    return s.rstrip(" ,.;:") + "…"


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
    keyframes only describe where they come from. Only LEDs and keys move;
    text printed on the faceplate stays put."""
    return "" if STATIC else f' style="animation:{name} {dur:g}s {ease} {delay:.2f}s both"'


def dots(points, d, colour, extra=""):
    """Round LEDs as one path: zero-length strokes with round caps."""
    path = "".join(f"M{n(x)} {n(y)}h0" for x, y in points)
    return f'<path d="{path}" stroke="{colour}" stroke-width="{n(d)}" stroke-linecap="round" fill="none"{extra}/>'


class Card:
    def __init__(self, w, h, plate=True, screws=True):
        self.w, self.h = w, h
        self.defs, self.body, self.used = [], [], {}
        if not plate:
            return
        self.defs.append(
            f'<linearGradient id="pl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{PLATE_HI}"/><stop offset="1" stop-color="{PLATE_LO}"/></linearGradient>'
            # brushed metal: faint horizontal grain
            '<pattern id="gr" width="7" height="3" patternUnits="userSpaceOnUse"><rect width="7" height="1" fill="#000" opacity=".028"/></pattern>'
            f'<clipPath id="pc"><rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{R}"/></clipPath>'
            '<radialGradient id="sc" cx=".35" cy=".3" r=".8"><stop offset="0" stop-color="#F2F2EE"/><stop offset="1" stop-color="#A9AAA4"/></radialGradient>'
            '<linearGradient id="gl" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#FFF" stop-opacity=".09"/><stop offset=".5" stop-color="#FFF" stop-opacity="0"/></linearGradient>'
        )
        self.add(
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{R}" fill="url(#pl)" stroke="{EDGE}"/>'
            f'<rect x=".5" y=".5" width="{w - 1}" height="{h - 1}" rx="{R}" fill="url(#gr)"/>'
            f'<rect x="1.5" y="1.5" width="{w - 3}" height="{h - 3}" rx="{R - 1}" fill="none" stroke="#FFF" stroke-opacity=".6"/>'
        )
        if screws:
            for i, (x, y) in enumerate([(14, 14), (w - 14, 14), (14, h - 14), (w - 14, h - 14)]):
                self.add(
                    f'<g transform="translate({x} {y}) rotate({(37 + 61 * i) % 180})"><circle r="4.5" fill="url(#sc)" stroke="{EDGE}"/>'
                    f'<path d="M-3 0h6" stroke="#6F706B" stroke-width="1.3" stroke-linecap="round"/></g>'
                )

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

    def glass(self, x, y, w, h, rx=9):
        """A display window let into the faceplate."""
        self.add(
            f'<rect x="{n(x - 1.5)}" y="{n(y - 1.5)}" width="{n(w + 3)}" height="{n(h + 3)}" rx="{rx + 1.5}" fill="none" stroke="#FFF" stroke-opacity=".7"/>'
            f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{rx}" fill="{GLASS}" stroke="#55564F"/>'
            f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" rx="{rx}" fill="url(#gl)"/>'
        )

    def blur(self, name, x, y, w, h, deviation):
        self.defs.append(
            f'<filter id="{name}" filterUnits="userSpaceOnUse" x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"><feGaussianBlur stdDeviation="{deviation}"/></filter>'
        )

    def readout(self, x, y, value, digits, delay, dh=30):
        """A seven-segment number in its own window. Returns the window's width."""
        dw, t, gap, pad = dh * 0.56, dh * 0.13, dh * 0.3, 11
        w, h = digits * dw + (digits - 1) * gap + 2 * pad + 4, dh + 2 * pad
        self.glass(x, y, w, h, rx=7)

        def segments(ox, which):
            hx0, hx1, s = t / 2 + 0.9, dw - t / 2 - 0.9, t / 2
            out = []
            for name, yc in (("a", s), ("g", dh / 2), ("d", dh - s)):
                if name in which:
                    out.append(f"M{n(ox + hx0)} {n(yc)}l{n(s)} {n(-s)}h{n(hx1 - hx0 - t)}l{n(s)} {n(s)}l{n(-s)} {n(s)}h{n(-(hx1 - hx0 - t))}z")
            half = dh / 2
            for name, xc, y0 in (("f", s, s), ("b", dw - s, s), ("e", s, half), ("c", dw - s, half)):
                if name in which:
                    y0, y1 = y0 + 0.9, y0 + half - s - 0.9
                    out.append(f"M{n(ox + xc)} {n(y0)}l{n(s)} {n(s)}v{n(y1 - y0 - t)}l{n(-s)} {n(s)}l{n(-s)} {n(-s)}v{n(-(y1 - y0 - t))}z")
            return "".join(out)

        shown = str(value)[-digits:].rjust(digits)
        ghost = "".join(segments(i * (dw + gap), "abcdefg") for i in range(digits))
        lit = "".join(segments(i * (dw + gap), SEGMENTS[ch]) for i, ch in enumerate(shown) if ch in SEGMENTS)
        self.add(
            f'<g transform="translate({n(x + pad + 4)} {n(y + pad)}) skewX(-7)"><path d="{ghost}" fill="{LED_OFF}"/>'
            f'<path d="{lit}" fill="{AMBER}"{anim("lit", delay, 0.5)}/></g>'
        )
        return w

    def lamp(self, cx, cy, colour, r=5):
        """A round indicator LED in a bezel."""
        return (
            f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{r + 2.5}" fill="#2A2B28" stroke="{EDGE}"/>'
            f'<circle cx="{n(cx)}" cy="{n(cy)}" r="{r}" fill="{colour}"/>'
            f'<circle cx="{n(cx - r * .3)}" cy="{n(cy - r * .35)}" r="{n(r * .32)}" fill="#FFF" opacity=".55"/>'
        )

    def render(self):
        faces = []
        for key in sorted(self.used):
            family, file, weight = FACES[key]
            faces.append(
                f"@font-face{{font-family:'{family}';font-weight:{weight};"
                f"src:url(data:font/woff;base64,{woff_base64(file, self.used[key])}) format('woff')}}"
                f".{key}{{font-family:'{family}',{FALLBACK};font-weight:{weight}}}"
            )
        css = "".join(faces) + ("" if STATIC else MOTION_CSS.replace("\n", ""))
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" width="{self.w}" height="{n(self.h)}" viewBox="0 0 {self.w} {n(self.h)}">'
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


def plural(count, word):
    return f"{count:,} {word}" + ("" if count == 1 else "s")


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


def matrix_points(text, x, y, pitch):
    """LED centres for text in the 5x7 alphabet, grouped by column."""
    columns = []
    for i, ch in enumerate(text.upper()):
        rows = FONT_5X7.get(ch, "").split()
        for col in range(5):
            columns.append([(x + (6 * i + col) * pitch, y + r * pitch) for r, row in enumerate(rows) if row[col] == "#"])
        columns.append([])
    return columns[:-1]


def hero(t0):
    rows = 9  # seven for the letters, one spare above and below
    cols = 6 * len(NAME) - 1
    gx, gy = PAD, PAD
    uri = portrait_uri(150)
    gw = W - 2 * PAD - (rows * PITCH + 24 + 14 if uri else 0)
    pitch = min(PITCH, (gw - 40) / cols)
    gh = rows * pitch + 24
    c = Card(W, gy + gh + 90)
    c.glass(gx, gy, gw, gh)

    # The whole window is a grid of unlit LEDs; the name lights some of them.
    x0, y0 = gx + (gw - cols * pitch) / 2 + pitch / 2, gy + 12 + pitch * 1.5
    spare = int((x0 - pitch / 2 - gx - 10) // pitch)
    left, d = x0 - pitch / 2 - spare * pitch, pitch * 0.66
    c.defs.append(
        f'<pattern id="off" x="{n(left)}" y="{n(gy + 12)}" width="{n(pitch)}" height="{n(pitch)}" patternUnits="userSpaceOnUse">'
        f'<circle cx="{n(pitch / 2)}" cy="{n(pitch / 2)}" r="{n(d / 2)}" fill="{LED_OFF}"/></pattern>'
    )
    c.add(f'<rect x="{n(left)}" y="{n(gy + 12)}" width="{n((cols + 2 * spare) * pitch)}" height="{n(rows * pitch)}" fill="url(#off)"/>')

    columns = matrix_points(NAME, x0, y0, pitch)
    lit, sweep = [p for col in columns for p in col], 1.1
    c.blur("glow", gx, gy, gw, gh, 5)
    c.add(dots(lit, d * 1.5, AMBER, f' filter="url(#glow)" opacity=".6"{anim("fade", t0 + sweep, 0.7, "ease-out")}'))
    for i, col in enumerate(columns):
        if col:
            c.add(dots(col, d, AMBER, anim("lit", t0 + sweep * i / len(columns), 0.45, "ease-out")))
    if not STATIC:
        # A brighter band that crosses the name every few seconds. The band
        # rests outside the window, so nothing shows where SMIL doesn't run.
        c.defs.append(
            f'<clipPath id="band"><rect x="{n(gx - 80)}" y="{n(gy)}" width="{n(pitch * 5)}" height="{n(gh)}">'
            f'<animate attributeName="x" values="{n(gx - 80)};{n(gx + gw)};{n(gx + gw)}" keyTimes="0;.22;1" dur="6s" begin="{t0 + 3:.1f}s" repeatCount="indefinite"/></rect></clipPath>'
        )
        c.motion_only(f'<g clip-path="url(#band)">{dots(lit, d, HOT)}</g>')

    if uri:
        px, size = gx + gw + 14, gh
        c.defs.append(f'<clipPath id="photo"><rect x="{n(px)}" y="{gy}" width="{n(size)}" height="{n(size)}" rx="9"/></clipPath>')
        c.glass(px, gy, size, size)
        c.add(f'<image href="{uri}" x="{n(px)}" y="{gy}" width="{n(size)}" height="{n(size)}" clip-path="url(#photo)" preserveAspectRatio="xMidYMid slice"/>')

    ty = gy + gh + 38
    c.add(c.text(PAD + 2, ty, fit(ABOUT[0], "s", 22, 600), "s", 22, INK) + c.text(PAD + 2, ty + 26, fit(ABOUT[1], "r", 16.5, 600), "r", 16.5, INK_SOFT))

    # Speaker grille and power lamp, bottom right.
    gx1, cy = W - PAD - 4, ty + 6
    holes = [(gx1 - 44 - 9 * i, cy - 13.5 + 9 * j) for i in range(14) for j in range(4)]
    c.add(dots(holes, 5, "#8D8E88") + dots([(x, y + 0.8) for x, y in holes], 3.6, "#3B3C38"))
    c.add(c.lamp(gx1 - 8, cy, AMBER))
    c.motion_only(f'<circle cx="{n(gx1 - 8)}" cy="{n(cy)}" r="5" fill="#7A3D00" opacity="0" style="animation:pulse 2.4s ease-in-out {t0 + 2:.1f}s infinite reverse"/>')
    return c


def tile(index, title, sub, delay):
    # 32.5% of the column. The README puts the three tiles side by side with no
    # space between the tags (a space would wrap the row on phones), so the gap
    # between them is the gutter drawn into each tile. Each tile is a key cap.
    w, h, gutter, drop = 275, 96, 3, 9
    face, skirt, ink = CAPS[index % len(CAPS)]
    c = Card(w, h, plate=False)
    kw, kh, x = w - 2 * gutter, h - drop - 1, gutter + 22
    c.add(f'<rect x="{gutter}" y="{drop}" width="{kw}" height="{kh}" rx="15" fill="{skirt}"/>')
    c.add(
        f"<g{anim('press', delay, 0.5, 'ease-in-out')}>"
        f'<rect x="{gutter}" y="0" width="{kw}" height="{kh}" rx="15" fill="{face}"/>'
        f'<rect x="{gutter + 1.5}" y="1.5" width="{kw - 3}" height="{kh - 3}" rx="13.5" fill="none" stroke="#FFF" stroke-opacity=".35" stroke-width="1.5"/>'
        + c.text(x, 39, title, "b", 23, ink) + c.text(x, 63, sub, "m", 15, ink)
        + f'<path d="M{w - x - 13} 37 l11 -11 m-8.5 0 h8.5 v8.5" fill="none" stroke="{ink}" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"/></g>'
    )
    return c


def months(weeks, t0):
    days = [d for week in weeks for d in week]
    per_month = {}
    for day, count, _ in days:
        per_month[(day.year, day.month)] = per_month.get((day.year, day.month), 0) + count
    peak = max(per_month.values()) or 1

    h = 300
    c = Card(W, h)
    c.add(c.text(PAD + 2, 44, "Contributions per month", "s", 17, INK))

    # Level meters: one column of LED segments per month.
    gx, gy, gw, gh = PAD, 60, 508, 184
    c.glass(gx, gy, gw, gh)
    segs, seg_h, step = 12, 6.5, 10
    pitch = (gw - 28) / len(per_month)
    seg_w, base, sweep = min(26, pitch - 10), gy + gh - 16, 0.9
    c.blur("glow", gx, gy, gw, gh, 4)
    ghost, glow = [], []
    for i, ((year, month), count) in enumerate(per_month.items()):
        cx = gx + 14 + pitch * (i + 0.5)
        x = cx - seg_w / 2
        delay = t0 + sweep * i / len(per_month)
        label = dt.date(year, month, 1)
        c.add(c.text(cx, gy + gh + 22, f"{label:%b}", "m", 13.5, INK, "middle"))
        if i == 0 or month == 1:
            c.add(c.text(cx, gy + gh + 38, str(year), "r", 12, INK_SOFT, "middle"))
        on = 0 if count == 0 else max(1, round(segs * count / peak))
        for s in range(segs):
            y = base - seg_h - s * step
            rect = f"M{n(x)} {n(y)}h{n(seg_w)}v{n(seg_h)}h{n(-seg_w)}z"
            if s >= on:
                ghost.append(rect)
                continue
            colour = RED if s >= segs - 2 else "#FF7A1A" if s >= segs - 5 else AMBER
            glow.append(f'<path d="{rect}" fill="{colour}"/>')
            c.add(f'<path d="{rect}" fill="{colour}"{anim("lit", delay + 0.045 * s, 0.4, "ease-out")}/>')
        if count:
            c.add(f"<g{anim('fade', delay + 0.045 * on + 0.2, 0.4)}>{c.text(cx, base - segs * step - 8, f'{count:,}', 'm', 13, HOT, 'middle')}</g>")
    c.add(f'<path d="{"".join(ghost)}" fill="{LED_OFF}"/>')
    c.add(f'<g filter="url(#glow)" opacity=".5"{anim("fade", t0 + sweep + 0.5, 0.7, "ease-out")}>{"".join(glow)}</g>')

    # Three seven-segment readouts.
    current, longest = streaks(days)
    busiest = max(days, key=lambda d: d[1])
    active = sum(1 for _, count, _ in days if count)
    stats = [
        ("Current streak", current, f"longest {plural(longest, 'day')}"),
        ("Active days", active, f"of the last {len(days)}"),
        ("Busiest day", busiest[1], f"on {short(busiest[0])}"),
    ]
    sx = gx + gw + 26
    for i, (label, value, detail) in enumerate(stats):
        y = gy + 66 * i
        rw = c.readout(sx, y, value, 3, t0 + 0.3 + 0.15 * i)
        room = W - PAD - (sx + rw + 14)
        c.add(c.text(sx + rw + 14, y + 23, fit(label, "s", 16, room), "s", 16, INK) + c.text(sx + rw + 14, y + 43, fit(detail, "r", 14.5, room), "r", 14.5, INK_SOFT))
    return c


def repo(index, name, info, fallback, delay):
    h = 100
    c = Card(W, h, screws=False)
    face = CAPS[index % len(CAPS)][0]
    c.add(f'<g clip-path="url(#pc)"><rect width="14" height="{h}" fill="{face}"/><rect x="14" width="1" height="{h}" fill="#000" opacity=".25"/></g>')

    # Right to left: star readout, star, language lamp.
    right, cy = W - PAD, h / 2
    stars = info.get("stargazerCount", 0)
    digits = max(2, len(str(stars)))
    rw = digits * 14.6 + (digits - 1) * 7.8 + 26
    x = right - rw
    c.readout(x, cy - 24, stars, digits, delay + 0.25, dh=26)
    x -= 26
    c.add(f'<path transform="translate({n(x)} {n(cy - 9)}) scale(1.3)" d="M7 1.2l1.8 3.7 4 .6-2.9 2.9.7 4L7 10.5l-3.6 1.9.7-4L1.2 5.5l4-.6z" fill="{INK}"/>')
    lang = info.get("primaryLanguage") or {}
    if lang.get("name"):
        x -= 22 + width(lang["name"], "m", 15)
        c.add(c.text(x, cy + 5, lang["name"], "m", 15, INK) + c.lamp(x - 15, cy, lang.get("color") or AMBER, 4.5))
        x -= 24
    left = 36
    desc = fit(printable(info.get("description") or "", "r") or fallback, "r", 15.5, x - 24 - left)
    c.add(c.text(left, 43, fit(name, "b", 21, x - 24 - left), "b", 21, INK) + c.text(left, 69, desc, "r", 15.5, INK_SOFT))
    return c


def graph(weeks, total, t0):
    gx, gy, gw = PAD, 60, W - 2 * PAD
    pitch = min(PITCH, (gw - 40) / len(weeks))
    d, sweep = pitch * 0.66, 1.2
    left = gx + (gw - len(weeks) * pitch) / 2 + pitch / 2
    top = gy + 40
    gh = 40 + 7 * pitch + 6
    h = gy + gh + PAD
    c = Card(W, h)
    c.glass(gx, gy, gw, gh)
    c.add(c.text(PAD + 2, 44, f"{plural(total, 'contribution')} in the last year", "s", 17, INK))

    # Legend: five LEDs in a small window of their own.
    x = W - PAD - 2 - width("More", "m", 13.5)
    c.add(c.text(x, 43, "More", "m", 13.5, INK_SOFT))
    lw = 5 * pitch + 10
    x -= 8 + lw
    c.glass(x, 28, lw, 21, rx=10.5)
    for i, colour in enumerate(LEVEL_LED):
        c.add(dots([(x + 5 + pitch * (i + 0.5), 38.5)], d, colour))
    c.add(c.text(x - 8, 43, "Less", "m", 13.5, INK_SOFT, "end"))

    # Month names sit over the first week of each month; drop one that would
    # collide with the next (a clipped first column, usually).
    marks = [i for i, week in enumerate(weeks) if i == 0 or week[0][0].month != weeks[i - 1][0][0].month]
    marks = [i for k, i in enumerate(marks) if k + 1 == len(marks) or marks[k + 1] - i >= 3]
    for i in marks:
        if left + i * pitch + 24 <= gx + gw - 12:
            c.add(c.text(left + i * pitch - d / 2, top - 15, f"{weeks[i][0][0]:%b}", "m", 12.5, "#B98A4E"))

    c.defs.append(
        f'<pattern id="off" x="{n(left - pitch / 2)}" y="{n(top - pitch / 2)}" width="{n(pitch)}" height="{n(pitch)}" patternUnits="userSpaceOnUse">'
        f'<circle cx="{n(pitch / 2)}" cy="{n(pitch / 2)}" r="{n(d / 2)}" fill="{LED_OFF}"/></pattern>'
    )
    c.add(f'<rect x="{n(left - pitch / 2)}" y="{n(top - pitch / 2)}" width="{n(len(weeks) * pitch)}" height="{n(7 * pitch)}" fill="url(#off)"/>')
    c.blur("glow", gx, gy, gw, gh, 3.5)
    bright = []
    for i, week in enumerate(weeks):
        by_level = {}
        for day, _, level in week:
            if level:
                by_level.setdefault(level, []).append((left + i * pitch, top + ((day.weekday() + 1) % 7) * pitch))
        bright += by_level.get(3, []) + by_level.get(4, [])
        switch_on = anim("lit", t0 + sweep * i / len(weeks), 0.45, "ease-out")
        c.add("".join(dots(points, d, LEVEL_LED[level], switch_on) for level, points in sorted(by_level.items())))
    if bright:
        c.add(dots(bright, d * 1.5, AMBER, f' filter="url(#glow)" opacity=".55"{anim("fade", t0 + sweep, 0.7, "ease-out")}'))
    return c


# ── Build ────────────────────────────────────────────────────────────────────
def main():
    weeks, total, repos = load()
    # Start times, staggered so the page plays from the top card to the bottom one.
    cards = {"hero": hero(0.1)}
    for i, (slug, title, sub) in enumerate(TILES):
        cards[f"tile-{slug}"] = tile(i, title, sub, 1.0 + 0.14 * i)
    cards["months"] = months(weeks, 1.5)
    for i, (name, fallback) in enumerate(FEATURED.items()):
        cards[f"repo-{name.lower()}"] = repo(i, name, repos.get(name, {}), fallback, 2.5 + 0.15 * i)
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
