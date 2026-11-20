"""Draws TikTok-style on-screen text, emoji included, into transparent PNGs that ffmpeg lays over a clip.

Two looks:
  meme      white text with a thin dark outline, centered (the "when shawty is on her 10th..." look)
  headline  black text on a white rounded box (the "No way THIS happened to..." look)
Emoji come from Twemoji images (downloaded once, then cached). If a download fails the emoji is skipped.
"""
from __future__ import annotations

import hashlib
import unicodedata
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

HERE = Path(__file__).resolve().parent
FONTS = HERE / "fonts"
EMOJI_CACHE = HERE / "output" / "_emoji"
EMOJI_URL = "https://raw.githubusercontent.com/jdecked/twemoji/main/assets/72x72/{}.png"


# ------------------------------------------------------------------ emoji
def _is_emoji(ch: str) -> bool:
    cp = ord(ch)
    if cp >= 0x1F000:
        return True
    if 0x2600 <= cp <= 0x27BF or 0x2B00 <= cp <= 0x2BFF or 0x2190 <= cp <= 0x21FF or 0x2300 <= cp <= 0x23FF:
        return unicodedata.category(ch) == "So"
    return cp in (0x00A9, 0x00AE, 0x203C, 0x2049, 0x2122, 0x2139, 0x3030, 0x303D)


def split_runs(text: str) -> list[tuple[str, str]]:
    """'hi 😭💔' -> [('t','hi '), ('e','😭'), ('e','💔')]. Keeps ZWJ sequences, skin tones and flags together."""
    runs: list[tuple[str, str]] = []
    i, n = 0, len(text)
    buf = ""
    while i < n:
        ch = text[i]
        if _is_emoji(ch):
            if buf:
                runs.append(("t", buf))
                buf = ""
            seq = ch
            i += 1
            if 0x1F1E6 <= ord(ch) <= 0x1F1FF and i < n and 0x1F1E6 <= ord(text[i]) <= 0x1F1FF:  # flag pair
                seq += text[i]
                i += 1
            while i < n:
                c = text[i]
                if ord(c) == 0xFE0F or 0x1F3FB <= ord(c) <= 0x1F3FF or ord(c) == 0x20E3:
                    seq += c
                    i += 1
                elif ord(c) == 0x200D and i + 1 < n:
                    seq += c + text[i + 1]
                    i += 2
                else:
                    break
            runs.append(("e", seq))
        elif ord(ch) == 0xFE0F:
            i += 1
        else:
            buf += ch
            i += 1
    if buf:
        runs.append(("t", buf))
    return runs


def _emoji_image(seq: str, size: int) -> Image.Image | None:
    EMOJI_CACHE.mkdir(parents=True, exist_ok=True)
    full = "-".join(f"{ord(c):x}" for c in seq)
    short = "-".join(f"{ord(c):x}" for c in seq if ord(c) != 0xFE0F)
    for code in dict.fromkeys([short, full]):
        f = EMOJI_CACHE / f"{code}.png"
        if not f.exists():
            try:
                req = urllib.request.Request(EMOJI_URL.format(code), headers={"User-Agent": "clip-agent"})
                with urllib.request.urlopen(req, timeout=8) as r:
                    f.write_bytes(r.read())
            except Exception:
                continue
        try:
            return Image.open(f).convert("RGBA").resize((size, size), Image.LANCZOS)
        except Exception:
            continue
    return None


# ------------------------------------------------------------------ layout
def _font(name: str, size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(str(FONTS / name), size)


def _word_width(runs, font, esize, egap) -> float:
    w = 0.0
    for kind, s in runs:
        w += font.getlength(s) if kind == "t" else esize + egap
    return w


def _wrap(text: str, font, esize, egap, max_w) -> list[list]:
    """Greedy word wrap. Returns lines; each line is a list of (runs, width) words."""
    space = font.getlength(" ")
    lines: list[list] = []
    for para in text.split("\n"):
        cur, cur_w = [], 0.0
        for word in para.split(" "):
            if not word:
                continue
            runs = split_runs(word)
            ww = _word_width(runs, font, esize, egap)
            add = ww if not cur else space + ww
            if cur and cur_w + add > max_w:
                lines.append(cur)
                cur, cur_w = [(runs, ww)], ww
            else:
                cur.append((runs, ww))
                cur_w += add
        if cur:
            lines.append(cur)
    return lines or [[([("t", " ")], 0.0)]]


def _line_width(line, space) -> float:
    return sum(w for _, w in line) + space * (len(line) - 1)


def _draw_lines(img, lines, font, size, esize, egap, x_center, top, line_h, fill, stroke=0, stroke_fill=None):
    draw = ImageDraw.Draw(img)
    space = font.getlength(" ")
    asc = font.getmetrics()[0]
    for li, line in enumerate(lines):
        x = x_center - _line_width(line, space) / 2
        baseline = top + li * line_h + (line_h - size) / 2 + asc * 0.92
        for wi, (runs, _w) in enumerate(line):
            if wi:
                x += space
            for kind, s in runs:
                if kind == "t":
                    draw.text((x, baseline), s, font=font, fill=fill, anchor="ls",
                              stroke_width=stroke, stroke_fill=stroke_fill)
                    x += font.getlength(s)
                else:
                    em = _emoji_image(s, esize)
                    if em is not None:
                        img.alpha_composite(em, (int(round(x + egap / 2)), int(round(baseline - esize * 0.86))))
                    x += esize + egap


def render(text: str, style: str, out: Path, max_width: int = 940) -> tuple[Path, int, int]:
    """Render text to a transparent PNG. Returns (path, width, height)."""
    text = " ".join((text or "").replace("\r", "").split(" ")).strip()
    if style == "meme":
        size, font = 56, _font("TikTokSans-Medium.ttf", 56)
        esize, egap, line_h, pad = int(size * 1.0), 6, int(size * 1.24), 14
        lines = _wrap(text, font, esize, egap, max_width - 2 * pad)
        w = int(max(_line_width(l, font.getlength(" ")) for l in lines) + 2 * pad + 8)
        h = int(len(lines) * line_h + 2 * pad)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # soft shadow, then thin outline, then the white text
        shadow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        _draw_lines(shadow, lines, font, size, esize, egap, w / 2, pad + 2, line_h, (0, 0, 0, 150), 4, (0, 0, 0, 150))
        img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(3)))
        _draw_lines(img, lines, font, size, esize, egap, w / 2, pad, line_h, (255, 255, 255, 255), 2, (0, 0, 0, 200))
    else:  # headline box
        size, font = 54, _font("TikTokSans-SemiBold.ttf", 54)
        esize, egap, line_h = int(size * 1.0), 6, int(size * 1.2)
        padx, pady, radius = 28, 18, 22
        lines = _wrap(text, font, esize, egap, max_width - 2 * padx)
        inner = max(_line_width(l, font.getlength(" ")) for l in lines)
        w = int(inner + 2 * padx)
        h = int(len(lines) * line_h + 2 * pady)
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ImageDraw.Draw(img).rounded_rectangle((0, 0, w - 1, h - 1), radius=radius, fill=(255, 255, 255, 255))
        _draw_lines(img, lines, font, size, esize, egap, w / 2, pady, line_h, (0, 0, 0, 255))
    out = Path(out)
    img.save(out)
    return out, img.width, img.height


def cache_name(text: str, style: str) -> str:
    return hashlib.sha1(f"{style}|{text}".encode()).hexdigest()[:12] + ".png"


if __name__ == "__main__":
    import sys
    print(render(sys.argv[2], sys.argv[1], Path(sys.argv[3])))
