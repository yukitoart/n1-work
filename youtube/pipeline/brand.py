#!/usr/bin/env python3
"""チャンネルアイコン (800x800) とバナー (2560x1440) を生成する。

  python3 pipeline/brand.py   → channel/ に PNG を書き出す
"""

import math
import sys
from pathlib import Path

import numpy as np
import skia

sys.path.insert(0, str(Path(__file__).resolve().parent))
import motion as m  # noqa: E402

OUT = Path(__file__).resolve().parent.parent / "channel"
NAME = "儲けのカラクリ研究所"
TAGLINE = "身近な企業の「儲けのカラクリ」を、決算の数字で解き明かす"


def surface(w, h):
    return skia.Surface(w, h)


def save_png(surf, path):
    from PIL import Image
    arr = surf.makeImageSnapshot().toarray(colorType=skia.kRGBA_8888_ColorType)
    Image.fromarray(arr, "RGBA").convert("RGB").save(path)


def dark_bg(c, w, h):
    sh = skia.GradientShader.MakeRadial((w * 0.35, h * 0.3), max(w, h) * 0.9,
                                        [m.C("#1C2431"), m.C("#0B0F14")])
    c.drawRect(skia.Rect(0, 0, w, h), skia.Paint(Shader=sh))


def draw_lens(c, cx, cy, r, lw):
    """虫眼鏡（レンズの中に円マーク）。チャンネルの「解き明かす」を表すマーク。"""
    ang = math.radians(45)
    hx0, hy0 = cx + r * math.cos(ang), cy + r * math.sin(ang)
    hx1, hy1 = cx + r * 1.75 * math.cos(ang), cy + r * 1.75 * math.sin(ang)
    c.drawLine(hx0, hy0, hx1, hy1, m.stroke(m.GOLD, lw * 1.6))
    c.drawCircle(cx, cy, r, m.fill("#0B0F14"))
    c.drawCircle(cx, cy, r, m.blur(m.stroke(m.GOLD, lw, 0.5), lw * 0.8))
    c.drawCircle(cx, cy, r, m.stroke(m.GOLD, lw))
    f = m.font(r * 1.25, True)
    m.draw_text(c, "¥", cx, cy + r * 0.02, f, m.GOLD, align="center", shadow=False)
    # 上昇グラフの線（レンズの中を横切る）
    path = skia.Path()
    pts = [(-0.75, 0.45), (-0.3, 0.1), (0.05, 0.3), (0.7, -0.45)]
    for i, (x, y) in enumerate(pts):
        px, py = cx + x * r, cy + y * r
        path.moveTo(px, py) if i == 0 else path.lineTo(px, py)
    c.save()
    clip = skia.Path()
    clip.addCircle(cx, cy, r - lw / 2)
    c.clipPath(clip, doAntiAlias=True)
    c.drawPath(path, m.stroke(m.RED, lw * 0.55, 0.9))
    c.restore()


def icon(path):
    s = 800
    surf = surface(s, s)
    with surf as c:
        dark_bg(c, s, s)
        draw_lens(c, 370, 360, 205, 34)
    save_png(surf, path)


def banner(path):
    w, h = 2560, 1440
    surf = surface(w, h)
    with surf as c:
        dark_bg(c, w, h)
        for i, (x, y, r, col) in enumerate([(700, 500, 900, m.GOLD), (1950, 1000, 900, m.BLUE)]):
            sh = skia.GradientShader.MakeRadial((x, y), r, [m.C(col, 0.12), m.C(col, 0)])
            c.drawCircle(x, y, r, skia.Paint(Shader=sh))
        # 背景の薄い上昇チャート
        chart = skia.Path()
        rng = np.random.default_rng(4)
        y = 980
        for i, x in enumerate(range(0, w + 40, 40)):
            y -= rng.normal(3.2, 14)
            chart.moveTo(x, y) if i == 0 else chart.lineTo(x, y)
        c.drawPath(chart, m.stroke(m.GOLD, 4, 0.12))
        # すべての端末で見えるセーフエリア (1546x423, 中央) に収める
        cx, cy = w / 2, h / 2
        draw_lens(c, cx - 560, cy - 10, 92, 16)
        m.draw_text(c, NAME, cx - 430, cy - 40, m.font(112, True), m.TEXT)
        m.draw_text(c, TAGLINE, cx - 428, cy + 70, m.font(40), m.MUTED, shadow=False)
        c.drawRect(skia.Rect.MakeXYWH(cx - 428, cy + 125, 120, 6), m.fill(m.GOLD))
    save_png(surf, path)


def main():
    OUT.mkdir(exist_ok=True)
    icon(OUT / "icon.png")
    banner(OUT / "banner.png")
    print(OUT / "icon.png", OUT / "banner.png")


if __name__ == "__main__":
    main()
