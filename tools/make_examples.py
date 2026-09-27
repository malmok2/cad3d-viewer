# -*- coding: utf-8 -*-
"""예제 형상 생성기 (그룹 이름은 영문 식별자 — 한/영 표시 이름과 초기 색은 examples/examples.json) — 뷰어에 굽는 예제 중 CAD 파일이 아닌 것을 파이썬으로 만든다 (단위 mm, 세로축 = y).

    python tools/make_examples.py            # examples/ 에 OBJ 세 개를 쓴다

  fuel_assembly_17x17.obj    17×17 핵연료 집합체 (높이 축소) — 연료봉 · 안내관/계측관 · 지지격자 · 상/하단 고정체
  helical_sg.obj             나선형 증기발생기 (SMR 일체형 원자로 개념) — 라이저 · 전열관 6열 · 관 지지대 · 슈라우드
  subchannel_3x3_mesh.obj    3×3 봉다발 부수로 유동 영역의 경계 메시 — Fluent zone 형식 (inlet/outlet/wall), O-grid 사각형

치수는 형상 확인·그림용 예시다. 17×17 격자 배치(안내관 24 + 계측관 1 위치, 피치 12.6, 봉 지름 9.5, 안내관 12.24)는
일반적인 PWR 17×17 값을 따랐고, 높이·격자 수·증기발생기 치수는 보기 좋게 줄였다 — 특정 노형의 설계값이 아니다.
면은 모두 바깥(유동 영역 메시는 유체 밖)을 향하게 감는다 — 투명 표시에서 뒷면·앞면 순서가 맞게.
"""
import math, os
import numpy as np

OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


class Mesh:
    """정점 + 다각형 면. 면 방향은 추가할 때 '바깥' 기준점/방향으로 맞춘다."""
    def __init__(self):
        self.V, self.F = [], []

    def add(self, verts, faces, outward):
        """outward(centroid) → 그 면이 향해야 할 방향 벡터."""
        base = len(self.V); self.V.extend(verts)
        P = np.asarray(verts, float)
        for f in faces:
            q = P[list(f)]
            n = np.zeros(3)
            for i in range(len(f)):                          # Newell 법선
                a, b = q[i], q[(i + 1) % len(f)]
                n += [(a[1] - b[1]) * (a[2] + b[2]), (a[2] - b[2]) * (a[0] + b[0]), (a[0] - b[0]) * (a[1] + b[1])]
            if np.dot(n, outward(q.mean(0))) < 0: f = f[::-1]
            self.F.append([base + i for i in f])

    def ntri(self):
        return sum(len(f) - 2 for f in self.F)


def radial(cx, cz, sign=1.0):          # 축(cx, cz)에서 멀어지는 방향 (sign=-1 이면 축 쪽)
    return lambda c: sign * np.array([c[0] - cx, 0.0, c[2] - cz])


def cylinder(m, cx, cz, r, y0, y1, seg, caps=True):
    th = [2 * math.pi * i / seg for i in range(seg)]
    V = [(cx + r * math.cos(t), y, cz + r * math.sin(t)) for y in (y0, y1) for t in th]
    m.add(V, [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)], radial(cx, cz))
    if caps:
        m.add(V[:seg], [tuple(range(seg))], lambda c: np.array([0.0, -1.0, 0.0]))
        m.add(V[seg:], [tuple(range(seg))], lambda c: np.array([0.0, 1.0, 0.0]))


def shell(m, r0, r1, y0, y1, seg):
    """두께 있는 원통 껍질 (안·바깥 원통 + 위·아래 고리)."""
    th = [2 * math.pi * i / seg for i in range(seg)]
    ring = lambda r, y: [(r * math.cos(t), y, r * math.sin(t)) for t in th]
    for r, s in ((r1, 1.0), (r0, -1.0)):
        V = ring(r, y0) + ring(r, y1)
        m.add(V, [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)], radial(0, 0, s))
    for y, s in ((y0, -1.0), (y1, 1.0)):
        V = ring(r0, y) + ring(r1, y)
        m.add(V, [(i, (i + 1) % seg, seg + (i + 1) % seg, seg + i) for i in range(seg)], lambda c, s=s: np.array([0.0, s, 0.0]))


def box(m, lo, hi):
    (x0, y0, z0), (x1, y1, z1) = lo, hi
    V = [(x0, y0, z0), (x1, y0, z0), (x1, y1, z0), (x0, y1, z0), (x0, y0, z1), (x1, y0, z1), (x1, y1, z1), (x0, y1, z1)]
    c = np.array([(x0 + x1) / 2, (y0 + y1) / 2, (z0 + z1) / 2])
    m.add(V, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3)], lambda q: q - c)


def sweep_tube(m, path, r, circ):
    """경로를 따라 원을 쓸어 관을 만든다 (회전 최소 프레임). 양 끝을 막아 닫힌 솔리드로 — 단면 뚜껑이 끝에서도 맞게."""
    P = np.asarray(path, float); n = len(P)
    T = np.gradient(P, axis=0); T /= np.linalg.norm(T, axis=1)[:, None]
    u = np.cross(T[0], [0, 1, 0]); u = u / np.linalg.norm(u) if np.linalg.norm(u) > 1e-6 else np.array([1.0, 0, 0])
    V, U = [], [u]
    for i in range(1, n):                                    # 이중 반사로 프레임을 옮긴다
        v1 = P[i] - P[i - 1]; c1 = v1 @ v1
        rL = U[-1] - (2 / c1) * (v1 @ U[-1]) * v1; tL = T[i - 1] - (2 / c1) * (v1 @ T[i - 1]) * v1
        v2 = T[i] - tL; c2 = v2 @ v2
        U.append(rL - (2 / c2) * (v2 @ rL) * v2 if c2 > 1e-12 else rL)
    for i in range(n):
        w = np.cross(T[i], U[i])
        for k in range(circ):
            a = 2 * math.pi * k / circ
            V.append(tuple(P[i] + r * (math.cos(a) * U[i] + math.sin(a) * w)))
    F = [(i * circ + k, i * circ + (k + 1) % circ, (i + 1) * circ + (k + 1) % circ, (i + 1) * circ + k)
         for i in range(n - 1) for k in range(circ)]
    base = len(m.V)
    # 바깥 = 그 단면 중심에서 멀어지는 쪽
    m.V.extend(V); PV = np.asarray(V)
    for f in F:
        q = PV[list(f)]; ctr = P[f[0] // circ] * 0.5 + P[f[2] // circ] * 0.5
        nrm = np.cross(q[1] - q[0], q[3] - q[0])
        if nrm @ (q.mean(0) - ctr) < 0: f = f[::-1]
        m.F.append([base + i for i in f])
    for i, s in ((0, -1.0), (n - 1, 1.0)):                   # 양 끝 마개: 바깥 = 진행 방향 앞뒤
        f = list(range(i * circ, (i + 1) * circ)); q = PV[f]
        if np.cross(q[1] - q[0], q[2] - q[0]) @ (s * T[i]) < 0: f = f[::-1]
        m.F.append([base + k for k in f])


def write_obj(path, groups, header):
    lines = ["# " + h for h in header]; off = 0
    for name, m in groups:
        lines.append("o " + name)
        lines += ["v %.4f %.4f %.4f" % v for v in m.V]
        lines += ["f " + " ".join(str(off + i + 1) for i in f) for f in m.F]
        off += len(m.V)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("\n".join(lines) + "\n")
    print("%-28s %s" % (os.path.basename(path), " · ".join("%s %s" % (n.split(" [")[0], format(m.ntri(), ",")) for n, m in groups)),
          "tri, %.2f MB" % (os.path.getsize(path) / 1e6))


# ── 1. 17×17 핵연료 집합체 ────────────────────────────────────────────────────
def fuel_assembly():
    P, N, DR, DG = 12.6, 17, 9.5, 12.24
    GT = {(2, 5), (2, 8), (2, 11), (3, 3), (3, 13), (5, 2), (5, 5), (5, 8), (5, 11), (5, 14), (8, 2), (8, 5), (8, 8),
          (8, 11), (8, 14), (11, 2), (11, 5), (11, 8), (11, 11), (11, 14), (13, 3), (13, 13), (14, 5), (14, 8), (14, 11)}
    X = lambda i: (i - (N - 1) / 2) * P
    H = N * P / 2                                           # 107.1
    rods, tubes, grids, nozz = Mesh(), Mesh(), Mesh(), Mesh()
    for r in range(N):
        for c in range(N):
            if (r, c) in GT: cylinder(tubes, X(c), X(r), DG / 2, 50, 1010, 20)
            else:            cylinder(rods, X(c), X(r), DR / 2, 62, 998, 20)
    for yg in (170, 385, 600, 815):                         # 지지격자: 끈판을 우물 정(井)자로
        for k in range(N + 1):
            t = 0.6 if k in (0, N) else 0.25
            x = (k - N / 2) * P
            box(grids, (x - t, yg, -H), (x + t, yg + 40, H))
            box(grids, (-H, yg, x - t), (H, yg + 40, x + t))
    box(nozz, (-H, 28, -H), (H, 50, H))                     # 하단 고정체: 판 + 다리 넷
    for sx in (-1, 1):
        for sz in (-1, 1):
            box(nozz, (min(sx * H, sx * (H - 26)), 0, min(sz * H, sz * (H - 26))), (max(sx * H, sx * (H - 26)), 28, max(sz * H, sz * (H - 26))))
    box(nozz, (-H, 1010, -H), (H, 1022, H))                 # 상단 고정체: 판 + 속 빈 사각 틀
    for a, b in (((-H, -H), (H, -H + 10)), ((-H, H - 10), (H, H)), ((-H, -H + 10), (-H + 10, H - 10)), ((H - 10, -H + 10), (H, H - 10))):
        box(nozz, (a[0], 1022, a[1]), (b[0], 1080, b[1]))
    write_obj(os.path.join(OUT, "fuel_assembly_17x17.obj"),
              [("fuel_rods", rods), ("guide_tubes", tubes), ("spacer_grids", grids), ("nozzles", nozz)],
              ["17x17 fuel assembly (shortened), mm, y-up. Generated by tools/make_examples.py",
               "pitch 12.6, rod OD 9.5, guide/instrument tube OD 12.24 (24 + 1). Heights are illustrative."])


# ── 2. 나선형 증기발생기 ──────────────────────────────────────────────────────
def helical_sg():
    riser, shroud, sup = Mesh(), Mesh(), Mesh()
    shell(riser, 360, 380, 0, 1300, 96)
    shell(shroud, 800, 820, 0, 1300, 96)
    cols = []
    y0, y1, turns, steps = 200, 1100, 6, 64
    for c in range(6):
        R, d = 440 + 60 * c, (1 if c % 2 == 0 else -1)       # 열마다 감김 방향을 바꾼다
        n = turns * steps
        path = [(R * math.cos(d * 2 * math.pi * turns * i / n + c * 0.7), y0 + (y1 - y0) * i / n,
                 R * math.sin(d * 2 * math.pi * turns * i / n + c * 0.7)) for i in range(n + 1)]
        m = Mesh(); sweep_tube(m, path, 14, 10); cols.append(("tubes_col%d" % (c + 1), m))
    for k in range(8):                                      # 관 지지대: 방사 방향 판 8개
        a = 2 * math.pi * k / 8 + math.pi / 8
        ca, sa = math.cos(a), math.sin(a)
        corners = [(r * ca - t * sa, r * sa + t * ca) for r, t in ((400, -6), (770, -6), (770, 6), (400, 6))]
        V = [(x, y, z) for y in (180, 1120) for x, z in corners]
        c0 = np.array([585 * ca, 650, 585 * sa])
        sup.add(V, [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (2, 3, 7, 6), (1, 2, 6, 5), (0, 4, 7, 3)], lambda q, c0=c0: q - c0)
    write_obj(os.path.join(OUT, "helical_sg.obj"), [("riser", riser)] + cols + [("tube_supports", sup), ("shroud", shroud)],
              ["Helical-coil steam generator concept (integral SMR), mm, y-up. Generated by tools/make_examples.py",
               "6 tube columns, alternating winding, 6 turns each. Dimensions are illustrative."])


# ── 3. 3×3 봉다발 부수로 유동 영역 경계 메시 (Fluent zone 형식) ────────────────────
def subchannel_mesh():
    P, D, NC, NS, K, L, NY = 12.6, 9.5, 3, 6, 5, 100.0, 25   # 한 변 NS 칸, 반지름 방향 K 칸, 축 방향 NY 칸
    h = P / 2
    def square_pts(cx, cz):                                 # 셀 경계 4NS 점 (반시계, (+h,-h) 에서 시작)
        pts = []
        for s, (a, b) in enumerate((((h, -h), (h, h)), ((h, h), (-h, h)), ((-h, h), (-h, -h)), ((-h, -h), (h, -h)))):
            for j in range(NS):
                t = j / NS; pts.append((cx + a[0] + (b[0] - a[0]) * t, cz + a[1] + (b[1] - a[1]) * t))
        return pts
    centers = [((i - 1) * P, (j - 1) * P) for j in range(NC) for i in range(NC)]
    inlet, outlet, rods, duct = Mesh(), Mesh(), Mesh(), Mesh()
    ys = [L * k / NY for k in range(NY + 1)]
    for cx, cz in centers:
        sq = square_pts(cx, cz); M = len(sq)
        circ = []
        for x, z in sq:
            a = math.atan2(z - cz, x - cx); circ.append((cx + D / 2 * math.cos(a), cz + D / 2 * math.sin(a)))
        for y, face, nrm in ((0.0, inlet, -1.0), (L, outlet, 1.0)):   # O-grid: 원 → 사각을 K 칸으로
            V = [(circ[j][0] + (sq[j][0] - circ[j][0]) * k / K, y, circ[j][1] + (sq[j][1] - circ[j][1]) * k / K)
                 for k in range(K + 1) for j in range(M)]
            face.add(V, [(k * M + j, k * M + (j + 1) % M, (k + 1) * M + (j + 1) % M, (k + 1) * M + j)
                         for k in range(K) for j in range(M)], lambda c, s=nrm: np.array([0.0, s, 0.0]))
        V = [(x, y, z) for y in ys for x, z in circ]           # 봉 벽: 유체 밖 = 봉 축 쪽
        rods.add(V, [(i * M + j, i * M + (j + 1) % M, (i + 1) * M + (j + 1) % M, (i + 1) * M + j)
                     for i in range(NY) for j in range(M)], radial(cx, cz, -1.0))
    H = NC * P / 2; n = NC * NS                              # 덕트 벽: 바깥 네 면
    for (a, b), out in ((((H, -H), (H, H)), (1, 0)), (((H, H), (-H, H)), (0, 1)), (((-H, H), (-H, -H)), (-1, 0)), (((-H, -H), (H, -H)), (0, -1))):
        pts = [(a[0] + (b[0] - a[0]) * j / n, a[1] + (b[1] - a[1]) * j / n) for j in range(n + 1)]
        V = [(x, y, z) for y in ys for x, z in pts]
        duct.add(V, [(i * (n + 1) + j, i * (n + 1) + j + 1, (i + 1) * (n + 1) + j + 1, (i + 1) * (n + 1) + j)
                     for i in range(NY) for j in range(n)], lambda c, o=out: np.array([o[0], 0.0, o[1]], float))
    write_obj(os.path.join(OUT, "subchannel_3x3_mesh.obj"),
              [("inlet [velocity-inlet]", inlet), ("outlet [pressure-outlet]", outlet),
               ("wall_rods [wall]", rods), ("wall_duct [wall]", duct)],
              ["3x3 rod-bundle subchannel fluid domain, boundary faces only, Fluent zone naming (as tools/fluent2obj.py writes).",
               "pitch 12.6, rod OD 9.5, length 100 mm, O-grid quads (24 around x 5 radial per cell, 25 axial). mm, y-up."])


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    fuel_assembly(); helical_sg(); subchannel_mesh()
