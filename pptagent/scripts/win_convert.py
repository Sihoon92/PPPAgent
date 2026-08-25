"""Runs on the Windows side of the WSL bridge.

    python.exe win_convert.py {pdf|wmf} <input> <output>

Every path passed in is a Windows path. The Windows-only imports deliberately
live behind a helper rather than at module scope: the script must still be able
to report a usage error when it is started anywhere else, and a missing
dependency has to name itself instead of surfacing as an import traceback.

Both modes go through PowerPoint. Pillow can read metafiles on Windows, but it
renders them through GDI and gives up on many real EMFs ("cannot render
metafile"), whereas PowerPoint draws exactly what the deck would show.
"""

from __future__ import annotations

import sys
from contextlib import contextmanager

PP_SAVE_AS_PDF = 32  # PpSaveAsFileType.ppSaveAsPDF
PP_SHAPE_FORMAT_PNG = 2  # PpShapeFormat.ppShapeFormatPNG
PP_LAYOUT_BLANK = 12  # PpSlideLayout.ppLayoutBlank
MSO_FALSE, MSO_TRUE = 0, -1


@contextmanager
def powerpoint():
    """Yield a PowerPoint application, quitting it only if we started it."""
    try:
        import pythoncom
        import win32com.client
    except ImportError:
        sys.exit("pywin32 is missing on the Windows interpreter: pip install pywin32")

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("PowerPoint.Application")
        started_here = False
    except pythoncom.com_error:
        try:
            app = win32com.client.Dispatch("PowerPoint.Application")
        except pythoncom.com_error as e:
            sys.exit(
                "could not start PowerPoint. COM automation needs PowerPoint "
                f"installed and an interactive desktop session. ({e})"
            )
        started_here = True

    try:
        yield app
    finally:
        # Never quit an instance the user already had open.
        if started_here:
            app.Quit()
        pythoncom.CoUninitialize()


def to_pdf(src: str, dst: str) -> None:
    """Export a presentation to PDF through PowerPoint's own exporter."""
    with powerpoint() as app:
        # Positional args: FileName, ReadOnly, Untitled, WithWindow.
        presentation = app.Presentations.Open(src, MSO_TRUE, MSO_FALSE, MSO_FALSE)
        try:
            # SaveAs rather than ExportAsFixedFormat: under late binding pywin32
            # cannot supply defaults for the latter's optional COM-object
            # parameters ("The Python instance can not be converted to a COM
            # object").
            presentation.SaveAs(dst, PP_SAVE_AS_PDF)
        finally:
            presentation.Close()


def to_png(src: str, dst: str) -> None:
    """Rasterise a WMF/EMF image by letting PowerPoint draw it."""
    with powerpoint() as app:
        presentation = app.Presentations.Add(MSO_FALSE)
        try:
            slide = presentation.Slides.Add(1, PP_LAYOUT_BLANK)
            # Positional args: FileName, LinkToFile, SaveWithDocument, Left, Top.
            # Omitting Width/Height keeps the metafile at its native size.
            picture = slide.Shapes.AddPicture(src, MSO_FALSE, MSO_TRUE, 0, 0)
            picture.Export(dst, PP_SHAPE_FORMAT_PNG)
        finally:
            presentation.Close()


MODES = {"pdf": to_pdf, "wmf": to_png}


def main(argv: list[str]) -> None:
    given = argv[1] if len(argv) > 1 else "(nothing)"
    if len(argv) != 4 or given not in MODES:
        sys.exit(
            f"usage: win_convert.py <{'|'.join(MODES)}> <input> <output>; "
            f"got mode {given!r}"
        )
    MODES[given](argv[2], argv[3])


if __name__ == "__main__":
    main(sys.argv)
