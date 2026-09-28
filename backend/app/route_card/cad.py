"""CAD (DXF/DWG) text harvest. DWF is stored but not parsed."""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from pathlib import Path


def harvest_dxf_text(data: bytes) -> str:
    try:
        import ezdxf
    except ImportError as exc:
        raise RuntimeError("ezdxf is not installed on the server") from exc

    with tempfile.NamedTemporaryFile(suffix=".dxf", delete=False) as tmp:
        tmp.write(data)
        path = tmp.name
    try:
        doc = ezdxf.readfile(path)
        msp = doc.modelspace()
        lines: list[str] = []
        for entity in msp:
            dxftype = entity.dxftype()
            if dxftype == "TEXT":
                lines.append(str(entity.dxf.text or ""))
            elif dxftype == "MTEXT":
                try:
                    lines.append(entity.plain_text())
                except Exception:
                    lines.append(str(getattr(entity.dxf, "text", "") or ""))
        for layout in doc.layouts:
            if layout.name.lower() == "model":
                continue
            for entity in layout:
                dxftype = entity.dxftype()
                if dxftype == "TEXT":
                    lines.append(str(entity.dxf.text or ""))
                elif dxftype == "MTEXT":
                    try:
                        lines.append(entity.plain_text())
                    except Exception:
                        pass
        return "\n".join(t.strip() for t in lines if t and t.strip())
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def convert_dwg_to_dxf(dwg_bytes: bytes, converter_path: str | None) -> bytes | None:
    converter = converter_path or os.getenv("ODA_CONVERTER_PATH", "")
    if not converter or not Path(converter).exists():
        which = shutil.which("ODAFileConverter") or shutil.which("ODAFileConverter.exe")
        converter = which or ""
    if not converter:
        return None
    with tempfile.TemporaryDirectory() as td:
        src_dir = Path(td) / "in"
        dst_dir = Path(td) / "out"
        src_dir.mkdir()
        dst_dir.mkdir()
        src = src_dir / "drawing.dwg"
        src.write_bytes(dwg_bytes)
        try:
            subprocess.run(
                [converter, str(src_dir), str(dst_dir), "ACAD2018", "DXF", "0", "1"],
                check=True,
                timeout=60,
                capture_output=True,
            )
        except (subprocess.SubprocessError, OSError):
            return None
        dxfs = list(dst_dir.rglob("*.dxf"))
        if not dxfs:
            return None
        return dxfs[0].read_bytes()
