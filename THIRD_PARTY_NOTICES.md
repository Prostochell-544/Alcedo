# Third-party notices

Alcedo contains no code copied from other projects so far.

If you copy code from another project, add an entry here with the project name, its
URL, the files concerned and the full text of its license and copyright notice. Keep
any notices from the original source. Apache-2.0 projects may also have a NOTICE file
that has to be preserved.

Projects whose ideas informed Alcedo's design are listed in `docs/ROADMAP.md`.

## Logo

`docs/assets/alcedo-logo.png` was drawn by [kesha_xdd](https://t.me/kesha_xdd). All rights stay with the artist, who
allowed its use for this project. It is not covered by the MIT license of the code, so forks and other projects need
the artist's own permission to use it.

The window of the desktop application shows a copy of it, `src/alcedo_lit/app/assets/logo.png`, and the icon of the
Windows program, `packaging/alcedo.ico`, is made from it. The same terms apply to both.

## Wordmark

`docs/assets/alcedo-wordmark-light.svg` and `alcedo-wordmark-dark.svg` show text set in Orbitron and converted to
outlines. The repository does not contain the font itself.

Orbitron: Copyright 2018 The Orbitron Project Authors (https://github.com/theleagueof/orbitron), with Reserved Font
Name "Orbitron". Licensed under the SIL Open Font License, Version 1.1: https://openfontlicense.org

## Runtime dependencies

The Python package does not include them: pip installs them separately.

| Package | License | Needed for |
|---|---|---|
| requests | Apache-2.0 | always |
| tqdm | MPL-2.0 AND MIT | always |
| scholarly | Unlicense | optional `scholar` extra |
| bibtexparser | LGPLv3 or BSD (version 1.x) | optional `scholar` extra |
| httpx | BSD-3-Clause | optional `scholar` extra |
| PySide6-Essentials, shiboken6 (Qt for Python) | LGPL-3.0-only, GPL-2.0-only or GPL-3.0-only | optional `app` extra |

## Windows program

The Windows program attached to releases, `Alcedo-<version>-windows.zip`, is built by `packaging/alcedo.spec`. Unlike
the Python package, it includes other software. Their license texts are in its `_internal/licenses` folder.

| Component | License |
|---|---|
| Python 3.12 | PSF-2.0; the licenses of its own parts, such as OpenSSL (Apache-2.0), are in `licenses/python` |
| Qt 6 and Qt for Python (PySide6-Essentials, shiboken6) | LGPL-3.0-only, texts in `licenses/qt` |
| requests | Apache-2.0 |
| urllib3 | MIT |
| idna | BSD-3-Clause |
| charset-normalizer | MIT |
| certifi | MPL-2.0 |
| tqdm | MPL-2.0 AND MIT |
| colorama | BSD-3-Clause |

Qt is used under the GNU LGPL version 3. Its libraries are separate files in `_internal/PySide6`, so you can replace
them with your own build of the same Qt version. The source code of Qt is at https://download.qt.io/official_releases/qt/
and that of Qt for Python at https://code.qt.io/cgit/pyside/pyside-setup.git/. The source code of Alcedo and the recipe
for the program are in this repository; `packaging/licenses` holds the license texts that the program carries.
