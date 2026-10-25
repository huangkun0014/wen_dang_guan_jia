# -*- coding: utf-8 -*-
# ============================================
# 文本提取工具：从各种格式文件里提取纯文本
# 支持: docx / pptx / pdf / xlsx / txt / md
#   .doc/.wps/.xls/.et 老格式：可选走本机 WPS/Word/Excel 的 COM 接口提取
#   （yun_xu_com=True 时开启，独立子进程执行+超时强杀，失败静默返回空；
#    总开关见 config 的 LAO_GESHI_COM_KAI_GUAN）
# 不支持（返回空串）: ppt/dwg 等其余老格式或二进制格式
# ============================================

import os
import io
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from html import unescape

import config

# .doc/.wps 的 COM 提取脚本：在独立子进程里跑（挂起时线程内无法中断，只能进程隔离兜底）。
# 文本经临时文件传出（避免控制台编码/长度问题）。子进程无输出=成功，退出码非0=失败。
_COM_JIAO_BEN = r'''
import sys
import win32com.client
import pythoncom

lu, shu_chu = sys.argv[1], sys.argv[2]
pythoncom.CoInitialize()
app = doc = None
try:
    for pid in ("Word.Application", "Kwps.Application", "WPS.Application"):
        try:
            app = win32com.client.DispatchEx(pid)
            break
        except Exception:
            continue
    if app is None:
        sys.exit(2)
    app.Visible = False
    try:
        app.DisplayAlerts = 0
    except Exception:
        pass
    doc = app.Documents.Open(lu, ReadOnly=True, AddToRecentFiles=False)
    wen = doc.Content.Text or ""
    with open(shu_chu, "w", encoding="utf-8") as f:
        f.write(wen)
finally:
    try:
        if doc is not None:
            doc.Close(False)
    except Exception:
        pass
    try:
        if app is not None:
            app.Quit()
    except Exception:
        pass
    try:
        del doc, app
    except Exception:
        pass
    try:
        pythoncom.CoUninitialize()
    except Exception:
        pass
'''

# .xls/.et 的表格提取脚本：同套子进程隔离方案。
# 注意 Open 用位置参数（Filename, UpdateLinks, ReadOnly）——WPS 表格的 COM
# 不认 AddToRecentFiles 这类命名参数（实测报 unexpected keyword argument）。
_COM_JIAO_BEN_BIAO = r'''
import sys
import win32com.client
import pythoncom

lu, shu_chu = sys.argv[1], sys.argv[2]
pythoncom.CoInitialize()
app = wb = None
try:
    for pid in ("Excel.Application", "Ket.Application", "ET.Application"):
        try:
            app = win32com.client.DispatchEx(pid)
            break
        except Exception:
            continue
    if app is None:
        sys.exit(2)
    app.Visible = False
    try:
        app.DisplayAlerts = False
    except Exception:
        pass
    wb = app.Workbooks.Open(lu, 0, True)
    hang = []
    for ws in wb.Worksheets:
        try:
            su = ws.UsedRange
            if su is None:
                continue
            hang.append("[工作表] " + str(ws.Name))
            # 只读有内容的区域，每表最多前 50 行 x 20 列（够命名和摘要用，防大表撑爆）
            r0, c0 = su.Row, su.Column
            rn = min(su.Rows.Count, 50)
            cn = min(su.Columns.Count, 20)
            if rn <= 0 or cn <= 0:
                continue
            rng = ws.Range(ws.Cells(r0, c0), ws.Cells(r0 + rn - 1, c0 + cn - 1))
            zhi = rng.Value
            if isinstance(zhi, tuple):
                for row in zhi:
                    if isinstance(row, tuple):
                        line = " ".join(str(c) for c in row if c is not None)
                    else:
                        line = str(row)
                    if line.strip():
                        hang.append(line)
            elif zhi is not None:
                hang.append(str(zhi))
        except Exception:
            continue
    with open(shu_chu, "w", encoding="utf-8") as f:
        f.write("\n".join(hang))
finally:
    try:
        if wb is not None:
            wb.Close(False)
    except Exception:
        pass
    try:
        if app is not None:
            app.Quit()
    except Exception:
        pass
    try:
        del wb, app
    except Exception:
        pass
    try:
        pythoncom.CoUninitialize()
    except Exception:
        pass
'''


def _pao_com_jiao_ben(jiao_ben: str, wen_jian_lu_jing: str, chao_shi: int = 90) -> str:
    """在独立子进程里跑一段 COM 提取脚本，文本经临时文件传回。失败/超时返回空串。

    关键：**先把原文件复制一份临时副本，让 WPS/Word 打开副本**，原文件从头到尾
    不被 Office 进程占用——否则重建时紧接着的改名/归档会被"另一个程序正在使用此文件"
    卡住（Windows 文件锁）。临时副本提取完即删（WPS 偶尔晚释放，删不掉就留给系统临时目录）。

    子进程 + 超时强杀：个别文档可能触发对话框把 COM 卡死，进程隔离才能兜底。
    """
    if not getattr(config, "LAO_GESHI_COM_KAI_GUAN", True):
        return ""
    try:
        import win32com  # noqa: F401   没装 pywin32 就直接走不通，静默降级
    except Exception:
        return ""

    kzm = os.path.splitext(wen_jian_lu_jing)[1] or ".tmp"
    fu_ben = tempfile.NamedTemporaryFile(delete=False, suffix=kzm)
    fu_ben_path = fu_ben.name
    fu_ben.close()
    try:
        shutil.copy2(wen_jian_lu_jing, fu_ben_path)
    except Exception:
        try:
            os.remove(fu_ben_path)
        except OSError:
            pass
        return ""

    huan_cun = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    huan_cun.close()
    try:
        jie_guo = subprocess.run(
            [sys.executable, "-c", jiao_ben, fu_ben_path, huan_cun.name],
            capture_output=True, timeout=chao_shi)
        if jie_guo.returncode != 0:
            return ""
        with open(huan_cun.name, encoding="utf-8") as f:
            wen = f.read()
        # 清掉 Office 的控制字符（\x07 表格分隔、\x0b 分页等），换行归一
        wen = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", wen)
        return wen.replace("\r", "\n")
    except Exception:
        return ""
    finally:
        try:
            os.remove(huan_cun.name)
        except OSError:
            pass
        try:
            os.remove(fu_ben_path)
        except OSError:
            pass      # WPS 尚未释放副本时留待系统清理，不影响原文件


def _lao_geshi_com_ti_qu(wen_jian_lu_jing: str, chao_shi: int = 90) -> str:
    """用 WPS/Word COM 提取 .doc/.wps 正文。失败/超时返回空串。"""
    return _pao_com_jiao_ben(_COM_JIAO_BEN, wen_jian_lu_jing, chao_shi)


def _biao_geshi_com_ti_qu(wen_jian_lu_jing: str, chao_shi: int = 90) -> str:
    """用 WPS 表格/Excel COM 提取 .xls/.et 内容。失败/超时返回空串。"""
    return _pao_com_jiao_ben(_COM_JIAO_BEN_BIAO, wen_jian_lu_jing, chao_shi)


def _pptx_wen_ben(wen_jian_lu_jing: str) -> str:
    """pptx 本质是 zip，直接读幻灯片 XML 里的 <a:t> 文本 run，无需第三方库。"""
    try:
        with zipfile.ZipFile(wen_jian_lu_jing) as z:
            huan_deng_pian = sorted(
                (n for n in z.namelist() if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)),
                key=lambda n: int(re.search(r"(\d+)", n).group(1)))
            duan = []
            for ming in huan_deng_pian:
                xml = z.read(ming).decode("utf-8", errors="ignore")
                duan.extend(unescape(t) for t in re.findall(r"<a:t>([^<]*)</a:t>", xml))
            return "\n".join(d for d in duan if d.strip())
    except Exception:
        return ""


def _qing_xi_pdf_wen_ben(wen: str) -> str:
    """去掉 PDF 的纯页码行/页眉页脚分隔线（- 1 -、— 12 —、第1页 共X页、1/20）。

    只删"明显是页码"的行，不删单独的 1、2 这种（可能是表格内容/条款序号）。
    """
    hang = []
    for line in (wen or "").replace("\f", "\n").split("\n"):
        s = line.strip()
        if not s:
            continue
        if re.fullmatch(r"[-—–－]+\s*\d{1,4}\s*[-—–－]+", s):
            continue
        if re.fullmatch(r"第\s*\d+\s*页(\s*共\s*\d+\s*页)?", s):
            continue
        if re.fullmatch(r"\d{1,4}\s*/\s*\d{1,4}", s):
            continue
        hang.append(line)
    return "\n".join(hang)


def _ti_qu_wen_ben_yuan(wen_jian_lu_jing: str, zi_shu_shang_xian: int = 1500,
                        yun_xu_com: bool = False) -> str:
    """提取文件文本，失败或格式不支持时返回空串。

    参数:
        wen_jian_lu_jing: 文件完整路径
        zi_shu_shang_xian: 最多返回多少字（防止超大文件撑爆内存）
        yun_xu_com: 是否为老格式（.doc/.wps/.xls/.et）启用 COM 提取。
            True 用于"单个按需"的 AI 功能（重命名/标签/归档建议）；
            批量场景（体检、批量摘要、迁移重建）默认 False，避免逐个子进程拖慢/卡住
    返回:
        纯文本字符串
    """
    if not os.path.exists(wen_jian_lu_jing):
        return ""
    kuo_zhan_ming = os.path.splitext(wen_jian_lu_jing)[1].lower()
    try:
        if kuo_zhan_ming == ".docx":
            import docx
            # 先读进内存再解析：避免 python-docx 持有文件句柄，锁住紧接着的改名/移动
            with open(wen_jian_lu_jing, "rb") as f:
                d = docx.Document(io.BytesIO(f.read()))
            duan = [p.text for p in d.paragraphs if p.text.strip()]
            # 表格内容也要：台账/清单类文档大量信息在表格里，只看段落会漏
            for biao in d.tables:
                for hang in biao.rows:
                    xian = " ".join(c.text.strip() for c in hang.cells if c.text.strip())
                    if xian:
                        duan.append(xian)
            return "\n".join(duan)[:zi_shu_shang_xian]
        if kuo_zhan_ming == ".pptx":
            return _pptx_wen_ben(wen_jian_lu_jing)[:zi_shu_shang_xian]
        if kuo_zhan_ming in (".doc", ".wps") and yun_xu_com:
            return _lao_geshi_com_ti_qu(wen_jian_lu_jing)[:zi_shu_shang_xian]
        if kuo_zhan_ming in (".xls", ".et") and yun_xu_com:
            return _biao_geshi_com_ti_qu(wen_jian_lu_jing)[:zi_shu_shang_xian]
        if kuo_zhan_ming == ".pdf":
            from pypdf import PdfReader
            t = ""
            with open(wen_jian_lu_jing, "rb") as f:
                r = PdfReader(f)
                for ye in r.pages[:20]:                 # 最多读前20页（索引要覆盖正文）
                    t += _qing_xi_pdf_wen_ben(ye.extract_text() or "") + "\n"
                    if len(t) >= zi_shu_shang_xian:
                        break
            return t[:zi_shu_shang_xian]
        if kuo_zhan_ming in (".xlsx", ".xlsm"):
            from openpyxl import load_workbook
            # 先读进内存；解析完必须 wb.close()——否则 zip 句柄一直占着，
            # 改名/移动会报"另一个程序正在使用此文件"（批量重建时踩过）
            with open(wen_jian_lu_jing, "rb") as f:
                wb = load_workbook(io.BytesIO(f.read()), read_only=True, data_only=True)
            try:
                hang = []
                for ws in wb.worksheets[:10]:           # 最多看10个工作表
                    hang.append("[工作表] " + ws.title)
                    for row in ws.iter_rows(max_row=100, values_only=True):
                        xian = " ".join(str(c) for c in row if c is not None)
                        if xian.strip():
                            hang.append(xian)
                    if sum(len(h) for h in hang) > zi_shu_shang_xian:
                        break
                return "\n".join(hang)[:zi_shu_shang_xian]
            finally:
                try:
                    wb.close()
                except Exception:
                    pass
        if kuo_zhan_ming in (".txt", ".md"):
            with open(wen_jian_lu_jing, encoding="utf-8", errors="ignore") as f:
                return f.read(zi_shu_shang_xian)
    except Exception:
        # 单个文件坏了不影响整体，静默跳过
        pass
    return ""


def ti_qu_wen_ben(wen_jian_lu_jing: str, zi_shu_shang_xian: int = 1500,
                  yun_xu_com: bool = False) -> str:
    """提取文件文本（对外入口）：内部提取后统一清洗。

    PDF/旧文档偶尔会提取出孤立的 Unicode 代理字符，直接送 tokenizers 或 JSON
    会报 "TextEncodeInput must be ..." / 编码错误；在入口统一丢弃非法字符。
    """
    wen = _ti_qu_wen_ben_yuan(wen_jian_lu_jing, zi_shu_shang_xian, yun_xu_com)
    if not wen:
        return ""
    return wen.encode("utf-8", "ignore").decode("utf-8", "ignore")
