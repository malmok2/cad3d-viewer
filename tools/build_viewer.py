# -*- coding: utf-8 -*-
"""뷰어 HTML 을 굽는다: 템플릿 + 기본 탑재 STL(int16 양자화, base64).

    python build_viewer.py <템플릿.html> <출력.html> [라벨=경로.stl ...]

탑재 STL 은 바이너리여야 한다 (tools/cad2stl.py 출력). 첫 번째가 기본으로 켜진다.
"""
import base64, json, os, sys
import numpy as np


def read_binary_stl(path):
    with open(path, "rb") as fh:
        fh.seek(80); n = int.from_bytes(fh.read(4), "little")
        raw = np.frombuffer(fh.read(n * 50), dtype=np.uint8).reshape(n, 50)
    return raw[:, 12:48].copy().view("<f4").reshape(-1, 3)      # (9n, 3) → 삼각형 수프


def main(tpl_path, out_path, specs):
    parts = []
    for i, spec in enumerate(specs):
        label, path = spec.split("=", 1)
        parts.append((label, read_binary_stl(path), i == 0))
    allv = np.vstack([p[1] for p in parts]) if parts else np.zeros((1, 3))
    lo, hi = allv.min(0), allv.max(0)
    ctr, half = (lo + hi) / 2, float((hi - lo).max() / 2) or 1.0
    qs = half / 32000.0

    js = []
    for label, V, on in parts:
        q = np.round((V - ctr) / qs).astype(np.int16)
        js.append(dict(label=label, on=on, pos=base64.b64encode(q.tobytes()).decode()))
        print("%-32s %8s tri  %.2f MB(b64)" % (label, format(len(V) // 3, ","), len(js[-1]["pos"]) / 1e6))

    tpl = open(tpl_path, encoding="utf-8").read()
    font = os.path.join(os.path.dirname(os.path.abspath(__file__)), "PretendardVariable.woff2")
    if not os.path.isfile(font):
        raise SystemExit("글꼴 파일이 없습니다: %s (Pretendard Variable woff2, SIL OFL)" % font)
    tools = os.path.dirname(os.path.abspath(__file__))
    version = open(os.path.join(tools, "VERSION"), encoding="utf-8").read().strip()   # 버전은 이 파일 한 곳
    rep = {"__PARTS__": json.dumps(js, ensure_ascii=False, separators=(",", ":")),
           "__CTR__": "[%.6f,%.6f,%.6f]" % tuple(ctr), "__QS__": "%.10g" % qs,
           "__FONT__": base64.b64encode(open(font, "rb").read()).decode(),
           "__VERSION__": version}
    for k, v in rep.items():
        assert k in tpl, k
        tpl = tpl.replace(k, v)
    out_dir = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(out_dir, exist_ok=True)
    open(out_path, "w", encoding="utf-8").write(tpl)
    print("wrote", out_path, "%.2f MB  (v%s)" % (os.path.getsize(out_path) / 1e6, version))

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
