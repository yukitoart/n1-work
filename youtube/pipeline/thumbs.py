#!/usr/bin/env python3
"""目立つアイコン・サムネイルの生成（複数案）。

  python3 pipeline/thumbs.py → channel/icon_*.png, build/<id>/thumbnail_*.png
"""

import math
import sys
from pathlib import Path

import numpy as np
import skia
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import motion as m  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
YELLOW = "#FFD23F"
RED = "#E8352B"
BLACK = "#111318"
WHITE = "#FFFFFF"


def save(surf, path):
    arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    Image.fromarray(arr, "RGBA").convert("RGB").save(path)


def outlined(c, s, x, y, size, fill_color, outline=BLACK, ow=0.16, align="center", shadow=True, inner=None):
    """太いフチ取り文字（サムネイル用）。y は文字の縦中心。"""
    f = m.font(size, True)
    w = f.measureText(s)
    if align == "center":
        x -= w / 2
    elif align == "right":
        x -= w
    base = y + size * 0.36
    if shadow:
        p = m.blur(m.stroke("#000000", size * ow * 2.2, 0.55), size * 0.06)
        c.drawString(s, x + size * 0.04, base + size * 0.06, f, p)
    c.drawString(s, x, base, f, m.stroke(outline, size * ow * 2))
    if inner:
        c.drawString(s, x, base, f, m.stroke(inner, size * ow * 0.8))
    c.drawString(s, x, base, f, m.fill(fill_color))
    return w


def burst(c, cx, cy, n, r, col1, col2, rot=0.0):
    """集中線（放射状の帯）の背景。"""
    c.drawRect(skia.Rect(-2000, -2000, 6000, 6000), m.fill(col1))
    for i in range(n):
        a0 = rot + 2 * math.pi * i / n
        a1 = a0 + math.pi / n
        path = skia.Path()
        path.moveTo(cx, cy)
        path.lineTo(cx + r * math.cos(a0), cy + r * math.sin(a0))
        path.lineTo(cx + r * math.cos(a1), cy + r * math.sin(a1))
        path.close()
        c.drawPath(path, m.fill(col2))


def lens(c, cx, cy, r, lw, ring=BLACK, glass="#FFFFFF", yen=RED, handle=BLACK, arrow=None):
    ang = math.radians(45)
    c.drawLine(cx + r * math.cos(ang), cy + r * math.sin(ang),
               cx + r * 1.8 * math.cos(ang), cy + r * 1.8 * math.sin(ang), m.stroke(handle, lw * 1.9))
    c.drawCircle(cx, cy, r, m.fill(glass))
    c.drawCircle(cx, cy, r, m.stroke(ring, lw))
    m.draw_text(c, "¥", cx, cy + r * 0.03, m.font(r * 1.35, True), yen, align="center", shadow=False)
    if arrow:
        path = skia.Path()
        pts = [(-0.72, 0.5), (-0.25, 0.12), (0.08, 0.32), (0.62, -0.38)]
        for i, (x, y) in enumerate(pts):
            px, py = cx + x * r, cy + y * r
            path.moveTo(px, py) if i == 0 else path.lineTo(px, py)
        c.drawPath(path, m.stroke(BLACK, lw * 1.05))
        c.drawPath(path, m.stroke(arrow, lw * 0.6))
        tip = skia.Path()
        tx, ty = cx + 0.62 * r, cy - 0.38 * r
        tip.moveTo(tx + r * 0.2, ty - r * 0.16)
        tip.lineTo(tx - r * 0.04, ty - r * 0.14)
        tip.lineTo(tx + r * 0.1, ty + r * 0.09)
        tip.close()
        c.drawPath(tip, m.fill(arrow))


# ---------------------------------------------------------------- アイコン

def icon_a(path):
    """黄色の集中線 × 黒い虫眼鏡 × 赤い¥。"""
    s = 800
    surf = skia.Surface(s, s)
    with surf as c:
        burst(c, 400, 400, 28, 900, YELLOW, "#FFC21A", rot=0.1)
        lens(c, 365, 360, 215, 46, arrow=RED)
    save(surf, path)


def icon_b(path):
    """赤地に白い「儲」を、金の虫眼鏡で囲む。"""
    s = 800
    surf = skia.Surface(s, s)
    with surf as c:
        burst(c, 400, 400, 28, 900, RED, "#D42C23", rot=0.05)
        ang = math.radians(45)
        cx, cy, r = 370, 365, 230
        c.drawLine(cx + r * math.cos(ang), cy + r * math.sin(ang),
                   cx + r * 1.75 * math.cos(ang), cy + r * 1.75 * math.sin(ang), m.stroke(YELLOW, 80))
        c.drawCircle(cx, cy, r, m.fill(BLACK))
        c.drawCircle(cx, cy, r, m.stroke(YELLOW, 44))
        outlined(c, "儲", cx, cy + 6, 300, WHITE, outline=BLACK, ow=0.05, shadow=False)
    save(surf, path)


def icon_c(path):
    """黒地に黄色の虫眼鏡。¥ と上昇矢印で「お金の仕組みを暴く」。"""
    s = 800
    surf = skia.Surface(s, s)
    with surf as c:
        sh = skia.GradientShader.MakeRadial((400, 380), 560, [m.C("#2A2F3A"), m.C(BLACK)])
        c.drawRect(skia.Rect(0, 0, s, s), skia.Paint(Shader=sh))
        lens(c, 365, 360, 215, 46, ring=YELLOW, glass=YELLOW, yen=BLACK, handle=YELLOW, arrow=RED)
    save(surf, path)


# ---------------------------------------------------------------- サムネイル (1280x720 を 1920x1080 座標で描く)

def thumb_a(path, ep):
    """集中線 × 巨大な「300円」 × ドリア。"""
    surf = skia.Surface(1280, 720)
    with surf as c:
        c.scale(1280 / 1920, 720 / 1080)
        burst(c, 1420, 560, 36, 2400, "#FFB000", YELLOW, rot=0.03)
        sh = skia.GradientShader.MakeRadial((1420, 560), 900, [m.C("#FFFFFF", 0.35), m.C("#FFFFFF", 0)])
        c.drawRect(skia.Rect(0, 0, 1920, 1080), skia.Paint(Shader=sh))
        c.save()
        c.translate(1440, 620)
        c.rotate(-8)
        m.draw_dish(c, 0, 0, 1.12, 1.0)
        c.restore()
        # 値札
        c.save()
        c.translate(1660, 300)
        c.rotate(12)
        c.drawCircle(0, 0, 170, m.blur(m.fill("#000000", 0.4), 16))
        c.drawCircle(0, 0, 165, m.fill(RED))
        c.drawCircle(0, 0, 165, m.stroke(WHITE, 10))
        outlined(c, "税込", 0, -70, 54, WHITE, ow=0.0, shadow=False)
        outlined(c, "300円", 0, 30, 104, WHITE, outline=BLACK, ow=0.08, shadow=False)
        c.restore()
        # 文字
        c.drawRect(skia.Rect(0, 0, 1920, 1080), skia.Paint(Shader=skia.GradientShader.MakeLinear(
            [(0, 0), (1100, 0)], [m.C("#000000", 0.25), m.C("#000000", 0)])))
        outlined(c, "サイゼリヤ", 90, 150, 110, WHITE, align="left", ow=0.14)
        outlined(c, "300円", 70, 420, 330, YELLOW, align="left", ow=0.09, inner=RED)
        outlined(c, "でなぜ儲かる？", 90, 700, 150, WHITE, align="left", ow=0.12)
        # 赤帯
        c.save()
        c.translate(80, 890)
        c.rotate(-3)
        f = m.font(84, True)
        bw = f.measureText("利益の2/3は海外だった") + 90
        c.drawRect(skia.Rect.MakeXYWH(0, -70, bw, 140), m.blur(m.fill("#000000", 0.5), 12))
        c.drawRect(skia.Rect.MakeXYWH(0, -70, bw, 140), m.fill(RED))
        outlined(c, "利益の2/3は海外だった", 45, 0, 84, WHITE, align="left", ow=0.06, shadow=False)
        c.restore()
    save(surf, path)


def thumb_b(path, ep):
    """黒背景 × 黄色の巨大文字 × 赤い「利益2/3は海外」。ダークでも強いコントラスト。"""
    surf = skia.Surface(1280, 720)
    with surf as c:
        c.scale(1280 / 1920, 720 / 1080)
        c.drawRect(skia.Rect(0, 0, 1920, 1080), m.fill(BLACK))
        sh = skia.GradientShader.MakeRadial((1450, 560), 820, [m.C("#FF9A1F", 0.55), m.C("#FF9A1F", 0)])
        c.drawRect(skia.Rect(0, 0, 1920, 1080), skia.Paint(Shader=sh))
        c.save()
        c.translate(1450, 600)
        c.rotate(-6)
        m.draw_dish(c, 0, 0, 1.1, 1.0)
        c.restore()
        outlined(c, "300円ドリアで", 80, 190, 140, WHITE, align="left", ow=0.1)
        outlined(c, "なぜ", 80, 440, 230, WHITE, align="left", ow=0.08)
        outlined(c, "儲かる？", 80, 690, 260, YELLOW, align="left", ow=0.08, inner=RED)
        # 赤いスタンプ
        c.save()
        c.translate(1500, 210)
        c.rotate(-10)
        f = m.font(70, True)
        txt = "利益の2/3は海外"
        bw = f.measureText(txt) + 80
        c.drawRRect(m.rrect(-bw / 2, -75, bw, 150, 18), m.fill(RED))
        c.drawRRect(m.rrect(-bw / 2 + 10, -65, bw - 20, 130, 12), m.stroke(WHITE, 6))
        outlined(c, txt, 0, 0, 70, WHITE, ow=0.0, shadow=False)
        c.restore()
        # 下の帯
        c.drawRect(skia.Rect.MakeXYWH(0, 900, 1920, 180), m.fill(YELLOW))
        outlined(c, "決算でわかった「安さのカラクリ」", 960, 990, 92, BLACK, outline=YELLOW, ow=0.0, shadow=False)
    save(surf, path)


def main():
    ep_id = "001_saizeriya"
    ch = ROOT / "channel"
    out = ROOT / "build" / ep_id
    out.mkdir(parents=True, exist_ok=True)
    icon_a(ch / "icon_a.png")
    icon_b(ch / "icon_b.png")
    icon_c(ch / "icon_c.png")
    thumb_a(out / "thumbnail_a.png", ep_id)
    thumb_b(out / "thumbnail_b.png", ep_id)
    print("ok")


if __name__ == "__main__":
    main()
