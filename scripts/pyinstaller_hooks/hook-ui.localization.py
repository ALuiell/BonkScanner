"""Ship Qt's standard dialog captions for the supported interface languages."""
from pathlib import Path
from PySide6.QtCore import QLibraryInfo

root = Path(QLibraryInfo.path(QLibraryInfo.TranslationsPath))
datas = [(str(root / f"qtbase_{code}.qm"), "PySide6/translations")
         for code in ("uk", "ru", "fr", "es", "de", "pt_BR")]
