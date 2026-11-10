# PR映像（現地写真レポート）

`homelandick_pr.mp4` … 1920×1080・30fps・76秒。撮影・素材なしで、全フレームをコードから描いている。

- `film.html` … 映像本体。`renderAt(秒)` がその時刻の1フレームを描く（ブラウザで開けばそのまま再生、`?t=40` で静止）
- `render.mjs` … film.html を1フレームずつ画像にして ffmpeg で mp4 にする
- `music.py` … 音楽を numpy だけで合成する（90BPM。章の切り替わりを小節の頭に合わせてある）
- `assets/pg-*.jpg` … サンプル物件を実際のエンジンに通して出した PDF（18ページ）の各ページ

映像に出る数値・図面は、`public/demo/sample.json`（架空のサンプル物件）を `webapp/service.build` に通した実際の出力。
サンプルや出力が変わったら、PDF を作り直して `pdftoppm` でページ画像を差し替え、film.html の数値を合わせる。

## 作り直す

```
pip install numpy
python video/music.py                       # video/music.wav
NODE_PATH=$(npm root -g) node video/render.mjs   # video/homelandick_pr.mp4（playwright・ffmpeg が必要）
NODE_PATH=$(npm root -g) node video/render.mjs --stills 19,40,48   # 指定した秒の静止画だけ（video/.frames/）
```

フォントは Google Fonts（Shippori Mincho／Noto Sans JP／Inter）を読み込むので、描画時はネットワークが必要。
