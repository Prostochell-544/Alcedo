"""Make packaging/alcedo.ico from the logo. Needs Pillow: python packaging/make_icon.py"""

from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SIZES = [(size, size) for size in (16, 20, 24, 32, 40, 48, 64, 128, 256)]

logo = Image.open(ROOT / "src" / "alcedo_lit" / "app" / "assets" / "logo.png").convert("RGBA")
logo = logo.crop(logo.getbbox())  # no empty margin, so that the bird fills the small sizes
side = max(logo.size)
square = Image.new("RGBA", (side, side))
square.paste(logo, ((side - logo.width) // 2, (side - logo.height) // 2))
square.save(ROOT / "packaging" / "alcedo.ico", sizes=SIZES)
print(f"packaging/alcedo.ico from a {logo.width}x{logo.height} logo")
