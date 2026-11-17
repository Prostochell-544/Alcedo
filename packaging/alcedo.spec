# PyInstaller recipe for the Windows program, a folder with Alcedo.exe.
#   python -m pip install ".[app]" pyinstaller
#   pyinstaller packaging/alcedo.spec --noconfirm
# The program is a folder, not one file: it starts faster, antivirus programs flag it less often, and the Qt
# libraries in it can be replaced, as their license (LGPL) asks.
import importlib.metadata as metadata
import sys
from pathlib import Path

ROOT = Path(SPECPATH).parent  # noqa: F821 - defined by PyInstaller
# Everything the program bundles besides Alcedo and Python, for the licenses folder.
BUNDLED = ("PySide6-Essentials", "shiboken6", "requests", "urllib3", "idna", "charset-normalizer", "certifi",
           "tqdm", "colorama")
LICENSE_WORDS = ("LICEN", "COPYING", "NOTICE", "AUTHORS")


def license_files():
    files = [(str(ROOT / "LICENSE"), "licenses/alcedo"),
             (str(ROOT / "THIRD_PARTY_NOTICES.md"), "licenses/alcedo"),
             (str(ROOT / "packaging" / "licenses" / "LGPL-3.0.txt"), "licenses/qt"),
             (str(ROOT / "packaging" / "licenses" / "GPL-3.0.txt"), "licenses/qt")]
    python_license = Path(sys.base_prefix) / "LICENSE.txt"
    if python_license.exists():
        files.append((str(python_license), "licenses/python"))
    for name in BUNDLED:
        try:
            dist = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            continue
        for file in dist.files or ():
            if any(word in file.name.upper() for word in LICENSE_WORDS):
                files.append((str(file.locate()), f"licenses/{name}"))
    return files


a = Analysis(
    [str(ROOT / "packaging" / "alcedo_app.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(ROOT / "src" / "alcedo_lit" / "app" / "assets" / "logo.png"), "alcedo_lit/app/assets")]
    + license_files(),
    # Direct Google Scholar search stays in the Python version; the window says so.
    excludes=["tkinter", "scholarly", "selenium", "PIL", "numpy"],
)
# Not needed by a window of widgets: software OpenGL, and Qt's own networking, since requests does all the network
# work with Python's OpenSSL. Qt's TLS plugin would also pull an OpenSSL from whatever is on the PATH.
UNUSED_FILES = {"opengl32sw.dll", "libcrypto-3-x64.dll", "libssl-3-x64.dll"}
UNUSED_PLUGINS = ("plugins/tls/", "plugins/networkinformation/")
a.binaries = [entry for entry in a.binaries
              if Path(entry[0]).name.lower() not in UNUSED_FILES
              and not any(part in entry[0].replace("\\", "/") for part in UNUSED_PLUGINS)]
pyz = PYZ(a.pure)  # noqa: F821
exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Alcedo",
    icon=str(ROOT / "packaging" / "alcedo.ico"),
    console=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Alcedo")  # noqa: F821
