"""
50 rounds text-preservation test
- Horizontal: real PDFs from test_files/sample-files-main
- Vertical:   synthetic PDFs with rotate=90 insert_htmlbox columns
Loss criterion: any non-target block text missing after edit -> LOSS
"""
import os, sys, time, random, logging, re, shutil
from dataclasses import dataclass, field
from typing import Optional

logging.disable(logging.CRITICAL)
sys.path.insert(0, os.path.dirname(__file__))

import fitz
from model.pdf_model import PDFModel
from model.text_block import TextBlock

# ?? constants ??????????????????????????????????????????????????????????????????
SAMPLE_DIR   = os.path.join(os.path.dirname(__file__), "test_files", "sample-files-main")
ROUNDS_HORIZ = 50
ROUNDS_VERT  = 50
KNOWN_PW = {
    "libreoffice-writer-password.pdf": "permissionpassword",
    "encrypted.pdf": "kanbanery",
}
WRAP_H = [
    "Edited first line\nEdited second line\nEdited third line",
    "This replacement text is longer\nacross multiple wrapped lines",
    "First edited line\nSecond edited line\nThird edited line",
    "Lorem ipsum dolor sit\nconsectetur adipiscing\nsed do eiusmod tempor",
    "Alpha beta gamma delta\nepsilon zeta eta theta\niota kappa lambda",
    "Line one of new content\nLine two of new content\nLine three",
    "New paragraph one\nNew paragraph two\nNew paragraph three",
]
WRAP_V = [
    "?A\n?B\n?C",
    "???\n???\n???",
    "???\n???\n???",
]


# ?? data classes ???????????????????????????????????????????????????????????????
@dataclass
class Issue:
    round_no:    int
    kind:        str
    pdf_path:    str
    page_num:    int
    edited_text: str
    new_text:    str
    lost_text:   str
    error_msg:   str = ""

@dataclass
class RoundResult:
    round_no:    int
    kind:        str
    pdf_path:    str
    page_num:    int
    status:      str   # OK | LOSS | SKIP | ERROR
    duration_ms: float = 0.0
    issues:      list  = field(default_factory=list)


# ?? helpers ????????????????????????????????????????????????????????????????????
_RE_WS = re.compile(r'\s+')
_LIG   = {'?':'fi','?':'fl','?':'ff','?':'ffi','?':'ffl',
          '\ufb06':'st','\u2019':"'",' \u2018':"'",
          '\u201c':'"','\u201d':'"','?':'-','?':'-'}

def _norm(t: str) -> str:
    for k, v in _LIG.items():
        t = t.replace(k, v)
    return _RE_WS.sub('', t).lower()

def _safe_text(page: fitz.Page) -> str:
    try:
        return page.get_text("text")
    except Exception:
        return ""

def _all_pdfs() -> list:
    paths = []
    for root, _, files in os.walk(SAMPLE_DIR):
        for f in files:
            if f.lower().endswith(".pdf"):
                paths.append(os.path.join(root, f))
    return sorted(paths)

def _open(path: str) -> Optional[PDFModel]:
    m = PDFModel()
    try:
        m.open_pdf(path, password=KNOWN_PW.get(os.path.basename(path)))
        return m
    except Exception:
        try: m.close()
        except: pass
        return None

def _safe_blocks(model: PDFModel, page_idx: int) -> list:
    try:
        return model.block_manager.get_blocks(page_idx)
    except Exception:
        return []

def _pre_snap(model: PDFModel, page_idx: int, target_id: str) -> list:
    blocks = _safe_blocks(model, page_idx)
    result = []
    for b in blocks:
        if b.block_id == target_id:
            continue
        n = _norm(b.text)
        if len(n) > 3:
            result.append(n)
    return result

def _check_loss(model: PDFModel, page_idx: int, pre: list) -> list:
    try:
        raw = _norm(_safe_text(model.doc[page_idx]))
        return [n for n in pre if n not in raw]
    except Exception:
        return []

def _pick_horiz(model: PDFModel):
    """Return (page_idx, TextBlock) with >=2 non-empty horiz blocks on page."""
    candidates = []
    for pi in range(len(model.doc)):
        try:
            blks = _safe_blocks(model, pi)
            ne = [b for b in blks
                  if b.text.strip() and len(b.text.strip()) > 5
                  and not b.is_vertical]
            if len(ne) < 2:
                continue
            for b in ne:
                candidates.append((pi, b))
        except Exception:
            continue
    if not candidates:
        return None, None
    candidates.sort(key=lambda x: len(x[1].text), reverse=True)
    pool = candidates[:min(10, len(candidates))]
    return random.choice(pool)


# ?? horizontal round ??????????????????????????????????????????????????????????
def horiz_round(rno: int, pdfs: list) -> RoundResult:
    random.shuffle(pdfs)
    model = chosen = pi = tb = None
    for path in pdfs:
        m = _open(path)
        if not m:
            continue
        try:
            cpi, ctb = _pick_horiz(m)
        except Exception:
            m.close(); continue
        if cpi is None:
            m.close(); continue
        model, chosen, pi, tb = m, path, cpi, ctb
        break

    if not model:
        return RoundResult(rno, "HORIZONTAL", "N/A", -1, "SKIP")

    new_text = WRAP_H[(rno - 1) % len(WRAP_H)]
    pre = _pre_snap(model, pi, tb.block_id)

    t0 = time.perf_counter()
    err = ""
    try:
        model.edit_text(
            page_num=pi + 1,
            rect=tb.layout_rect,
            new_text=new_text,
            font="helv",
            size=int(tb.size) if tb.size else 12,
            original_text=tb.text,
        )
    except Exception as e:
        err = str(e)[:200]
    dur = (time.perf_counter() - t0) * 1000

    lost = _check_loss(model, pi, pre)
    model.close()

    issues = []
    if lost:
        for l in lost:
            issues.append(Issue(rno,"HORIZONTAL",chosen,pi+1,
                                tb.text[:60],new_text[:60],l[:80],err))
    if err and not lost:
        return RoundResult(rno,"HORIZONTAL",chosen,pi+1,"ERROR",dur,
                           [Issue(rno,"HORIZONTAL",chosen,pi+1,
                                  tb.text[:60],new_text[:60],"",err)])
    if lost:
        return RoundResult(rno,"HORIZONTAL",chosen,pi+1,"LOSS",dur,issues)
    return RoundResult(rno,"HORIZONTAL",chosen,pi+1,"OK",dur)


# ?? vertical synthetic PDF + round ???????????????????????????????????????????
def _make_vert_pdf(seed: int) -> bytes:
    """3 vertical columns (rotate=90) + 1 horizontal reference block."""
    labels = [
        ["Vertical Block One",   "Column Entry Alpha", "Text Column First"],
        ["Another Vertical Col", "Column Entry Beta",  "Text Column Second"],
        ["Third Column Entry",   "Column Entry Gamma", "Text Column Third"],
    ]
    doc  = fitz.open()
    page = doc.new_page(width=500, height=600)
    css  = "span { font-size: 13pt; white-space: pre-wrap; }"
    for ci in range(3):
        txt  = labels[ci][seed % 3]
        x    = 30 + ci * 80
        rect = fitz.Rect(x, 50, x + 65, 420)
        try:
            page.insert_htmlbox(rect, f"<span>{txt}</span>",
                                css=css, rotate=90)
        except Exception:
            pass
    page.insert_text(fitz.Point(50, 540),
                     "Horizontal reference line at bottom", fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


def vert_round(rno: int, tmp_dir: str) -> RoundResult:
    pdf_bytes = _make_vert_pdf(rno)
    tmp = os.path.join(tmp_dir, f"_vt_{rno}.pdf")
    with open(tmp, "wb") as f:
        f.write(pdf_bytes)

    model = PDFModel()
    try:
        model.open_pdf(tmp)
    except Exception as e:
        try: model.close()
        except: pass
        if os.path.exists(tmp): os.remove(tmp)
        return RoundResult(rno,"VERTICAL",tmp,-1,"ERROR",0,
                           [Issue(rno,"VERTICAL",tmp,-1,"","","",str(e)[:200])])

    pi = 0
    try:
        blks  = _safe_blocks(model, pi)
        verts = [b for b in blks
                 if b.is_vertical and b.text.strip()
                 and len(b.text.strip()) > 3]
        total = [b for b in blks
                 if b.text.strip() and len(b.text.strip()) > 3]
    except Exception:
        model.close()
        if os.path.exists(tmp): os.remove(tmp)
        return RoundResult(rno,"VERTICAL",tmp,-1,"SKIP")

    if not verts or len(total) < 2:
        model.close()
        if os.path.exists(tmp): os.remove(tmp)
        return RoundResult(rno,"VERTICAL",tmp,-1,"SKIP")

    tb       = random.choice(verts)
    new_text = WRAP_V[(rno - 1) % len(WRAP_V)]
    pre      = _pre_snap(model, pi, tb.block_id)

    t0 = time.perf_counter()
    err = ""
    try:
        model.edit_text(
            page_num=pi + 1,
            rect=tb.layout_rect,
            new_text=new_text,
            font="helv",
            size=int(tb.size) if tb.size else 12,
            original_text=tb.text,
            vertical_shift_left=True,
        )
    except Exception as e:
        err = str(e)[:200]
    dur = (time.perf_counter() - t0) * 1000

    lost = _check_loss(model, pi, pre)
    model.close()
    if os.path.exists(tmp): os.remove(tmp)

    issues = []
    if lost:
        for l in lost:
            issues.append(Issue(rno,"VERTICAL","[synthetic]",pi+1,
                                tb.text[:60],new_text[:60],l[:80],err))
    if err and not lost:
        return RoundResult(rno,"VERTICAL","[synthetic]",pi+1,"ERROR",dur,
                           [Issue(rno,"VERTICAL","[synthetic]",pi+1,
                                  tb.text[:60],new_text[:60],"",err)])
    if lost:
        return RoundResult(rno,"VERTICAL","[synthetic]",pi+1,"LOSS",dur,issues)
    return RoundResult(rno,"VERTICAL","[synthetic]",pi+1,"OK",dur)


# ?? main ???????????????????????????????????????????????????????????????????????
def main():
    random.seed(42)
    pdfs = _all_pdfs()
    print(f"Found {len(pdfs)} PDFs in sample-files-main")

    tmp_dir = os.path.join(os.path.dirname(__file__), "_tmp_vert")
    os.makedirs(tmp_dir, exist_ok=True)

    all_res: list[RoundResult] = []

    # ?? horizontal 50 rounds ????????????????????????????
    print(f"\n{'='*64}")
    print(f"?????? {ROUNDS_HORIZ} ?")
    print(f"{'='*64}")
    for r in range(1, ROUNDS_HORIZ + 1):
        res = horiz_round(r, list(pdfs))
        all_res.append(res)
        ic = {"OK":"?","LOSS":"?","SKIP":"?","ERROR":"?"}.get(res.status,"?")
        nm = os.path.basename(res.pdf_path) if res.pdf_path!="N/A" else "N/A"
        print(f"  H{r:02d} [{ic} {res.status:<5}] {nm:<44} "
              f"p{res.page_num:>2} {res.duration_ms:7.1f}ms", flush=True)

    # ?? vertical 50 rounds ??????????????????????????????
    print(f"\n{'='*64}")
    print(f"?????? {ROUNDS_VERT} ?")
    print(f"{'='*64}")
    for r in range(1, ROUNDS_VERT + 1):
        res = vert_round(r, tmp_dir)
        all_res.append(res)
        ic = {"OK":"?","LOSS":"?","SKIP":"?","ERROR":"?"}.get(res.status,"?")
        print(f"  V{r:02d} [{ic} {res.status:<5}] synthetic_vertical_pdf"
              f"                  p{res.page_num:>2} {res.duration_ms:7.1f}ms",
              flush=True)

    try: shutil.rmtree(tmp_dir)
    except: pass

    # ?? stats ??????????????????????????????????????????
    def stats(rs):
        ok = sum(1 for r in rs if r.status=="OK")
        lo = sum(1 for r in rs if r.status=="LOSS")
        er = sum(1 for r in rs if r.status=="ERROR")
        sk = sum(1 for r in rs if r.status=="SKIP")
        ds = [r.duration_ms for r in rs if r.status in ("OK","LOSS","ERROR")]
        av = sum(ds)/len(ds) if ds else 0
        mx = max(ds) if ds else 0
        return ok,lo,er,sk,av,mx

    hr = [r for r in all_res if r.kind=="HORIZONTAL"]
    vr = [r for r in all_res if r.kind=="VERTICAL"]
    h_ok,h_lo,h_er,h_sk,h_av,h_mx = stats(hr)
    v_ok,v_lo,v_er,v_sk,v_av,v_mx = stats(vr)
    total_loss = h_lo + v_lo
    total_err  = h_er + v_er

    print(f"\n{'='*64}")
    print("??????")
    print(f"{'='*64}")
    print(f"  {'':12} {'??':>7} {'??':>7}")
    print(f"  {'OK':12} {h_ok:>7} {v_ok:>7}")
    print(f"  {'LOSS(??)':12} {h_lo:>7} {v_lo:>7}")
    print(f"  {'ERROR(??)':12} {h_er:>7} {v_er:>7}")
    print(f"  {'SKIP':12} {h_sk:>7} {v_sk:>7}")
    print(f"  {'????':12} {h_av:>6.1f}ms {v_av:>6.1f}ms")
    print(f"  {'????':12} {h_mx:>6.1f}ms {v_mx:>6.1f}ms")
    print()
    if total_loss == 0 and total_err == 0:
        print("  ? ??????????????")
    elif total_loss == 0:
        print(f"  ? ? LOSS?ERROR {total_err} ???? issue_report.txt?")
    else:
        print(f"  ? LOSS {total_loss} ???? issue_report.txt?")

    # ?? write report ???????????????????????????????????
    all_iss   = [i for r in all_res for i in r.issues]
    loss_iss  = [i for i in all_iss if i.lost_text]
    error_iss = [i for i in all_iss if not i.lost_text and i.error_msg]

    rpt = os.path.join(os.path.dirname(__file__), "issue_report.txt")
    with open(rpt, "w", encoding="utf-8") as f:
        sep = "=" * 70
        f.write(sep + "\n")
        f.write("?????? ? ??????\n")
        f.write(f"?????{time.strftime('%Y-%m-%d %H:%M:%S')}\n")
        f.write(sep + "\n\n")

        f.write("??????\n")
        f.write(f"  ??????  ?{ROUNDS_HORIZ}\n")
        f.write(f"  ??????  ?{ROUNDS_VERT}\n")
        f.write(f"  ?? PDF ?? ?{SAMPLE_DIR}\n")
        f.write(f"  ?? PDF ?? ?{len(pdfs)}\n\n")

        f.write("??????\n")
        hdr = f"  {'??':<10} {'OK':>5} {'LOSS':>5} {'ERROR':>6} {'SKIP':>5} {'avg_ms':>8} {'max_ms':>8}\n"
        f.write(hdr)
        f.write(f"  {'??':<10} {h_ok:>5} {h_lo:>5} {h_er:>6} {h_sk:>5} {h_av:>8.1f} {h_mx:>8.1f}\n")
        f.write(f"  {'??':<10} {v_ok:>5} {v_lo:>5} {v_er:>6} {v_sk:>5} {v_av:>8.1f} {v_mx:>8.1f}\n")
        f.write(f"  LOSS ??  ?{total_loss} ?\n")
        f.write(f"  ERROR ?? ?{total_err} ?\n\n")

        f.write(sep + "\n")
        if loss_iss:
            f.write(f"?LOSS ???? {len(loss_iss)} ???\n")
            f.write(sep + "\n")
            for idx, iss in enumerate(loss_iss, 1):
                f.write(f"\nLOSS #{idx}\n")
                f.write(f"  ??      : {iss.kind}\n")
                f.write(f"  ??      : {iss.round_no}\n")
                f.write(f"  ??      : {os.path.basename(iss.pdf_path)}\n")
                f.write(f"  ??      : {iss.page_num}\n")
                f.write(f"  ?????: {iss.edited_text!r}\n")
                f.write(f"  ???    : {iss.new_text!r}\n")
                f.write(f"  ?????: {iss.lost_text!r}\n")
                if iss.error_msg:
                    f.write(f"  ????  : {iss.error_msg}\n")
        else:
            f.write("?LOSS ???? ? ????????\n")

        f.write("\n" + sep + "\n")
        if error_iss:
            f.write(f"?ERROR ???? {len(error_iss)} ???\n")
            f.write(sep + "\n")
            for idx, iss in enumerate(error_iss, 1):
                f.write(f"\nERROR #{idx}\n")
                f.write(f"  ??      : {iss.kind}\n")
                f.write(f"  ??      : {iss.round_no}\n")
                f.write(f"  ??      : {os.path.basename(iss.pdf_path)}\n")
                f.write(f"  ??      : {iss.page_num}\n")
                f.write(f"  ?????: {iss.edited_text!r}\n")
                f.write(f"  ???    : {iss.new_text!r}\n")
                f.write(f"  ????  : {iss.error_msg}\n")
        else:
            f.write("?ERROR ?????\n")

        f.write("\n" + sep + "\n")
        f.write("????\n")

    print(f"\n????????{rpt}")
    return total_loss


if __name__ == "__main__":
    sys.exit(0 if main() == 0 else 1)

