"""ナレーション合成・BGM 生成・ミックス。"""

import hashlib
import io
import json
import os
import urllib.parse
import urllib.request
import wave
from pathlib import Path

import numpy as np

SR = 48000


# ---------------------------------------------------------------- ナレーション

def tts_openjtalk(text, cfg):
    import pyopenjtalk

    x, sr = pyopenjtalk.tts(text, speed=cfg.get("speed", 1.0))
    assert sr == SR, sr
    return (x / 32768.0).astype(np.float32)


def tts_voicevox(text, cfg):
    """VOICEVOX エンジン。cfg: speaker / speed / pitch / intonation / volume / pause"""
    base = os.environ.get("VOICEVOX_URL", "http://127.0.0.1:50021")
    speaker = cfg.get("speaker", 13)
    q = urllib.parse.urlencode({"text": text, "speaker": speaker})
    query = json.loads(urllib.request.urlopen(
        urllib.request.Request(f"{base}/audio_query?{q}", method="POST")).read())
    query["speedScale"] = cfg.get("speed", 1.0)
    query["pitchScale"] = cfg.get("pitch", 0.0)
    query["intonationScale"] = cfg.get("intonation", 1.0)
    query["volumeScale"] = cfg.get("volume", 1.0)
    query["outputSamplingRate"] = SR
    query["prePhonemeLength"] = 0.05
    query["postPhonemeLength"] = 0.05
    if "pause" in cfg:  # 読点などの間の長さ (エンジン 0.19 以降)
        query["pauseLengthScale"] = cfg["pause"]
    data = urllib.request.urlopen(urllib.request.Request(
        f"{base}/synthesis?speaker={speaker}", data=json.dumps(query).encode(),
        headers={"Content-Type": "application/json"}, method="POST")).read()
    return read_wav_bytes(data)


def read_wav_bytes(data):
    with wave.open(io.BytesIO(data)) as w:
        pcm = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)
        if w.getnchannels() == 2:
            pcm = pcm[::2]
    return (pcm / 32768.0).astype(np.float32)


def synthesize(text, cache_dir, cfg):
    """1 行ぶんの音声 (float32, 48kHz)。同じ条件の音声はキャッシュを再利用する。"""
    key = hashlib.sha1(json.dumps([cfg, text], sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    path = Path(cache_dir) / f"{key}.npy"
    if path.exists():
        return np.load(path)
    if cfg.get("engine") == "voicevox":
        x = tts_voicevox(text, cfg)
    else:
        x = tts_openjtalk(text, cfg)
    peak = float(np.max(np.abs(x))) or 1.0
    x = (x / peak * 0.9).astype(np.float32)
    np.save(path, x)
    return x


# ---------------------------------------------------------------- BGM (自動生成のアンビエント)

def _note(midi):
    return 440.0 * 2 ** ((midi - 69) / 12)


def _reverb(x, seconds=2.8, mix=0.35, seed=1):
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    ir = rng.standard_normal(n).astype(np.float32) * np.exp(-np.linspace(0, 7, n)).astype(np.float32)
    ir /= np.sqrt(np.sum(ir ** 2))
    # 円状畳み込みにして、ループのつなぎ目でも残響が切れないようにする
    size = len(x)
    wet = np.fft.irfft(np.fft.rfft(x, size) * np.fft.rfft(ir, size), size).astype(np.float32)
    return (1 - mix) * x + mix * wet


def make_bgm_loop(bar_sec=4.0):
    """Am7 - Fmaj7 - Cmaj7 - G6 の進行を、パッド＋柔らかい分散和音で 8 小節ループにする。"""
    chords = [[57, 60, 64, 67], [53, 57, 60, 64], [48, 52, 55, 59], [55, 59, 62, 64]] * 2
    bass = [45, 41, 48, 43] * 2
    n = int(bar_sec * SR)
    total = n * len(chords)
    t_bar = np.arange(n) / SR
    out = np.zeros(total, dtype=np.float32)
    env = np.minimum(1, t_bar / 1.2) * np.minimum(1, (bar_sec - t_bar) / 1.0 + 0.25)
    rng = np.random.default_rng(5)
    for b, (ch, bs) in enumerate(zip(chords, bass)):
        seg = np.zeros(n, dtype=np.float32)
        for m in ch:
            f = _note(m)
            for det in (-0.12, 0.12):
                ph = rng.uniform(0, 2 * np.pi)
                seg += 0.05 * np.sin(2 * np.pi * f * (1 + det / 100) * t_bar + ph)
                seg += 0.012 * np.sin(2 * np.pi * 2 * f * t_bar + ph)
        seg *= env
        seg += 0.07 * np.sin(2 * np.pi * _note(bs) * t_bar) * env
        # 8分音符の分散和音 (減衰する柔らかい音)
        arp = ch + [ch[1] + 12]
        step = n // 8
        for k in range(8):
            if rng.random() < 0.35:
                continue
            m = arp[k % len(arp)] + 12
            ln = n - k * step
            tt = np.arange(ln) / SR
            tone = (np.sin(2 * np.pi * _note(m) * tt) + 0.3 * np.sin(4 * np.pi * _note(m) * tt))
            seg[k * step:] += (0.035 * tone * np.exp(-tt * 2.2)).astype(np.float32)
        out[b * n:(b + 1) * n] += seg
    out = _reverb(out)
    return out / (np.max(np.abs(out)) + 1e-9) * 0.9


def whoosh(seconds=1.0):
    rng = np.random.default_rng(9)
    n = int(seconds * SR)
    x = rng.standard_normal(n).astype(np.float32)
    # 簡易ローパス (移動平均の長さを変化させて、音が近づいて遠ざかる感じにする)
    t = np.linspace(0, 1, n)
    env = np.sin(np.pi * t) ** 2
    out = np.zeros(n, dtype=np.float32)
    acc = 0.0
    for i in range(0, n, 64):
        k = 0.02 + 0.25 * env[i]
        blk = x[i:i + 64]
        for j in range(len(blk)):
            acc += k * (blk[j] - acc)
            out[i + j] = acc
    return out * env * 0.5


def hit(seconds=0.7):
    """強調テロップ用の低い「ドン」。"""
    n = int(seconds * SR)
    t = np.arange(n) / SR
    f = 45 + 90 * np.exp(-t * 18)
    body = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-t * 6)
    click = np.random.default_rng(3).standard_normal(n) * np.exp(-t * 120) * 0.25
    return ((body + click) * 0.8).astype(np.float32)


# ---------------------------------------------------------------- ミックス

def mix(total_sec, voice_events, sfx_events, bgm_gain_db=-21.0, duck_db=-7.0):
    """voice_events / sfx_events: [(開始秒, float32 配列)]"""
    n = int(np.ceil(total_sec * SR)) + SR
    voice = np.zeros(n, dtype=np.float32)
    for t0, x in voice_events:
        i = int(t0 * SR)
        voice[i:i + len(x)] += x[: max(0, n - i)]
    loop = make_bgm_loop()
    bgm = np.tile(loop, int(np.ceil(n / len(loop))))[:n]
    # ナレーション中は BGM を下げる (サイドチェイン風)
    env = np.abs(voice)
    win = int(0.25 * SR)
    env = np.convolve(env, np.ones(win, dtype=np.float32) / win, mode="same")
    talking = np.clip(env / 0.02, 0, 1)
    gain = 10 ** (bgm_gain_db / 20) * (10 ** (duck_db / 20 * talking))
    fade = np.minimum(1, np.arange(n) / (2 * SR)) * np.minimum(1, (n - np.arange(n)) / (3 * SR))
    out = voice + bgm * gain * fade
    for t0, x in sfx_events:
        i = int(t0 * SR)
        out[i:i + len(x)] += x[: max(0, n - i)] * 0.35
    out = out[: int(total_sec * SR)]
    return out / max(1.0, float(np.max(np.abs(out))) / 0.98)


def write_wav(x, path):
    pcm = (np.clip(x, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())
