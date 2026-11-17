"""Entry point of the Windows program that PyInstaller builds from packaging/alcedo.spec."""

import sys

from alcedo_lit.app.__main__ import main

sys.exit(main())
