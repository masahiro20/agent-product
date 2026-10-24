"""住所 → 座標・標高（敷地ローカル格子）・航空写真・ハザード等を取得して spec に書き込む。

敷地ローカル座標と実世界の対応:
  site.anchor = {"x":.., "y":..}            ローカル座標のどの点が
  site.anchor_latlon = {"lat":.., "lon":..} この緯度経度か（省略時は住所のジオコード結果＝番地の代表点）
  site.north_rot_deg                         図の上方向が真北から時計回りに何度か（0=北が上）
"""
import math
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
import public_data  # noqa: E402

M_PER_DEG_LAT = 111_320.0


def _local_to_world(x, y, ax, ay, rot):
    """ローカル(x,y) → アンカーからの東西・南北距離(m)。"""
    dx, dy = x - ax, y - ay
    r = math.radians(rot)
    e = dx * math.cos(r) + dy * math.sin(r)
    n = -dx * math.sin(r) + dy * math.cos(r)
    return e, n


def _bilinear(grid, e, n):
    xs, ys, z = grid["xs"], grid["ys"], grid["z"]
    if not (xs[0] <= e <= xs[-1] and ys[0] <= n <= ys[-1]):
        return None
    i = max(0, min(len(xs) - 2, int((e - xs[0]) / (xs[1] - xs[0]))))
    j = max(0, min(len(ys) - 2, int((n - ys[0]) / (ys[1] - ys[0]))))
    tx = (e - xs[i]) / (xs[i + 1] - xs[i])
    ty = (n - ys[j]) / (ys[j + 1] - ys[j])
    v = [z[j][i], z[j][i + 1], z[j + 1][i], z[j + 1][i + 1]]
    if any(a is None for a in v):
        vals = [a for a in v if a is not None]
        return sum(vals) / len(vals) if vals else None
    return v[0] * (1 - tx) * (1 - ty) + v[1] * tx * (1 - ty) + v[2] * (1 - tx) * ty + v[3] * tx * ty


def _ensure_ascending(grid):
    xs, ys, z = list(grid["xs"]), list(grid["ys"]), [list(r) for r in grid["z"]]
    if xs[0] > xs[-1]:
        xs = xs[::-1]
        z = [r[::-1] for r in z]
    if ys[0] > ys[-1]:
        ys = ys[::-1]
        z = z[::-1]
    return {"xs": xs, "ys": ys, "z": z}


def apply_dem(spec):
    """terrain.dem_world（住所の代表点を原点とする東西・南北m格子）を敷地ローカル格子に変換して
    site.existing.dem に入れる。敷地の形・アンカー・方位を変えたら呼び直す。標高の範囲を返す。"""
    site = spec.get("site")
    g = (spec.get("terrain") or {}).get("dem_world")
    if not site or not g:
        return None
    pts = site["boundary"]
    cx = sum(p[0] for p in pts) / len(pts)
    cy = sum(p[1] for p in pts) / len(pts)
    anc = site.get("anchor") or {"x": cx, "y": cy}
    rot = site.get("north_rot_deg", 0.0)
    xs_b = [p[0] for p in pts]
    ys_b = [p[1] for p in pts]
    margin = (site.get("road", {}).get("width_m", 4.0)) + 5
    lx = [min(xs_b) - margin + k for k in range(int(max(xs_b) - min(xs_b) + 2 * margin) + 1)]
    ly = [min(ys_b) - margin + k for k in range(int(max(ys_b) - min(ys_b) + 2 * margin) + 1)]
    z = []
    for y in ly:
        row = []
        for x in lx:
            e, n = _local_to_world(x, y, anc["x"], anc["y"], rot)
            row.append(_bilinear(g, e, n))
        z.append(row)
    ex = site.setdefault("existing", {})
    ex["dem"] = {"xs": lx, "ys": ly, "z": z}
    ex["source"] = "dem+points" if ex.get("points") else "dem"
    vals = [v for r_ in z for v in r_ if v is not None]
    return [round(min(vals), 2), round(max(vals), 2)] if vals else None


def fetch(spec, base_dir, half_size_m=30.0, step_m=1.0):
    info = {}
    proj = spec.setdefault("project", {})
    site = spec.get("site")
    addr = proj.get("address")
    if site and site.get("anchor_latlon"):
        lat, lon = site["anchor_latlon"]["lat"], site["anchor_latlon"]["lon"]
        title = addr
    else:
        g = public_data.geocode(addr)
        if isinstance(g, dict) and g.get("error"):
            raise RuntimeError(f"住所から座標を取得できません: {g['error']}")
        lat, lon, title = g
    info["lat"], info["lon"], info["geocode_title"] = lat, lon, title
    terr = spec.setdefault("terrain", {})
    terr.update({"lat": lat, "lon": lon, "geocode_title": title})

    out_dir = os.path.join(base_dir, "terrain")
    os.makedirs(out_dir, exist_ok=True)

    # 航空写真
    ap = os.path.join(out_dir, "aerial.jpg")
    r = public_data.aerial_photo(lat, lon, zoom=19, size_px=768, out_path=ap)
    if not (isinstance(r, dict) and r.get("error")):
        terr["aerial_photo"] = ap
        info["aerial_photo"] = ap

    # 標高（世界座標の格子を保存し、敷地ローカル格子へ再サンプリング）
    grid = public_data.elevation_grid(lat, lon, half_size_m=half_size_m, step_m=step_m)
    if isinstance(grid, dict) and grid.get("error"):
        info["dem_error"] = grid["error"]
    else:
        g = _ensure_ascending(grid)
        terr["dem_world"] = {"xs": g["xs"], "ys": g["ys"], "z": g["z"]}
        terr["dem_source"] = grid.get("source")
        info["dem_source"] = grid.get("source")
        if site:
            info["dem_range"] = apply_dem(spec)

    # 土地情報（取れたものだけ。確実性: 公的データの代表点読取り＝要確認／推測）
    li = spec.setdefault("land_info", [])
    have = {x["item"] for x in li}

    def add(item, value, conf, src):
        if item not in have and value not in (None, ""):
            li.append({"item": item, "value": value, "confidence": conf, "source": src})
            have.add(item)

    zn = public_data.zoning_at(lat, lon)
    if isinstance(zn, dict) and not zn.get("error"):
        sm = zn.get("summary") or {}
        if sm.get("用途地域"):
            add("用途地域", f"{sm['用途地域']}（建ぺい率{sm.get('建ぺい率%')}%／容積率{sm.get('容積率%')}%）",
                "要確認", "国交省 都市計画決定GISデータ（参考。自治体の都市計画図で確認）")
        if sm.get("防火"):
            add("防火・準防火", "、".join(sm["防火"]) if isinstance(sm["防火"], list) else str(sm["防火"]), "要確認", "同上")
        if sm.get("高度地区"):
            add("高度地区", str(sm["高度地区"]), "要確認", "同上")
        sb = (zn.get("senbiki") or [{}])[0].get("AreaType")
        add("区域区分", sb, "要確認", "同上")
        info["zoning"] = sm
    lp = public_data.land_price_nearby(lat, lon, n=3)
    if isinstance(lp, dict) and not lp.get("error"):
        pts = (lp.get("L01") or []) + (lp.get("L02") or [])
        pts = sorted(pts, key=lambda r: r.get("dist_m", 1e9))[:3]
        for i, r in enumerate(pts, 1):
            add(f"近傍地価 {i}", f"{r['price']:,}円/㎡（約{r['price'] * 3.30579 / 10000:.0f}万円/坪、{r.get('year')}年 {r['label']}、"
                f"{r.get('dist_m', 0):.0f}m先、{r.get('addr', '').replace('　', '')}、{r.get('surround', '')}）",
                "確定", "国土数値情報 地価公示・地価調査（地点の価格。本敷地の価格ではない）")
        info["land_price"] = pts
    rg = public_data.reverse_geocode(lat, lon)
    if isinstance(rg, dict) and not rg.get("error"):
        txt = rg.get("address") or rg.get("full") or " ".join(str(v) for k, v in rg.items() if isinstance(v, str) and k != "attribution")
        add("所在（座標の逆引き）", f"{txt}（緯度{lat:.6f} 経度{lon:.6f}）", "推測", "国土地理院 逆ジオコーダ（住所の代表点）")
    hz = public_data.hazard_at(lat, lon)
    if isinstance(hz, dict) and not hz.get("error"):
        outside = []
        src = "重ねるハザードマップ（代表点の画素読取り。自治体ハザードマップで確認）"
        for k, lay in (hz.get("layers") or {}).items():
            if not isinstance(lay, dict):
                continue
            if lay.get("in_area") is False or str(lay.get("class", "")).startswith("区域外"):
                outside.append(lay.get("name", k))
            else:
                add(f"ハザード：{lay.get('name', k)}", lay.get("class", ""), "要確認", src)
        if outside:
            add("ハザード：区域外（代表点）", "、".join(outside), "要確認", src)
        q = hz.get("jshis_quake_prob_30y")
        if isinstance(q, dict) and q.get("震度6弱以上_30年確率") is not None:
            add("地震：30年以内に震度6弱以上", f"{q['震度6弱以上_30年確率'] * 100:.1f}%", "推測", "J-SHIS 確率論的地震動予測地図（250mメッシュ）")
        info["hazard"] = hz
    lf = public_data.landform_at(lat, lon)
    if isinstance(lf, dict) and not lf.get("error"):
        for k, v in lf.items():
            if isinstance(v, dict) and v.get("class"):
                add(f"地形：{v.get('name', k)}", v["class"], "推測", "国土地理院 地形分類（1/2.5万〜1/5万の概略）")
            elif isinstance(v, dict) and v.get("微地形区分"):
                add("地形：微地形区分（J-SHIS）", f"{v['微地形区分']}（地盤増幅率{v.get('地盤増幅率')}）", "推測", "J-SHIS 250mメッシュ")
        info["landform"] = lf
    attrs = spec.setdefault("data_attribution", [])
    for a in ("国土地理院 地理院タイル（標高・空中写真・地形分類）／住所検索・逆ジオコーダ", "ハザードマップポータルサイト（国土交通省・国土地理院）",
              "国土交通省 都市計画決定GISデータ（参考情報）", "国土数値情報（地価公示・都道府県地価調査）", "防災科学技術研究所 J-SHIS"):
        if a not in attrs:
            attrs.append(a)
    return info
