# -*- coding: utf-8 -*-
"""Fluent 메시 → OBJ (경계면만, zone 별 그룹). 뷰어에서 zone 을 각각 켜고 끄고 격자선을 볼 수 있다.

    python fluent2obj.py <입력> [출력.obj] [--all]

입력:
  .msh / .cas            Fluent 레거시 텍스트 (ASCII 섹션 + 바이너리 섹션 2010/3010/2013/3013 혼용 가능)
  .msh.gz / .cas.gz      위와 같되 gzip
  .msh.h5 / .cas.h5      Fluent CFF (HDF5). 이 PC 에 시험 파일이 없어 문서 구조대로 짰고 실행해 보지 못했다.
                         구조가 다르면 트리를 통째로 찍고 멈춘다 — 그 출력을 그대로 붙여 주면 맞출 수 있다.

기본은 경계면(zone type 이 interior 가 아닌 것)만 쓴다. --all 이면 interior 도 쓴다 (내부 격자면 전부 — 크다).
2D 메시(2 2)는 면이 선분이라 여기서는 다루지 않는다.

출력 OBJ: `o <zone name> [<zone type>]` 그룹마다 f 줄. 사각형은 사각형 그대로(삼각화 안 함).
"""
import argparse, gzip, os, re, sys

# ── 레거시 텍스트 포맷 ──────────────────────────────────────────────────────
INTERIOR_TYPES = {2}                     # bc type 2 = interior
BC_NAMES = {2: "interior", 3: "wall", 4: "pressure-inlet", 5: "pressure-outlet", 7: "symmetry",
            8: "periodic-shadow", 9: "pressure-far-field", 10: "velocity-inlet", 12: "periodic",
            14: "fan/porous-jump/radiator", 20: "mass-flow-inlet", 24: "interface", 31: "parent",
            36: "outflow", 37: "axis"}


def log(*a):
    print(*a, flush=True)


class Reader:
    """섹션 헤더는 텍스트로, 바이너리 페이로드는 바이트로 읽는 커서."""
    def __init__(self, data):
        self.d = data; self.i = 0

    def skip_ws(self):
        while self.i < len(self.d) and self.d[self.i] in b" \t\r\n":
            self.i += 1

    def read_header(self):
        """'(' index '(' … ')' 까지 읽어 (index, [필드 문자열]) 를 돌려준다. 문자열 필드는 따옴표 유지."""
        self.skip_ws()
        if self.i >= len(self.d) or self.d[self.i] != 0x28:
            return None
        m = re.compile(rb"\(\s*(\d+)\s*").match(self.d, self.i)
        if not m:
            return None
        idx = int(m.group(1)); self.i = m.end()
        self.skip_ws()
        if self.i < len(self.d) and self.d[self.i] == 0x22:            # (0 "comment")
            j = self.d.index(b'"', self.i + 1); s = self.d[self.i + 1:j]; self.i = j + 1
            self.skip_ws(); self.expect(b")"); return idx, [s.decode("latin1")], None
        if self.i < len(self.d) and self.d[self.i] == 0x28:            # (idx (a b c ...)
            j = self.d.index(b")", self.i); fields = self.d[self.i + 1:j].split(); self.i = j + 1
            return idx, [f.decode("latin1") for f in fields], True
        j = self.d.index(b")", self.i); fields = self.d[self.i:j].split(); self.i = j + 1   # (2 3)
        return idx, [f.decode("latin1") for f in fields], False

    def expect(self, tok):
        self.skip_ws()
        if self.d[self.i:self.i + len(tok)] != tok:
            raise ValueError("offset %d: '%s' 이 와야 하는데 '%s'" % (self.i, tok.decode(), self.d[self.i:self.i + 20]))
        self.i += len(tok)

    def at_open(self):
        self.skip_ws(); return self.i < len(self.d) and self.d[self.i] == 0x28

    def text_body(self):
        """'(' … ')' 텍스트 본문 (중첩 없음) 을 잘라 준다."""
        self.expect(b"("); j = self.d.index(b")", self.i); body = self.d[self.i:j]; self.i = j + 1
        return body

    def binary_body(self, nbytes, idx):
        self.expect(b"("); body = self.d[self.i:self.i + nbytes]; self.i += nbytes
        end = re.compile(rb"\s*\)\s*End of Binary Section\s+%d\)" % idx).match(self.d, self.i)
        if not end:
            raise ValueError("바이너리 섹션 %d 의 끝 표식이 없다 (offset %d). 자료형/크기 가정이 틀렸다: %r"
                             % (idx, self.i, self.d[self.i:self.i + 40]))
        self.i = end.end(); return body

    def close_section(self):
        self.skip_ws()
        if self.i < len(self.d) and self.d[self.i] == 0x29:
            self.i += 1


def read_legacy(path):
    import numpy as np
    raw = open(path, "rb").read()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    r = Reader(raw)
    dim = None; nodes = None; faces = {}; zones = {}; node_zones = []; cells_n = 0
    while True:
        h = r.read_header()
        if h is None:
            if r.i >= len(raw) - 1:
                break
            raise ValueError("offset %d 에서 섹션 헤더를 읽지 못했다: %r" % (r.i, raw[r.i:r.i + 40]))
        idx, f, paren = h
        if idx == 0:
            continue
        if idx == 2:
            dim = int(f[0]); continue
        if idx in (10, 2010, 3010):                                   # 노드
            zid, first, last = int(f[0], 16), int(f[1], 16), int(f[2], 16)
            if zid == 0:
                nodes = np.full((last, 3), np.nan); r.close_section(); continue
            nd = int(f[4]) if len(f) > 4 else dim
            n = last - first + 1
            if idx == 10:
                body = r.text_body(); arr = np.array(body.split(), dtype=float).reshape(n, nd)
            else:
                dt = "<f4" if idx == 2010 else "<f8"
                arr = np.frombuffer(r.binary_body(n * nd * np.dtype(dt).itemsize, idx), dtype=dt).reshape(n, nd)
            if nodes is None:
                nodes = np.full((last, 3), np.nan)
            nodes[first - 1:last, :nd] = arr
            if nd < 3:
                nodes[first - 1:last, nd:] = 0
            r.close_section(); continue
        if idx in (12, 2012, 3012):                                   # 셀 — 개수만
            if int(f[0], 16) != 0:
                cells_n += int(f[2], 16) - int(f[1], 16) + 1
                if paren and r.at_open():
                    if idx == 12: r.text_body()
                    else: raise ValueError("바이너리 셀 섹션은 건너뛰지 못한다 (idx %d)" % idx)
            r.close_section(); continue
        if idx in (13, 2013, 3013):                                   # 면
            zid, first, last = int(f[0], 16), int(f[1], 16), int(f[2], 16)
            if zid == 0:
                r.close_section(); continue
            bc, ftype = int(f[3], 16), int(f[4], 16)
            n = last - first + 1
            if idx == 13:
                toks = r.text_body().split()
                polys = []; k = 0
                for _ in range(n):
                    nn = ftype if ftype else int(toks[k], 16)
                    if not ftype: k += 1
                    polys.append([int(t, 16) for t in toks[k:k + nn]]); k += nn + 2   # 뒤의 c0 c1 은 버린다
            else:
                if ftype == 0:
                    raise ValueError("바이너리 혼합형(face-type 0) 면 섹션은 길이를 미리 알 수 없어 다루지 않는다 — Fluent 에서 ASCII 로 저장한다")
                ints = np.frombuffer(r.binary_body(n * (ftype + 2) * 4, idx), dtype="<i4").reshape(n, ftype + 2)
                polys = ints[:, :ftype].tolist()
            faces[zid] = dict(bc=bc, polys=polys)
            r.close_section(); continue
        if idx in (39, 45):                                           # zone 이름
            zid = int(f[0]); zones[zid] = dict(type=f[1], name=f[2] if len(f) > 2 else f[1])
            if paren and r.at_open(): r.text_body()
            r.close_section(); continue
        # 그 밖의 섹션 (경계조건 값, 코텍스 등) — 본문이 있으면 괄호 깊이로 건너뛴다
        if paren:
            depth = 0
            while r.i < len(raw):
                c = raw[r.i]; r.i += 1
                if c == 0x28: depth += 1
                elif c == 0x29:
                    if depth == 0: break
                    depth -= 1
    if dim != 3:
        raise ValueError("차원 %s — 3D 메시만 다룬다 (2D 는 면이 선분이다)" % dim)
    if nodes is None or not faces:
        raise ValueError("노드 %s / 면 섹션 %d 개 — 메시가 아니거나 섹션 인덱스가 낯설다" % (None if nodes is None else nodes.shape, len(faces)))
    return nodes, faces, zones, cells_n


# ── CFF (HDF5) ──────────────────────────────────────────────────────────────
def read_cff(path):
    import h5py, numpy as np
    f = h5py.File(path, "r")
    tree = []
    f.visititems(lambda n, o: tree.append("%s %s" % (n, getattr(o, "shape", ""))))
    try:
        m = f["meshes/1"]
        coords = m["nodes/coords/1"][()]
        fn = m["faces/nodes/1"]; nn = fn["nnodes"][()]; nd = fn["nodes"][()]
        zt = m["faces/zoneTopology"]
        ids, lo, hi = zt["id"][()], zt["minId"][()], zt["maxId"][()]
        types = zt["zoneType"][()]
        names = zt["name"][()]
        names = (names.tobytes() if hasattr(names, "tobytes") else bytes(names)).decode("latin1").strip("\x00").split(";")
    except KeyError as e:
        raise ValueError("CFF 구조가 예상과 다르다 (%s). 파일의 트리:\n  " % e + "\n  ".join(tree[:200]))
    off = np.concatenate([[0], np.cumsum(nn)])
    faces = {}; zones = {}
    for k, zid in enumerate(ids):
        polys = [nd[off[i]:off[i + 1]].tolist() for i in range(lo[k] - 1, hi[k])]
        faces[int(zid)] = dict(bc=int(types[k]), polys=polys)
        zones[int(zid)] = dict(type=BC_NAMES.get(int(types[k]), str(types[k])), name=names[k] if k < len(names) else "zone%d" % zid)
    return coords, faces, zones, None


# ── OBJ 쓰기 ────────────────────────────────────────────────────────────────
def write_obj(out, nodes, faces, zones, include_interior):
    import numpy as np
    used = np.zeros(len(nodes) + 1, dtype=bool)
    sel = []
    for zid, sec in sorted(faces.items()):
        z = zones.get(zid, dict(type=BC_NAMES.get(sec["bc"], "type%d" % sec["bc"]), name="zone%d" % zid))
        interior = sec["bc"] in INTERIOR_TYPES or z["type"] == "interior"
        if interior and not include_interior:
            continue
        for p in sec["polys"]:
            used[p] = True
        sel.append((zid, z, sec))
    if not sel:
        raise ValueError("쓸 zone 이 없다. 있는 zone: " + ", ".join("%s[%s]" % (z["name"], z["type"]) for z in zones.values()))
    remap = np.cumsum(used) * used                       # 쓰인 노드만 1.. 로 번호를 다시 매긴다
    with open(out, "w", encoding="utf-8") as fh:
        fh.write("# Fluent boundary mesh, zone groups. Units as in the mesh file.\n")
        for i in np.nonzero(used)[0]:
            x, y, z = nodes[i - 1]
            fh.write("v %.9g %.9g %.9g\n" % (x, y, z))
        for zid, z, sec in sel:
            fh.write("o %s [%s]\n" % (z["name"].replace(" ", "_"), z["type"]))
            for p in sec["polys"]:
                fh.write("f " + " ".join(str(remap[i]) for i in p) + "\n")
    return sel, int(used.sum())


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input"); ap.add_argument("output", nargs="?")
    ap.add_argument("--all", action="store_true", help="interior 면도 포함")
    a = ap.parse_args()
    src = os.path.abspath(a.input)
    if not os.path.isfile(src):
        log("입력 파일 없음:", src); return 2
    low = src.lower()
    out = os.path.abspath(a.output) if a.output else re.sub(r"\.(msh|cas)(\.gz|\.h5)?$", "", src, flags=re.I) + "_boundary.obj"
    try:
        nodes, faces, zones, ncell = read_cff(src) if low.endswith(".h5") else read_legacy(src)
        sel, nused = write_obj(out, nodes, faces, zones, a.all)
    except ValueError as e:
        log("변환 실패:", e); return 3
    log("노드 %s개 중 %s개 사용, 셀 %s" % (format(len(nodes), ","), format(nused, ","), format(ncell, ",") if ncell else "?"))
    for zid, z, sec in sel:
        log("  zone %-3d %-22s [%s]  면 %s" % (zid, z["name"], z["type"], format(len(sec["polys"]), ",")))
    skipped = [(zid, zones.get(zid, {}).get("name", "?")) for zid, sec in faces.items() if sec["bc"] in INTERIOR_TYPES and not a.all]
    if skipped:
        log("  건너뜀 (interior, --all 로 포함):", ", ".join("%d %s" % s for s in skipped))
    log("저장:", out, "%.1f MB" % (os.path.getsize(out) / 1e6))
    return 0


if __name__ == "__main__":
    sys.exit(main())
