"""Write the PWA icons: a green tile with Tally's mark.

Plain zlib PNG writing, so the build needs no image library. Run it again if
the brand colour changes.

    python scripts/make_icons.py
"""
import struct
import zlib
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "web" / "public"
BG = (18, 122, 87)        # --accent, light mode
FG = (255, 255, 255)


def png(width: int, height: int, pixels: list[list[tuple[int, int, int]]]) -> bytes:
    def chunk(tag: bytes, data: bytes) -> bytes:
        body = tag + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + b"".join(bytes(p) for p in row) for row in pixels)
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def draw(size: int, *, padding: float) -> bytes:
    """The mark: a crossbar and a stem, the same shape as the favicon."""
    px = [[BG for _ in range(size)] for _ in range(size)]
    inset = int(size * padding)
    bar_h = max(2, int(size * 0.085))
    stem_w = bar_h
    top = int(size * 0.33)
    left, right = inset, size - inset
    for y in range(top, min(top + bar_h, size)):
        for x in range(left, right):
            px[y][x] = FG
    cx0 = size // 2 - stem_w // 2
    for y in range(top, size - inset):
        for x in range(cx0, cx0 + stem_w):
            px[y][x] = FG
    return png(size, size, px)


for size, name, padding in [(192, "icon-192.png", 0.28), (512, "icon-512.png", 0.28),
                            (512, "icon-maskable.png", 0.34)]:
    (OUT / name).write_bytes(draw(size, padding=padding))
    print("wrote", name)
