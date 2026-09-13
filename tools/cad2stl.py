# -*- coding: utf-8 -*-
"""CAD → STL 변환기 (OpenCASCADE 파이썬 바인딩 OCP 사용, SALOME 불필요).

    python cad2stl.py <입력> [출력폴더] [--defl 0.001] [--ang 0.2]

입력:
  .hdf                SALOME 스터디 — GEOM 컴포넌트의 형상 전부 (BinOcaf 를 직접 읽는다)
  .step .stp          STEP
  .iges .igs          IGES
  .brep               OpenCASCADE BREP
  .stl                STL (재테셀레이션 없이 그대로 통과)

출력: <입력이름>__<형상이름>.stl (바이너리). 형상이 여럿이면 여러 개.

--defl  선형 편차, 바운딩박스 대각선 대비 상대값 (작을수록 촘촘). 기본 0.001
--ang   각도 편차 [rad]. 기본 0.2

필요: pip install cadquery-ocp h5py numpy
"""
import argparse, io, os, re, sys, tempfile

from OCP.BRep import BRep_Tool
from OCP.BRepMesh import BRepMesh_IncrementalMesh
from OCP.BRepTools import BRepTools
from OCP.BRep import BRep_Builder
from OCP.StlAPI import StlAPI_Writer
from OCP.TopAbs import TopAbs_ShapeEnum
from OCP.TopoDS import TopoDS_Shape
from OCP.IFSelect import IFSelect_ReturnStatus

_KEEP = []   # OCAF 문서/앱 핸들이 먼저 해제되면 형상 접근 때 죽는다 — 프로세스 끝까지 붙잡아 둔다

SOLIDISH = {TopAbs_ShapeEnum.TopAbs_COMPOUND, TopAbs_ShapeEnum.TopAbs_COMPSOLID,
            TopAbs_ShapeEnum.TopAbs_SOLID, TopAbs_ShapeEnum.TopAbs_SHELL,
            TopAbs_ShapeEnum.TopAbs_FACE}


def log(*a):
    print(*a, flush=True)


def safe(s):
    return re.sub(r"[^\w.-]+", "_", s) or "shape"


# ── 입력별 로더: [(이름, TopoDS_Shape)] ─────────────────────────────────────
def load_step(path):
    from OCP.STEPControl import STEPControl_Reader
    r = STEPControl_Reader()
    if r.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError("STEP 읽기 실패")
    r.TransferRoots()
    return [("step", r.OneShape())]


def load_iges(path):
    from OCP.IGESControl import IGESControl_Reader
    r = IGESControl_Reader()
    if r.ReadFile(path) != IFSelect_ReturnStatus.IFSelect_RetDone:
        raise RuntimeError("IGES 읽기 실패")
    r.TransferRoots()
    return [("iges", r.OneShape())]


def load_brep(path):
    s = TopoDS_Shape()
    if not BRepTools.Read_s(s, path, BRep_Builder()):
        raise RuntimeError("BREP 읽기 실패")
    return [("brep", s)]


def load_salome_hdf(path):
    """SALOME 스터디: FILE_STREAM 데이터셋 안의 _GEOM.cbf(BinOcaf) 를 꺼내 OCAF 로 연다.

    형상은 라벨 0:1:N:1:1:2 의 TNaming_NamedShape 에, 이름은 0:1:N 의 TDataStd_Name 에 있다.
    """
    import h5py
    from OCP.TDocStd import TDocStd_Application, TDocStd_Document
    from OCP.BinDrivers import BinDrivers, BinDrivers_DocumentRetrievalDriver
    from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
    from OCP.TDF import TDF_ChildIterator, TDF_AttributeIterator
    from OCP.PCDM import PCDM_ReaderStatus

    with h5py.File(path, "r") as f:
        streams = [(k, f["DATACOMPONENT"][k]) for k in f["DATACOMPONENT"]
                   if "FILE_STREAM" in f["DATACOMPONENT"][k]]
        if not streams:
            raise RuntimeError("DATACOMPONENT/*/FILE_STREAM 이 없습니다 (GEOM 컴포넌트 없음)")
        buf = streams[0][1]["FILE_STREAM"][()].tobytes()
    i = buf.find(b"BINFILE")
    if i < 0:
        raise RuntimeError("BinOcaf 헤더(BINFILE) 를 찾지 못했습니다")
    tmp = os.path.join(tempfile.gettempdir(), "cad2stl_geom.cbf")
    with open(tmp, "wb") as fh:
        fh.write(buf[i:])

    app = TDocStd_Application()
    BinDrivers.DefineFormat_s(app)
    doc = TDocStd_Document(TCollection_ExtendedString("BinOcaf"))
    drv = BinDrivers_DocumentRetrievalDriver()
    drv.Read(TCollection_ExtendedString(tmp), doc, app)
    if drv.GetStatus() != PCDM_ReaderStatus.PCDM_RS_OK:
        raise RuntimeError("OCAF 읽기 실패: %s" % drv.GetStatus())
    _KEEP.extend([app, doc, drv])

    def attrs(lab):
        out = {}
        it = TDF_AttributeIterator(lab)
        while it.More():
            a = it.Value(); out[a.DynamicType().Name()] = a; it.Next()
        return out

    shapes = []
    top = TDF_ChildIterator(doc.Main(), False)        # 0:1:N — 오브젝트 하나씩
    while top.More():
        obj = top.Value(); top.Next()
        a = attrs(obj)
        name = (TCollection_AsciiString(a["TDataStd_Name"].Get()).ToCString()
                if "TDataStd_Name" in a else "0:1:%d" % obj.Tag())
        # 그 아래 어디든 비어있지 않은 NamedShape 하나 (결과 형상)
        stack = [obj]; shape = None
        while stack and shape is None:
            lab = stack.pop()
            ns = attrs(lab).get("TNaming_NamedShape")
            if ns is not None and not ns.IsEmpty():
                shape = ns.Get()
            ch = TDF_ChildIterator(lab, False)
            while ch.More():
                stack.append(ch.Value()); ch.Next()
        if shape is not None:
            shapes.append((name, shape))
    return shapes


def load_stl_passthrough(path):
    return None      # 변환 없이 복사


LOADERS = {".step": load_step, ".stp": load_step, ".iges": load_iges, ".igs": load_iges,
           ".brep": load_brep, ".hdf": load_salome_hdf, ".stl": load_stl_passthrough}


# ── 테셀레이션 + 저장 ───────────────────────────────────────────────────────
def write_stl(shape, out, defl_rel, ang):
    BRepMesh_IncrementalMesh(shape, defl_rel, True, ang, True)
    w = StlAPI_Writer(); w.ASCIIMode = False
    if not w.Write(shape, out):
        raise RuntimeError("STL 쓰기 실패: " + out)


def count_tris(stl):
    with open(stl, "rb") as fh:
        fh.seek(80); return int.from_bytes(fh.read(4), "little")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input"); ap.add_argument("outdir", nargs="?")
    ap.add_argument("--defl", type=float, default=0.001); ap.add_argument("--ang", type=float, default=0.2)
    a = ap.parse_args()
    src = os.path.abspath(a.input)
    if not os.path.isfile(src):
        log("입력 파일 없음:", src); return 2
    outdir = os.path.abspath(a.outdir or os.path.dirname(src))
    os.makedirs(outdir, exist_ok=True)
    stem, ext = os.path.splitext(os.path.basename(src)); ext = ext.lower()
    loader = LOADERS.get(ext)
    if loader is None:
        log("지원하지 않는 확장자:", ext, "—", " ".join(sorted(LOADERS))); return 4

    if ext == ".stl":
        import shutil
        dst = os.path.join(outdir, safe(stem) + ".stl"); shutil.copyfile(src, dst)
        log("복사:", dst); return 0

    shapes = [(n, s) for n, s in loader(src) if s.ShapeType() in SOLIDISH]
    if not shapes:
        log("면이 있는 형상이 없습니다"); return 3
    for name, shape in shapes:
        out = os.path.join(outdir, "%s__%s.stl" % (safe(stem), safe(name)))
        write_stl(shape, out, a.defl, a.ang)
        log("저장: %s  (%s 삼각형, %d KB)" % (out, format(count_tris(out), ","), os.path.getsize(out) // 1024))
    return 0


if __name__ == "__main__":
    sys.exit(main())
