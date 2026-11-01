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

## Wordmark

`docs/assets/alcedo-wordmark-light.svg` and `alcedo-wordmark-dark.svg` show text set in Orbitron and converted to
outlines. The repository does not contain the font itself.

Orbitron: Copyright 2018 The Orbitron Project Authors (https://github.com/theleagueof/orbitron), with Reserved Font
Name "Orbitron". Licensed under the SIL Open Font License, Version 1.1: https://openfontlicense.org

## Runtime dependencies

These are installed separately and are not distributed with Alcedo.

| Package | License | Needed for |
|---|---|---|
| requests | Apache-2.0 | always |
| tqdm | MPL-2.0 AND MIT | always |
| scholarly | Unlicense | optional `scholar` extra |
| bibtexparser | LGPLv3 or BSD (version 1.x) | optional `scholar` extra |
| httpx | BSD-3-Clause | optional `scholar` extra |
