"""シネマティックなモーショングラフィックスの描画 (skia-python)。

各ショット種別は draw_<type>(c, t, v, ctx) で、t はショット開始からの秒数。
ctx["at"](i) はシーン内 i 行目のナレーションが始まる時刻 (ショット開始基準)。
"""

import json
import math
import random
import re
import subprocess
from functools import lru_cache
from pathlib import Path

import numpy as np
import skia

ROOT = Path(__file__).resolve().parent
W, H = 1920, 1080
FPS = 30

TF_REG = skia.Typeface.MakeFromFile(str(ROOT / "fonts" / "NotoSansJP_500Medium.ttf"))
TF_BOLD = skia.Typeface.MakeFromFile(str(ROOT / "fonts" / "NotoSansJP_800ExtraBold.ttf"))

# 配色 (ダーク・シネマティック)
BG_TOP = "#0B0F14"
BG_BOT = "#151B24"
TEXT = "#F2EFE9"
MUTED = "#8C95A3"
LINE = "#2A323D"
GLASS = "#FFFFFF"
GOLD = "#E8B04B"
RED = "#E5533D"
GREEN = "#3FB57E"
BLUE = "#5B8DEF"
ORANGE = "#F08A3C"

ACCENTS = {"gold": GOLD, "red": RED, "green": GREEN, "blue": BLUE, "orange": ORANGE}


# ---------------------------------------------------------------- 基本ユーティリティ

def C(hexstr, a=1.0):
    v = int(hexstr[1:], 16)
    return skia.ColorSetARGB(max(0, min(255, int(a * 255))), (v >> 16) & 255, (v >> 8) & 255, v & 255)


def clamp(x, lo=0.0, hi=1.0):
    return max(lo, min(hi, x))


def ease_out(x):
    x = clamp(x)
    return 1 - (1 - x) ** 3


def ease_in_out(x):
    x = clamp(x)
    return 4 * x ** 3 if x < 0.5 else 1 - (-2 * x + 2) ** 3 / 2


def prog(t, t0, d=0.6):
    return ease_out((t - t0) / d)


def font(size, bold=False):
    f = skia.Font(TF_BOLD if bold else TF_REG, size)
    f.setSubpixel(True)
    f.setEdging(skia.Font.Edging.kAntiAlias)
    return f


def fill(color, a=1.0):
    return skia.Paint(Color=C(color, a), AntiAlias=True)


def stroke(color, width, a=1.0, cap=skia.Paint.kRound_Cap):
    p = skia.Paint(Color=C(color, a), AntiAlias=True, Style=skia.Paint.kStroke_Style, StrokeWidth=width)
    p.setStrokeCap(cap)
    p.setStrokeJoin(skia.Paint.kRound_Join)
    return p


def blur(paint, sigma):
    paint.setMaskFilter(skia.MaskFilter.MakeBlur(skia.kNormal_BlurStyle, sigma))
    return paint


def text_width(s, f):
    return f.measureText(s)


def draw_text(c, s, x, y, f, color=TEXT, a=1.0, align="left", shadow=True):
    """y は文字の縦方向の中心。"""
    if a <= 0.001 or not s:
        return
    w = text_width(s, f)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    base = y + f.getSize() * 0.36
    if shadow:
        c.drawString(s, x, base + 4, f, blur(fill("#000000", 0.55 * a), 6))
    c.drawString(s, x, base, f, fill(color, a))


RICH = re.compile(r"\[([^\]]+)\]")


def rich_segments(line):
    out, pos = [], 0
    for m in RICH.finditer(line):
        if m.start() > pos:
            out.append((line[pos:m.start()], False))
        out.append((m.group(1), True))
        pos = m.end()
    if pos < len(line):
        out.append((line[pos:], False))
    return out


def rich_width(line, f):
    return sum(text_width(s, f) for s, _ in rich_segments(line))


def draw_rich(c, line, x, y, f, color=TEXT, accent=GOLD, a=1.0, align="center"):
    w = rich_width(line, f)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    for s, hl in rich_segments(line):
        draw_text(c, s, x, y, f, accent if hl else color, a)
        x += text_width(s, f)


def rrect(x, y, w, h, r):
    return skia.RRect.MakeRectXY(skia.Rect.MakeXYWH(x, y, w, h), r, r)


def glass_card(c, x, y, w, h, a=1.0, r=26, color=GLASS, alpha=0.06, border=0.13):
    c.drawRRect(rrect(x, y + 10, w, h, r), blur(fill("#000000", 0.35 * a), 18))
    c.drawRRect(rrect(x, y, w, h, r), fill(color, alpha * a))
    c.drawRRect(rrect(x, y, w, h, r), stroke("#FFFFFF", 2, border * a))


@lru_cache(maxsize=256)
def icon_image(name, size, color):
    svg = (ROOT / "vendor" / "icons" / "filled" / f"{name}.svg").read_text()
    svg = svg.replace('width="24" height="24"', f'width="{size}" height="{size}"')
    svg = svg.replace("<path ", f'<path fill="{color}" ')
    data = svg.encode()
    dom = skia.SVGDOM.MakeFromStream(skia.MemoryStream(data, True))  # True = データをコピーして保持
    if dom is None:
        raise RuntimeError(f"icon {name} を読み込めません")
    dom.setContainerSize(skia.Size(size, size))
    surf = skia.Surface(size, size)
    with surf as cv:
        cv.clear(skia.ColorTRANSPARENT)
        dom.render(cv)
    return surf.makeImageSnapshot()


def draw_icon(c, name, cx, cy, size, color=TEXT, a=1.0):
    img = icon_image(name, int(size), color)
    p = skia.Paint(AntiAlias=True)
    p.setAlphaf(clamp(a))
    c.drawImage(img, cx - size / 2, cy - size / 2, skia.SamplingOptions(skia.FilterMode.kLinear), p)


def fmt_count(target, p):
    """'2,567億円' のような文字列の最初の数値を p (0..1) までカウントアップした表示にする。"""
    m = re.search(r"\d[\d,]*(\.\d+)?", target)
    if not m:
        return target
    num_s = m.group(0)
    decimals = len(m.group(1)) - 1 if m.group(1) else 0
    val = float(num_s.replace(",", "")) * p
    s = f"{val:,.{decimals}f}" if "," in num_s else f"{val:.{decimals}f}"
    return target[:m.start()] + s + target[m.end():]


def at_of(ctx, item, default):
    """要素の出現時刻。item['at'] があれば該当行の開始時刻。"""
    if isinstance(item, dict) and "at" in item:
        return ctx["at"](item["at"]) + 0.15
    return default


# ---------------------------------------------------------------- 背景・仕上げ

BLOBS = [(380, 260, 700, GOLD, 0.07), (1560, 820, 760, BLUE, 0.05), (1500, 160, 520, ORANGE, 0.06)]


def draw_background(c, tg):
    shader = skia.GradientShader.MakeLinear([(0, 0), (0, H)], [C(BG_TOP), C(BG_BOT)])
    c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=shader))
    for i, (cx, cy, r, col, sp) in enumerate(BLOBS):
        x = cx + 140 * math.sin(tg * sp + i * 1.7)
        y = cy + 90 * math.cos(tg * sp * 0.8 + i)
        sh = skia.GradientShader.MakeRadial((x, y), r, [C(col, 0.13), C(col, 0.0)])
        c.drawCircle(x, y, r, skia.Paint(Shader=sh, AntiAlias=True))


_GRAIN = None


def grain_images():
    global _GRAIN
    if _GRAIN is None:
        rng = np.random.default_rng(7)
        _GRAIN = []
        for _ in range(6):
            arr = np.zeros((H // 2, W // 2, 4), dtype=np.uint8)
            v = rng.integers(0, 2, size=(H // 2, W // 2), dtype=np.uint8) * 255
            arr[..., 0] = v
            arr[..., 1] = v
            arr[..., 2] = v
            arr[..., 3] = rng.integers(0, 7, size=(H // 2, W // 2), dtype=np.uint8)
            _GRAIN.append(skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType))
    return _GRAIN


def draw_finish(c, frame_idx):
    sh = skia.GradientShader.MakeRadial((W / 2, H / 2), W * 0.75, [C("#000000", 0), C("#000000", 0.0),
                                                                  C("#000000", 0.6)], [0, 0.55, 1])
    c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=sh))
    g = grain_images()[(frame_idx // 4) % 6]  # 4フレームごとに切り替え (圧縮しやすくする)
    c.drawImageRect(g, skia.Rect(0, 0, W, H), skia.SamplingOptions())


# ---------------------------------------------------------------- テロップ

HL = "#FFD54A"  # 字幕の強調色
NO_LINE_START = set("、。，．・：；？！）」』】ー〜ぁぃぅぇぉっゃゅょァィゥェォッャュョ%％")


def caption_chars(s):
    """[ ] で囲んだ部分を強調として、(文字, 強調か) の列にする。"""
    out = []
    for seg, hl in rich_segments(s):
        out += [(ch, hl) for ch in seg]
    return out


def wrap_chars(chars, f, max_w):
    lines, cur = [], []
    for item in chars:
        if text_width("".join(ch for ch, _ in cur) + item[0], f) <= max_w:
            cur.append(item)
            continue
        if item[0] in NO_LINE_START and cur:
            lines.append(cur[:-1])
            cur = [cur[-1], item]
        else:
            lines.append(cur)
            cur = [item]
    if cur:
        lines.append(cur)
    return lines


def char_runs(line):
    runs = []
    for ch, hl in line:
        if runs and runs[-1][1] == hl:
            runs[-1][0] += ch
        else:
            runs.append([ch, hl])
    return runs


def draw_caption(c, s, tl, a=1.0):
    """下部の字幕。[ ] の部分は黄色＋マーカー。行の頭でふわっと出る。"""
    if not s:
        return
    chars = caption_chars(s)
    for size in (48, 44, 40):
        f = font(size, bold=True)
        lines = wrap_chars(chars, f, 1600)
        if len(lines) <= 2:
            break
    p = ease_out(tl / 0.25)
    lh = size * 1.5
    y0 = H - 78 - lh * (len(lines) - 1) + 12 * (1 - p)
    sh = skia.GradientShader.MakeLinear([(0, H - 300), (0, H)], [C("#000000", 0), C("#000000", 0.6)])
    c.drawRect(skia.Rect(0, H - 300, W, H), skia.Paint(Shader=sh))
    for i, ln in enumerate(lines):
        x = W / 2 - text_width("".join(ch for ch, _ in ln), f) / 2
        base = y0 + i * lh + size * 0.36
        for seg, hl in char_runs(ln):
            sw = text_width(seg, f)
            if hl:
                c.drawRect(skia.Rect.MakeXYWH(x - 3, base + 4, (sw + 6) * ease_out((tl - 0.15) / 0.35), 12),
                           fill(HL, 0.45 * a * p))
            c.drawString(seg, x, base, f, stroke("#000000", 9, 0.9 * a * p))
            c.drawString(seg, x, base, f, fill(HL if hl else "#FFFFFF", a * p))
            x += sw
    return y0


def draw_note(c, s, y, tl):
    """字幕の上に小さく出す注記（※報道ベース など）。"""
    p = ease_out(tl / 0.4)
    f = font(26, True)
    w = text_width(s, f) + 36
    c.drawRRect(rrect(W / 2 - w / 2, y - 22, w, 44, 22), fill("#0B0F14", 0.7 * p))
    draw_text(c, s, W / 2, y, f, MUTED, p, align="center", shadow=False)


def draw_impact(c, text, tl, dur, accent=GOLD):
    """画面中央にドンと出る強調テロップ（パターンインタラプト用）。"""
    if tl < 0 or tl > dur:
        return
    pin = ease_out(tl / 0.35)
    a = clamp((dur - tl) / 0.3)
    if tl < 0.12:
        c.drawRect(skia.Rect(0, 0, W, H), fill("#FFFFFF", 0.12 * (1 - tl / 0.12)))
    sc = 1.0 + 0.22 * (1 - pin)
    f = font(112, True)
    lines = text.split("\n")
    bw = max(rich_width(ln, f) for ln in lines) + 140
    lh = 150
    bh = lh * len(lines) + 40
    c.save()
    c.translate(W / 2, H * 0.44)
    c.rotate(-2.5)
    c.scale(sc, sc)
    band = skia.Path()
    k = 36
    band.moveTo(-bw / 2 + k, -bh / 2)
    band.lineTo(bw / 2 + k, -bh / 2)
    band.lineTo(bw / 2 - k, bh / 2)
    band.lineTo(-bw / 2 - k, bh / 2)
    band.close()
    c.save()
    c.translate(0, 14)
    c.drawPath(band, blur(fill("#000000", 0.6 * a * pin), 22))
    c.restore()
    c.drawPath(band, fill("#0B0F14", 0.92 * a * pin))
    c.drawRect(skia.Rect.MakeXYWH(-bw / 2 - k - 4, bh / 2 - 12, (bw + 8) * pin, 12), fill(accent, a))
    for i, ln in enumerate(lines):
        y = -bh / 2 + 20 + lh / 2 + i * lh
        draw_rich(c, ln, 0, y, f, "#FFFFFF", accent, a * pin)
    c.restore()


def draw_question(c, text, tl):
    """左上に出しっぱなしにする「いまの問い」。"""
    p = ease_out(tl / 0.45)
    f = font(36, True)
    w = text_width(text, f) + 120
    x, y = 60 - 30 * (1 - p), 62
    c.drawRRect(rrect(x, y - 32, w, 64, 12), fill("#0B0F14", 0.8 * p))
    c.drawRect(skia.Rect.MakeXYWH(x, y - 32, 8, 64), fill(GOLD, p))
    draw_text(c, "Q.", x + 46, y, font(36, True), GOLD, p, align="center", shadow=False)
    draw_text(c, text, x + 82, y, f, TEXT, p, shadow=False)


# ---------------------------------------------------------------- 共通パーツ

def draw_heading(c, t, s, y=150):
    if not s:
        return
    p = prog(t, 0.05, 0.7)
    draw_text(c, s, 140, y - 20 * (1 - p), font(58, True), TEXT, p)
    c.drawRect(skia.Rect.MakeXYWH(140, y + 50, 110 * prog(t, 0.3, 0.8), 8), fill(GOLD, p))


def draw_source(c, t, s):
    if s:
        draw_text(c, s, W - 80, 60, font(22), MUTED, prog(t, 0.8, 0.8), align="right", shadow=False)


# ---------------------------------------------------------------- ショット種別

def draw_title(c, t, v, ctx):
    p0 = prog(t, 0.1, 0.8)
    if v.get("kicker"):
        draw_text(c, v["kicker"], W / 2, 300, font(40, True), GOLD, p0, align="center")
        lw = 260 * prog(t, 0.2, 1.0)
        c.drawRect(skia.Rect.MakeXYWH(W / 2 - lw / 2, 345, lw, 4), fill(GOLD, p0))
    lines = v["title"].split("\n")
    f = font(v.get("size", 128), True)
    for i, ln in enumerate(lines):
        p = prog(t, 0.35 + 0.18 * i, 0.8)
        draw_rich(c, ln, W / 2, 490 + i * 150 - 40 * (1 - p), f, TEXT, GOLD, p)
    if v.get("subtitle"):
        draw_text(c, v["subtitle"], W / 2, 490 + len(lines) * 150 + 20, font(44), MUTED,
                  prog(t, 0.9, 0.8), align="center")


def draw_headline(c, t, v, ctx):
    lines = v["text"].split("\n")
    size = v.get("size", 100)
    f = font(size, True)
    lh = size * 1.45
    top = H / 2 - 40 - lh * (len(lines) - 1) / 2
    accent = ACCENTS.get(v.get("accent", "gold"), GOLD)
    if v.get("icon"):
        pi = prog(t, 0.0, 0.7)
        cy = top - lh / 2 - 130
        c.drawCircle(W / 2, cy, 78 * (0.8 + 0.2 * pi), fill(accent, 0.16 * pi))
        draw_icon(c, v["icon"], W / 2, cy, 88, accent, pi)
    if v.get("kicker"):
        k_y = top - lh / 2 - (260 if v.get("icon") else 70)
        draw_text(c, v["kicker"], W / 2, k_y, font(40, True), MUTED, prog(t, 0.05, 0.7), align="center")
    reveal = v.get("reveal")
    for i, ln in enumerate(lines):
        t0 = (ctx["at"](reveal[i]) + 0.1) if reveal else 0.2 + 0.22 * i
        p = prog(t, t0, 0.8)
        draw_rich(c, ln, W / 2, top + i * lh + 36 * (1 - p), f, TEXT, accent, p)
    if v.get("sub"):
        draw_text(c, v["sub"], W / 2, top + len(lines) * lh + 10, font(40), MUTED,
                  prog(t, 0.6 + 0.22 * len(lines), 0.8), align="center")


_SPOTS = None


def dish_spots():
    global _SPOTS
    if _SPOTS is None:
        rng = random.Random(3)
        _SPOTS = []
        for _ in range(70):
            ang = rng.uniform(0, 2 * math.pi)
            rad = math.sqrt(rng.uniform(0, 1))
            _SPOTS.append((math.cos(ang) * rad, math.sin(ang) * rad, rng.uniform(10, 46),
                           rng.uniform(8, 30), rng.uniform(0.2, 0.55), rng.random()))
    return _SPOTS


def draw_dish(c, cx, cy, s, t, a=1.0):
    """ミラノ風ドリアをイメージしたグラタン皿のイラスト (真上から)。"""
    rx, ry = 420 * s, 300 * s
    c.drawOval(skia.Rect(cx - rx, cy - ry + 40 * s, cx + rx, cy + ry + 60 * s), blur(fill("#000000", 0.55 * a), 30))
    sh = skia.GradientShader.MakeRadial((cx - 80 * s, cy - 90 * s), rx * 1.3, [C("#FBF8F2", a), C("#D9D0C1", a)])
    c.drawOval(skia.Rect(cx - rx, cy - ry, cx + rx, cy + ry), skia.Paint(Shader=sh, AntiAlias=True))
    c.drawOval(skia.Rect(cx - rx * 0.89, cy - ry * 0.86, cx + rx * 0.89, cy + ry * 0.86), fill("#CFC4B2", 0.9 * a))
    gx, gy = rx * 0.83, ry * 0.79
    sh = skia.GradientShader.MakeRadial((cx - 70 * s, cy - 60 * s), gx * 1.25,
                                        [C("#F7D774", a), C("#E3A443", a), C("#B66D27", a)], [0, 0.6, 1])
    c.drawOval(skia.Rect(cx - gx, cy - gy, cx + gx, cy + gy), skia.Paint(Shader=sh, AntiAlias=True))
    c.save()
    path = skia.Path()
    path.addOval(skia.Rect(cx - gx, cy - gy, cx + gx, cy + gy))
    c.clipPath(path, doAntiAlias=True)
    for x, y, w, h, al, kind in dish_spots():
        px, py = cx + x * gx * 0.95, cy + y * gy * 0.95
        if kind < 0.75:
            c.drawOval(skia.Rect(px - w * s, py - h * s, px + w * s, py + h * s),
                       blur(fill("#7A3E14", al * a), 7 * s))
        elif kind < 0.92:
            c.drawOval(skia.Rect(px - w * s * 0.6, py - h * s * 0.5, px + w * s * 0.6, py + h * s * 0.5),
                       blur(fill("#FFF0B8", 0.55 * a), 5 * s))
        else:
            c.drawCircle(px, py, 5 * s, fill("#4E8B3A", 0.9 * a))
    c.restore()
    for i in range(3):
        x0 = cx + (-140 + 140 * i) * s
        path = skia.Path()
        ph = t * 1.4 + i * 2.1
        rise = (t * 60 + i * 80) % 260
        for k in range(30):
            yy = cy - 120 * s - k * 12 * s - rise * s * 0.3
            xx = x0 + math.sin(ph + k * 0.28) * 26 * s
            if k == 0:
                path.moveTo(xx, yy)
            else:
                path.lineTo(xx, yy)
        c.drawPath(path, blur(stroke("#FFFFFF", 22 * s, 0.07 * a), 10 * s))


def draw_doria(c, t, v, ctx):
    p = prog(t, 0.0, 1.0)
    draw_dish(c, 760, 560 + 30 * (1 - p), 1.0, t, p)
    pb = prog(t, 0.5, 0.7)
    bx, by, r = 1420, 520, 190 * (0.85 + 0.15 * pb)
    draw_text(c, v.get("label", ""), bx, by - 280, font(48, True), TEXT, pb, align="center")
    c.drawCircle(bx, by + 8, r, blur(fill("#000000", 0.5 * pb), 20))
    c.drawCircle(bx, by, r, fill(RED, pb))
    c.drawCircle(bx, by, r - 14, stroke("#FFFFFF", 3, 0.35 * pb))
    draw_text(c, v.get("tax", "税込"), bx, by - 95, font(40, True), "#FFFFFF", pb, align="center", shadow=False)
    n = int(round(v["price"] * ease_out((t - 0.7) / 1.2)))
    draw_text(c, f"{n}円", bx, by + 25, font(118, True), "#FFFFFF", pb, align="center", shadow=False)
    if v.get("note"):
        draw_text(c, v["note"], bx, by + 290, font(36), MUTED, prog(t, 1.6, 0.8), align="center")


def draw_ring(c, t, v, ctx):
    cx, cy, r = 640, 540, 270
    p = prog(t, 0.0, 0.7)
    rect = skia.Rect(cx - r, cy - r, cx + r, cy + r)
    c.drawArc(rect, 0, 360, False, stroke(LINE, 48, p))
    sweep = 360 * v["pct"] / 100 * ease_in_out((t - 0.3) / 1.6)
    accent = ACCENTS.get(v.get("accent", "orange"), ORANGE)
    c.drawArc(rect, -90, sweep, False, blur(stroke(accent, 60, 0.35 * p), 14))
    c.drawArc(rect, -90, sweep, False, stroke(accent, 48, p))
    shown = v["pct"] * ease_in_out((t - 0.3) / 1.6)
    draw_text(c, f"{shown:.0f}%", cx, cy - 10, font(150, True), TEXT, p, align="center")
    draw_text(c, v.get("center_label", ""), cx, cy + 110, font(30), MUTED, p, align="center")
    for i, ln in enumerate(v.get("label", "").split("\n")):
        pl = prog(t, 0.6 + 0.15 * i, 0.8)
        draw_rich(c, ln, 1060, 420 + i * 110 + 30 * (1 - pl), font(72, True), TEXT, accent, pl, align="left")
    if v.get("note"):
        draw_text(c, v["note"], 1060, 760, font(32), MUTED, prog(t, 1.4, 0.8))


def draw_year(c, t, v, ctx):
    year = v["year"]
    p = prog(t, 0.0, 0.8)
    if isinstance(year, int):
        k = ease_out((t - 0.0) / 1.1)
        shown = str(int(round(year - 30 * (1 - k))))
    else:
        shown = year
    f = font(v.get("size", 280), True)
    draw_text(c, shown, W / 2, 430, f, GOLD, p, align="center")
    lw = 520 * prog(t, 0.6, 0.9)
    c.drawRect(skia.Rect.MakeXYWH(W / 2 - lw / 2, 600, lw, 4), fill(TEXT, 0.5 * p))
    pt = prog(t, 0.8, 0.8)
    draw_rich(c, v["text"], W / 2, 690 + 30 * (1 - pt), font(64, True), TEXT, GOLD, pt)
    if v.get("sub"):
        draw_text(c, v["sub"], W / 2, 790, font(36), MUTED, prog(t, 1.2, 0.8), align="center")


def draw_pricedrop(c, t, v, ctx):
    p = prog(t, 0.0, 0.7)
    draw_text(c, v.get("year", ""), W / 2, 230, font(56, True), GOLD, p, align="center")
    draw_text(c, v.get("label", ""), W / 2, 320, font(44), MUTED, p, align="center")
    f_old = font(190, True)
    ox = 620
    draw_text(c, v["from"], ox, 560, f_old, MUTED, p, align="center")
    ws = text_width(v["from"], f_old)
    ps = ease_in_out((t - 0.9) / 0.5)
    if ps > 0:
        c.drawLine(ox - ws / 2 - 20, 560, ox - ws / 2 - 20 + (ws + 40) * ps, 560, stroke(RED, 14))
    pa = prog(t, 1.3, 0.6)
    if pa > 0:
        x0, x1 = 900, 1010 + 20 * pa
        c.drawLine(x0, 560, x1, 560, stroke(TEXT, 10, pa))
        path = skia.Path()
        path.moveTo(x1 + 30, 560)
        path.lineTo(x1 - 10, 530)
        path.lineTo(x1 - 10, 590)
        path.close()
        c.drawPath(path, fill(TEXT, pa))
    pn = prog(t, 1.6, 0.6)
    sc = 0.8 + 0.2 * pn
    c.save()
    c.translate(1400, 560)
    c.scale(sc, sc)
    draw_text(c, v["to"], 0, 0, font(230, True), GOLD, pn, align="center")
    c.restore()
    if v.get("note"):
        draw_text(c, v["note"], W / 2, 800, font(40), TEXT, prog(t, 2.2, 0.8), align="center")


def draw_stats(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    stats = v["stats"]
    gap = 60
    cw = (W - 280 - gap * (len(stats) - 1)) / len(stats)
    for i, s in enumerate(stats):
        t0 = at_of(ctx, s, 0.3 + 0.25 * i)
        p = prog(t, t0, 0.7)
        x = 140 + i * (cw + gap)
        y = 330 + 40 * (1 - p)
        glass_card(c, x, y, cw, 420, p)
        draw_text(c, s["label"], x + cw / 2, y + 80, font(40), MUTED, p, align="center")
        shown = fmt_count(s["value"], ease_out((t - t0) / 1.3))
        draw_text(c, shown, x + cw / 2, y + 215, font(96, True), GOLD, p, align="center")
        if s.get("delta"):
            col = GREEN if s["delta"].find("+") >= 0 else MUTED
            draw_text(c, s["delta"], x + cw / 2, y + 340, font(34, True), col, prog(t, t0 + 0.8, 0.6), align="center")
    draw_source(c, t, v.get("source"))


def draw_bars(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    x0, x1 = 480, W - 140
    bw = x1 - x0
    for i, row in enumerate(v["rows"]):
        t0 = at_of(ctx, row, 0.3 + 0.4 * i)
        p = prog(t, t0, 0.5)
        g = ease_in_out((t - t0) / 1.1)
        y = 300 + i * 200
        total = row["japan"] + row["asia"]
        jw = bw * row["japan"] / total
        draw_text(c, row["label"], 140, y + 70, font(50, True), TEXT, p)
        c.drawRRect(rrect(x0, y, bw, 140, 14), fill("#FFFFFF", 0.05 * p))
        c.save()
        c.clipRect(skia.Rect.MakeXYWH(x0, y, bw * g, 140))
        c.drawRRect(rrect(x0, y, jw, 140, 14), fill(BLUE, p))
        c.drawRRect(rrect(x0 + jw, y, bw - jw, 140, 14), fill(ORANGE, p))
        c.restore()
        pl = prog(t, t0 + 1.0, 0.6)
        jp = round(row["japan"] / total * 100)
        u = row["unit"]
        draw_text(c, f"日本 {jp}%", x0 + 30, y + 45, font(38, True), "#FFFFFF", pl)
        draw_text(c, f"{row['japan']:,g}{u}", x0 + 30, y + 98, font(34), "#FFFFFF", pl)
        draw_text(c, f"アジア {100 - jp}%", x1 - 30, y + 45, font(38, True), "#FFFFFF", pl, align="right")
        draw_text(c, f"{row['asia']:,g}{u}", x1 - 30, y + 98, font(34), "#FFFFFF", pl, align="right")
    m = v.get("margins")
    if m:
        t0 = at_of(ctx, m, 1.6)
        p = prog(t, t0, 0.7)
        glass_card(c, 140, 720 + 30 * (1 - p), W - 280, 120, p)
        yy = 780 + 30 * (1 - p)
        draw_text(c, "営業利益率", 200, yy, font(42, True), TEXT, p)
        draw_text(c, f"日本  {m['japan']}", 900, yy, font(58, True), BLUE, p, align="center")
        draw_text(c, "／", 1210, yy, font(44), MUTED, p, align="center")
        draw_text(c, f"アジア  {m['asia']}", 1520, yy, font(58, True), ORANGE, p, align="center")
    draw_source(c, t, v.get("source"))


# --- 地図

@lru_cache(maxsize=4)
def map_paths(bounds):
    lon0, lon1, lat0, lat1 = bounds
    topo = json.loads((ROOT / "vendor" / "world-atlas" / "countries-50m.json").read_text())
    sx, sy = topo["transform"]["scale"]
    tx, ty = topo["transform"]["translate"]
    arcs = []
    for arc in topo["arcs"]:
        x = y = 0
        pts = []
        for dx, dy in arc:
            x += dx
            y += dy
            pts.append((x * sx + tx, y * sy + ty))
        arcs.append(pts)

    def merc(lat):
        return math.log(math.tan(math.pi / 4 + math.radians(lat) / 2))

    mx0, mx1 = math.radians(lon0), math.radians(lon1)
    my0, my1 = merc(lat0), merc(lat1)
    k = min(W / (mx1 - mx0), H / (my1 - my0))
    ox = (W - (mx1 - mx0) * k) / 2
    oy = (H - (my1 - my0) * k) / 2

    def proj(lon, lat):
        lat = max(-85, min(85, lat))
        return ox + (math.radians(lon) - mx0) * k, oy + (my1 - merc(lat)) * k

    def ring(idx):
        pts = []
        for a in idx:
            seg = arcs[a] if a >= 0 else arcs[~a][::-1]
            pts.extend(seg if not pts else seg[1:])
        return pts

    paths = {}
    for g in topo["objects"]["countries"]["geometries"]:
        polys = g["arcs"] if g["type"] == "MultiPolygon" else [g["arcs"]] if g["type"] == "Polygon" else []
        path = skia.Path()
        hit = False
        for poly in polys:
            for r in poly:
                pts = ring(r)
                if not any(lon0 - 20 < x < lon1 + 20 and lat0 - 20 < y < lat1 + 20 for x, y in pts):
                    continue
                hit = True
                for j, (x, y) in enumerate(pts):
                    px, py = proj(x, y)
                    if j == 0:
                        path.moveTo(px, py)
                    else:
                        path.lineTo(px, py)
                path.close()
        if hit:
            paths[g["properties"]["name"]] = path
    return paths, proj


def draw_map(c, t, v, ctx):
    bounds = tuple(v.get("bounds", [92, 150, -4, 50]))
    paths, proj = map_paths(bounds)
    hl = v.get("highlight", {})
    ph = prog(t, 0.2, 1.2)
    for name, path in paths.items():
        c.drawPath(path, fill("#1B232E"))
        if name in hl:
            col = ACCENTS.get(hl[name], ORANGE)
            c.drawPath(path, fill(col, (0.75 if hl[name] == "blue" else 0.42) * ph))
        c.drawPath(path, stroke("#33404F", 1.5, 0.9, cap=skia.Paint.kButt_Cap))
    for i, pt in enumerate(v.get("points", [])):
        t0 = at_of(ctx, pt, 0.6 + 0.3 * i)
        p = prog(t, t0, 0.6)
        if p <= 0:
            continue
        x, y = proj(pt["lon"], pt["lat"])
        col = ACCENTS.get(pt.get("color", "gold"), GOLD)
        pulse = (t - t0) % 2.0 / 2.0
        c.drawCircle(x, y, 14 + 40 * pulse, stroke(col, 3, (1 - pulse) * 0.8 * p))
        c.drawCircle(x, y, 13 * p, fill(col, p))
        c.drawCircle(x, y, 13 * p, stroke("#FFFFFF", 3, p))
        f1, f2 = font(36, True), font(30)
        tw = max(text_width(pt["name"], f1), text_width(pt.get("value", ""), f2)) + 48
        dx, dy = pt.get("dx", 40), pt.get("dy", -60)
        bx = x + dx if dx >= 0 else x + dx - tw
        by = y + dy - 50
        c.drawLine(x, y, bx if dx >= 0 else bx + tw, by + 50, stroke(col, 2, 0.8 * p))
        glass_card(c, bx, by, tw, 100 if pt.get("value") else 64, p, r=14, color="#0B0F14", alpha=0.8, border=0.25)
        draw_text(c, pt["name"], bx + 24, by + 32, f1, TEXT, p)
        if pt.get("value"):
            draw_text(c, pt["value"], bx + 24, by + 74, f2, col, p)
    if v.get("heading"):
        draw_heading(c, t, v["heading"])
    draw_source(c, t, v.get("source"))


# --- 流れ図

def draw_flow(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    x0, x1 = 500, W - 420
    for i, row in enumerate(v["rows"]):
        t0 = at_of(ctx, row, 0.4 + 1.5 * i)
        yc = 400 + i * 290
        accent = row.get("tone") == "accent"
        col = GREEN if accent else MUTED
        p = prog(t, t0, 0.6)
        lab = row["label"].split("\n")
        for k, ln in enumerate(lab):
            draw_text(c, ln, 140, yc + (k - (len(lab) - 1) / 2) * 56, font(46, True), GREEN if accent else TEXT, p)
        steps = row["steps"]
        n = len(steps)
        xs = [x0 + (x1 - x0) * j / (n - 1) for j in range(n)]
        draw_d = 1.8
        g = ease_in_out((t - t0 - 0.2) / draw_d)
        if g > 0:
            c.drawLine(xs[0], yc, xs[0] + (xs[-1] - xs[0]) * g, yc, stroke(col, 6, 0.8 * p))
        if g >= 1:
            u = ((t - t0 - 0.2 - draw_d) * 0.35) % 1.0
            dot_x = xs[0] + (xs[-1] - xs[0]) * u
            c.drawCircle(dot_x, yc, 14, blur(fill(GOLD, 0.8), 8))
            c.drawCircle(dot_x, yc, 9, fill(GOLD))
        for j, (x, st) in enumerate(zip(xs, steps)):
            tj = t0 + 0.2 + draw_d * (j / max(1, n - 1)) - 0.15
            pj = prog(t, tj, 0.5)
            r = 64 * (0.7 + 0.3 * pj)
            c.drawCircle(x, yc, r, fill(BG_BOT, pj))
            c.drawCircle(x, yc, r, fill(col, (0.9 if accent else 0.22) * pj))
            c.drawCircle(x, yc, r, stroke(col, 3, pj))
            draw_icon(c, st["icon"], x, yc, 64, "#FFFFFF", pj)
            for k, ln in enumerate(st["text"].split("\n")):
                draw_text(c, ln, x, yc + 100 + k * 40, font(32, True), TEXT, pj, align="center")
            if row.get("margins") and 0 < j < n - 1:
                pm = prog(t, tj + 0.35, 0.4)
                by = yc - 120 - 14 * pm
                c.drawRRect(rrect(x - 70, by - 26, 140, 52, 26), fill(RED, pm))
                draw_text(c, "+利益", x, by, font(30, True), "#FFFFFF", pm, align="center", shadow=False)
        end = row.get("end")
        if end:
            pe = prog(t, t0 + 0.2 + draw_d, 0.5)
            ecol = RED if not accent else GREEN
            ex = xs[-1] + 120
            c.drawRRect(rrect(ex - 10, yc - 40, 190, 80, 40), fill(ecol, pe))
            draw_text(c, end, ex + 85, yc, font(36, True), "#FFFFFF", pe, align="center", shadow=False)
    if v.get("note"):
        draw_text(c, v["note"], W / 2, H - 190, font(40, True), GOLD, prog(t, at_of(ctx, v, 3.0), 0.7), align="center")


def draw_checklist(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    items = v["items"]
    gap = min(130, 520 / max(1, len(items) - 1)) if len(items) > 1 else 0
    for i, it in enumerate(items):
        t0 = at_of(ctx, it, 0.4 + 0.3 * i)
        p = prog(t, t0, 0.6)
        y = 330 + i * gap
        x = 160 - 40 * (1 - p)
        accent = ACCENTS.get(it.get("color", "gold"), GOLD)
        c.drawCircle(x + 40, y, 44, fill(accent, 0.18 * p))
        draw_icon(c, it.get("icon", "check_circle"), x + 40, y, 52, accent, p)
        draw_rich(c, it["text"], x + 120, y, font(52, True), TEXT, accent, p, align="left")
    if v.get("footer"):
        draw_text(c, v["footer"], 140, 330 + len(items) * gap + 10, font(26), MUTED, prog(t, 1.0, 0.8), shadow=False)


def draw_formula(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    terms = v["terms"]
    emph = v.get("emphasis")
    f = font(56, True)
    widths = [text_width(s, f) + 120 for s in terms]
    ops = v.get("ops", ["=", "×"])
    gap = 130
    total = sum(widths) + gap * (len(terms) - 1)
    x = (W - total) / 2
    yc = 500
    for i, s in enumerate(terms):
        p = prog(t, 0.3 + 0.35 * i, 0.6)
        hl = i == emph
        yy = yc + 30 * (1 - p)
        if hl:
            pulse = 0.5 + 0.5 * math.sin(t * 3)
            c.drawRRect(rrect(x - 8, yy - 118, widths[i] + 16, 236, 30), blur(fill(GOLD, (0.25 + 0.2 * pulse) * p), 24))
            c.drawRRect(rrect(x, yy - 110, widths[i], 220, 26), fill(GOLD, p))
            draw_text(c, s, x + widths[i] / 2, yy, f, BG_TOP, p, align="center", shadow=False)
        else:
            glass_card(c, x, yy - 110, widths[i], 220, p)
            draw_text(c, s, x + widths[i] / 2, yy, f, TEXT, p, align="center")
        x += widths[i]
        if i < len(terms) - 1:
            draw_text(c, ops[i], x + gap / 2, yc, font(86, True), MUTED, prog(t, 0.5 + 0.35 * i, 0.5), align="center")
            x += gap
    if v.get("note"):
        draw_text(c, v["note"], W / 2, 760, font(42, True), GOLD, prog(t, at_of(ctx, v, 1.6), 0.7), align="center")


def draw_linechart(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    pts = v["points"]
    vmax = v.get("max", max(p["value"] for p in pts) * 1.3)
    x0, x1, y0, y1 = 300, W - 300, 730, 330
    p0 = prog(t, 0.2, 0.6)
    c.drawLine(x0 - 60, y0, x1 + 60, y0, stroke(LINE, 4, p0))
    xy = [(x0 + (x1 - x0) * i / (len(pts) - 1), y0 - (y0 - y1) * p["value"] / vmax) for i, p in enumerate(pts)]
    times = [at_of(ctx, p, 0.5 + 0.8 * i) for i, p in enumerate(pts)]
    accent = ACCENTS.get(v.get("accent", "blue"), BLUE)
    for i in range(1, len(pts)):
        g = ease_in_out((t - times[i]) / 0.8)
        if g > 0:
            (ax, ay), (bx, by) = xy[i - 1], xy[i]
            c.drawLine(ax, ay, ax + (bx - ax) * g, ay + (by - ay) * g, stroke(accent, 8))
    for i, (pt, (x, y)) in enumerate(zip(pts, xy)):
        p = prog(t, times[i] + (0.6 if i else 0), 0.5)
        c.drawCircle(x, y, 26 * p, blur(fill(accent, 0.5 * p), 12))
        c.drawCircle(x, y, 16 * p, fill(accent, p))
        c.drawCircle(x, y, 16 * p, stroke("#FFFFFF", 4, p))
        draw_text(c, pt.get("display", str(pt["value"])), x, y - 80, font(64, True), TEXT, p, align="center")
        for k, ln in enumerate(pt["label"].split("\n")):
            draw_text(c, ln, x, y0 + 55 + k * 40, font(32), MUTED, p, align="center")
    draw_source(c, t, v.get("source"))


def draw_timeline(c, t, v, ctx):
    draw_heading(c, t, v.get("heading"))
    ev = v["events"]
    top, bottom = 310, 790
    step = (bottom - top) / max(1, len(ev) - 1)
    lx = 560
    g = ease_in_out((t - 0.2) / 1.2)
    c.drawLine(lx, top, lx, top + (bottom - top) * g, stroke(LINE, 6))
    for i, e in enumerate(ev):
        t0 = at_of(ctx, e, 0.4 + 0.3 * i)
        p = prog(t, t0, 0.6)
        y = top + i * step
        col = RED if e.get("hl") else GOLD
        c.drawCircle(lx, y, 20 * p, fill(col, p))
        draw_text(c, e["date"], lx - 50, y, font(40, True), col, p, align="right")
        draw_text(c, e["text"], lx + 50 + 30 * (1 - p), y, font(40), TEXT, p)
    draw_source(c, t, v.get("source"))


def draw_bignum(c, t, v, ctx):
    if v.get("heading"):
        draw_heading(c, t, v["heading"])
    pl = prog(t, 0.2, 0.6)
    draw_text(c, v["left_label"], 560, 380, font(44), MUTED, pl, align="center")
    draw_text(c, v["left"], 560, 540, font(170, True), TEXT, pl, align="center")
    pa = prog(t, 0.8, 0.6)
    path = skia.Path()
    path.moveTo(860, 540)
    path.lineTo(960 + 30 * pa, 540)
    c.drawPath(path, stroke(GOLD, 10, pa))
    tri = skia.Path()
    tri.moveTo(1010 + 30 * pa, 540)
    tri.lineTo(965 + 30 * pa, 505)
    tri.lineTo(965 + 30 * pa, 575)
    tri.close()
    c.drawPath(tri, fill(GOLD, pa))
    t0 = at_of(ctx, v, 1.1)
    pr = prog(t, t0, 0.6)
    draw_text(c, v["right_label"], 1460, 380, font(44), MUTED, pr, align="center")
    draw_text(c, fmt_count(v["right"], ease_out((t - t0) / 1.2)), 1460, 540, font(150, True), GOLD, pr, align="center")
    if v.get("note"):
        draw_text(c, v["note"], W / 2, 730, font(36), MUTED, prog(t, t0 + 1.0, 0.8), align="center")
    draw_source(c, t, v.get("source"))


def draw_chapter(c, t, v, ctx):
    p = prog(t, 0.0, 0.7)
    draw_text(c, "CHAPTER", W / 2, 360, font(32, True), MUTED, p, align="center")
    draw_text(c, v["number"], W / 2, 480, font(150, True), GOLD, p, align="center")
    lw = 640 * ease_in_out((t - 0.2) / 0.9)
    c.drawRect(skia.Rect.MakeXYWH(W / 2 - lw / 2, 590, lw, 3), fill(TEXT, 0.6))
    pt = prog(t, 0.4, 0.7)
    draw_text(c, v["title"], W / 2, 680 + 20 * (1 - pt), font(76, True), TEXT, pt, align="center")


class VideoReader:
    """ffmpeg で動画素材を 1920x1080・30fps に変換しながら 1 フレームずつ読む。"""

    def __init__(self, path):
        self.path = path
        self.proc = None
        self.idx = -1
        self.length = None
        self.img = None

    def _open(self):
        if self.proc:
            self.proc.kill()
        self.proc = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-i", self.path, "-an", "-vf",
             f"scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}",
             "-f", "rawvideo", "-pix_fmt", "rgba", "-"], stdout=subprocess.PIPE)
        self.idx = -1

    def get(self, i):
        if self.length:
            i %= self.length
        if self.proc is None or i < self.idx:
            self._open()
        while self.idx < i:
            buf = self.proc.stdout.read(W * H * 4)
            if len(buf) < W * H * 4:
                self.length = max(1, self.idx + 1)
                i %= self.length
                self._open()
                continue
            self.idx += 1
            if self.idx == i:
                arr = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 4)
                self.img = skia.Image.fromarray(arr, colorType=skia.kRGBA_8888_ColorType)
        return self.img


_READERS = {}


def asset_path(rel):
    p = ROOT.parent / rel
    return p if p.exists() else None


def draw_footage(c, t, v, ctx):
    """実写素材（動画・写真）。素材ファイルが無いときは fallback の演出を描く。"""
    path = asset_path(v["path"])
    if path is None:
        fb = v.get("fallback")
        if fb:
            RENDERERS[fb["type"]](c, t, fb, ctx)
        else:
            draw_text(c, f"[素材待ち] {v['path']}", W / 2, H / 2, font(40, True), MUTED, align="center")
        return
    if path.suffix.lower() in (".mp4", ".mov", ".webm", ".mkv"):
        key = (str(path), ctx.get("key"))
        if key not in _READERS:
            _READERS[key] = VideoReader(str(path))
        img = _READERS[key].get(int((t + v.get("offset", 0)) * FPS))
    else:
        img = image_cache(str(path))
    s = 1.02 + 0.06 * clamp(t / max(ctx["dur"], 0.1))
    iw, ih = img.width(), img.height()
    k = max(W / iw, H / ih) * s
    c.drawImageRect(img, skia.Rect.MakeXYWH((W - iw * k) / 2 + v.get("pan", 0) * t, (H - ih * k) / 2, iw * k, ih * k),
                    skia.SamplingOptions(skia.FilterMode.kLinear))
    # シネマ風のカラーグレーディング（暗部をティール、明部をオレンジ寄りに）
    c.drawRect(skia.Rect(0, 0, W, H), fill("#000000", v.get("dim", 0.3)))
    sh = skia.GradientShader.MakeLinear([(0, 0), (W, H)], [C("#0E4A55", 0.22), C("#0E4A55", 0.0), C("#C86A2A", 0.16)],
                                        [0, 0.5, 1])
    c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=sh))
    lt = v.get("lower_third")
    if lt:
        p = prog(t, 0.4, 0.7)
        x, y = 120 - 40 * (1 - p), H - 330
        c.drawRect(skia.Rect.MakeXYWH(x, y - 40, 8, 110), fill(GOLD, p))
        draw_text(c, lt["title"], x + 34, y, font(56, True), TEXT, p)
        if lt.get("sub"):
            draw_text(c, lt["sub"], x + 34, y + 54, font(30), MUTED, p)
    if v.get("text"):
        draw_rich(c, v["text"], W / 2, H / 2, font(96, True), TEXT, GOLD, prog(t, 0.3, 0.8))


def draw_image(c, t, v, ctx):
    draw_footage(c, t, v, ctx)


@lru_cache(maxsize=16)
def image_cache(path):
    return skia.Image.open(path)


def draw_endscreen(c, t, v, ctx):
    """終了画面。YouTube の終了画面要素（動画・登録ボタン）を置く場所を空けておく。"""
    p = prog(t, 0.0, 0.8)
    draw_text(c, v.get("title", ""), W / 2, 170, font(64, True), TEXT, p, align="center")
    draw_text(c, v.get("sub", ""), W / 2, 250, font(34), MUTED, p, align="center")
    # 左: おすすめ動画の枠 (16:9)、右: チャンネル登録の丸
    c.drawRRect(rrect(260, 380, 800, 450, 24), stroke(GOLD, 4, 0.8 * p))
    draw_text(c, v.get("next", "次の動画"), 660, 605, font(44, True), MUTED, 0.6 * p, align="center")
    c.drawCircle(1440, 605, 190, stroke(GOLD, 4, 0.8 * p))
    draw_text(c, "チャンネル登録", 1440, 605, font(40, True), MUTED, 0.6 * p, align="center")


RENDERERS = {
    "title": draw_title, "headline": draw_headline, "doria": draw_doria, "ring": draw_ring,
    "year": draw_year, "pricedrop": draw_pricedrop, "stats": draw_stats, "bars": draw_bars,
    "map": draw_map, "flow": draw_flow, "checklist": draw_checklist, "formula": draw_formula,
    "linechart": draw_linechart, "timeline": draw_timeline, "bignum": draw_bignum,
    "chapter": draw_chapter, "image": draw_image, "footage": draw_footage, "endscreen": draw_endscreen,
}


# ---------------------------------------------------------------- クリップ単位の描画

XFADE = 0.45
EDGE_FADE = 0.3


def draw_clip_frame(c, clip, t, tg, frame_idx, captions):
    """clip: {'dur', 'shots': [{'start','end','at','visual'}], 'lines': [{'st','en','text',...}]} (時刻はクリップ基準)。"""
    draw_background(c, tg)
    shots = clip["shots"]
    idx = 0
    for i, s in enumerate(shots):
        if t >= s["start"]:
            idx = i
    layers = [(idx, 1.0)]
    if idx > 0 and t - shots[idx]["start"] < XFADE:
        p = ease_in_out((t - shots[idx]["start"]) / XFADE)
        layers = [(idx - 1, 1 - p), (idx, p)]
    for i, a in layers:
        s = shots[i]
        ts = t - s["start"]
        dur = s["end"] - s["start"]
        zoom = 1.0 + 0.04 * clamp(ts / max(dur, 0.1))
        if a < 0.999:
            c.saveLayerAlpha(None, int(255 * a))
        else:
            c.save()
        c.translate(W / 2, H / 2)
        c.scale(zoom, zoom)
        c.translate(-W / 2, -H / 2)
        at = s["at"]
        ctx = {"dur": dur, "key": (clip.get("id"), i), "at": (lambda j, at=at: at.get(j, 0.0))}
        RENDERERS[s["visual"]["type"]](c, ts, s["visual"], ctx)
        c.restore()
    if captions:
        cur = None
        question = None
        for ln in clip["lines"]:
            if t >= ln["st"]:
                cur = ln
                if ln.get("q"):
                    question = ln
        for ln in clip["lines"]:
            if ln.get("impact"):
                draw_impact(c, ln["impact"], t - ln["st"], ln.get("impact_dur", 2.2),
                            ACCENTS.get(ln.get("accent", "gold"), GOLD))
        if question:
            draw_question(c, question["q"], t - question["st"])
        if cur:
            y0 = draw_caption(c, cur["text"], t - cur["st"])
            if cur.get("note") and y0:
                draw_note(c, cur["note"], y0 - 70, t - cur["st"])
    draw_finish(c, frame_idx)
    edge = min(1.0, t / EDGE_FADE, (clip["dur"] - t) / EDGE_FADE)
    if edge < 1.0:
        c.drawRect(skia.Rect(0, 0, W, H), fill("#000000", 1 - max(0.0, edge)))


def render_thumbnail(thumb, channel, out):
    w, h = 1280, 720
    arr = np.zeros((h, w, 4), dtype=np.uint8)
    surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType)
    with surf as c:
        c.scale(w / W, h / H)
        draw_background(c, 2.0)
        draw_dish(c, 1440, 600, 1.05, 1.0)
        c.drawRect(skia.Rect(0, 0, W, H), skia.Paint(Shader=skia.GradientShader.MakeLinear(
            [(0, 0), (W, 0)], [C("#05070A", 0.9), C("#05070A", 0.55), C("#05070A", 0)], [0, 0.5, 0.8])))
        draw_text(c, thumb.get("kicker", ""), 110, 170, font(60, True), GOLD)
        for i, ln in enumerate(thumb["title"].split("\n")):
            draw_rich(c, ln, 110, 400 + i * 200, font(170, True), "#FFFFFF", GOLD, align="left")
        if thumb.get("badge"):
            f = font(72, True)
            bw = text_width(thumb["badge"], f) + 100
            c.drawRRect(rrect(110, 780, bw, 140, 24), fill(RED))
            draw_text(c, thumb["badge"], 110 + bw / 2, 850, f, "#FFFFFF", align="center")
        draw_text(c, channel, W - 60, H - 50, font(34, True), MUTED, align="right")
    surf.makeImageSnapshot().save(str(out), skia.kPNG)
