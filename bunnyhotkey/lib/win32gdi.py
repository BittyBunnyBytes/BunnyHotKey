"""GDI for DllCall (registered into dllcall.EMU): device contexts, bitmaps and DIB sections, BitBlt/StretchBlt
from the screen or a window (screen capture), GetDIBits/SetDIBits, GetPixel/SetPixel, solid brushes and
FillRect.  Bitmaps live in native memory in the Windows layout (DIB sections expose their bits through ppvBits),
so scripts that read pixels with NumGet work unchanged.  Drawing goes into memory DCs only: an X11 screen has no
GDI surface, so a blit or fill whose destination is the screen or a window fails with ERROR_NOT_SUPPORTED."""
from __future__ import annotations

import ctypes
import os
import struct
import tempfile
import zlib

from .dllcall import EMU, I, _arg, _fail, _hwnd, _null, _write_out
from .win32emu import _alloc, _free, _handles, _new_handle, _ptr, _read, _write

ERROR_INVALID_HANDLE, ERROR_INVALID_PARAMETER, ERROR_NOT_SUPPORTED = 6, 87, 50
OBJ_PEN, OBJ_BRUSH, OBJ_DC, OBJ_FONT, OBJ_BITMAP, OBJ_MEMDC = 1, 2, 3, 6, 7, 10


class _Bitmap:
    """Pixels in native memory: bpp 32 or 24, rows `stride` bytes apart, bottom-up unless top_down."""

    def __init__(self, w, h, bpp=32, top_down=True, dib=False, addr=0):
        self.w, self.h, self.bpp, self.top_down, self.dib = w, h, bpp, top_down, dib
        self.stride = ((w * bpp + 31) // 32) * 4
        self.size = self.stride * h
        self.owned = not addr
        self.addr = addr or _alloc(max(self.size, 1), True)
        self.selected = 0                                   # the DC it is selected into

    def _row_addr(self, y):
        return self.addr + (y if self.top_down else self.h - 1 - y) * self.stride

    def rows(self, x=0, y=0, w=None, h=None):
        """Top-down BGRA rows of a region (clipped to the bitmap; outside pixels are black)."""
        w = self.w - x if w is None else w
        h = self.h - y if h is None else h
        out = []
        for ry in range(y, y + h):
            if not 0 <= ry < self.h:
                out.append(bytes(4 * w))
                continue
            x0, x1 = max(x, 0), min(x + w, self.w)
            raw = ctypes.string_at(self._row_addr(ry), self.stride) if x1 > x0 else b""
            if self.bpp == 24:
                px = b"".join(raw[i * 3:i * 3 + 3] + b"\0" for i in range(x0, x1))
            else:
                px = raw[x0 * 4:x1 * 4]
            out.append(bytes(4 * (x0 - x)) + px + bytes(4 * max(x + w - max(x1, x0), 0)))
        return out

    def put(self, x, y, rows):
        """Write top-down BGRA rows at (x, y), clipped to the bitmap."""
        for i, row in enumerate(rows):
            ry = y + i
            if not 0 <= ry < self.h:
                continue
            n = len(row) // 4
            x0, x1 = max(x, 0), min(x + n, self.w)
            if x1 <= x0:
                continue
            px = row[(x0 - x) * 4:(x1 - x) * 4]
            if self.bpp == 24:
                px = b"".join(px[k:k + 3] for k in range(0, len(px), 4))
                ctypes.memmove(self._row_addr(ry) + x0 * 3, px, len(px))
            else:
                ctypes.memmove(self._row_addr(ry) + x0 * 4, px, len(px))

    def free(self):
        if self.owned:
            _free(self.addr)
        self.addr = 0


class _DC:
    def __init__(self, kind, hwnd=0, client=True):
        self.kind, self.hwnd, self.client = kind, hwnd, client      # kind: "screen", "window" or "memory"
        self.bitmap = _stock_bitmap() if kind == "memory" else 0
        self.selected = {}                                          # object type -> handle
        self.stretch_mode = 1                                       # BLACKONWHITE

    def origin(self):
        """Screen position of (0, 0) for a screen/window DC."""
        if self.kind == "screen" or not self.hwnd:
            return 0, 0
        if self.client:
            from .dllcall import _client_origin
            return _client_origin(self.hwnd)
        from .dllcall import _win
        from .window import geometry
        d, w, c = _win(self.hwnd)
        if not w:
            return 0, 0
        if c is not None:
            from .dllcall import _client_origin
            return _client_origin(self.hwnd)
        x, y, _, _ = geometry(d, w)
        return x, y

    def size(self):
        if self.kind == "memory":
            bm = _handles.get(self.bitmap)
            return (bm.w, bm.h) if isinstance(bm, _Bitmap) else (1, 1)
        if self.kind == "screen" or not self.hwnd:
            from .window import screen_size
            return screen_size()
        from .dllcall import _win
        from .window import geometry
        d, w, c = _win(self.hwnd)
        if c is not None:
            return c.w, c.h
        if not w:
            return 0, 0
        _, _, ww, wh = geometry(d, w, client=self.client)
        return ww, wh

    def read(self, x, y, w, h):
        """Top-down BGRA rows of a region of what the DC shows."""
        if self.kind == "memory":
            bm = _handles.get(self.bitmap)
            return bm.rows(x, y, w, h) if isinstance(bm, _Bitmap) else [bytes(4 * w)] * h
        ox, oy = self.origin()
        return _screen_rows(ox + x, oy + y, w, h)


class _Brush:
    def __init__(self, color):
        self.color = color                                  # COLORREF 0x00BBGGRR


_STOCK = {}


def _stock_bitmap():
    """The 1x1 monochrome bitmap every new memory DC starts with (what SelectObject first returns)."""
    if "bitmap" not in _STOCK:
        _STOCK["bitmap"] = _new_handle(_Bitmap(1, 1))
    return _STOCK["bitmap"]


def _screen_rows(x, y, w, h):
    """BGRA rows of a screen region; parts outside the screen are black, as BitBlt from the screen DC gives."""
    from .window import grab, screen_size
    if w <= 0 or h <= 0:
        return []
    sw, sh = screen_size()
    x0, y0, x1, y1 = max(x, 0), max(y, 0), min(x + w, sw), min(y + h, sh)
    out = [bytes(4 * w) for _ in range(h)]
    if x1 <= x0 or y1 <= y0:
        return out
    _gw, _gh, rows = grab(x0, y0, x1 - x0, y1 - y0)
    left, right = bytes(4 * (x0 - x)), bytes(4 * (x + w - x1))
    for i, row in enumerate(rows):
        # XImage pixels are BGRX; GDI leaves the fourth byte 0 in screen captures
        px = bytearray(row)
        px[3::4] = bytes(len(px) // 4)
        out[y0 - y + i] = left + bytes(px) + right
    return out


def _dc(h):
    obj = _handles.get(h)
    return obj if isinstance(obj, _DC) else None


def _bitmap(h):
    obj = _handles.get(h)
    if isinstance(obj, _Bitmap):
        return obj
    from .gui import PICTURES
    path = PICTURES.get(h)
    if path:                                                # a LoadPicture handle: decode it once
        bm = _load_picture(path)
        if bm is not None:
            _handles[h] = bm
        return bm
    return None


def _load_picture(path):
    try:
        from .images import _decode_bmp, _decode_png
        with open(path, "rb") as fh:
            data = fh.read()
        w, h, img = _decode_png(data) if data[:4] == b"\x89PNG" else _decode_bmp(data)
        bm = _Bitmap(w, h)
        bm.put(0, 0, [b"".join(bytes((b, g, r, a)) for r, g, b, a in row) for row in img])
        return bm
    except (OSError, ValueError, KeyError, struct.error):
        pass
    try:                                                    # other formats through GdkPixbuf when it's there
        import gi
        gi.require_version("GdkPixbuf", "2.0")
        from gi.repository import GdkPixbuf
        pb = GdkPixbuf.Pixbuf.new_from_file(path)
    except Exception:
        return None
    w, h, n, rs = pb.get_width(), pb.get_height(), pb.get_n_channels(), pb.get_rowstride()
    raw = pb.get_pixels()
    bm = _Bitmap(w, h)
    rows = []
    for y in range(h):
        line = raw[y * rs:y * rs + w * n]
        rows.append(b"".join(bytes((line[i + 2], line[i + 1], line[i], line[i + 3] if n == 4 else 255))
                             for i in range(0, w * n, n)))
    bm.put(0, 0, rows)
    return bm


def png_of(h):
    """A temporary PNG of a GDI bitmap handle (for Gui Picture / ImageSearch "HBITMAP:" specs), or None."""
    bm = _handles.get(h)
    if not isinstance(bm, _Bitmap):
        return None
    raw = bytearray()
    for row in bm.rows():
        raw.append(0)
        rgb = bytearray(len(row) // 4 * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = row[2::4], row[1::4], row[0::4]
        raw += rgb

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    png = (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", bm.w, bm.h, 8, 2, 0, 0, 0)) +
           chunk(b"IDAT", zlib.compress(bytes(raw), 6)) + chunk(b"IEND", b""))
    fd, path = tempfile.mkstemp(prefix="bhk-hbitmap-", suffix=".png")
    with os.fdopen(fd, "wb") as fh:
        fh.write(png)
    return path


# ---------------------------------------------------------------- DCs
def _get_dc(p, client=True):
    h = _hwnd(_arg(p, 0))
    if h:
        from .dllcall import _win
        _d, w, _c = _win(h)
        if not w:
            return 0
        return _new_handle(_DC("window", h, client))
    return _new_handle(_DC("screen"))


def _create_dc(p):
    from .dllcall import _get_str
    drv = (_get_str(_arg(p, 0)) or "").upper()
    dev = (_get_str(_arg(p, 1)) or "").upper()
    if drv == "DISPLAY" or dev.startswith("\\\\.\\DISPLAY"):
        return _new_handle(_DC("screen"))
    return _fail(ERROR_INVALID_PARAMETER)


def _create_compatible_dc(p):
    return _new_handle(_DC("memory"))


def _delete_dc(p):
    dc = _handles.pop(_ptr(_arg(p, 0)), None)
    if not isinstance(dc, _DC):
        return 0
    bm = _handles.get(dc.bitmap)
    if isinstance(bm, _Bitmap) and bm.selected is dc:
        bm.selected = 0
    return 1


def _device_caps(p):
    dc = _dc(_ptr(_arg(p, 0)))
    idx = I(_arg(p, 1))
    from .window import screen_dpi, screen_size
    sw, sh = screen_size()
    w, h = dc.size() if dc is not None and dc.kind != "screen" else (sw, sh)
    dpi = int(screen_dpi())
    return {8: w, 10: h, 12: 32, 14: 1, 88: dpi, 90: dpi, 116: 60, 117: sh, 118: sw, 24: -1,
            4: w * 254 // dpi // 10, 6: h * 254 // dpi // 10}.get(idx, 0)


# ---------------------------------------------------------------- bitmaps
def _bmi(addr):
    """(width, height, bpp, compression) of a BITMAPINFOHEADER."""
    _size, w, h, _planes, bpp, comp = struct.unpack("<IiiHHI", _read(addr, 20))
    return w, h, bpp, comp


def _create_dib_section(p):
    w, h, bpp, comp = _bmi(_ptr(_arg(p, 1)))
    if w <= 0 or h == 0 or bpp not in (24, 32) or comp not in (0, 3):
        return _fail(ERROR_INVALID_PARAMETER)
    bm = _Bitmap(w, abs(h), bpp, top_down=h < 0, dib=True)
    hb = _new_handle(bm)
    if not _null(_arg(p, 3)):
        _write_out(_arg(p, 3), "Q", bm.addr)
    return hb


def _create_compatible_bitmap(p):
    w, h = I(_arg(p, 1)), I(_arg(p, 2))
    if w < 0 or h < 0:
        return _fail(ERROR_INVALID_PARAMETER)
    return _new_handle(_Bitmap(max(w, 1), max(h, 1)))


def _create_bitmap(p):
    w, h, planes, bpp = I(_arg(p, 0)), I(_arg(p, 1)), I(_arg(p, 2)), I(_arg(p, 3))
    bm = _Bitmap(max(w, 1), max(h, 1), 24 if bpp == 24 else 32)
    src = _ptr(_arg(p, 4))
    if src and bpp in (24, 32):
        # CreateBitmap rows are WORD-aligned, top-down
        stride = ((w * bpp + 15) // 16) * 2
        raw = ctypes.string_at(src, stride * h) if src >= 0x10000 else _read(src, stride * h)
        for y in range(h):
            ctypes.memmove(bm._row_addr(y), raw[y * stride:y * stride + w * bpp // 8], w * bpp // 8)
    return _new_handle(bm)


def _select_object(p):
    dc = _dc(_ptr(_arg(p, 0)))
    h = _ptr(_arg(p, 1))
    if dc is None:
        return 0
    bm = _bitmap(h)
    if bm is not None:
        if dc.kind != "memory":
            return 0
        if bm.selected and bm.selected is not dc and h != _stock_bitmap():
            return 0                                        # a bitmap can be selected into one DC only
        old = dc.bitmap
        prev = _handles.get(old)
        if isinstance(prev, _Bitmap) and prev.selected is dc:
            prev.selected = 0
        dc.bitmap = h
        if h != _stock_bitmap():
            bm.selected = dc
        return old
    kind = "brush" if isinstance(_handles.get(h), _Brush) else "other"
    old = dc.selected.get(kind) or _stock(kind)
    dc.selected[kind] = h
    return old


def _stock(kind):
    if kind not in _STOCK:
        _STOCK[kind] = _new_handle(_Brush(0xFFFFFF) if kind in ("brush", 0) else "stock")
    return _STOCK[kind]


def _delete_object(p):
    h = _ptr(_arg(p, 0))
    obj = _handles.get(h)
    if isinstance(obj, _Bitmap):
        if obj.selected or h == _STOCK.get("bitmap"):
            return 0
        obj.free()
        _handles.pop(h, None)
        return 1
    if isinstance(obj, _Brush) or obj == "stock":
        if h not in _STOCK.values():
            _handles.pop(h, None)
        return 1
    return 0


def _get_object(p):
    h, cb, out = _ptr(_arg(p, 0)), I(_arg(p, 1)), _ptr(_arg(p, 2))
    obj = _bitmap(h)
    if obj is not None:
        bmp = struct.pack("<iiiiHHxxxxQ", 0, obj.w, obj.h, obj.stride, 1, obj.bpp, obj.addr if obj.dib else 0)
        if obj.dib and (cb >= 104 or not out):
            hdr = struct.pack("<IiiHHIIiiII", 40, obj.w, -obj.h if obj.top_down else obj.h, 1, obj.bpp, 0,
                              obj.size, 0, 0, 0, 0)
            data = bmp + hdr + bytes(12) + bytes(4) + bytes(8) + bytes(4) + bytes(4)    # x64 DIBSECTION: 104
        else:
            data = bmp
        if not out:
            return len(data)
        n = min(cb, len(data))
        _write(out, data[:n])
        return n
    obj = _handles.get(h)
    if isinstance(obj, _Brush):                             # LOGBRUSH
        data = struct.pack("<IIQ", 0, obj.color, 0)
        if out:
            _write(out, data[:min(cb, 16)])
        return min(cb, 16) if out else 16
    return 0


def _object_type(p):
    h = _ptr(_arg(p, 0))
    obj = _handles.get(h)
    if isinstance(obj, _DC):
        return OBJ_MEMDC if obj.kind == "memory" else OBJ_DC
    if _bitmap(h) is not None:
        return OBJ_BITMAP
    if isinstance(obj, _Brush):
        return OBJ_BRUSH
    return 0


def _copy_image(p):
    h, kind, cx, cy = _ptr(_arg(p, 0)), I(_arg(p, 1)), I(_arg(p, 2)), I(_arg(p, 3))
    src = _bitmap(h)
    if kind != 0 or src is None:                            # IMAGE_BITMAP only
        return _fail(ERROR_INVALID_HANDLE)
    w, ht = cx or src.w, cy or src.h
    bm = _Bitmap(w, ht)
    bm.put(0, 0, _scale(src.rows(), src.w, src.h, w, ht))
    flags = I(_arg(p, 4))
    if flags & 0x8:                                         # LR_COPYDELETEORG
        _delete_object([("Ptr", h)])
    return _new_handle(bm)


# ---------------------------------------------------------------- blits
SRCCOPY, NOTSRCCOPY, SRCINVERT, SRCAND, SRCPAINT = 0xCC0020, 0x330008, 0x660046, 0x8800C6, 0xEE0086
BLACKNESS, WHITENESS, DSTINVERT, PATCOPY = 0x42, 0xFF0062, 0x550009, 0xF00021


def _rop(rop, src, dst):
    """Combine two equal-length BGRA rows with a ternary raster operation."""
    n = len(dst)
    if rop == SRCCOPY:
        return src
    if rop == BLACKNESS:
        return bytes(n)
    if rop == WHITENESS:
        return b"\xff" * n
    s = int.from_bytes(src, "little") if src is not None else 0
    d = int.from_bytes(dst, "little")
    mask = (1 << (8 * n)) - 1
    r = {NOTSRCCOPY: ~s & mask, SRCINVERT: s ^ d, SRCAND: s & d, SRCPAINT: s | d,
         DSTINVERT: ~d & mask}.get(rop)
    if r is None:
        return None
    return r.to_bytes(n, "little")


def _blit(dst_dc, x, y, rows, rop):
    if dst_dc.kind != "memory":
        return _fail(ERROR_NOT_SUPPORTED)
    bm = _handles.get(dst_dc.bitmap)
    if not isinstance(bm, _Bitmap) or not rows:
        return 1
    if rop != SRCCOPY:
        w = len(rows[0]) // 4
        cur = bm.rows(x, y, w, len(rows))
        out = []
        for s, d in zip(rows, cur):
            r = _rop(rop, s, d)
            if r is None:
                return _fail(ERROR_INVALID_PARAMETER)
            out.append(r)
        rows = out
    bm.put(x, y, rows)
    return 1


def _bit_blt(p):
    dst = _dc(_ptr(_arg(p, 0)))
    x, y, w, h = (I(_arg(p, i)) for i in (1, 2, 3, 4))
    rop = I(_arg(p, 8)) & 0x00FFFFFF                        # CAPTUREBLT / NOMIRRORBITMAP don't change pixels
    if dst is None:
        return _fail(ERROR_INVALID_HANDLE)
    if rop in (BLACKNESS, WHITENESS, DSTINVERT):
        return _blit(dst, x, y, [bytes(4 * w)] * h, rop)
    src = _dc(_ptr(_arg(p, 5)))
    if src is None:
        return _fail(ERROR_INVALID_HANDLE)
    return _blit(dst, x, y, src.read(I(_arg(p, 6)), I(_arg(p, 7)), w, h), rop)


def _scale(rows, sw, sh, dw, dh):
    """Nearest-neighbour resize of BGRA rows (negative sizes mirror, as StretchBlt does)."""
    if not rows or sw == 0 or sh == 0:
        return [bytes(4 * abs(dw))] * abs(dh)
    fx, fy = dw < 0, dh < 0
    dw, dh = abs(dw), abs(dh)
    cols = [min(int((i + 0.5) * sw / dw), sw - 1) for i in range(dw)]
    if fx:
        cols.reverse()
    out = []
    for j in range(dh):
        row = rows[min(int((j + 0.5) * sh / dh), sh - 1)]
        px = [row[4 * c:4 * c + 4] for c in range(sw)]
        out.append(b"".join(px[c] for c in cols))
    if fy:
        out.reverse()
    return out


def _stretch_blt(p):
    dst = _dc(_ptr(_arg(p, 0)))
    x, y, w, h = (I(_arg(p, i)) for i in (1, 2, 3, 4))
    src = _dc(_ptr(_arg(p, 5)))
    sx, sy, sw, sh = (I(_arg(p, i)) for i in (6, 7, 8, 9))
    rop = I(_arg(p, 10)) & 0x00FFFFFF
    if dst is None or src is None:
        return _fail(ERROR_INVALID_HANDLE)
    rows = src.read(min(sx, sx + sw), min(sy, sy + sh), abs(sw), abs(sh))
    rows = _scale(rows, abs(sw), abs(sh), w * (-1 if sw < 0 else 1), h * (-1 if sh < 0 else 1))
    return _blit(dst, min(x, x + w), min(y, y + h), rows, rop)


def _print_window(p):
    """PrintWindow(hwnd, hdc, flags): the window as it's shown on screen (PW_CLIENTONLY = client area only)."""
    h = _hwnd(_arg(p, 0))
    dst = _dc(_ptr(_arg(p, 1)))
    if dst is None:
        return 0
    src = _DC("window", h, bool(I(_arg(p, 2)) & 1))
    w, ht = src.size()
    if not w:
        return 0
    return _blit(dst, 0, 0, src.read(0, 0, w, ht), SRCCOPY)


# ---------------------------------------------------------------- DIB bits
def _get_dibits(p):
    """GetDIBits(hdc, hbm, start, lines, bits, bmi, usage)."""
    bm = _bitmap(_ptr(_arg(p, 1)))
    start, lines, bits, info = I(_arg(p, 2)), I(_arg(p, 3)), _ptr(_arg(p, 4)), _ptr(_arg(p, 5))
    if bm is None or not info:
        return 0
    size, w, h, _planes, bpp, comp = struct.unpack("<IiiHHI", _read(info, 20))
    if not bits:                                            # fill in the header
        if bpp == 0:
            hdr = struct.pack("<iiHHII", bm.w, bm.h, 1, bm.bpp, 0, bm.size)
            _write(info + 4, hdr)
        else:
            _write(info + 20, struct.pack("<I", ((abs(w) * bpp + 31) // 32) * 4 * abs(h)))
        return bm.h
    if bpp not in (24, 32) or comp not in (0, 3):
        return _fail(ERROR_INVALID_PARAMETER)
    top_down = h < 0
    w = abs(w) or bm.w
    stride = ((w * bpp + 31) // 32) * 4
    rows = bm.rows(0, 0, w, bm.h)                           # top-down
    n = max(0, min(lines, bm.h - start))
    for k in range(n):
        # a bottom-up DIB counts scan lines from the bottom, a top-down one from the top
        src = rows[start + k] if top_down else rows[bm.h - 1 - start - k]
        if bpp == 24:
            src = b"".join(src[i:i + 3] for i in range(0, len(src), 4))
        _write(bits + k * stride, src.ljust(stride, b"\0"))
    return n


def _set_dibits(p):
    """SetDIBits(hdc, hbm, start, lines, bits, bmi, usage)."""
    bm = _bitmap(_ptr(_arg(p, 1)))
    start, lines, bits, info = I(_arg(p, 2)), I(_arg(p, 3)), _ptr(_arg(p, 4)), _ptr(_arg(p, 5))
    if bm is None or not bits or not info:
        return 0
    w, h, bpp, comp = _bmi(info)
    if bpp not in (24, 32):
        return _fail(ERROR_INVALID_PARAMETER)
    stride = ((abs(w) * bpp + 31) // 32) * 4
    n = max(0, min(lines, bm.h - start))
    for k in range(n):
        raw = _read(bits + k * stride, abs(w) * bpp // 8)
        if bpp == 24:
            raw = b"".join(raw[i:i + 3] + b"\0" for i in range(0, len(raw), 3))
        y = start + k if h < 0 else bm.h - 1 - start - k
        bm.put(0, y, [raw])
    return n


def _bitmap_bits(p, setting):
    """GetBitmapBits / SetBitmapBits: the raw 32bpp top-down rows."""
    bm = _bitmap(_ptr(_arg(p, 0)))
    n, buf = I(_arg(p, 1)), _ptr(_arg(p, 2))
    if bm is None or not buf:
        return 0
    stride = bm.w * 4
    n = min(n, stride * bm.h)
    if setting:
        raw = _read(buf, n)
        bm.put(0, 0, [raw[i:i + stride] for i in range(0, n, stride)])
    else:
        _write(buf, b"".join(bm.rows())[:n])
    return n


# ---------------------------------------------------------------- pixels, brushes, FillRect
def _get_pixel(p):
    dc = _dc(_ptr(_arg(p, 0)))
    if dc is None:
        return 0xFFFFFFFF                                   # CLR_INVALID
    x, y = I(_arg(p, 1)), I(_arg(p, 2))
    w, h = dc.size()
    if not (0 <= x < w and 0 <= y < h):
        return 0xFFFFFFFF
    b, g, r, _a = dc.read(x, y, 1, 1)[0]
    return r | g << 8 | b << 16


def _set_pixel(p):
    dc = _dc(_ptr(_arg(p, 0)))
    x, y, c = I(_arg(p, 1)), I(_arg(p, 2)), I(_arg(p, 3)) & 0xFFFFFF
    if dc is None or dc.kind != "memory":
        return 0xFFFFFFFF
    bm = _handles.get(dc.bitmap)
    if not isinstance(bm, _Bitmap) or not (0 <= x < bm.w and 0 <= y < bm.h):
        return 0xFFFFFFFF
    bm.put(x, y, [bytes((c >> 16 & 255, c >> 8 & 255, c & 255, 0))])
    return c


def _fill_rect(p):
    dc = _dc(_ptr(_arg(p, 0)))
    left, top, right, bottom = struct.unpack("<4i", _read(_ptr(_arg(p, 1)), 16))
    br = _arg(p, 2)
    hb = _ptr(br)
    brush = _handles.get(hb)
    if isinstance(brush, _Brush):
        c = brush.color
    elif 0 < hb <= 31:                                      # COLOR_* + 1 instead of a brush
        from .dllcall import _sys_color
        c = _sys_color(hb - 1)
    else:
        return _fail(ERROR_INVALID_HANDLE)
    if dc is None:
        return _fail(ERROR_INVALID_HANDLE)
    w, h = right - left, bottom - top
    if w <= 0 or h <= 0:
        return 1
    px = bytes((c >> 16 & 255, c >> 8 & 255, c & 255, 0))
    return _blit(dc, left, top, [px * w] * h, SRCCOPY)


_STOCK_BRUSHES = {0: 0xFFFFFF, 1: 0xC0C0C0, 2: 0x808080, 3: 0x404040, 4: 0x000000, 5: None}


def _get_stock_object(p):
    i = I(_arg(p, 0))
    key = ("stock", i)
    if key not in _STOCK:
        color = _STOCK_BRUSHES.get(i, 0)
        _STOCK[key] = _new_handle(_Brush(color if color is not None else 0) if i in _STOCK_BRUSHES else "stock")
    return _STOCK[key]


EMU.update({
    "getdc": _get_dc, "getdcex": _get_dc, "getwindowdc": lambda p: _get_dc(p, False),
    "releasedc": lambda p: int(_handles.pop(_ptr(_arg(p, 1)), None) is not None),
    "createdc": _create_dc, "createcompatibledc": _create_compatible_dc, "deletedc": _delete_dc,
    "getdevicecaps": _device_caps,
    "createdibsection": _create_dib_section, "createcompatiblebitmap": _create_compatible_bitmap,
    "createbitmap": _create_bitmap, "selectobject": _select_object, "deleteobject": _delete_object,
    "getobject": _get_object, "getobjecttype": _object_type, "copyimage": _copy_image,
    "getcurrentobject": lambda p: (_dc(_ptr(_arg(p, 0))) or _DC("screen")).bitmap if I(_arg(p, 1)) == OBJ_BITMAP else 0,
    "bitblt": _bit_blt, "stretchblt": _stretch_blt, "printwindow": _print_window,
    "setstretchbltmode": lambda p: _set_stretch_mode(p), "getstretchbltmode": lambda p: getattr(
        _dc(_ptr(_arg(p, 0))), "stretch_mode", 0),
    "getdibits": _get_dibits, "setdibits": _set_dibits,
    "getbitmapbits": lambda p: _bitmap_bits(p, False), "setbitmapbits": lambda p: _bitmap_bits(p, True),
    "getpixel": _get_pixel, "setpixel": _set_pixel, "setpixelv": lambda p: int(_set_pixel(p) != 0xFFFFFFFF),
    "createsolidbrush": lambda p: _new_handle(_Brush(I(_arg(p, 0)) & 0xFFFFFF)),
    "fillrect": _fill_rect, "getstockobject": _get_stock_object,
    "destroyicon": lambda p: 1,
    "gdiflush": lambda p: 1,
})


def _set_stretch_mode(p):
    dc = _dc(_ptr(_arg(p, 0)))
    if dc is None:
        return 0
    old, dc.stretch_mode = dc.stretch_mode, I(_arg(p, 1))
    return old
