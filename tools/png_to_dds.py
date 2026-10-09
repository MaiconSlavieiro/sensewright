#!/usr/bin/env python3
# Sensewright — PNG → TS4 DDS converter (build machine only).
#
# The Sims 4 loads pie-menu category icons as DDS files with the fourcc "DXT5"
# (DXT5 / BC3 compression) plus a full mipmap chain. The .package stores this as
# a resource of type 0x00B2D882; the tuning XML references the same instance as
# type 0x2F7D0004 (the "Icon" key type), and build_package.py emits the DDS key
# (00B2D882) into the binary SimData — exactly how S4TK/S4CL do it.
#
# Usage:  python tools/png_to_dds.py input.png output.dds [size]
#   size defaults to 64; must be a power of two (64, 128, 256, 512, ...).

import struct
import sys

from PIL import Image


def _round_div(a, b):
    return (a + b // 2) // b


def _clamp_u8(v):
    return max(0, min(255, v))


def dxt5_encode_block(pixels):
    """Encode one 4x4 RGBA block (16 pixels) to 16 bytes of BC3/DXT5."""
    # --- Alpha (BC3) ----------------------------------------------------
    alphas = [p[3] for p in pixels]
    a_min = min(alphas)
    a_max = max(alphas)

    if a_max > a_min:
        # 8-value interpolation: a0 = max, a1 = min, 6 in-between
        a0, a1 = a_max, a_min
        alpha_table = [a0, a1] + [
            _clamp_u8((a0 * (7 - i) + a1 * i) // 7) for i in range(1, 7)
        ]
    else:
        # Degenerate: 6-value mode with explicit 0 (transparent) and 255 (opaque)
        a0, a1 = a_max, a_min
        alpha_table = [a0, a1] + [
            _clamp_u8((a0 * (5 - i) + a1 * i) // 5) for i in range(1, 5)
        ] + [0, 255]

    def alpha_index(a):
        best = 0
        best_d = abs(a - alpha_table[0])
        for idx in range(1, 8):
            d = abs(a - alpha_table[idx])
            if d < best_d:
                best_d = d
                best = idx
        return best

    alpha_bits = 0
    for i, p in enumerate(pixels):
        alpha_bits |= alpha_index(p[3]) << (3 * i)

    # --- Color (BC3 / DXT5) ---------------------------------------------
    def rgb565(p):
        r = p[0] >> 3
        g = p[1] >> 2
        b = p[2] >> 3
        return (r << 11) | (g << 5) | b

    c565 = [rgb565(p) for p in pixels]
    # Simple min/max selection (adequate for small UI icons).
    c0, c1 = max(c565), min(c565)
    if c0 == c1:
        c1 = c0 ^ 0xFFFF  # avoid degenerate interpolation

    def unpack565(c):
        r = (c >> 11) & 0x1F
        g = (c >> 5) & 0x3F
        b = c & 0x1F
        return (r << 3 | r >> 2, g << 2 | g >> 4, b << 3 | b >> 2)

    col0 = unpack565(c0)
    col1 = unpack565(c1)
    # DXT5 color ramp: c0, c1, (2*c0 + c1)/3, (c0 + 2*c1)/3
    col2 = tuple(_round_div(2 * col0[j] + col1[j], 3) for j in range(3))
    col3 = tuple(_round_div(col0[j] + 2 * col1[j], 3) for j in range(3))
    color_table = [col0, col1, col2, col3]

    def color_index(p):
        pr = p[0]
        pg = p[1]
        pb = p[2]
        best = 0
        best_d = 1 << 30
        for idx in range(4):
            cr, cg, cb = color_table[idx]
            d = (cr - pr) ** 2 + (cg - pg) ** 2 + (cb - pb) ** 2
            if d < best_d:
                best_d = d
                best = idx
        return best

    color_bits = 0
    for i, p in enumerate(pixels):
        color_bits |= color_index(p) << (2 * i)

    # --- Assemble 16 bytes ----------------------------------------------
    out = bytearray(16)
    out[0] = a0 & 0xFF
    out[1] = a1 & 0xFF
    # 6 bytes of 3-bit alpha indices (48 bits), little-endian
    for j in range(6):
        out[2 + j] = (alpha_bits >> (8 * j)) & 0xFF
    struct.pack_into("<H", out, 8, c0)
    struct.pack_into("<H", out, 10, c1)
    for j in range(4):
        out[12 + j] = (color_bits >> (8 * j)) & 0xFF
    return bytes(out)


def encode_dxt5_mipmap(img):
    """Encode a single RGBA image (w, h both multiples of 4) to DXT5 bytes."""
    w, h = img.size
    px = img.load()
    data = bytearray()
    for by in range(0, h, 4):
        for bx in range(0, w, 4):
            block = []
            for y in range(4):
                for x in range(4):
                    block.append(px[bx + x, by + y])
            data += dxt5_encode_block(block)
    return bytes(data)


def build_dds(img):
    """Build a TS4-style DST5 DDS file (with full mipmap chain) from an RGBA image."""
    w, h = img.size
    mip_count = 1
    levels = []
    cur = img.convert("RGBA")
    while True:
        levels.append(cur)
        if cur.size == (1, 1):
            break
        nw = max(1, cur.size[0] // 2)
        nh = max(1, cur.size[1] // 2)
        cur = cur.resize((nw, nh), Image.LANCZOS)
        mip_count += 1

    body = bytearray()
    for lvl in levels:
        # Pad mipmaps smaller than 4x4 up to 4x4 for DXT block alignment.
        if lvl.size[0] < 4 or lvl.size[1] < 4:
            lvl = lvl.resize((max(4, lvl.size[0]), max(4, lvl.size[1])), Image.NEAREST)
        body += encode_dxt5_mipmap(lvl)

    # The full DDS file header is 128 bytes: the 4-byte magic ("DDS ") plus the
    # 124-byte DDS_HEADER struct (dwSize = 124 covers offsets 4..127). Allocating
    # only 124 bytes here left the pixel data 4 bytes early and omitted the
    # trailing dwReserved2 field, producing a malformed texture the game can't
    # load. (Verified against S4CL's working DDS: pixel data starts at 0x80.)
    header = bytearray(128)
    header[0:4] = b"DDS "
    struct.pack_into("<I", header, 4, 124)          # header size
    # CAPS|HEIGHT|WIDTH|PIXELFORMAT|MIPMAPCOUNT|LINEARSIZE
    struct.pack_into("<I", header, 8, 0x000A1007)
    struct.pack_into("<I", header, 12, h)           # height
    struct.pack_into("<I", header, 16, w)           # width
    # Linear size of the top mip level (DXT5: one 16-byte block per 4x4 texels).
    struct.pack_into("<I", header, 20, ((w + 3) // 4) * ((h + 3) // 4) * 16)
    struct.pack_into("<I", header, 24, 0)           # depth (0 for a 2D texture)
    struct.pack_into("<I", header, 28, mip_count)   # mipmap count
    # reserved[11] = zeros (offset 32..75)
    struct.pack_into("<I", header, 76, 32)          # pixel format size
    struct.pack_into("<I", header, 80, 0x4)         # DDPF_FOURCC
    header[84:88] = b"DXT5"                          # fourcc
    struct.pack_into("<I", header, 88, 0)           # RGB bit count
    struct.pack_into("<I", header, 92, 0)           # R mask
    struct.pack_into("<I", header, 96, 0)           # G mask
    struct.pack_into("<I", header, 100, 0)          # B mask
    struct.pack_into("<I", header, 104, 0)          # A mask
    struct.pack_into("<I", header, 108, 0x00401008)  # caps: COMPLEX|MIPMAP|TEXTURE
    struct.pack_into("<I", header, 112, 0)          # caps2
    struct.pack_into("<I", header, 116, 0)          # caps3
    struct.pack_into("<I", header, 120, 0)          # caps4
    struct.pack_into("<I", header, 124, 0)          # reserved2

    return bytes(header) + bytes(body)


def convert(png_path, dds_path, size=64):
    data = convert_to_bytes(png_path, size)
    with open(dds_path, "wb") as f:
        f.write(data)
    return len(data)


def convert_to_bytes(png_path, size=64):
    """Convert a PNG to TS4 DST5 DDS bytes (no file I/O)."""
    img = Image.open(png_path).convert("RGBA")
    if size and (img.size[0] != size or img.size[1] != size):
        img = img.resize((size, size), Image.LANCZOS)
    return build_dds(img)


def convert_to_png_bytes(png_path, size=64):
    """Resize a PNG to a square icon and return raw PNG bytes (TS4 "Icon" type)."""
    import io
    img = Image.open(png_path).convert("RGBA")
    if size and (img.size[0] != size or img.size[1] != size):
        img = img.resize((size, size), Image.LANCZOS)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def main():
    if len(sys.argv) < 3:
        print("usage: python png_to_dds.py input.png output.dds [size]")
        sys.exit(1)
    png = sys.argv[1]
    dds = sys.argv[2]
    size = int(sys.argv[3]) if len(sys.argv) > 3 else 64
    n = convert(png, dds, size)
    print("wrote {} ({} bytes)".format(dds, n))


if __name__ == "__main__":
    main()
