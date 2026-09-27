# -*- coding: utf-8 -*-
"""뷰어 HTML 을 굽는다: 템플릿 + 예제 형상(int16 양자화 · 정점 색인 · gzip · base64) + 글꼴.

    python build_viewer.py <템플릿.html> <출력.html> examples/examples.json   # 예제 목록 (권장)
    python build_viewer.py <템플릿.html> <출력.html> [라벨=경로.stl ...]      # 예전 방식: STL 들을 예제 하나로

예제 목록(JSON)의 첫 번째가 기본으로 열린다. STL 은 parts 에 파일마다, OBJ 는 file 하나에 그룹(o/g)마다 파트가 된다.
STL 은 바이너리여야 한다 (tools/cad2stl.py 출력). 인자 없이 굽으면 빈 뷰어(파일 열기만)가 된다.

형상 인코딩 — 예제마다 바운딩박스 가운데 근처를 0 으로, 가장 긴 반폭이 ±32000 안에 들도록 1·2·5×10ⁿ 간격으로 int16 양자화하고, 같은 점을
처음 나온 순서대로 합쳐 색인으로 만든 뒤 gzip 한다. 삼각형 수프(점을 매번 반복)보다 3 배쯤 작다.
브라우저는 DecompressionStream 으로 푼다 — 서버 없이 파일 하나로 열린다.
"""
import base64, gzip, json, math, os, sys
import numpy as np


def read_binary_stl(path):
    with open(path, "rb") as fh:
        fh.seek(80); n = int.from_bytes(fh.read(4), "little")
        raw = np.frombuffer(fh.read(n * 50), dtype=np.uint8).reshape(n, 50)
    V = raw[:, 12:48].copy().view("<f4").reshape(-1, 3)          # (3n, 3) 삼각형 수프
    return V, [(3 * i, 3 * i + 1, 3 * i + 2) for i in range(n)]


def read_obj_groups(path):
    """[(그룹 이름, 정점 배열, 면 목록)] — 면 색인은 그 그룹이 쓰는 정점만 추려 새로 매긴다."""
    V, groups, cur = [], [], None
    stem = os.path.splitext(os.path.basename(path))[0]
    with open(path, encoding="utf-8", errors="replace") as fh:
        for raw in fh:
            s = raw.strip()
            if s.startswith("v "):
                V.append([float(x) for x in s.split()[1:4]])
            elif s.startswith(("o ", "g ")):
                cur = [s[2:].strip() or stem, []]; groups.append(cur)
            elif s.startswith("f "):
                if cur is None: cur = [stem, []]; groups.append(cur)
                idx = [int(t.split("/")[0]) for t in s.split()[1:]]
                cur[1].append([i - 1 if i > 0 else len(V) + i for i in idx])
    V = np.asarray(V, np.float32); out = []
    for name, F in groups:
        if not F: continue
        used = sorted({i for f in F for i in f}); m = {v: k for k, v in enumerate(used)}
        out.append((name, V[used], [[m[i] for i in f] for f in F]))
    return out


def weld(q):
    """같은 int16 점을 처음 나온 순서대로 합친다 → (정점, 옛 색인 → 새 색인). 뷰어의 용접 순서와 같아 결과가 같다."""
    u, first, inv = np.unique(q, axis=0, return_index=True, return_inverse=True)
    order = np.argsort(first, kind="stable"); rank = np.empty_like(order); rank[order] = np.arange(len(order))
    return u[order], rank[np.asarray(inv).ravel()]


def bake(example, root):
    parts = []                                                    # (meta, V, faces)
    if "file" in example:
        presets = example.get("parts", {})
        for name, V, F in read_obj_groups(os.path.join(root, example["file"])):
            p = dict(presets.get(name, {})); p.setdefault("names", {"ko": name, "en": name}); parts.append((p, V, F))
    else:
        for p in example["parts"]:
            V, F = read_binary_stl(os.path.join(root, p["file"])); parts.append(({k: v for k, v in p.items() if k != "file"}, V, F))
    allv = np.vstack([V for _, V, _ in parts]).astype(np.float64)   # float32 로 하면 중심이 60.000004 처럼 된다
    lo, hi = allv.min(0), allv.max(0)
    half = float((hi - lo).max() / 2) or 1.0
    # 양자화 간격은 1·2·5 × 10ⁿ 로 반올림하고 중심도 그 배수에 둔다 — mm 로 설계한 치수(1300, 215.4 …)가
    # 반올림 오차 없이 그대로 나온다 (0.0256 같은 간격이면 1300.01 로 찍힌다). |q| ≤ 32000.5 라 int16 에 들어간다.
    raw = half / 32000.0; e = math.floor(math.log10(raw))
    qs = next(m * 10.0 ** e for m in (1, 2, 5, 10) if m * 10.0 ** e >= raw * (1 - 1e-12))
    ctr = np.round((lo + hi) / 2 / qs) * qs
    blob, meta = bytearray(), []
    for p, V, F in parts:
        q = np.round((V.astype(np.float64) - ctr) / qs).astype(np.int16)
        Vw, remap = weld(q)
        stream = []
        for f in F: stream.append(len(f)); stream.extend(int(remap[i]) for i in f)
        blob += Vw.astype("<i2").tobytes() + np.asarray(stream, "<u4").tobytes()
        m = {"names": p["names"], "nv": len(Vw), "nf": len(stream), "on": p.get("on", True)}
        for k in ("color", "op"):
            if k in p: m[k] = p[k]
        meta.append(m)
        print("  %-30s %8s tri" % (p["names"]["ko"], format(sum(len(f) - 2 for f in F), ",")))
    data = base64.b64encode(gzip.compress(bytes(blob), 9, mtime=0)).decode()   # mtime=0: 다시 구워도 같은 파일
    out = {"id": example["id"], "title": example["title"], "desc": example.get("desc", {"ko": "", "en": ""}),
           "ctr": [round(float(c), 6) for c in ctr], "qs": float("%.10g" % qs), "parts": meta, "data": data}
    if "display" in example: out["display"] = example["display"]
    print("%-32s %.2f MB (base64, gzip)" % (example["id"], len(data) / 1e6))
    return out


def main(tpl_path, out_path, args):
    if len(args) == 1 and args[0].endswith(".json"):
        root = os.path.dirname(os.path.abspath(args[0]))
        spec = json.load(open(args[0], encoding="utf-8"))["examples"]
    else:                                                          # 예전 방식: 라벨=경로.stl ... → 예제 하나
        root = os.getcwd()
        spec = [{"id": "default", "title": {"ko": "기본 형상", "en": "Default"},
                 "parts": [{"file": a.split("=", 1)[1], "names": {"ko": a.split("=", 1)[0], "en": a.split("=", 1)[0]}, "on": i == 0}
                           for i, a in enumerate(args)]}] if args else []
    examples = [bake(e, root) for e in spec]

    tpl = open(tpl_path, encoding="utf-8").read()
    tools = os.path.dirname(os.path.abspath(__file__))
    font = os.path.join(tools, "PretendardVariable.woff2")
    if not os.path.isfile(font):
        raise SystemExit("글꼴 파일이 없습니다: %s (Pretendard Variable woff2, SIL OFL)" % font)
    version = open(os.path.join(tools, "VERSION"), encoding="utf-8").read().strip()   # 버전은 이 파일 한 곳
    rep = {"__EXAMPLES__": json.dumps(examples, ensure_ascii=False, separators=(",", ":")),
           "__FONT__": base64.b64encode(open(font, "rb").read()).decode(),
           "__VERSION__": version}
    for k, v in rep.items():
        assert k in tpl, k
        tpl = tpl.replace(k, v)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    open(out_path, "w", encoding="utf-8").write(tpl)
    print("wrote", out_path, "%.2f MB  (v%s, 예제 %d개)" % (os.path.getsize(out_path) / 1e6, version, len(examples)))

    # 홈페이지 배너·아이콘: 같은 폴더에 같이 굽는다. 버전 태그는 오른쪽 위, 글자 수로 폭을 잡는다.
    banner = open(os.path.join(tools, "banner_template.svg"), encoding="utf-8").read()
    tag_w = 16 + 7.0 * len("v" + version)
    tag_x = 360 - 6 - 14 - tag_w
    for k, v in {"__VERSION__": version, "__TAGW__": "%.1f" % tag_w, "__TAGX__": "%.1f" % tag_x,
                 "__TAGCX__": "%.1f" % (tag_x + tag_w / 2)}.items():
        assert k in banner, k
        banner = banner.replace(k, v)
    assert "__" not in banner.replace("__VERSION__", ""), "배너에 채워지지 않은 자리표시자가 남았다"
    open(os.path.join(out_dir, "banner.svg"), "w", encoding="utf-8").write(banner)
    import shutil; shutil.copy(os.path.join(tools, "icon.svg"), os.path.join(out_dir, "icon.svg"))
    print("wrote", os.path.join(out_dir, "banner.svg"), "+ icon.svg")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
