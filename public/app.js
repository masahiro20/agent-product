/* 現地写真レポート 画面ロジック（フレームワーク不使用） */
(() => {
  "use strict";

  const $ = (s) => document.querySelector(s);
  const MAX_PHOTOS = 12;
  const MAX_SIDE = 1568; // Claude の画像入力に最適な長辺
  const REGION_LABELS = { default: "全国標準", tokyo23: "東京23区", kanagawa: "神奈川", osaka: "大阪", nagoya: "名古屋",
    fukuoka: "福岡", hokkaido: "北海道" };
  const STRUCT_LABELS = { wood: "木造", light_steel: "軽量鉄骨造", heavy_steel: "重量鉄骨造", rc: "RC造" };
  const SIDE_LABELS = { S: "南", N: "北", E: "東", W: "西", unknown: "不明" };

  const state = { photos: [], land: null, reading: null, summary: null, pdfUrl: null, catalog: null, current: 0 };

  // ---------------- 共通 ----------------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const man = (v) => (v == null ? "-" : (v / 10000).toLocaleString("ja-JP", { maximumFractionDigits: 0 }));
  const num = (v, d = 2) => (v == null || isNaN(v) ? "" : Number(v).toFixed(d).replace(/\.?0+$/, ""));

  function toast(msg, isError = false) {
    const t = $("#toast");
    t.textContent = msg;
    t.className = "toast is-active" + (isError ? " toast--error" : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => (t.className = "toast"), isError ? 7000 : 3500);
  }

  function getKey() { try { return localStorage.getItem("hl_access_key") || ""; } catch { return ""; } }
  function setKey(k) { try { localStorage.setItem("hl_access_key", k); } catch { /* 保存できない環境 */ } }

  function askKey() {
    return new Promise((resolve) => {
      const m = $("#keyModal");
      m.classList.add("is-active");
      $("#keyInput").value = "";
      $("#keyInput").focus();
      $("#keyForm").onsubmit = (e) => {
        e.preventDefault();
        setKey($("#keyInput").value.trim());
        m.classList.remove("is-active");
        resolve();
      };
    });
  }

  async function api(path, body, { raw = false, method = "POST" } = {}) {
    for (let attempt = 0; attempt < 3; attempt++) {
      const res = await fetch(path, {
        method, headers: { "content-type": "application/json", "x-access-key": getKey() },
        body: method === "POST" ? JSON.stringify(body || {}) : undefined,
      });
      if (res.status === 401) { await askKey(); continue; }
      if (!res.ok) {
        let msg = `通信エラー（${res.status}）`;
        try { const j = await res.json(); if (j.error) msg = j.error; } catch { /* 本文なし */ }
        if (res.status === 413) msg = "写真の容量が大きすぎます。枚数を減らしてください。";
        if (res.status === 504) msg = "時間がかかりすぎて止まりました。写真の枚数を減らして再度お試しください。";
        throw new Error(msg);
      }
      return raw ? res.blob() : res.json();
    }
    throw new Error("アクセスキーを確認してください");
  }

  // ---------------- ステップ切り替え ----------------
  function go(step) {
    document.querySelectorAll(".view").forEach((v, i) => v.classList.toggle("is-active", i === step - 1));
    document.querySelectorAll(".step").forEach((s) => {
      const n = Number(s.dataset.step);
      s.classList.toggle("is-active", n === step);
      s.classList.toggle("is-done", n < step);
    });
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // ---------------- 進行表示 ----------------
  const progress = {
    start(title, items, hint) {
      $("#progTitle").textContent = title;
      $("#progHint").textContent = hint || "画面を閉じずにお待ちください";
      $("#progList").innerHTML = items.map((t) => `<li><span class="dot"></span><span>${esc(t)}</span></li>`).join("");
      $("#overlay").classList.add("is-active");
      const t0 = Date.now();
      clearInterval(this._timer);
      this._timer = setInterval(() => {
        const s = Math.floor((Date.now() - t0) / 1000);
        $("#progTime").textContent = `経過 ${Math.floor(s / 60)}分${String(s % 60).padStart(2, "0")}秒`;
      }, 500);
    },
    step(i) {
      document.querySelectorAll("#progList li").forEach((li, k) => {
        li.classList.toggle("is-done", k < i);
        li.classList.toggle("is-run", k === i);
      });
    },
    end() { clearInterval(this._timer); $("#overlay").classList.remove("is-active"); $("#progTime").textContent = ""; },
  };

  // ---------------- STEP 1: 写真 ----------------
  async function resize(file) {
    let bmp;
    try { bmp = await createImageBitmap(file, { imageOrientation: "from-image" }); }
    catch { bmp = await createImageBitmap(file); }
    const k = Math.min(1, MAX_SIDE / Math.max(bmp.width, bmp.height));
    const cv = document.createElement("canvas");
    cv.width = Math.round(bmp.width * k);
    cv.height = Math.round(bmp.height * k);
    cv.getContext("2d").drawImage(bmp, 0, 0, cv.width, cv.height);
    const dataUrl = cv.toDataURL("image/jpeg", 0.82);
    return { name: file.name, data: dataUrl.split(",")[1], url: dataUrl };
  }

  async function addFiles(files) {
    const list = [...files].filter((f) => f.type.startsWith("image/") || /\.(heic|heif|jpe?g|png|webp)$/i.test(f.name));
    if (!list.length) return;
    const room = MAX_PHOTOS - state.photos.length;
    if (room <= 0) { toast(`写真は${MAX_PHOTOS}枚までです`, true); return; }
    if (list.length > room) toast(`${MAX_PHOTOS}枚を超えた分は追加していません`);
    for (const f of list.slice(0, room)) {
      try { state.photos.push(await resize(f)); }
      catch { toast(`${f.name} を読み込めませんでした（JPEG・PNG で撮り直してください）`, true); }
      renderThumbs();
    }
  }

  function renderThumbs() {
    $("#thumbs").innerHTML = state.photos.map((p, i) =>
      `<div class="thumb"><img src="${p.url}" alt="写真${i + 1}"><span class="thumb__no">${i + 1}</span>` +
      `<button class="thumb__del" data-i="${i}" aria-label="写真${i + 1}を外す">×</button></div>`).join("");
    $("#count").textContent = state.photos.length ? `${state.photos.length} / ${MAX_PHOTOS} 枚` : "";
    $("#btnAnalyze").disabled = !state.photos.length;
  }

  function initStep1() {
    const drop = $("#drop");
    const input = $("#fileInput");
    drop.addEventListener("click", (e) => { if (e.target !== input) input.click(); });
    drop.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); input.click(); } });
    input.addEventListener("change", () => { addFiles(input.files); input.value = ""; });
    ["dragenter", "dragover"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.add("is-over"); }));
    ["dragleave", "drop"].forEach((ev) => drop.addEventListener(ev, (e) => { e.preventDefault(); drop.classList.remove("is-over"); }));
    drop.addEventListener("drop", (e) => addFiles(e.dataTransfer.files));
    $("#thumbs").addEventListener("click", (e) => {
      const b = e.target.closest(".thumb__del");
      if (!b) return;
      state.photos.splice(Number(b.dataset.i), 1);
      renderThumbs();
    });
    $("#address").addEventListener("change", () => {
      if (/名古屋/.test($("#address").value)) $("#region").value = "nagoya";
    });
    $("#btnAnalyze").addEventListener("click", analyze);
  }

  async function analyze() {
    const address = $("#address").value.trim();
    const items = [address ? "住所から地図・標高・用途地域・地価を取得" : "住所なし（公開データは使いません）",
      "AI が写真を読み取り（1〜3分かかります）", "読み取り結果を整理"];
    progress.start("読み取り中", items, "写真の枚数が多いほど時間がかかります。画面を閉じずにお待ちください。");
    try {
      progress.step(0);
      state.land = null;
      if (address) {
        try { state.land = await api("/api/land", { address }); }
        catch (e) { toast(`公開データを取得できませんでした（${e.message}）。写真だけで続けます。`, true); }
      }
      progress.step(1);
      const r = await api("/api/analyze", {
        address, notes: $("#notes").value.trim(),
        photos: state.photos.map(({ name, data }) => ({ name, data })),
        land_info: state.land?.land_info || [], aerial_b64: state.land?.aerial_b64 || null,
      });
      progress.step(2);
      state.reading = r.reading;
      if (!$("#projectName").value.trim() && r.reading.project_name) $("#projectName").value = r.reading.project_name;
      renderStep2();
      progress.end();
      go(2);
    } catch (e) {
      progress.end();
      toast(e.message, true);
    }
  }

  // ---------------- STEP 2: 確認 ----------------
  const B_FIELDS = [
    ["structure", "構造", "select", "", STRUCT_LABELS], ["use", "用途", "text"], ["floors", "階数", "int", "階"],
    ["built_year_est", "推定築年", "int", "年頃"], ["frontage_m", "建物の幅（道路側）", "num", "m"], ["depth_m", "建物の奥行", "num", "m"],
    ["eave_h", "軒高", "num", "m"], ["ridge_h", "最高高さ", "num", "m"], ["units_count", "戸数", "int", "戸"],
    ["unit_layout", "間取り", "select", "", null], ["unit_area_m2", "1戸の面積", "num", "㎡"],
    ["occupied_units", "家財が残る戸数", "int", "戸"], ["aircon_units", "室外機", "int", "台"], ["outdoor_leftover_m3", "屋外の残置物", "num", "㎥"],
  ];
  const S_FIELDS = [
    ["frontage_m", "敷地の間口", "num", "m"], ["depth_m", "敷地の奥行", "num", "m"], ["road_side", "前面道路の方位", "select", "", SIDE_LABELS],
    ["road_width_m", "道路の幅員", "num", "m"], ["building_offset_left_m", "建物の左の離れ", "num", "m"], ["building_setback_m", "建物の道路からの離れ", "num", "m"],
  ];

  function fieldHtml(obj, [key, label, type, unit, opts], group) {
    const v = obj[key];
    let ctl;
    if (type === "select") {
      const o = opts || Object.fromEntries((state.catalog?.layouts || []).map((x) => [x, x.replace("house_", "戸建 ")]));
      ctl = `<select class="select" data-g="${group}" data-k="${key}">` +
        Object.entries(o).map(([k, l]) => `<option value="${esc(k)}" ${k === v ? "selected" : ""}>${esc(l)}</option>`).join("") + "</select>";
    } else {
      const inputType = type === "text" ? "text" : "number";
      const step = type === "int" ? "1" : "0.01";
      ctl = `<input class="input ${type !== "text" ? "input--num" : ""}" type="${inputType}" step="${step}" inputmode="decimal" ` +
        `data-g="${group}" data-k="${key}" data-t="${type}" value="${esc(type === "num" ? num(v) : v ?? "")}">`;
    }
    return `<label class="field"><span class="field__label">${esc(label)}${unit ? `<span class="unit">${unit}</span>` : ""}</span>${ctl}</label>`;
  }

  function bindFields(container, getObj, after) {
    container.addEventListener("input", (e) => {
      const el = e.target.closest("[data-k]");
      if (!el) return;
      const obj = getObj();
      const t = el.dataset.t;
      if (t === "num" || t === "int") {
        const n = t === "int" ? parseInt(el.value, 10) : parseFloat(el.value);
        if (!isNaN(n)) obj[el.dataset.k] = n;
      } else obj[el.dataset.k] = el.value;
      after && after();
    });
  }

  function renderStats() {
    const b = state.reading.building || {};
    const s = state.reading.site || {};
    const nobe = (b.frontage_m || 0) * (b.depth_m || 0) * (b.floors || 1);
    const dz = (s.level_points || []).map((p) => p.dz_from_road_center_m);
    const rng = dz.length ? `${num(Math.min(0, ...dz), 1)}〜${num(Math.max(0, ...dz), 1)}` : "-";
    const items = b.exists === false ? [] : [
      ["構造", STRUCT_LABELS[b.structure] || "-", ""], ["階数", b.floors, "階"], ["延床（概算）", Math.round(nobe), "㎡"],
      ["戸数", b.units_count, "戸"], ["推定築年", b.built_year_est, "年頃"]];
    items.push(["敷地", Math.round((s.frontage_m || 0) * (s.depth_m || 0)), "㎡"], ["道路との高低差", rng, "m"]);
    $("#stats").innerHTML = items.map(([l, v, u]) =>
      `<div class="stat"><div class="stat__label">${esc(l)}</div><div class="stat__value">${esc(v ?? "-")}<small>${u}</small></div></div>`).join("");
    $("#nobe").textContent = b.exists === false ? "" : `延床 約${Math.round(nobe)}㎡（${(nobe / 3.30579).toFixed(1)}坪）`;
  }

  function renderViewer() {
    const ph = state.photos[state.current];
    if (!ph) return;
    $("#stageImg").src = ph.url;
    const pr = (state.reading.photos || []).find((p) => p.photo_index === state.current + 1) || { marks: [] };
    const svg = $("#stageSvg");
    svg.setAttribute("viewBox", "0 0 1000 1000");
    svg.setAttribute("preserveAspectRatio", "none");
    svg.innerHTML = $("#showMarks").checked ? (pr.marks || []).map((m, i) => {
      const x = m.x0 * 1000, y = m.y0 * 1000, w = (m.x1 - m.x0) * 1000, h = (m.y1 - m.y0) * 1000;
      return `<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="none" stroke="#d23c3c" stroke-width="4" vector-effect="non-scaling-stroke"/>` +
        `<rect x="${x}" y="${Math.max(0, y - 42)}" width="46" height="40" fill="#d23c3c"/>` +
        `<text x="${x + 23}" y="${Math.max(0, y - 42) + 29}" fill="#fff" font-size="28" text-anchor="middle" font-family="sans-serif">${i + 1}</text>`;
    }).join("") : "";
    $("#marks").innerHTML = (pr.caption ? `<li><strong>${esc(pr.caption)}</strong></li>` : "") + (pr.marks || []).map((m, i) =>
      `<li><span class="marks__no">${i + 1}</span><span>${esc(m.label)}${m.basis ? `<br><span class="marks__basis">${esc(m.basis)}</span>` : ""}</span></li>`).join("");
    $("#viewerThumbs").innerHTML = state.photos.map((p, i) =>
      `<button class="${i === state.current ? "is-active" : ""}" data-i="${i}" aria-label="写真${i + 1}"><img src="${p.url}" alt=""></button>`).join("");
  }

  function renderExterior() {
    const rows = state.reading.exterior || [];
    $("#extRows").innerHTML = rows.map((e, i) =>
      `<tr><td><input class="input" data-i="${i}" data-f="label" value="${esc(e.label)}"></td>` +
      `<td class="num" style="width:90px"><input class="input input--num" type="number" step="0.1" inputmode="decimal" data-i="${i}" data-f="qty" value="${num(e.qty, 1)}"></td>` +
      `<td style="width:70px">${esc(e.unit || state.catalog?.exterior?.[e.key]?.unit || "")}</td>` +
      `<td style="width:36px"><button class="icon-btn" data-del="${i}" aria-label="削除">×</button></td></tr>`).join("") ||
      `<tr><td colspan="4" style="color:var(--sub)">外構・付帯はありません</td></tr>`;
  }

  function renderLevels() {
    const pts = state.reading.site.level_points || [];
    $("#lvlRows").innerHTML = pts.map((p, i) =>
      `<tr><td data-label="高さを読んだ場所"><input class="input" data-i="${i}" data-f="label" value="${esc(p.label)}"></td>` +
      [["x", "左から m"], ["y", "道路から奥 m"], ["dz_from_road_center_m", "道路中心との差 m"]].map(([f, lab]) =>
        `<td class="num" data-label="${lab}" style="width:84px"><input class="input input--num" type="number" step="0.05" inputmode="decimal" data-i="${i}" data-f="${f}" value="${num(p[f])}"></td>`).join("") +
      `<td style="width:36px"><button class="icon-btn" data-del="${i}" aria-label="削除">×</button></td></tr>`).join("");
  }

  function renderPlan() {
    const s = state.reading.site;
    const b = state.reading.building || {};
    const F = s.frontage_m || 10, D = s.depth_m || 10, rw = s.road_width_m || 4;
    const W = 400, H = 300, pad = 34;
    const k = Math.min((W - pad * 2) / F, (H - pad * 2) / (D + rw));
    const ox = (W - F * k) / 2, oy = pad + (H - pad * 2 - (D + rw) * k) / 2;
    const X = (x) => ox + x * k, Y = (y) => oy + (D - y) * k;
    let h = `<rect x="0" y="${Y(0)}" width="${W}" height="${rw * k}" fill="#eef1f3"/>`;
    h += `<line x1="0" y1="${Y(0)}" x2="${W}" y2="${Y(0)}" stroke="#8c9baa"/>`;
    h += `<text x="${W / 2}" y="${Y(-rw / 2) + 4}" text-anchor="middle" font-size="11" fill="#818181">前面道路 幅員${num(rw, 1)}m（${SIDE_LABELS[s.road_side] || "不明"}側）・中心が高さ±0</text>`;
    h += `<rect x="${X(0)}" y="${Y(D)}" width="${F * k}" height="${D * k}" fill="#fff" stroke="#a94442" stroke-dasharray="6 3"/>`;
    if (b.exists !== false && b.frontage_m) {
      const bx = s.building_offset_left_m ?? 1, by = s.building_setback_m ?? 1;
      h += `<rect x="${X(bx)}" y="${Y(by + b.depth_m)}" width="${b.frontage_m * k}" height="${b.depth_m * k}" fill="#f1f3f4" stroke="#333"/>`;
      h += `<text x="${X(bx + b.frontage_m / 2)}" y="${Y(by + b.depth_m / 2) + 4}" text-anchor="middle" font-size="11" fill="#333">既存建物</text>`;
    }
    (s.extra_footprints || []).forEach((r) => {
      h += `<rect x="${X(r.x)}" y="${Y(r.y + r.d)}" width="${r.w * k}" height="${r.d * k}" fill="none" stroke="#818181" stroke-dasharray="3 2"/>`;
    });
    (s.level_points || []).forEach((p) => {
      const c = p.dz_from_road_center_m;
      h += `<circle cx="${X(p.x)}" cy="${Y(p.y)}" r="4" fill="${c >= 0 ? "#a18c4c" : "#8c9baa"}"/>`;
      h += `<text x="${X(p.x) + 6}" y="${Y(p.y) - 6}" font-size="11" fill="#333">${c >= 0 ? "+" : ""}${num(c)}m</text>`;
    });
    h += `<text x="${X(F / 2)}" y="${Y(D) - 8}" text-anchor="middle" font-size="11" fill="#818181">間口 ${num(F, 1)}m × 奥行 ${num(D, 1)}m</text>`;
    $("#planSvg").innerHTML = h;
  }

  function renderSite() {
    const s = state.reading.site;
    $("#siteFields").innerHTML = S_FIELDS.map((f) => fieldHtml(s, f, "site")).join("");
    renderPlan();
    renderLevels();
  }

  function renderLand() {
    const l = state.land;
    const img = $("#aerial");
    if (l?.aerial_b64) { img.src = "data:image/jpeg;base64," + l.aerial_b64; img.hidden = false; } else img.hidden = true;
    const rows = l?.land_info || [];
    $("#landRows").innerHTML = rows.length ? rows.map((r) =>
      `<tr><td style="width:34%">${esc(r.item)}</td><td>${esc(r.value)}</td><td><span class="badge badge--${esc(r.confidence)}">${esc(r.confidence)}</span></td></tr>`).join("")
      : `<tr><td style="color:var(--sub)">住所が無いため公開データは使っていません</td></tr>`;
    $("#cardLand").hidden = !l;
  }

  function renderStep2() {
    const r = state.reading;
    r.building = r.building || { exists: false };
    r.site = r.site || { frontage_m: 10, depth_m: 15, road_side: "unknown", road_width_m: 4, level_points: [] };
    r.site.level_points = r.site.level_points || [];
    state.current = 0;
    $("#cardBuilding").hidden = r.building.exists === false || !$("#optDemo").checked;
    $("#cardExterior").hidden = $("#cardBuilding").hidden;
    $("#cardSite").hidden = !$("#optGrade").checked;
    $("#buildingFields").innerHTML = B_FIELDS.map((f) => fieldHtml(r.building, f, "b")).join("");
    $("#basisList").innerHTML = (r.building.measure_basis || []).map((m) =>
      `<li><span>${esc(m.item)}：${esc(m.value)}<br><span class="marks__basis">${esc(m.basis)}</span></span></li>`).join("");
    const cat = state.catalog;
    $("#extAdd").innerHTML = Object.entries(cat?.exterior || {}).map(([k, v]) => `<option value="${k}">${esc(v.name)}</option>`).join("");
    $("#condChecks").innerHTML = Object.entries(cat?.conditions || {}).map(([k, v]) =>
      `<label class="chip-check"><input type="checkbox" value="${k}" ${(r.conditions || []).includes(k) ? "checked" : ""}><span>${esc(v)}</span></label>`).join("");
    $("#summaryText").value = (r.summary || []).join("\n");
    $("#checksText").value = (r.next_checks || []).join("\n");
    renderExterior();
    renderSite();
    renderLand();
    renderStats();
    renderViewer();
  }

  function initStep2() {
    bindFields($("#buildingFields"), () => state.reading.building, renderStats);
    bindFields($("#siteFields"), () => state.reading.site, () => { renderPlan(); renderStats(); });
    $("#siteFields").addEventListener("change", (e) => { if (e.target.dataset.k === "road_side") renderPlan(); });
    $("#buildingFields").addEventListener("change", renderStats);
    $("#viewerThumbs").addEventListener("click", (e) => {
      const b = e.target.closest("button");
      if (!b) return;
      state.current = Number(b.dataset.i);
      renderViewer();
    });
    $("#showMarks").addEventListener("change", renderViewer);

    $("#extRows").addEventListener("input", (e) => {
      const el = e.target;
      const row = state.reading.exterior[Number(el.dataset.i)];
      if (!row) return;
      if (el.dataset.f === "qty") { const n = parseFloat(el.value); if (!isNaN(n)) row.qty = n; } else row.label = el.value;
    });
    $("#extRows").addEventListener("click", (e) => {
      const d = e.target.closest("[data-del]");
      if (!d) return;
      state.reading.exterior.splice(Number(d.dataset.del), 1);
      renderExterior();
    });
    $("#btnExtAdd").addEventListener("click", () => {
      const key = $("#extAdd").value;
      const c = state.catalog.exterior[key];
      (state.reading.exterior = state.reading.exterior || []).push({ key, label: c.name, qty: 1, unit: c.unit, basis: "手入力", x0: 0, y0: 0, x1: 0, y1: 0 });
      renderExterior();
      toast(`「${c.name}」を追加しました。数量を入れてください`);
    });

    $("#lvlRows").addEventListener("input", (e) => {
      const el = e.target;
      const p = state.reading.site.level_points[Number(el.dataset.i)];
      if (!p) return;
      if (el.dataset.f === "label") p.label = el.value;
      else { const n = parseFloat(el.value); if (!isNaN(n)) p[el.dataset.f] = n; }
      renderPlan();
      renderStats();
    });
    $("#lvlRows").addEventListener("click", (e) => {
      const d = e.target.closest("[data-del]");
      if (!d) return;
      state.reading.site.level_points.splice(Number(d.dataset.del), 1);
      renderLevels(); renderPlan(); renderStats();
    });
    $("#btnLvlAdd").addEventListener("click", () => {
      const s = state.reading.site;
      s.level_points.push({ label: "新しい点", x: (s.frontage_m || 10) / 2, y: (s.depth_m || 10) / 2, dz_from_road_center_m: 0, basis: "手入力" });
      renderLevels(); renderPlan();
    });

    $("#btnBack1").addEventListener("click", () => go(1));
    $("#btnBuild").addEventListener("click", build);
  }

  function collectReading() {
    const r = state.reading;
    r.conditions = [...document.querySelectorAll("#condChecks input:checked")].map((i) => i.value);
    r.summary = $("#summaryText").value.split("\n").map((s) => s.trim()).filter(Boolean);
    r.next_checks = $("#checksText").value.split("\n").map((s) => s.trim()).filter(Boolean);
    return r;
  }

  function buildBody(format) {
    const land = state.land ? { ...state.land } : null;
    return {
      format, reading: collectReading(), land,
      photos: state.photos.map(({ name, data }) => ({ name, data })),
      options: {
        address: $("#address").value.trim(), project_name: $("#projectName").value.trim(),
        region: $("#region").value, fh_mode: $("#fhMode").value,
        include_demolition: $("#optDemo").checked, include_grading: $("#optGrade").checked,
        purpose: [$("#optDemo").checked && "解体概算", $("#optGrade").checked && "造成計画"].filter(Boolean).join("・"),
      },
    };
  }

  // ---------------- STEP 3: 資料 ----------------
  async function build() {
    progress.start("資料を作成中", ["概算を計算", "図面と PDF を作成"], "30秒ほどかかります");
    try {
      progress.step(0);
      state.summary = await api("/api/build", buildBody("summary"));
      progress.step(1);
      const pdf = await api("/api/build", buildBody("pdf"), { raw: true });
      if (state.pdfUrl) URL.revokeObjectURL(state.pdfUrl);
      state.pdfUrl = URL.createObjectURL(pdf);
      state.files = { pdf };
      renderStep3();
      progress.end();
      go(3);
    } catch (e) {
      progress.end();
      toast(e.message, true);
    }
  }

  function resultCard(label, t, note, total = false) {
    return `<div class="result ${total ? "result--total" : ""}"><div class="result__label">${esc(label)}</div>` +
      `<div class="result__value">${man(t.mid)}<small>万円</small></div>` +
      `<div class="result__range">幅 ${man(t.low)}〜${man(t.high)}万円（税別）</div>` +
      (note ? `<div class="result__note">${note}</div>` : "") + "</div>";
  }

  function renderStep3() {
    const s = state.summary;
    const cards = [];
    const d = s.demolition_total, g = s.grading_total;
    if (d) {
      let note = `延床 約${s.floor_area_m2}㎡（${s.floor_area_tsubo}坪）／坪単価 約${(s.per_tsubo_mid / 10000).toFixed(1)}万円`;
      if (s.asbestos_extra?.length) note += `<br>アスベスト含有時の追加 約${man(s.asbestos_extra[0].mid)}万円（別枠）`;
      cards.push(resultCard("解体工事", d, note));
    }
    if (g) {
      const gr = s.grading;
      cards.push(resultCard("造成工事", g, `切土 ${Math.round(gr.cut_m3)}㎥／盛土 ${Math.round(gr.fill_m3)}㎥／敷地 ${Math.round(gr.area_m2)}㎡`));
    }
    if (d && g) cards.push(resultCard("合計", { low: d.low + g.low, mid: d.mid + g.mid, high: d.high + g.high }, "解体＋造成", true));
    $("#results").innerHTML = cards.join("");

    const alts = s.alternatives || [];
    $("#cardAlt").hidden = !alts.length;
    $("#altRows").innerHTML = alts.map((a, i) =>
      `<tr><td>${i === 0 ? "<strong>採用</strong> " : ""}${esc(a.label.replace("採用案：", ""))}${a.below_road ? '<br><span class="badge badge--要確認">道路より低い</span>' : ""}</td>` +
      `<td class="num">${a.fh_rel >= 0 ? "+" : ""}${num(a.fh_rel)}m</td><td class="num">${num(a.wall_m, 1)}m</td><td class="num">${man(a.total_mid)}万円</td></tr>`).join("");

    const cheaper = alts.slice(1).filter((a) => a.total_mid < (alts[0]?.total_mid || 0) - 50000)
      .sort((a, b) => a.total_mid - b.total_mid)[0];
    $("#altHint").hidden = !cheaper;
    if (cheaper) {
      $("#altHint").innerHTML = `「${esc(cheaper.label)}」にすると約${man(alts[0].total_mid - cheaper.total_mid)}万円安くなります` +
        (cheaper.below_road ? "。ただし敷地が道路より低くなるため、雨水の流入対策（排水・浸透桝）が前提です。" : "。");
    }

    const flags = [...(s.grading?.flags || [])];
    (s.walls || []).filter((w) => w.h_max > 0.3 && !/不要|構造物なし/.test(w.type_name)).forEach((w) => flags.push(`境界${w.index + 1}：${w.type_name}（高さ 約${num(w.h_max)}m・長さ ${num(w.length_m, 1)}m）`));
    if (s.asbestos_extra?.length) flags.push("築年からアスベスト含有の可能性。解体前の事前調査（有資格者）が義務です");
    $("#flags").innerHTML = flags.length ? flags.map((f) => `<li>${esc(f)}</li>`).join("") : "<li>特記事項なし</li>";

    const frame = $("#pdfFrame");
    frame.src = state.pdfUrl;
  }

  async function download(fmt) {
    try {
      let blob = state.files?.[fmt];
      if (!blob) {
        toast(`${fmt.toUpperCase()} を作成中…`);
        blob = await api("/api/build", buildBody(fmt), { raw: true });
        state.files[fmt] = blob;
      }
      const name = ($("#projectName").value.trim() || "現地写真レポート").replace(/[\\/:*?"<>|]/g, "_");
      const a = document.createElement("a");
      a.href = URL.createObjectURL(blob);
      a.download = `${name}${fmt === "xlsx" ? "_見積" : fmt === "dxf" ? "_図面" : ""}.${fmt}`;
      document.body.appendChild(a);
      a.click();
      setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
    } catch (e) { toast(e.message, true); }
  }

  function initStep3() {
    document.querySelectorAll(".dl").forEach((b) => b.addEventListener("click", () => download(b.dataset.fmt)));
    $("#btnBack2").addEventListener("click", () => go(2));
    $("#btnNew").addEventListener("click", () => {
      if (!confirm("入力内容を消して、新しい物件を始めますか？")) return;
      Object.assign(state, { photos: [], land: null, reading: null, summary: null, files: null });
      ["#address", "#projectName", "#notes"].forEach((s) => ($(s).value = ""));
      renderThumbs();
      go(1);
    });
  }

  // ---------------- 起動 ----------------
  async function init() {
    initStep1(); initStep2(); initStep3();
    try {
      state.catalog = await api("/api/catalog", null, { method: "GET" });
    } catch (e) { toast(e.message, true); state.catalog = { exterior: {}, conditions: {}, regions: { default: 1 }, layouts: [] }; }
    const regions = Object.keys(state.catalog.regions || { default: 1 });
    $("#region").innerHTML = ["default", ...regions.filter((r) => r !== "default")].map((r) =>
      `<option value="${r}">${REGION_LABELS[r] || r}（係数 ×${state.catalog.regions?.[r] ?? 1}）</option>`).join("");
    renderThumbs();
  }
  init();
})();
