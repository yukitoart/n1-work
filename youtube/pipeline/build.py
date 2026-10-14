#!/usr/bin/env python3
"""エピソード定義 (episode.json) から動画を自動生成する。

  python3 pipeline/build.py episodes/001_saizeriya                 # 仮ナレーション (Open JTalk)
  python3 pipeline/build.py episodes/001_saizeriya --tts voicevox  # VOICEVOX エンジンで本番ナレーション
  python3 pipeline/build.py episodes/001_saizeriya --still recent  # 1シーンの静止画を確認

出力 (build/<episode id>/):
  video.mp4  thumbnail.png  captions.srt  chapters.txt  description.txt
"""

import argparse
import json
import subprocess
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import audio  # noqa: E402

ROOT = Path(__file__).resolve().parent
FPS = 30
W, H = 1920, 1080
LINE_GAP = 0.45      # 行と行のあいだの間 (秒)
SCENE_TAIL = 0.6     # シーン終わりの余韻
CARD_SEC = 2.0       # チャプターカードの長さ


def line_text(line):
    return line if isinstance(line, str) else line["text"]


def line_say(line):
    return line if isinstance(line, str) else line.get("say", line["text"])


def build_timeline(ep, durations):
    """クリップ (チャプターカード / シーン) の並びと、各行の絶対時刻を決める。"""
    clips, lines, chapters = [], [], []
    t = 0.0
    k = 0
    chapter_no = 0
    for si, sc in enumerate(ep["scenes"]):
        if sc.get("chapter") and si > 0:
            chapter_no += 1
            chapters.append((t, sc["chapter"]))
            clips.append({"kind": "card", "start": t, "dur": CARD_SEC, "lines": [],
                          "shots": [{"start": 0, "end": CARD_SEC, "at": {},
                                     "visual": {"type": "chapter", "number": f"{chapter_no:02d}",
                                                "title": sc["chapter"]}}]})
            t += CARD_SEC
        elif si == 0:
            chapters.append((t, sc.get("chapter", "オープニング")))
        start = t
        rel = []
        tt = 0.35
        for ln in sc["lines"]:
            d = durations[k]
            rel.append((tt, tt + d, line_text(ln)))
            lines.append((start + tt, start + tt + d, line_text(ln), k))
            tt += d + LINE_GAP
            k += 1
        dur = tt - LINE_GAP + SCENE_TAIL
        shots_def = sc.get("shots") or [{"from": 0, "visual": sc["visual"]}]
        shots = []
        for j, sh in enumerate(shots_def):
            s0 = 0.0 if j == 0 else rel[sh["from"]][0] - 0.2
            s1 = dur if j == len(shots_def) - 1 else rel[shots_def[j + 1]["from"]][0] - 0.2
            at = {i: rel[i][0] - s0 for i in range(len(rel))}
            shots.append({"start": s0, "end": s1, "at": at, "visual": sh["visual"]})
        clips.append({"kind": "scene", "id": sc["id"], "start": start, "dur": dur,
                      "lines": rel, "shots": shots})
        t += dur
    return clips, lines, chapters, t


def render_clip(args):
    """1クリップ分のフレームを描画して ffmpeg に流し込む (別プロセスで実行)。"""
    clip, out_path, captions = args
    import skia
    import motion

    f0 = round(clip["start"] * FPS)
    f1 = round((clip["start"] + clip["dur"]) * FPS)
    arr = np.zeros((H, W, 4), dtype=np.uint8)
    surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType)
    proc = subprocess.Popen(
        ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "rgba", "-s", f"{W}x{H}",
         "-r", str(FPS), "-i", "-", "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
         "-pix_fmt", "yuv420p", "-threads", "2", str(out_path)], stdin=subprocess.PIPE)
    for f in range(f0, f1):
        tg = f / FPS
        with surf as c:
            motion.draw_clip_frame(c, clip, tg - clip["start"], tg, f, captions)
        proc.stdin.write(arr.tobytes())
    proc.stdin.close()
    if proc.wait() != 0:
        raise RuntimeError(f"ffmpeg failed for {out_path}")
    return str(out_path)


def still(clip, t, out):
    import skia
    import motion

    arr = np.zeros((H, W, 4), dtype=np.uint8)
    surf = skia.Surface(arr, colorType=skia.kRGBA_8888_ColorType)
    with surf as c:
        motion.draw_clip_frame(c, clip, t, clip["start"] + t, 0, True)
    surf.makeImageSnapshot().save(str(out), skia.kPNG)


def fmt_srt(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def fmt_chapter(t):
    t = int(t)
    return f"{t // 60}:{t % 60:02d}"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("episode_dir")
    ap.add_argument("--tts", choices=["openjtalk", "voicevox"], default="openjtalk")
    ap.add_argument("--speaker", type=int, default=13, help="VOICEVOX の話者 ID (13 = 青山龍星)")
    ap.add_argument("--still", help="指定したシーン id の静止画を数枚書き出して終了する (確認用)")
    ap.add_argument("--jobs", type=int, default=4)
    args = ap.parse_args()

    ep_dir = Path(args.episode_dir)
    ep = json.loads((ep_dir / "episode.json").read_text())
    out = ROOT.parent / "build" / ep["id"]
    for d in ("clips", "tts", "stills"):
        (out / d).mkdir(parents=True, exist_ok=True)
    speed = ep.get("voice", {}).get("speed", 1.0)

    # 1. ナレーション
    voices = []
    for sc in ep["scenes"]:
        for ln in sc["lines"]:
            voices.append(audio.synthesize(line_say(ln), out / "tts", args.tts, speed, args.speaker))
    durations = [len(v) / audio.SR for v in voices]

    # 2. タイムライン
    clips, lines, chapters, total = build_timeline(ep, durations)
    print(f"尺: {fmt_chapter(total)} ({total:.1f} 秒) / {len(lines)} 行 / {len(clips)} クリップ")

    if args.still:
        clip = next(c for c in clips if c.get("id") == args.still)
        for j, sh in enumerate(clip["shots"]):
            t = sh["end"] - 0.6
            p = out / "stills" / f"{args.still}_{j}.png"
            still(clip, t, p)
            print(p)
        return

    # 3. 音声ミックス
    voice_events = [(st, voices[k]) for st, _, _, k in lines]
    sfx = [(c["start"] + 0.1, audio.whoosh(1.0)) for c in clips if c["kind"] == "card"]
    master = audio.mix(total, voice_events, sfx)
    audio.write_wav(master, out / "master.wav")

    # 4. 映像 (クリップごとに並列で描画)
    jobs = [(c, out / "clips" / f"{i:02d}.mp4", True) for i, c in enumerate(clips)]
    order = sorted(range(len(jobs)), key=lambda i: -jobs[i][0]["dur"])
    with ProcessPoolExecutor(max_workers=args.jobs) as ex:
        for p in ex.map(render_clip, [jobs[i] for i in order]):
            print("  rendered", Path(p).name)
    (out / "clips.txt").write_text("".join(f"file '{j[1].resolve()}'\n" for j in jobs))
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(out / "clips.txt"),
                    "-i", str(out / "master.wav"), "-map", "0:v", "-map", "1:a", "-c:v", "copy",
                    "-af", "loudnorm=I=-14:TP=-1.5:LRA=11", "-ar", "48000", "-c:a", "aac", "-b:a", "192k",
                    "-shortest", "-movflags", "+faststart", str(out / "video.mp4")], check=True)

    # 5. 字幕・チャプター・概要欄・サムネイル
    (out / "captions.srt").write_text("\n".join(
        f"{i + 1}\n{fmt_srt(st)} --> {fmt_srt(en)}\n{txt}\n" for i, (st, en, txt, _) in enumerate(lines)))
    chapter_txt = "\n".join(f"{fmt_chapter(t)} {name}" for t, name in chapters)
    (out / "chapters.txt").write_text(chapter_txt + "\n")
    tmpl = ep_dir / "description.md"
    if tmpl.exists():
        (out / "description.txt").write_text(tmpl.read_text().replace("{{CHAPTERS}}", chapter_txt))
    if ep.get("thumbnail"):
        import motion
        motion.render_thumbnail(ep["thumbnail"], ep.get("channel", ""), out / "thumbnail.png")

    print(f"\n完成: {out / 'video.mp4'}  ({fmt_chapter(total)})")


if __name__ == "__main__":
    main()
