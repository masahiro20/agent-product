"""PR映像の音楽を合成する（素材なし。numpy だけで作る）。 python video/music.py → video/music.wav

90BPM・4/4（1小節 2.667秒）。映像の章の切り替わりを小節の頭に合わせてある。
  0–16s 導入（低いドローンとピアノ）／16s 開く／21.3s 写真を読む／34.7s 図面／45.3s 概算（山場）／56s 資料／64s 結び
"""
import os
import wave

import numpy as np

SR = 48000
DUR = 76.0
BEAT = 60 / 90
BAR = BEAT * 4
N = int(SR * DUR)
rng = np.random.default_rng(5)
L = np.zeros(N)
R = np.zeros(N)
REV_L = np.zeros(N)  # リバーブへ送る分
REV_R = np.zeros(N)

NOTE = {"C": 0, "C#": 1, "D": 2, "D#": 3, "E": 4, "F": 5, "F#": 6, "G": 7, "G#": 8, "A": 9, "A#": 10, "B": 11}


def hz(name):
    n, o = name[:-1], int(name[-1])
    return 440 * 2 ** ((NOTE[n] + (o - 4) * 12 - 9) / 12)


def put(sig, t, gain=1.0, pan=0.0, rev=0.25):
    i = int(t * SR)
    if i >= N or i < 0:
        return
    sig = sig[: N - i] * gain
    l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
    L[i:i + len(sig)] += sig * l
    R[i:i + len(sig)] += sig * r
    REV_L[i:i + len(sig)] += sig * l * rev
    REV_R[i:i + len(sig)] += sig * r * rev


def env(n, a, r):
    e = np.ones(n)
    na, nr = max(1, int(a * SR)), max(1, int(r * SR))
    e[:na] = np.linspace(0, 1, na) ** 1.5
    e[-nr:] *= np.linspace(1, 0, nr) ** 1.5
    return e


def piano(f, dur=3.0, vel=1.0):
    t = np.arange(int(dur * SR)) / SR
    s = np.zeros_like(t)
    for k in range(1, 9):
        fk = f * k * np.sqrt(1 + 0.0004 * k * k)  # わずかな不協和（弦らしさ）
        if fk > 9000:
            break
        s += np.sin(2 * np.pi * fk * t + k) * (1 / k ** 1.25) * np.exp(-t * (1.1 + 0.55 * k) * (1 + f / 900))
    s *= 1 - np.exp(-t * 320)
    return s * vel * 0.5


def pad(freqs, dur, bright=1.0):
    t = np.arange(int(dur * SR)) / SR
    s = np.zeros_like(t)
    for f in freqs:
        for det in (-0.004, 0.0, 0.004):
            for k in range(1, 7):
                s += np.sin(2 * np.pi * f * (1 + det) * k * t + rng.uniform(0, 6.28)) / (k ** (2.6 - 0.7 * bright))
    s *= 1 + 0.12 * np.sin(2 * np.pi * 0.22 * t)
    return s / (len(freqs) * 3) * env(len(t), dur * 0.3, dur * 0.3)


def pluck(f, dur=0.5):
    t = np.arange(int(dur * SR)) / SR
    s = sum(np.sin(2 * np.pi * f * k * t) / k ** 1.6 for k in (1, 2, 3, 4)) * np.exp(-t * 9)
    return s * (1 - np.exp(-t * 600)) * 0.3


def bass(f, dur):
    t = np.arange(int(dur * SR)) / SR
    return (np.sin(2 * np.pi * f * t) + 0.3 * np.sin(4 * np.pi * f * t)) * env(len(t), 0.03, 0.25) * 0.3


def kick():
    t = np.arange(int(0.45 * SR)) / SR
    ph = 2 * np.pi * (46 * t + (110 - 46) / 28 * (1 - np.exp(-28 * t)))
    return np.sin(ph) * np.exp(-t * 9) * 0.9


def noise(dur, lo, hi):
    n = int(dur * SR)
    sp = np.fft.rfft(rng.standard_normal(n))
    fr = np.fft.rfftfreq(n, 1 / SR)
    sp *= np.exp(-0.5 * ((np.log(fr + 1) - np.log((lo * hi) ** 0.5)) / (np.log(hi / lo) / 2)) ** 2)
    s = np.fft.irfft(sp, n)
    return s / (np.abs(s).max() + 1e-9)


def hat():
    s = noise(0.08, 6000, 12000)
    return s * np.exp(-np.arange(len(s)) / SR * 70) * 0.25


def riser(dur):
    s = noise(dur, 800, 7000)
    t = np.linspace(0, 1, len(s))
    return s * t ** 3 * 0.5


def tick(f=2400):
    t = np.arange(int(0.09 * SR)) / SR
    return np.sin(2 * np.pi * f * t) * np.exp(-t * 60) * 0.22


def boom():
    t = np.arange(int(2.5 * SR)) / SR
    return np.sin(2 * np.pi * (38 + 30 * np.exp(-t * 6)) * t) * np.exp(-t * 1.6) + noise(2.5, 60, 900) * np.exp(-t * 5) * 0.5


# ---------- 導入 0–16s：D のドローン、まばらなピアノ ----------
put(pad([hz("D2"), hz("A2"), hz("D3")], 17.5, 0.2), 0, 0.3, 0, 0.5)
put(pad([hz("A3"), hz("E4")], 9.5, 0.4), 7.5, 0.22, 0.2, 0.6)
for t, n, v in [(1.0, "D4", .8), (2.33, "A4", .6), (4.5, "F#4", .7), (5.83, "E4", .5), (7.0, "D4", .5)]:
    put(piano(hz(n), 4, v), t, 0.55, -0.15, 0.6)
# 仕事の項目が現れる（0.72秒おき）
for i in range(6):
    put(tick(1500 + i * 130), 8.4 + i * 0.72, 0.9, -0.5, 0.5)
    put(piano(hz(["D4", "E4", "F#4", "A4", "B4", "D5"][i]), 2.5, .5), 8.4 + i * 0.72, 0.4, -0.3, 0.6)
put(piano(hz("A4"), 4, .8), 13.0, 0.5, 0.3, 0.6)
put(piano(hz("D5"), 4, .8), 13.7, 0.5, 0.3, 0.6)
put(riser(2.2), 13.8, 0.55, 0, 0.4)
put(boom(), 16.0, 0.7, 0, 0.5)

# ---------- 本編 16s〜：D – A/C# – Bm – G ----------
PROG = [(["D3", "A3", "D4", "F#4", "A4"], "D2"), (["C#3", "A3", "E4", "A4"], "C#2"), (["B2", "F#3", "B3", "D4", "F#4"], "B1"), (["G2", "D3", "G3", "B3", "D4"], "G1")]
ARP = [["D4", "F#4", "A4", "D5", "A4", "F#4", "A4", "E5"], ["C#4", "E4", "A4", "C#5", "A4", "E4", "A4", "E5"], ["B3", "D4", "F#4", "B4", "F#4", "D4", "F#4", "D5"], ["B3", "D4", "G4", "B4", "G4", "D4", "G4", "D5"]]
MEL = {  # 小節番号 → [(拍, 音, 強さ)]
    8: [(0, "F#5", .8), (2, "E5", .6)], 9: [(0, "E5", .7), (3, "C#5", .5)], 10: [(0, "D5", .8), (2, "F#5", .6)], 11: [(0, "B4", .7), (3, "D5", .5)],
    13: [(0, "A5", .8), (1.5, "F#5", .6), (3, "E5", .6)], 14: [(0, "E5", .7), (2, "A5", .6)], 15: [(0, "F#5", .8), (2, "D5", .6)], 16: [(0, "D5", .7), (2, "B4", .5), (3, "D5", .6)],
    17: [(0, "A5", .9), (1, "F#5", .6), (2, "D6", .8)], 18: [(0, "C#6", .8), (2, "A5", .6), (3, "E5", .5)], 19: [(0, "B5", .8), (2, "F#5", .6), (3, "D5", .5)], 20: [(0, "D5", .7), (1, "G5", .7), (2, "B5", .7), (3, "D6", .7)],
    21: [(0, "A5", .7), (2, "F#5", .5)], 22: [(0, "E5", .6), (2, "C#5", .5)], 23: [(0, "D5", .6), (2, "B4", .5)],
    24: [(0, "F#5", .8), (2, "A5", .6)], 25: [(0, "E5", .7), (2, "C#5", .5)], 26: [(0, "D5", .7), (2, "F#5", .6)], 27: [(0, "D5", .9)],
}
for bar in range(6, 28):
    t0 = bar * BAR
    ch, bs = PROG[(bar - 6) % 4]
    if bar >= 27:
        ch, bs = PROG[0]
    sec = "title" if bar < 8 else "read" if bar < 13 else "draw" if bar < 17 else "est" if bar < 21 else "docs" if bar < 24 else "end"
    lvl = {"title": .5, "read": .6, "draw": .75, "est": 1.0, "docs": .7, "end": .6}[sec]
    put(pad([hz(n) for n in ch], BAR * 1.7, 0.5 + 0.5 * lvl), t0 - 0.9, 0.17 * lvl + .05, 0, 0.5)
    if bar < 27:
        put(bass(hz(bs), BAR * (0.98 if sec in ("title", "end") else 0.48)), t0, 0.55 * lvl + .1, 0, 0.05)
        if sec not in ("title", "end"):
            put(bass(hz(bs), BEAT * 1.4), t0 + BEAT * 2.5, 0.45 * lvl, 0, 0.05)
    else:
        put(bass(hz(bs), 6), t0, 0.5, 0, 0.1)
    if sec in ("read", "draw", "est", "docs"):
        for i in range(8):
            put(pluck(hz(ARP[(bar - 6) % 4][i])), t0 + i * BEAT / 2, (0.5 + 0.25 * (i % 2 == 0)) * lvl, 0.55 * (-1) ** i, 0.5)
    if sec in ("draw", "est", "docs"):
        for b in (0, 2.5) if sec != "est" else (0, 1.5, 2.5):
            put(kick(), t0 + b * BEAT, 0.6 * lvl, 0, 0.03)
        for i in range(8):
            put(hat(), t0 + (i + 0.5) * BEAT / 2, 0.5 * lvl, 0.3, 0.2)
    if sec == "title" and bar == 6:
        for i, n in enumerate(["D4", "A4", "D5", "F#5"]):
            put(piano(hz(n), 5, .7), t0 + 0.5 + i * 0.33, 0.5, 0.2 * (i - 1.5), 0.7)
    for b, n, v in MEL.get(bar, []):
        put(piano(hz(n), 4, v), t0 + b * BEAT, 0.55, 0.15, 0.7)
        put(piano(hz(n) / 2, 4, v * .5), t0 + b * BEAT, 0.3, -0.15, 0.6)

put(riser(2.4), 13 * BAR - 2.4, 0.3, 0, 0.4)
put(riser(2.6), 17 * BAR - 2.6, 0.5, 0, 0.4)
put(boom(), 17 * BAR, 0.5, 0, 0.5)
put(riser(2.0), 21 * BAR - 2.0, 0.35, 0, 0.4)
put(boom(), 21 * BAR, 0.45, 0, 0.5)
put(riser(2.0), 24 * BAR - 2.0, 0.3, 0, 0.4)
# 画面の動きに合わせた小さな音
for i in range(5):
    put(tick(2100 + i * 90), 23.6 + i * 0.42, 0.8, -0.4, 0.4)       # 読み取り箇所の赤枠
for i in range(6):
    put(tick(1700), 25.2 + i * 0.95, 0.5, 0.5, 0.4)                 # 読み取り結果の行
for i in range(4):
    put(tick(1900), 40.6 + i * 1.05, 0.6, 0.3, 0.4)                 # 図面の切り替え
for t in (46.6, 47.5, 48.6):
    put(tick(1300), t, 0.7, 0.4, 0.4)

# ---------- リバーブ（減衰するノイズとの畳み込み）→ まとめ ----------
def reverb(x, seed):
    g = np.random.default_rng(seed)
    n = int(3.2 * SR)
    ir = g.standard_normal(n) * np.exp(-np.arange(n) / SR * 2.4)
    ir[: int(0.012 * SR)] = 0
    m = 1 << int(np.ceil(np.log2(len(x) + n)))
    y = np.fft.irfft(np.fft.rfft(x, m) * np.fft.rfft(ir, m), m)[: len(x)]
    return y / 60

L += reverb(REV_L, 1)
R += reverb(REV_R, 2)
t = np.arange(N) / SR
fade = np.clip(t / 0.8, 0, 1) * np.clip((DUR - 0.2 - t) / 3.2, 0, 1)
mix = np.stack([L, R], 1) * fade[:, None]
mix = np.tanh(mix / np.percentile(np.abs(mix), 99.9) * 0.9) * 0.62  # やわらかく頭を抑える（-16 LUFS 前後）
out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "music.wav")
with wave.open(out, "wb") as w:
    w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
    w.writeframes((mix * 32767).astype("<i2").tobytes())
print(out)
