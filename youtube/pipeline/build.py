#!/usr/bin/env python3
"""エピソード定義 (episode.json) から下書き動画を自動生成する。

  python3 youtube/pipeline/build.py youtube/episodes/001_saizeriya

出力 (youtube/build/<episode id>/):
  video.mp4        字幕焼き込み済みの本編
  thumbnail.png    サムネイル (1280x720)
  captions.srt     YouTube にアップロードする字幕ファイル
  description.txt  チャプター入りの概要欄 (episode フォルダの description.md を元に生成)
  frames/ audio/   中間ファイル

音声は --tts で切り替える:
  openjtalk (既定)  オフラインで動く。仮ナレーション用
  voicevox          VOICEVOX エンジン (VOICEVOX_URL, 既定 http://127.0.0.1:50021) を呼ぶ
"""

import argparse
import json
import os
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.patches import FancyBboxPatch, Rectangle, FancyArrowPatch, Circle
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
FONT_DIR = ROOT / "fonts"
FONT_REGULAR = FONT_DIR / "NotoSansJP_500Medium.ttf"
FONT_BOLD = FONT_DIR / "NotoSansJP_800ExtraBold.ttf"

W, H = 1920, 1080
FPS = 30
SAMPLE_RATE = 48000
PAUSE_BEFORE = 0.15  # 秒
PAUSE_AFTER = 0.35

# 配色
BG = "#F7F3EC"
INK = "#1E2227"
MUTED = "#7C828C"
CARD = "#FFFFFF"
LINE = "#E3DDD2"
GREEN = "#2F7D55"
RED = "#C2412D"
NAVY = "#3B5B8C"
ORANGE = "#D9822B"
GRAY_BOX = "#E6E2DA"


# ---------------------------------------------------------------- 描画ユーティリティ

def px(size):
    """ピクセル指定の文字サイズを matplotlib のポイントに変換 (dpi=100)。"""
    return size * 0.72


def setup_fonts():
    for f in (FONT_REGULAR, FONT_BOLD):
        if not f.exists():
            sys.exit(f"フォントがありません: {f}\n先に youtube/pipeline/setup.sh を実行してください。")
        font_manager.fontManager.addfont(str(f))
    plt.rcParams["font.family"] = font_manager.FontProperties(fname=str(FONT_REGULAR)).get_name()
    plt.rcParams["font.weight"] = "medium"


def bold():
    return font_manager.FontProperties(fname=str(FONT_BOLD))


def regular():
    return font_manager.FontProperties(fname=str(FONT_REGULAR))


def new_canvas(w=W, h=H, bg=BG):
    fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis("off")
    fig.patch.set_facecolor(bg)
    return fig, ax


def text(ax, x, y, s, size, color=INK, weight="regular", ha="left", va="center", **kw):
    fp = bold() if weight == "bold" else regular()
    fp.set_size(px(size))
    ax.text(x, y, s, fontproperties=fp, color=color, ha=ha, va=va, **kw)


def card(ax, x, y, w, h, fc=CARD, ec=LINE, r=24, lw=2):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                fc=fc, ec=ec, lw=lw))


def heading(ax, s):
    text(ax, 120, 120, s, 64, weight="bold")
    ax.add_patch(Rectangle((120, 172), 96, 10, fc=GREEN, ec="none"))


def source(ax, s):
    if s:
        text(ax, 120, 830, s, 24, color=MUTED)


def watermark(ax, channel):
    text(ax, W - 80, 56, channel, 24, color=MUTED, ha="right")


# ---------------------------------------------------------------- シーン種別ごとの描画

def draw_title(ax, v):
    text(ax, W / 2, 270, v.get("kicker", ""), 40, color=GREEN, weight="bold", ha="center")
    text(ax, W / 2, 480, v["title"], 120, weight="bold", ha="center", linespacing=1.25)
    text(ax, W / 2, 720, v.get("subtitle", ""), 44, color=MUTED, ha="center")


def draw_stats(ax, v):
    heading(ax, v["heading"])
    stats = v["stats"]
    gap = 60
    cw = (W - 240 - gap * (len(stats) - 1)) / len(stats)
    for i, s in enumerate(stats):
        x = 120 + i * (cw + gap)
        card(ax, x, 270, cw, 440)
        text(ax, x + cw / 2, 350, s["label"], 40, ha="center")
        text(ax, x + cw / 2, 480, s["value"], 96, color=GREEN, weight="bold", ha="center")
        if s.get("delta"):
            text(ax, x + cw / 2, 610, s["delta"], 32, color=MUTED, ha="center")
    source(ax, v.get("source"))


def draw_share_flip(ax, v):
    heading(ax, v["heading"])
    x0, x1 = 440, W - 120
    bw = x1 - x0
    for i, row in enumerate(v["rows"]):
        y = 260 + i * 210
        total = row["japan"] + row["asia"]
        jw = bw * row["japan"] / total
        text(ax, 120, y + 70, row["label"], 48, weight="bold")
        ax.add_patch(Rectangle((x0, y), jw, 140, fc=NAVY, ec="none"))
        ax.add_patch(Rectangle((x0 + jw, y), bw - jw, 140, fc=ORANGE, ec="none"))
        jp = round(row["japan"] / total * 100)
        unit = row["unit"]
        text(ax, x0 + 30, y + 70, f"日本 {jp}%\n{row['japan']:,g}{unit}", 36, color="white",
             weight="bold", linespacing=1.3)
        text(ax, x1 - 30, y + 70, f"アジア {100 - jp}%\n{row['asia']:,g}{unit}", 36, color="white",
             weight="bold", ha="right", linespacing=1.3)
    m = v["margins"]
    card(ax, 120, 690, W - 240, 110)
    text(ax, 170, 745, "営業利益率", 40, weight="bold")
    text(ax, 900, 745, f"日本  {m['japan']}", 52, color=NAVY, weight="bold", ha="center")
    text(ax, 1200, 745, "／", 40, color=MUTED, ha="center")
    text(ax, 1500, 745, f"アジア  {m['asia']}", 52, color=ORANGE, weight="bold", ha="center")
    source(ax, v.get("source"))


def draw_flow(ax, v):
    heading(ax, v["heading"])
    x0, x1 = 460, W - 120
    for i, row in enumerate(v["rows"]):
        yc = 340 + i * 230
        accent = row.get("tone") == "accent"
        text(ax, 120, yc, row["label"], 44, weight="bold", color=GREEN if accent else INK)
        n = len(row["steps"])
        arrow = 70
        bw = (x1 - x0 - arrow * (n - 1)) / n
        for j, step in enumerate(row["steps"]):
            bx = x0 + j * (bw + arrow)
            card(ax, bx, yc - 75, bw, 150, fc=GREEN if accent else GRAY_BOX, ec="none", r=18)
            text(ax, bx + bw / 2, yc, step, 36, color="white" if accent else INK,
                 weight="bold", ha="center", linespacing=1.2)
            if j < n - 1:
                ax.add_patch(FancyArrowPatch((bx + bw + 10, yc), (bx + bw + arrow - 10, yc),
                                             arrowstyle="-|>", mutation_scale=30, lw=4,
                                             color=GREEN if accent else MUTED))
    if v.get("note"):
        text(ax, W / 2, 780, v["note"], 40, color=RED, weight="bold", ha="center")


def draw_bullets(ax, v):
    heading(ax, v["heading"])
    for i, item in enumerate(v["items"]):
        y = 300 + i * 120
        ax.add_patch(Rectangle((130, y - 14), 28, 28, fc=GREEN, ec="none"))
        text(ax, 190, y, item, 52)
    if v.get("footer"):
        text(ax, 120, 830, v["footer"], 26, color=MUTED)


def draw_formula(ax, v):
    heading(ax, v["heading"])
    terms = v["terms"]
    emph = v.get("emphasis")
    widths = [360, 560, 560]
    ops = ["=", "×"]
    gap = 120
    total = sum(widths) + gap * 2
    x = (W - total) / 2
    yc = 470
    for i, t in enumerate(terms):
        hl = i == emph
        card(ax, x, yc - 110, widths[i], 220, fc=GREEN if hl else CARD,
             ec="none" if hl else LINE, r=24)
        text(ax, x + widths[i] / 2, yc, t, 56, weight="bold", color="white" if hl else INK, ha="center")
        x += widths[i]
        if i < len(ops):
            text(ax, x + gap / 2, yc, ops[i], 80, weight="bold", color=MUTED, ha="center")
            x += gap
    if v.get("note"):
        text(ax, W / 2, 720, v["note"], 40, color=RED, weight="bold", ha="center")


def draw_timeline(ax, v):
    heading(ax, v["heading"])
    events = v["events"]
    top, bottom = 280, 760
    step = (bottom - top) / max(1, len(events) - 1)
    ax.plot([460, 460], [top, bottom], color=LINE, lw=6, zorder=1)
    for i, e in enumerate(events):
        y = top + i * step
        last = i == len(events) - 1
        color = RED if last else GREEN
        ax.add_patch(Circle((460, y), 18, fc=color, ec="none", zorder=2))
        text(ax, 410, y, e["date"], 38, weight="bold", color=color, ha="right")
        text(ax, 510, y, e["text"], 38)
    source(ax, v.get("source"))


RENDERERS = {
    "title": draw_title,
    "stats": draw_stats,
    "share_flip": draw_share_flip,
    "flow": draw_flow,
    "bullets": draw_bullets,
    "formula": draw_formula,
    "timeline": draw_timeline,
}


def render_scene(visual, channel, out):
    fig, ax = new_canvas()
    RENDERERS[visual["type"]](ax, visual)
    watermark(ax, channel)
    fig.savefig(out, dpi=100, facecolor=BG)
    plt.close(fig)


# ---------------------------------------------------------------- 字幕の焼き込み

NO_LINE_START = set("、。，．・：；？！）」』】ー〜ぁぃぅぇぉっゃゅょァィゥェォッャュョ%％")


def wrap_ja(s, font, max_w, draw):
    lines, cur = [], ""
    for ch in s:
        trial = cur + ch
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
            continue
        if ch in NO_LINE_START and cur:
            # 行頭禁則: 直前の文字ごと次の行へ送る
            lines.append(cur[:-1])
            cur = cur[-1] + ch
        else:
            lines.append(cur)
            cur = ch
    if cur:
        lines.append(cur)
    return lines


def burn_caption(base_png, caption, out):
    img = Image.open(base_png).convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    max_w = W - 320
    for size in (46, 42, 38):
        font = ImageFont.truetype(str(FONT_REGULAR), size)
        lines = wrap_ja(caption, font, max_w, draw)
        if len(lines) <= 2:
            break
    line_h = int(size * 1.45)
    band_h = line_h * len(lines) + 48
    top = H - 36 - band_h
    draw.rounded_rectangle((120, top, W - 120, H - 36), radius=20, fill=(20, 22, 26, 225))
    y = top + 24
    for ln in lines:
        tw = draw.textlength(ln, font=font)
        draw.text(((W - tw) / 2, y), ln, font=font, fill="white")
        y += line_h
    img.save(out)


# ---------------------------------------------------------------- 音声合成

def tts_openjtalk(text, speed):
    import pyopenjtalk

    x, sr = pyopenjtalk.tts(text, speed=speed)
    if sr != SAMPLE_RATE:
        raise RuntimeError(f"unexpected sample rate {sr}")
    peak = np.max(np.abs(x)) or 1.0
    return (x / peak * 0.85).astype(np.float32)


def tts_voicevox(text, speed, speaker):
    base = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    req = urllib.request.Request(f"{base}/audio_query?{q}", method="POST")
    query = json.loads(urllib.request.urlopen(req).read())
    query["speedScale"] = speed
    query["outputSamplingRate"] = SAMPLE_RATE
    req = urllib.request.Request(
        f"{base}/synthesis?speaker={speaker}", data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"}, method="POST")
    wav_bytes = urllib.request.urlopen(req).read()
    tmp = Path("/tmp/_vv.wav")
    tmp.write_bytes(wav_bytes)
    with wave.open(str(tmp)) as w:
        data = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
    return (data / 32768.0).astype(np.float32)


def write_wav(samples, path):
    pad_a = np.zeros(int(PAUSE_BEFORE * SAMPLE_RATE), dtype=np.float32)
    pad_b = np.zeros(int(PAUSE_AFTER * SAMPLE_RATE), dtype=np.float32)
    data = np.concatenate([pad_a, samples, pad_b])
    pcm = (np.clip(data, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(pcm.tobytes())
    return len(data) / SAMPLE_RATE


# ---------------------------------------------------------------- サムネイル

def render_thumbnail(thumb, channel, out):
    fig, ax = new_canvas(1280, 720, bg=INK)
    ax.add_patch(Rectangle((0, 0), 22, 720, fc=RED, ec="none"))
    text(ax, 70, 90, thumb.get("kicker", ""), 40, color="#FFD54A", weight="bold")
    text(ax, 70, 330, thumb["title"], 118, color="white", weight="bold", linespacing=1.15)
    if thumb.get("badge"):
        card(ax, 70, 545, 640, 110, fc=RED, ec="none", r=16)
        text(ax, 390, 600, thumb["badge"], 52, color="white", weight="bold", ha="center")
    text(ax, 1240, 680, channel, 26, color="#9AA0A8", ha="right")
    fig.savefig(out, dpi=100, facecolor=INK)
    plt.close(fig)


# ---------------------------------------------------------------- 本体

def fmt_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_chapter(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def run(cmd):
    subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode_dir")
    ap.add_argument("--tts", choices=["openjtalk", "voicevox"], default="openjtalk")
    ap.add_argument("--speaker", type=int, default=13, help="VOICEVOX の話者 ID")
    ap.add_argument("--only", help="指定したシーン id だけを描画する (確認用、動画は作らない)")
    args = ap.parse_args()

    setup_fonts()
    ep_dir = Path(args.episode_dir)
    ep = json.loads((ep_dir / "episode.json").read_text())
    out = ROOT.parent / "build" / ep["id"]
    (out / "frames").mkdir(parents=True, exist_ok=True)
    (out / "audio").mkdir(parents=True, exist_ok=True)
    (out / "segments").mkdir(parents=True, exist_ok=True)
    channel = ep.get("channel", "")
    speed = ep.get("voice", {}).get("speed", 1.0)

    if args.only:
        sc = next(s for s in ep["scenes"] if s["id"] == args.only)
        render_scene(sc["visual"], channel, out / "frames" / f"{sc['id']}.png")
        print(out / "frames" / f"{sc['id']}.png")
        return

    segments, srt, chapters = [], [], []
    t = 0.0
    n = 0
    for sc in ep["scenes"]:
        base = out / "frames" / f"{sc['id']}.png"
        render_scene(sc["visual"], channel, base)
        chapters.append((t, sc.get("chapter", sc["id"])))
        for line in sc["lines"]:
            n += 1
            shown = line if isinstance(line, str) else line["text"]
            spoken = line if isinstance(line, str) else line.get("say", line["text"])
            frame = out / "frames" / f"{n:03d}.png"
            burn_caption(base, shown, frame)
            if args.tts == "voicevox":
                samples = tts_voicevox(spoken, speed, args.speaker)
            else:
                samples = tts_openjtalk(spoken, speed)
            wav = out / "audio" / f"{n:03d}.wav"
            dur = write_wav(samples, wav)
            seg = out / "segments" / f"{n:03d}.mp4"
            run(["ffmpeg", "-y", "-loop", "1", "-framerate", str(FPS), "-i", str(frame), "-i", str(wav),
                 "-t", f"{dur:.3f}", "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
                 "-r", str(FPS), "-c:a", "aac", "-b:a", "192k", "-ar", str(SAMPLE_RATE), str(seg)])
            segments.append(seg)
            srt.append(f"{n}\n{fmt_srt(t + PAUSE_BEFORE)} --> {fmt_srt(t + dur - PAUSE_AFTER / 2)}\n{shown}\n")
            t += dur
            print(f"[{n:03d}] {dur:5.1f}s  {shown[:40]}")

    concat = out / "segments.txt"
    concat.write_text("".join(f"file '{s.resolve()}'\n" for s in segments))
    run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy",
         "-movflags", "+faststart", str(out / "video.mp4")])
    (out / "captions.srt").write_text("\n".join(srt))

    chapter_txt = "\n".join(f"{fmt_chapter(ct)} {name}" for ct, name in chapters)
    (out / "chapters.txt").write_text(chapter_txt + "\n")
    tmpl = ep_dir / "description.md"
    if tmpl.exists():
        (out / "description.txt").write_text(tmpl.read_text().replace("{{CHAPTERS}}", chapter_txt))

    if ep.get("thumbnail"):
        render_thumbnail(ep["thumbnail"], channel, out / "thumbnail.png")

    print(f"\n完成: {out / 'video.mp4'}  ({fmt_chapter(t)} / {n} 行)")


if __name__ == "__main__":
    main()
