"""results_<tag>.json を掲載値と比べて採点する。 python3 score.py v0 [v1 ...]"""
import json
import os
import re
import statistics as st
import sys

EVAL = os.environ.get("EVAL_DIR", os.path.join(os.path.dirname(__file__), "../../jobs/eval"))


def year(s):
    m = re.search(r"(\d{4})", s or "")
    return int(m.group(1)) if m else None


def score(tag, verbose=True):
    # "v2a+v2a_new" は結果を合わせる。"ens:v2a+v2a_new,v2b+v2b_new" は2回の読み取りの平均（延床・敷地・築年）
    def load(t):
        out = {}
        for part in t.split("+"):
            try:
                for r in json.load(open(f"{EVAL}/results_{part}.json", encoding="utf-8")):
                    if not r.get("error"):
                        out[r["id"]] = r
            except FileNotFoundError:
                pass
        return out
    if tag.startswith("ens:"):
        runs = [load(t) for t in tag[4:].split(",")]
        ids = set.intersection(*(set(r) for r in runs))
        rs = []
        for i in ids:
            base = json.loads(json.dumps(runs[0][i]))
            for k in ("floor_area_m2", "site_area_m2", "built_year"):
                base["pred"][k] = sum(r[i]["pred"][k] for r in runs) / len(runs)
            base["pred"]["built_year"] = round(base["pred"]["built_year"])
            rs.append(base)
    else:
        rs = list(load(tag).values())
    rs.sort(key=lambda r: r["id"])
    rows, ae, se, fl_ok, yr_e, site_e = [], [], [], 0, [], []
    for r in rs:
        t, p = r["truth"], r["pred"]
        ta, pa = t["建物面積_m2"], p["floor_area_m2"]
        err = (pa - ta) / ta
        ae.append(abs(err))
        se.append(err)
        fl_ok += int(p["floors"] == t.get("階数"))
        ye = p["built_year"] - year(t.get("築年月"))
        yr_e.append(ye)
        ts = t.get("土地面積_m2")
        s_err = (p["site_area_m2"] - ts) / ts if ts else None
        if s_err is not None:
            site_e.append(abs(s_err))
        per = ""
        if t.get("各階面積"):
            fa = {f["floor"]: f["area_m2"] for f in (p.get("detail") or {}).get("floors", [])}
            per = " / ".join(f"{k}: {fa.get(int(k[0]), 0):.0f} vs {v:.0f}" for k, v in t["各階面積"].items())
        rows.append(f"{r['id']} 延床 {pa:6.1f} vs {ta:6.1f} ({err:+.0%})  階 {p['floors']}/{t.get('階数')}  築 {p['built_year']}/{year(t.get('築年月'))}"
                    f"  敷地 {p['site_area_m2']:.0f}/{ts:.0f} ({s_err:+.0%})  外形 {p['frontage_m']:.1f}x{p['depth_m']:.1f} {per}")
    n = len(rs)
    summ = {"n": n, "延床_平均誤差": st.mean(ae), "延床_中央誤差": st.median(ae), "延床_偏り": st.mean(se),
            "延床_±10%以内": sum(a <= .10 for a in ae) / n, "延床_±20%以内": sum(a <= .20 for a in ae) / n,
            "階数_正解率": fl_ok / n, "築年_平均誤差": st.mean(abs(y) for y in yr_e), "築年_偏り": st.mean(yr_e),
            "敷地_平均誤差": st.mean(site_e) if site_e else None}
    if verbose:
        print(f"== {tag}")
        print("\n".join(rows))
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in summ.items()})
    return summ


if __name__ == "__main__":
    for t in sys.argv[1:]:
        score(t)
