"""ホームランディック テーマソング（1番・約2分）を合成する。 python song/theme_song.py

出力: homelandick_theme.wav（伴奏＋ガイドメロディ）、homelandick_theme_karaoke.wav（伴奏のみ）、homelandick_theme.mid（メロディ＋歌詞＋コード）

80BPM・4/4（1小節3秒）。ハ長調で始まり、サビのあとニ長調へ転調する。
  0–3 イントロ（モチーフを小さく）／4–11 Aメロ／12–19 A'／20–23 Bメロ／24–31 サビ／32–35 モチーフ（オーケストラ）／36–39 結び
MOTIF が「YouTube 冒頭のBGM」の差し込み口。いまは仮の旋律。本物の旋律・調・テンポに書き換えれば曲全体がそれに合う。
"""
import os
import struct
import wave

import numpy as np

SR = 44100
BPM = 92
BEAT = 60 / BPM
BAR = BEAT * 4
BARS = 42
TAIL = 5.0
N = int(SR * (BARS * BAR + TAIL))
rng = np.random.default_rng(3)
HERE = os.path.dirname(os.path.abspath(__file__))

PC = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}


def midi(name):
    p = PC[name[0]]
    rest = name[1:]
    if rest[0] == "#":
        p, rest = p + 1, rest[1:]
    elif rest[0] == "b":
        p, rest = p - 1, rest[1:]
    return p + (int(rest) + 1) * 12


def hz(m):
    return 440 * 2 ** ((m - 69) / 12)


QUAL = {"": [0, 4, 7], "m": [0, 3, 7], "7": [0, 4, 7, 10], "m7": [0, 3, 7, 10], "maj7": [0, 4, 7, 11], "sus4": [0, 5, 7], "add9": [0, 4, 7, 14]}


def chord(sym, shift=0):
    """'Am7/G' → (bass の音高クラス, 構成音の音高クラス)"""
    body, _, slash = sym.partition("/")
    root = PC[body[0]]
    q = body[1:]
    if q[:1] in "#b" and q[:1]:
        root += 1 if q[0] == "#" else -1
        q = q[1:]
    pcs = [(root + i + shift) % 12 for i in QUAL[q]]
    b = root
    if slash:
        b = PC[slash[0]] + (1 if slash[1:] == "#" else -1 if slash[1:] == "b" else 0)
    return (b + shift) % 12, pcs


# ---------------------------------------------------------------- 曲

def mel(s):
    """'E4:.5:ま G4:1:な R:1' → [(音名 or None, 拍, 歌詞)]"""
    out = []
    for tok in s.split():
        p = tok.split(":")
        out.append((None if p[0] == "R" else p[0], float(p[1]), p[2] if len(p) > 2 else ""))
    assert abs(sum(b for _, b, _ in out) % 4) < 1e-6, s
    return out


KEY = -5  # 全体の移調（半音）。ハ長調で書いて、ト長調（→転調後イ長調）で鳴らす。歌声合成の声が安定するのは C4〜D5

SMALL = "ゃゅょぁぃぅぇぉャュョァィゥェォ"


def moras(text):
    out = []
    for ch in text.replace(" ", "").replace("　", ""):
        if ch in SMALL and out:
            out[-1] += ch
        else:
            out.append(ch)
    return out


def line(notes, rhythm, text):
    """音名の並び・拍の並び・歌詞（1音に1モーラ）→ [(音名, 拍, 歌詞)]。'R' は休符。"""
    ns, rs, ms = notes.split(), [float(x) for x in rhythm.split()], moras(text)
    assert len(ns) == len(rs), (notes, rhythm)
    assert sum(1 for n in ns if n != "R") == len(ms), (notes, text, len(ms))
    it = iter(ms)
    return [(None, r, "") if n == "R" else (n, r, next(it)) for n, r in zip(ns, rs)]


# 仮のモチーフ（ハ長調で書く。後半は +2 で転調）
MOTIF = mel("G4:.5 C5:.5 E5:1 D5:.5 C5:.5 G4:1  A4:.5 C5:.5 F5:1 E5:.5 D5:.5 C5:1  G4:.5 C5:.5 E5:.5 G5:.5 A5:1 G5:1  F5:.5 E5:.5 D5:1 C5:2")
MOTIF_CH = [[("C", 4)], [("F", 4)], [("C/E", 2), ("Am", 2)], [("Dm7", 2), ("G", 2)]]

# 主題：七五調×4行（8小節）。同じ旋律に歌詞だけを替えて3回歌う
R7, R5, R8, R5E = ".5 .5 1 .5 .5 .5 .5", ".5 .5 .5 .5 1.5 .5", ".5 .5 .5 .5 .5 .5 .5 .5", ".5 .5 .5 .5 2"
TH_CH = [[("C", 4)], [("G/B", 4)], [("Am", 4)], [("Em", 4)], [("F", 4)], [("C/E", 4)], [("Dm7", 2), ("G", 2)], [("C", 4)]]
P = [("G4 G4 C5 C5 B4 A4 G4", "A4 B4 A4 G4 G4 R"), ("A4 A4 C5 C5 D5 C5 A4", "B4 C5 B4 G4 G4 R"),
     ("A4 C5 F5 F5 E5 D5 C5", "C5 D5 E5 D5 C5 R"), ("D5 D5 F5 D5 D5 C5 B4", "C5 C5 D5 E5 C5")]


def theme(lines, name_row=None):
    out = []
    for i, (seven, five) in enumerate(lines):
        if i == name_row:   # 「ホームランディック」は8モーラ：付点の1拍を8分2つに割る
            n = P[i][0].split()
            out += line(" ".join(n[:2] + [n[2], n[2]] + n[3:]), R8, seven)
        else:
            out += line(P[i][0], R7, seven)
        out += line(P[i][1], R5E if i == 3 else R5, five)
    return out


A_CH = TH_CH
A1 = theme([("しろいずめんに", "せんをひく"), ("あなたのこえが", "みちしるべ"), ("まどのむこうに", "ひがのぼる"), ("ここがはじまり", "いえづくり")])
A2 = theme([("かぜのとおりを", "たしかめて"), ("ひかりのいろを", "えらんでく"), ("せいくらべする", "はしらにも"), ("おもいでがすむ", "いえになる")])
B_CH = [[("Am", 4)], [("Em", 4)], [("F", 4)], [("Gsus4", 2), ("G", 2)]]
B1 = line("A4 C5 E5 D5 B4 G4 A4 C5 F5 E5 D5 R", "1 1 2 1 1 2 1 1 1 1 3 1", "いえは いきる ばしょだから")
# サビ：王道進行（F–G–Em–Am）に、社名から始まる短いフック。2小節で1行、語尾を食って（シンコペーション）弾ませる
C_CH = [[("F", 2), ("G", 2)], [("Em", 2), ("Am", 2)], [("F", 2), ("G", 2)], [("C", 4)],
        [("F", 2), ("G", 2)], [("Em", 2), ("Am", 2)], [("Dm7", 2), ("G", 2)], [("C", 3), ("A7", 1)]]
S5, S6 = ".5 .5 1 .5 1.5", ".5 .5 .5 .5 .5 1.5"
HOOK = line("A4 A4 C5 C5 D5 G5 G5 E5", R8, "ホームランディック")
C_TAIL = (HOOK + line("G5 E5 D5 E5 C5", S5, "このまちで")
          + line("F5 F5 E5 D5 D5 E5 D5 B4", R8, "いっしょにつくろう") + line("C5 D5 E5 D5 C5", S5, "きみのいえ"))
C1 = (HOOK + line("E5 D5 E5 D5 C5", S5, "ゆめのいえ")
      + line("A4 C5 F5 F5 E5 D5 B4", R7, "きょうもだれかの") + line("C5 D5 E5 G5 G5 E5", S6, "あかりになる") + C_TAIL)
E_CH = C_CH[4:7] + [[("C", 4)]]
# 転調後は2度高くなるので、いちばん高い音を下げた形で歌う
E1 = (line("A4 A4 C5 C5 D5 E5 E5 E5", R8, "ホームランディック") + line("E5 E5 D5 E5 C5", S5, "このまちで")
      + line("F5 F5 E5 D5 D5 E5 D5 B4", R8, "いっしょにつくろう") + line("C5 D5 E5 D5 C5", S5, "きみのいえ"))

#            名前, 開始小節, コード, メロディ, 移調, 歌い方（"lyr"=歌詞 / "la"=1オクターブ下でラララ / None=歌わない）
SECTIONS = [("intro", 0, MOTIF_CH, MOTIF, KEY, None), ("A", 4, A_CH, A1, KEY, "lyr"), ("A2", 12, A_CH, A2, KEY, "lyr"), ("B", 20, B_CH, B1, KEY, "lyr"),
            ("chorus", 24, C_CH, C1, KEY, "lyr"), ("motif", 32, MOTIF_CH, MOTIF, KEY + 2, None), ("end", 36, E_CH, E1, KEY + 2, "lyr")]
LEVEL = {"intro": .35, "A": .45, "A2": .62, "B": .75, "chorus": 1.0, "motif": 1.15, "end": 1.05}
END_BAR = 40                         # 最後の和音を鳴らす小節
TONIC = (KEY + 2) % 12               # 転調後の主音


def vocal_note(nm, shift, mode, lyr):
    """歌う音高と歌詞。歌わない音は None"""
    if not nm or not mode:
        return None
    return (midi(nm) + shift - (12 if mode == "la" else 0), "ラ" if mode == "la" else lyr)

# ---------------------------------------------------------------- 音色

class Mix:
    def __init__(self):
        self.L, self.R, self.rl, self.rr = (np.zeros(N) for _ in range(4))

    def put(self, sig, t, gain=1.0, pan=0.0, rev=0.25):
        i = int(t * SR)
        if i < 0 or i >= N:
            return
        sig = sig[: N - i] * gain
        l, r = np.cos((pan + 1) * np.pi / 4), np.sin((pan + 1) * np.pi / 4)
        self.L[i:i + len(sig)] += sig * l
        self.R[i:i + len(sig)] += sig * r
        self.rl[i:i + len(sig)] += sig * l * rev
        self.rr[i:i + len(sig)] += sig * r * rev


def tt(d):
    return np.arange(int(d * SR)) / SR


def ar(n, a, r):
    e = np.ones(n)
    na, nr = min(n, max(1, int(a * SR))), min(n, max(1, int(r * SR)))
    e[:na] *= np.linspace(0, 1, na)
    e[-nr:] *= np.linspace(1, 0, nr)
    return e


def piano(m, d=2.5, v=1.0):
    f, t = hz(m), tt(d)
    s = np.zeros_like(t)
    for k in range(1, 10):
        fk = f * k * np.sqrt(1 + 0.0005 * k * k)
        if fk > 9000:
            break
        s += np.sin(2 * np.pi * fk * t + k * .7) / k ** (1.9 - .7 * v) * np.exp(-t * (0.9 + 0.5 * k) * (1 + f / 800))
    return s * (1 - np.exp(-t * 400)) * ar(len(t), 0, .08) * v * .45


def strings(m, d, bright=.5):
    f, t = hz(m), tt(d)
    s = np.zeros_like(t)
    for det in (-.006, -.002, .003, .007):
        ph = 2 * np.pi * f * (1 + det) * t + 2 * np.pi * f * .004 / 5.2 * np.sin(2 * np.pi * (5.2 + det * 40) * t) + rng.uniform(0, 6.28)
        for k in range(1, 12):
            if f * k > 7000:
                break
            s += np.sin(k * ph) / k ** (1.9 - bright * .8)
    return s / 4 * ar(len(t), min(.35, d * .3), min(.5, d * .35)) * .3


def brass(m, d):
    f, t = hz(m), tt(d)
    s = np.zeros_like(t)
    e = 1 - np.exp(-t * 18)
    for k in range(1, 14):
        if f * k > 6000:
            break
        s += np.sin(2 * np.pi * f * k * t + k) / k * np.clip(e * 9 / k, 0, 1)
    return s * ar(len(t), .04, .12) * .22


def flute(m, d, v=1.0):
    """ガイドメロディ（歌の代わり）。やわらかい笛＋少しの息。"""
    f, t = hz(m), tt(d)
    vib = 1 + .006 * np.clip((t - .25) * 4, 0, 1) * np.sin(2 * np.pi * 5.3 * t)
    ph = 2 * np.pi * np.cumsum(f * vib) / SR
    s = np.sin(ph) + .32 * np.sin(2 * ph) + .12 * np.sin(3 * ph) + .05 * np.sin(4 * ph)
    br = rng.standard_normal(len(t)) * .025 * np.exp(-t * 14)
    return (s + br) * ar(len(t), .035, min(.09, d * .3)) * v * .3


def glock(m, d=2.0):
    f, t = hz(m), tt(d)
    return (np.sin(2 * np.pi * f * t) + .45 * np.sin(2 * np.pi * f * 2.76 * t) * np.exp(-t * 9) + .2 * np.sin(2 * np.pi * f * 5.4 * t) * np.exp(-t * 16)) * np.exp(-t * 3.2) * .22


def bass(m, d):
    f, t = hz(m), tt(d)
    return (np.sin(2 * np.pi * f * t) + .35 * np.sin(4 * np.pi * f * t) * np.exp(-t * 3) + .1 * np.sin(6 * np.pi * f * t) * np.exp(-t * 6)) * ar(len(t), .012, .12) * .42


def band(d, lo, hi):
    n = int(d * SR)
    sp = np.fft.rfft(rng.standard_normal(n))
    fr = np.fft.rfftfreq(n, 1 / SR)
    sp *= (fr > lo) * (fr < hi)
    s = np.fft.irfft(sp, n)
    return s / (np.abs(s).max() + 1e-9)


def kick():
    t = tt(.4)
    return np.sin(2 * np.pi * (48 * t + (120 - 48) / 30 * (1 - np.exp(-30 * t)))) * np.exp(-t * 10) * .8


def rim():
    t = tt(.12)
    return (np.sin(2 * np.pi * 820 * t) * .6 + band(.12, 1500, 6000) * .5) * np.exp(-t * 45) * .35


def snare():
    t = tt(.25)
    return (np.sin(2 * np.pi * 190 * t) * np.exp(-t * 28) * .5 + band(.25, 1200, 8000) * np.exp(-t * 20)) * .4


def clap():
    t = tt(.18)
    e = sum(np.exp(-np.clip(t - o, 0, None) * 55) * (t >= o) for o in (0, .011, .023))
    return band(.18, 900, 5000) * e * .22


def hat(d=.07):
    s = band(d, 6500, 13000)
    return s * np.exp(-tt(d) * 60) * .16


def swell(d):
    s = band(d, 2500, 12000)
    return s * np.linspace(0, 1, len(s)) ** 2.5 * .3


def crash():
    t = tt(3.0)
    return band(3.0, 3000, 14000) * np.exp(-t * 1.6) * .32


def timp(m, d=1.6):
    f, t = hz(m), tt(d)
    return (np.sin(2 * np.pi * f * t * (1 + .02 * np.exp(-t * 20))) + .4 * np.sin(2 * np.pi * f * 1.5 * t) * np.exp(-t * 5)) * np.exp(-t * 3) * .6


# ---------------------------------------------------------------- 編曲

def near(pc, center):
    """音高クラスを center に近い音高にする"""
    m = center - (center % 12) + pc
    return m if abs(m - center) <= 6 else m + (12 if m < center else -12)


def render(lead="guide", vocal=None):
    mx = Mix()
    midi_mel, midi_ch = [], []
    for name, bar0, chs, melody, shift, sung in SECTIONS:
        lv = LEVEL[name]
        # ---- 伴奏
        for bi, bar in enumerate(chs):
            t0 = (bar0 + bi) * BAR
            b = 0.0
            for sym, beats in bar:
                bpc, pcs = chord(sym, shift)
                tc, dur = t0 + b * BEAT, beats * BEAT
                voic = sorted(near(p, 62) for p in pcs)
                midi_ch.append((tc, dur, [near(bpc, 43)] + voic))
                # ベース
                if name != "intro":
                    mx.put(bass(near(bpc, 41), dur * .96), tc, .55 * lv + .15, 0, .03)
                    if name in ("chorus", "motif", "end", "B") and beats >= 4:
                        mx.put(bass(near(bpc, 41), BEAT * .9), tc + 2.5 * BEAT, .4 * lv, 0, .03)
                # ピアノ：8分のアルペジオ（サビ以降は頭に和音）
                pat = [near(bpc, 48)] + voic + [voic[0] + 12]
                order = [0, 2, 3, 2, 4, 2, 3, 2] if len(pat) >= 5 else [0, 1, 2, 1, 3, 1, 2, 1]
                for k in range(int(round(beats * 2))):
                    acc = 1.0 if k % 4 == 0 else .7
                    mx.put(piano(pat[order[k % 8] % len(pat)], 2.4, .55 * acc * (.6 + .5 * lv)), tc + k * BEAT / 2 + rng.uniform(0, .008), .8, -.25 + .1 * (k % 3), .35)
                if name in ("chorus", "motif", "end"):
                    for m in voic:
                        mx.put(piano(m, 3, .6), tc, .55 * lv, -.2, .35)
                # 弦
                if name not in ("intro", "A"):
                    for j, m in enumerate(voic[:4]):
                        mx.put(strings(m, dur + .45, .3 + .5 * lv), tc - .12, (.5 * lv) * (.9 if j else 1.1), .35 - .25 * j, .5)
                    if name in ("chorus", "motif", "end"):
                        mx.put(strings(voic[-1] + 12, dur + .45, .8), tc - .12, .32 * lv, .45, .6)
                        mx.put(strings(near(bpc, 38), dur + .45, .4), tc - .12, .5 * lv, -.4, .4)
                elif name == "A" and bi >= 4:
                    mx.put(strings(voic[1] + 12, dur + .5, .2), tc - .15, .16, .3, .6)
                b += beats
            # ドラム
            if name in ("A2", "B", "chorus", "motif", "end"):
                full = name in ("chorus", "motif", "end")
                for kb in ((0, 2.5) if not full else (0, 1.5, 2.5)):
                    mx.put(kick(), t0 + kb * BEAT, .55 * lv, 0, .03)
                for sb in (1, 3):
                    mx.put(snare() if full else rim(), t0 + sb * BEAT, .6 * lv, .1, .25)
                for k in range(8):
                    mx.put(hat(), t0 + k * BEAT / 2, (.9 if k % 2 == 0 else .5) * lv, .3, .15)
                if full:                                   # サビ：手拍子とタンバリンで弾ませる
                    for sb in (1, 3):
                        mx.put(clap(), t0 + sb * BEAT, .5 * lv, -.25, .3)
                    for k in range(16):
                        mx.put(hat(.04), t0 + k * BEAT / 4, (.45 if k % 4 == 2 else .2) * lv, -.35, .15)
        # ---- 旋律
        t = bar0 * BAR
        for nm, beats, lyr in melody:
            d = beats * BEAT
            vn = vocal_note(nm, shift, sung, lyr)
            if vn:
                midi_mel.append((t, d, vn[0], vn[1]))
                if lead == "guide":
                    mx.put(flute(vn[0], d * .97, .9 + .25 * lv), t, .95, .05, .4)
                    mx.put(piano(vn[0], 2.0, .35), t, .35, .15, .4)
            if nm:
                m = midi(nm) + shift
                if sung == "lyr":
                    pass
                elif name == "intro":      # モチーフ：遠くでオルゴールのように
                    mx.put(glock(m + 12), t, .5, .3, .7)
                    mx.put(piano(m, 3, .4), t, .4, .2, .6)
                else:                      # モチーフ：オーケストラで
                    mx.put(strings(m + 12, d + .15, .9), t - .05, .75, .3, .6)
                    mx.put(strings(m, d + .15, .8), t - .05, .7, -.3, .6)
                    mx.put(brass(m, d * .95), t, .75, -.15, .5)
                    mx.put(brass(m - 12, d * .95), t, .5, .15, .5)
                    mx.put(glock(m + 12), t, .55, .4, .6)
            t += d
    if vocal is not None:
        mx.put(vocal, 0, 1.0, 0, .32)
    # ---- つなぎ
    st = {n: b0 for n, b0, *_ in SECTIONS}
    mx.put(swell(BAR), st["chorus"] * BAR - BAR, .5, 0, .5)             # サビ前
    mx.put(crash(), st["chorus"] * BAR, .55, .2, .5)
    for k in range(8):                                                  # 転調前の盛り上げ（スネアのロール）
        mx.put(snare(), st["motif"] * BAR - 2 * BEAT + k * BEAT / 4, .25 + .08 * k, .1, .3)
    mx.put(swell(BAR * 1.2), st["motif"] * BAR - BAR * 1.2, .7, 0, .5)
    mx.put(crash(), st["motif"] * BAR, .8, -.2, .5)
    for k in range(4):
        mx.put(timp(near(TONIC if k % 2 == 0 else TONIC + 7, 40)), (st["motif"] + k) * BAR, .7, -.3, .5)
    mx.put(crash(), st["end"] * BAR, .5, .2, .5)
    # 最後の和音
    r = near(TONIC, 36)
    for m in (r, r + 12, r + 19, r + 24, r + 28, r + 31, r + 36):
        mx.put(piano(m, 6, .7), END_BAR * BAR, .55, 0, .5)
    for m in (r + 24, r + 28, r + 31, r + 43):
        mx.put(strings(m, 6, .5), END_BAR * BAR, .4, 0, .6)
    mx.put(glock(r + 48, 4), END_BAR * BAR + .05, .5, .3, .7)
    mx.put(timp(r, 3), END_BAR * BAR, .5, 0, .5)
    mx.put(crash(), END_BAR * BAR, .4, 0, .5)
    # ---- リバーブ・まとめ
    def reverb(x, seed):
        g = np.random.default_rng(seed)
        n = int(2.8 * SR)
        ir = g.standard_normal(n) * np.exp(-np.arange(n) / SR * 2.6)
        ir[: int(.015 * SR)] = 0
        k = 1 << int(np.ceil(np.log2(len(x) + n)))
        return np.fft.irfft(np.fft.rfft(x, k) * np.fft.rfft(ir, k), k)[: len(x)] / 55
    out = np.stack([mx.L + reverb(mx.rl, 1), mx.R + reverb(mx.rr, 2)], 1)
    t = np.arange(N) / SR
    out *= (np.clip(t / .05, 0, 1) * np.clip((N / SR - t) / 2.5, 0, 1))[:, None]
    out = np.tanh(out / np.percentile(np.abs(out), 99.9) * .95) * .7
    return out, midi_mel, midi_ch


def save_wav(path, x):
    with wave.open(path, "wb") as w:
        w.setnchannels(2); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((x * 32767).astype("<i2").tobytes())


def save_midi(path, mel_ev, ch_ev):
    TPQ = 480

    def vlq(n):
        b = [n & 0x7F]
        while n > 0x7F:
            n >>= 7
            b.insert(0, (n & 0x7F) | 0x80)
        return bytes(b)

    def track(events):
        events.sort(key=lambda e: (e[0], e[1]))
        data, last = b"", 0
        for tick, _, raw in events:
            data += vlq(tick - last) + raw
            last = tick
        data += b"\x00\xff\x2f\x00"
        return b"MTrk" + struct.pack(">I", len(data)) + data

    tk = lambda sec: int(round(sec / BEAT * TPQ))
    t0 = [(0, 0, b"\xff\x51\x03" + struct.pack(">I", int(60e6 / BPM))[1:]), (0, 0, b"\xff\x58\x04\x04\x02\x18\x08")]
    t1 = [(0, 0, b"\xff\x03" + vlq(6) + b"Melody"), (0, 0, b"\xc0\x49")]
    for t, d, m, lyr in mel_ev:
        ly = lyr.encode("utf-8")
        t1 += [(tk(t), 1, b"\xff\x05" + vlq(len(ly)) + ly), (tk(t), 2, bytes([0x90, m, 90])), (tk(t + d) - 10, 0, bytes([0x80, m, 0]))]
    t2 = [(0, 0, b"\xff\x03" + vlq(6) + b"Chords"), (0, 0, b"\xc1\x00")]
    for t, d, ms in ch_ev:
        for m in ms:
            t2 += [(tk(t), 2, bytes([0x91, m, 64])), (tk(t + d) - 10, 0, bytes([0x81, m, 0]))]
    with open(path, "wb") as f:
        f.write(b"MThd" + struct.pack(">IHHH", 6, 1, 3, TPQ) + track(t0) + track(t1) + track(t2))


STEP = {0: ("C", 0), 1: ("C", 1), 2: ("D", 0), 3: ("D", 1), 4: ("E", 0), 5: ("F", 0), 6: ("F", 1), 7: ("G", 0), 8: ("G", 1), 9: ("A", 0), 10: ("A", 1), 11: ("B", 0)}
TYPE = {.5: ("eighth", 0), 1: ("quarter", 0), 1.5: ("quarter", 1), 2: ("half", 0), 3: ("half", 1), 4: ("whole", 0)}


def save_musicxml(path):
    """歌のパートを MusicXML にする（歌声合成の入力。休符も含めて曲頭から）。"""
    ev = []   # (開始拍, 拍, midi or None, 歌詞)
    for name, bar0, _, melody, shift, sung in SECTIONS:
        b = bar0 * 4.0
        for nm, beats, lyr in melody:
            vn = vocal_note(nm, shift, sung, lyr)
            ev.append((b, beats, vn[0] if vn else None, vn[1] if vn else ""))
            b += beats
    ev.append((BARS * 4.0, 4.0, None, ""))
    bars = [[] for _ in range(BARS + 1)]
    for b, beats, m, lyr in ev:
        bars[int(b // 4)].append((beats, m, lyr))
    x = ['<?xml version="1.0" encoding="UTF-8"?>', '<score-partwise version="3.1"><part-list><score-part id="P1"><part-name>Vocal</part-name></score-part></part-list><part id="P1">']
    for i, notes in enumerate(bars):
        x.append(f'<measure number="{i + 1}">')
        if i == 0:
            x.append(f'<attributes><divisions>2</divisions><key><fifths>0</fifths></key><time><beats>4</beats><beat-type>4</beat-type></time><clef><sign>G</sign><line>2</line></clef></attributes>'
                     f'<direction><direction-type><metronome><beat-unit>quarter</beat-unit><per-minute>{BPM}</per-minute></metronome></direction-type><sound tempo="{BPM}"/></direction>')
        if not notes:
            notes = [(4.0, None, "")]
        for beats, m, lyr in notes:
            ty, dot = TYPE[beats]
            body = "<rest/>" if m is None else f'<pitch><step>{STEP[m % 12][0]}</step>' + (f'<alter>1</alter>' if STEP[m % 12][1] else "") + f'<octave>{m // 12 - 1}</octave></pitch>'
            x.append(f'<note>{body}<duration>{int(beats * 2)}</duration><type>{ty}</type>' + ("<dot/>" if dot else "")
                     + (f'<lyric><syllabic>single</syllabic><text>{lyr}</text></lyric>' if m is not None else "") + '</note>')
        x.append('</measure>')
    x.append('</part></score-partwise>')
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(x))


def sing(xml_path):
    """MusicXML を歌わせる（pysinsy：HMM 歌声合成 Sinsy と付属の女声）。→ SR に合わせたモノラル波形"""
    import pysinsy
    sy = pysinsy.sinsy.Sinsy()
    assert sy.setLanguages("j", pysinsy.get_default_dic_dir())
    assert sy.loadVoices(pysinsy.get_default_htsvoice())
    assert sy.loadScoreFromMusicXML(xml_path)
    wav, sr = sy.synthesize()
    wav = np.asarray(wav, dtype=float)
    wav /= np.abs(wav).max() + 1e-9
    t = np.arange(int(len(wav) * SR / sr)) / SR
    v = np.interp(t, np.arange(len(wav)) / sr, wav)[:N]
    # 低域を切り、少し明るくする
    sp = np.fft.rfft(v); fr = np.fft.rfftfreq(len(v), 1 / SR)
    sp *= np.clip(fr / 140, 0, 1) ** 2 * (1 + .5 * np.clip((fr - 2500) / 2500, 0, 1))
    v = np.fft.irfft(sp, len(v))
    # やわらかい圧縮（小さい声を持ち上げる）
    e = np.sqrt(np.convolve(v ** 2, np.ones(2205) / 2205, "same")) + 1e-4
    v = v * (e / e.max()) ** -.35
    return np.pad(v / np.abs(v).max(), (0, max(0, N - len(v)))) * .5


if __name__ == "__main__":
    import sys
    out = lambda n: os.path.join(HERE, n)
    save_musicxml(out("homelandick_theme.musicxml"))
    vocal = None if "--no-vocal" in sys.argv else sing(out("homelandick_theme.musicxml"))
    full, mel_ev, ch_ev = render("none" if vocal is not None else "guide", vocal)
    save_wav(out("homelandick_theme.wav"), full)
    rng = np.random.default_rng(3)
    kara, _, _ = render("none")
    save_wav(out("homelandick_theme_karaoke.wav"), kara)
    if vocal is not None:
        save_wav(out("homelandick_theme_vocal.wav"), np.stack([vocal, vocal], 1) * 1.3)
    save_midi(out("homelandick_theme.mid"), mel_ev, ch_ev)
    print("ok", round(N / SR, 1), "sec", len(mel_ev), "notes")
