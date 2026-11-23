"""Draw the app icons, committed alongside the PNGs they produce.

The mark is the same 2x2 tile grid the hub uses for its game cards: a cobalt
field, three white tiles and one warm tile for the game you have not played yet.

Run from the repository root:

    node scripts/py.mjs web/public/icons/make_icons.py

It writes ``icon-192.png``, ``icon-512.png``, ``maskable-512.png`` and
``apple-touch-icon.png`` here, and ``web/app/icon.png`` (the favicon Next serves).
No image library is used: the file format is small enough to write directly, and
a school laptop should not need Pillow to rebuild an icon.
"""

from __future__ import annotations

import pathlib
import struct
import zlib

HERE = pathlib.Path(__file__).resolve().parent
APP = HERE.parent.parent / "app"

BRAND = (0x0D, 0x5B, 0xFF)
BRAND_DEEP = (0x00, 0x45, 0xCC)
TILE = (0xFF, 0xFF, 0xFF)
SUN = (0xFF, 0x8B, 0x00)


def _chunk(kind: bytes, data: bytes) -> bytes:
    return (
        struct.pack(">I", len(data))
        + kind
        + data
        + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    )


def write_png(path: pathlib.Path, size: int, rows: list[bytes]) -> None:
    header = struct.pack(">IIBBBBB", size, size, 8, 6, 0, 0, 0)
    raw = b"".join(b"\x00" + row for row in rows)
    path.write_bytes(
        b"\x89PNG\r\n\x1a\n"
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 9))
        + _chunk(b"IEND", b"")
    )


def _coverage(x: float, y: float, box: tuple[float, float, float, float], radius: float) -> float:
    """1 inside a rounded rectangle, 0 outside, sampled at one sub-point."""
    x0, y0, x1, y1 = box
    if x < x0 or x > x1 or y < y0 or y > y1:
        return 0.0
    cx = min(max(x, x0 + radius), x1 - radius)
    cy = min(max(y, y0 + radius), y1 - radius)
    dx, dy = x - cx, y - cy
    return 1.0 if dx * dx + dy * dy <= radius * radius else 0.0


def draw(size: int, *, glyph_scale: float) -> list[bytes]:
    """The full-bleed field with the tile grid centred at ``glyph_scale``."""
    side = size * glyph_scale
    gap = side * 0.12
    tile = (side - gap) / 2
    radius = tile * 0.2
    left = (size - side) / 2
    top = (size - side) / 2

    boxes = [
        (left, top, left + tile, top + tile, TILE),
        (left + tile + gap, top, left + tile + gap + tile, top + tile, TILE),
        (left, top + tile + gap, left + tile, top + tile + gap + tile, TILE),
        (
            left + tile + gap,
            top + tile + gap,
            left + tile + gap + tile,
            top + tile + gap + tile,
            SUN,
        ),
    ]

    samples = [(0.25, 0.25), (0.75, 0.25), (0.25, 0.75), (0.75, 0.75)]
    rows: list[bytes] = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            hits: dict[tuple[int, int, int], float] = {}
            for sx, sy in samples:
                x, y = px + sx, py + sy
                colour = BRAND
                for x0, y0, x1, y1, paint in boxes:
                    if _coverage(x, y, (x0, y0, x1, y1), radius) > 0.5:
                        colour = paint
                hits[colour] = hits.get(colour, 0.0) + 0.25
            r = sum(c[0] * w for c, w in hits.items())
            g = sum(c[1] * w for c, w in hits.items())
            b = sum(c[2] * w for c, w in hits.items())
            row += bytes((round(r), round(g), round(b), 255))
        rows.append(bytes(row))
    return rows


def main() -> None:
    outputs = {
        "icon-192.png": (192, 0.60),
        "icon-512.png": (512, 0.60),
        # Maskable icons are cropped to a circle by the launcher, so the mark
        # shrinks into the safe zone instead of touching the edge.
        "maskable-512.png": (512, 0.44),
        "apple-touch-icon.png": (180, 0.60),
    }
    for name, (size, scale) in outputs.items():
        write_png(HERE / name, size, draw(size, glyph_scale=scale))
        print(f"wrote {name} ({size}px)")

    favicon = draw(192, glyph_scale=0.60)
    write_png(APP / "icon.png", 192, favicon)
    print("wrote web/app/icon.png")


if __name__ == "__main__":
    main()
