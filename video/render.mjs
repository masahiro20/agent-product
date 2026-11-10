// film.html を1フレームずつ描いて動画にする。
//   node video/render.mjs                … 全フレームを書き出して mp4 にする（音は music.py の出力を合わせる）
//   node video/render.mjs --stills 3,12  … 指定した秒の静止画だけ（確認用）
import { createRequire } from "node:module";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const { chromium } = createRequire(import.meta.url)("playwright"); // グローバルに入っている場合は NODE_PATH=$(npm root -g)
const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const OUT = process.env.FILM_TMP || path.join(ROOT, "video", ".frames");
const FPS = 30, DUR = 76, WORKERS = 4;
const MIME = { ".html": "text/html", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".jpg": "image/jpeg", ".png": "image/png", ".css": "text/css" };

const server = http.createServer((req, res) => {
  const p = path.join(ROOT, decodeURIComponent(req.url.split("?")[0]));
  if (!p.startsWith(ROOT) || !fs.existsSync(p) || fs.statSync(p).isDirectory()) { res.writeHead(404); return res.end(); }
  res.writeHead(200, { "content-type": MIME[path.extname(p)] || "application/octet-stream" });
  fs.createReadStream(p).pipe(res);
});
await new Promise((r) => server.listen(0, r));
const url = `http://127.0.0.1:${server.address().port}/video/film.html`;

const browser = await chromium.launch();
async function open() {
  const page = await browser.newPage({ viewport: { width: 1920, height: 1080 }, deviceScaleFactor: 1 });
  await page.goto(url);
  await page.evaluate(() => window.ready);
  return page;
}
fs.mkdirSync(OUT, { recursive: true });

const si = process.argv.indexOf("--stills");
if (si > 0) {
  const page = await open();
  for (const t of process.argv[si + 1].split(",").map(Number)) {
    await page.evaluate((t) => window.renderAt(t), t);
    await page.screenshot({ path: path.join(OUT, `still_${t.toFixed(2)}.jpg`), type: "jpeg", quality: 85 });
  }
} else {
  const total = FPS * DUR;
  let next = 0, done = 0;
  await Promise.all([...Array(WORKERS)].map(async () => {
    const page = await open();
    while (next < total) {
      const f = next++;
      await page.evaluate((t) => window.renderAt(t), f / FPS);
      await page.screenshot({ path: path.join(OUT, `f${String(f).padStart(5, "0")}.jpg`), type: "jpeg", quality: 95 });
      if (++done % 300 === 0) console.log(`${done}/${total}`);
    }
  }));
  const audio = path.join(ROOT, "video", "music.wav");
  const args = ["-y", "-loglevel", "error", "-framerate", String(FPS), "-i", path.join(OUT, "f%05d.jpg")];
  if (fs.existsSync(audio)) args.push("-i", audio, "-c:a", "aac", "-b:a", "192k", "-shortest");
  args.push("-c:v", "libx264", "-preset", "slow", "-crf", "18", "-pix_fmt", "yuv420p", "-movflags", "+faststart", path.join(ROOT, "video", "homelandick_pr.mp4"));
  execFileSync("ffmpeg", args, { stdio: "inherit" });
  console.log("video/homelandick_pr.mp4");
}
await browser.close();
server.close();
