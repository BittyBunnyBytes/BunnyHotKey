"""ImageSearch with a pure-Python PNG/BMP decoder."""
from __future__ import annotations

import re
import struct
import zlib

from .. import objects as O
from ..objects import throw
from . import setref
from .files import host_path


def _decode_png(data):
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not png")
    pos = 8
    w = h = 0
    ct = bd = 0
    idat = b""
    palette = None
    while pos < len(data):
        ln, = struct.unpack(">I", data[pos:pos + 4])
        typ = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", body[:10])
        elif typ == b"PLTE":
            palette = [body[i:i + 3] for i in range(0, len(body), 3)]
        elif typ == b"IDAT":
            idat += body
        elif typ == b"IEND":
            break
    if bd != 8:
        raise ValueError("unsupported PNG bit depth")
    ch = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}[ct]
    raw = zlib.decompress(idat)
    stride = w * ch
    rows = []
    prev = bytearray(stride)
    i = 0
    for _ in range(h):
        ft = raw[i]
        line = bytearray(raw[i + 1:i + 1 + stride])
        i += 1 + stride
        for x in range(stride):
            a = line[x - ch] if x >= ch else 0
            b = prev[x]
            c = prev[x - ch] if x >= ch else 0
            if ft == 1:
                line[x] = (line[x] + a) & 255
            elif ft == 2:
                line[x] = (line[x] + b) & 255
            elif ft == 3:
                line[x] = (line[x] + (a + b) // 2) & 255
            elif ft == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        px = []
        for x in range(w):
            o = x * ch
            if ct == 2:
                px.append((line[o], line[o + 1], line[o + 2], 255))
            elif ct == 6:
                px.append((line[o], line[o + 1], line[o + 2], line[o + 3]))
            elif ct == 0:
                px.append((line[o],) * 3 + (255,))
            elif ct == 4:
                px.append((line[o],) * 3 + (line[o + 1],))
            else:
                r, g, b = palette[line[o]]
                px.append((r, g, b, 255))
        rows.append(px)
    return w, h, rows


def _decode_bmp(data):
    if data[:2] != b"BM":
        raise ValueError("not bmp")
    off, = struct.unpack("<I", data[10:14])
    w, h, _, bpp = struct.unpack("<iiHH", data[18:30])
    flip = h > 0
    h = abs(h)
    stride = (w * bpp // 8 + 3) & ~3
    rows = []
    for y in range(h):
        base = off + y * stride
        px = []
        for x in range(w):
            o = base + x * bpp // 8
            b, g, r = data[o], data[o + 1], data[o + 2]
            px.append((r, g, b, 255))
        rows.append(px)
    if flip:
        rows.reverse()
    return w, h, rows


def image_search(outx, outy, x1, y1, x2, y2, spec):
    r = O.RT
    var = 0
    trans = None
    m = re.match(r"^((?:\*\S+\s+)*)(.*)$", spec)
    opts, path = m.group(1), m.group(2)
    for o in opts.split():
        ol = o[1:].lower()
        if ol.isdigit():
            var = int(ol)
        elif ol.startswith("trans"):
            c = ol[5:]
            trans = int(c, 16) if c.startswith("0x") else {"black": 0, "white": 0xFFFFFF}.get(c, None)
            if trans is None and c:
                trans = int(c, 16)
    try:
        from .gui import picture_path
        with open(picture_path(path), "rb") as fh:
            data = fh.read()
        iw, ih, img = _decode_png(data) if data[:4] == b"\x89PNG" else _decode_bmp(data)
    except (OSError, ValueError, KeyError) as e:
        throw("Error", f"Cannot load image: {e}", path)
    from .window import grab, _coord_origin
    ox, oy = _coord_origin("Pixel")
    X1, Y1, X2, Y2 = (r.to_int(v) for v in (x1, y1, x2, y2))
    sw, sh, rows = grab(X1 + ox, Y1 + oy, X2 - X1 + 1, Y2 - Y1 + 1)
    tr = ((trans >> 16) & 255, (trans >> 8) & 255, trans & 255) if trans is not None else None
    for sy in range(sh - ih + 1):
        for sx in range(sw - iw + 1):
            ok = True
            for iy in range(ih):
                row = rows[sy + iy]
                irow = img[iy]
                for ix in range(iw):
                    pr, pg, pb, pa = irow[ix]
                    if pa < 128 or (tr is not None and (pr, pg, pb) == tr):
                        continue
                    o = (sx + ix) * 4
                    b, g, rr = row[o], row[o + 1], row[o + 2]
                    if abs(rr - pr) > var or abs(g - pg) > var or abs(b - pb) > var:
                        ok = False
                        break
                if not ok:
                    break
            if ok:
                setref(outx, X1 + sx)
                setref(outy, Y1 + sy)
                return 1
    setref(outx, "")
    setref(outy, "")
    return 0
