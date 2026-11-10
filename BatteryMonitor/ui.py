# Battery Monitor UI layer: display backends, input, drawing and text.
# Shares its design with Collection Art (same author). Pure Python standard library.
import os, sys, time, json, struct, select, glob, math, zlib

HERE = os.path.dirname(os.path.abspath(__file__))
W, H = 640, 480
BG = (9, 11, 18); PANEL = (15, 21, 40); PANEL2 = (24, 32, 60); LINE = (34, 44, 78)
ACC = (84, 104, 227); WHITE = (255, 255, 255); GREY = (150, 160, 190); DIM = (95, 104, 135)
GREEN = (72, 199, 116); YELLOW = (244, 184, 40); RED = (236, 64, 52); TEAL = (43, 170, 160)
ORANGE = (240, 128, 48); BLUE = (66, 103, 178)
LOG = os.path.join(HERE, "last_run.log")

def log(*a):
    try:
        with open(LOG, "a") as f: f.write(time.strftime("%H:%M:%S ") + " ".join(str(x) for x in a) + "\n")
    except OSError: pass

def mix(a, b, k):
    return tuple(int(a[i] + (b[i] - a[i]) * k) for i in range(3))

def load_bin(path):
    with open(path, "rb") as f: data = f.read()
    magic, w, h, ch = struct.unpack(">4sHHB", data[:9])
    return w, h, bytearray(zlib.decompress(data[9:]))

# ======================= display backends =======================
class SDLDisplay:
    def __init__(self, buf):
        import ctypes
        from ctypes import c_void_p, c_int, c_uint32, c_char_p
        lib = None
        for n in ("libSDL2-2.0.so.0", "libSDL2.so", "/usr/lib/libSDL2-2.0.so.0"):
            try: lib = ctypes.CDLL(n); break
            except OSError: pass
        if not lib: raise RuntimeError("no SDL2")
        self.l = l = lib
        l.SDL_Init.argtypes = [c_uint32]
        l.SDL_CreateWindow.restype = c_void_p
        l.SDL_CreateWindow.argtypes = [c_char_p, c_int, c_int, c_int, c_int, c_uint32]
        l.SDL_CreateRenderer.restype = c_void_p; l.SDL_CreateRenderer.argtypes = [c_void_p, c_int, c_uint32]
        l.SDL_CreateTexture.restype = c_void_p; l.SDL_CreateTexture.argtypes = [c_void_p, c_uint32, c_int, c_int, c_int]
        l.SDL_UpdateTexture.argtypes = [c_void_p, c_void_p, c_void_p, c_int]
        l.SDL_RenderClear.argtypes = [c_void_p]; l.SDL_RenderPresent.argtypes = [c_void_p]
        l.SDL_RenderCopy.argtypes = [c_void_p, c_void_p, c_void_p, c_void_p]
        l.SDL_GetError.restype = c_char_p
        if l.SDL_Init(0x20) != 0: raise RuntimeError("SDL_Init: %s" % l.SDL_GetError())
        l.SDL_ShowCursor(0)
        self.win = l.SDL_CreateWindow(b"Battery Monitor", 0x2FFF0000, 0x2FFF0000, W, H, 0x1001 | 0x4)
        if not self.win: raise RuntimeError("window: %s" % l.SDL_GetError())
        self.ren = l.SDL_CreateRenderer(self.win, -1, 0)
        if not self.ren: raise RuntimeError("renderer: %s" % l.SDL_GetError())
        self.tex = l.SDL_CreateTexture(self.ren, 0x17101803, 1, W, H)
        if not self.tex: raise RuntimeError("texture: %s" % l.SDL_GetError())
        self.ptr = ctypes.addressof((ctypes.c_char * len(buf)).from_buffer(buf))
    def present(self):
        l = self.l
        l.SDL_PumpEvents()
        l.SDL_UpdateTexture(self.tex, None, self.ptr, W * 3)
        l.SDL_RenderClear(self.ren); l.SDL_RenderCopy(self.ren, self.tex, None, None); l.SDL_RenderPresent(self.ren)
    def idle(self): self.l.SDL_PumpEvents()
    def close(self):
        try: self.l.SDL_Quit()
        except Exception: pass

class FBDisplay:
    def __init__(self, buf):
        self.buf = buf
        rd = lambda n: open("/sys/class/graphics/fb0/" + n).read().strip()
        if int(rd("bits_per_pixel")) != 32: raise RuntimeError("fb bpp unsupported")
        vw, vh = [int(v) for v in rd("virtual_size").split(",")]
        try: self.stride = int(rd("stride"))
        except Exception: self.stride = vw * 4
        try: self.pany = int(rd("pan").split(",")[1])
        except Exception: self.pany = 0
        self.fd = os.open("/dev/fb0", os.O_RDWR)
        self.out = bytearray(b"\xff" * (W * H * 4))
    def present(self):
        o, b = self.out, self.buf
        o[0::4] = b[2::3]; o[1::4] = b[1::3]; o[2::4] = b[0::3]
        rowb = W * 4
        if self.stride == rowb:
            os.pwrite(self.fd, bytes(o), self.pany * self.stride)
        else:
            for y in range(H):
                os.pwrite(self.fd, bytes(o[y*rowb:(y+1)*rowb]), (self.pany + y) * self.stride)
    def idle(self): pass
    def close(self):
        try: os.close(self.fd)
        except OSError: pass

class DumpDisplay:          # headless, used for testing on a PC
    def __init__(self, buf): self.buf = buf
    def present(self): pass
    def idle(self): pass
    def close(self): pass

# ======================= input =======================
class Input:
    UP, DOWN, LEFT, RIGHT, OK, BACK, L1, R1 = "up", "down", "left", "right", "ok", "back", "l1", "r1"
    def __init__(self):
        self.fds = []; self.size = struct.calcsize("llHHi"); self.script = []
        for p in sorted(glob.glob("/dev/input/event*")):
            try: self.fds.append(os.open(p, os.O_RDONLY | os.O_NONBLOCK))
            except OSError: pass
    def poll(self):
        acts = []
        if self.script: acts.append(self.script.pop(0))
        if not self.fds: return acts
        try: r, _, _ = select.select(self.fds, [], [], 0)
        except Exception: return acts
        for fd in r:
            try: data = os.read(fd, self.size * 64)
            except OSError: continue
            for i in range(0, len(data) - self.size + 1, self.size):
                _, _, typ, code, val = struct.unpack("llHHi", data[i:i+self.size])
                if typ == 1 and val in (1, 2):
                    if code in (103, 544): acts.append(self.UP)
                    elif code in (108, 545): acts.append(self.DOWN)
                    elif code in (105, 546): acts.append(self.LEFT)
                    elif code in (106, 547): acts.append(self.RIGHT)
                    elif code in (310, 312): acts.append(self.L1)
                    elif code in (311, 313): acts.append(self.R1)
                    elif code in (304, 305, 307, 308, 315, 28, 57): acts.append(self.OK)
                    elif code in (314, 316, 1, 158, 139): acts.append(self.BACK)
                elif typ == 3 and code in (16, 17) and val != 0:
                    if code == 17: acts.append(self.UP if val < 0 else self.DOWN)
                    else: acts.append(self.LEFT if val < 0 else self.RIGHT)
        return acts

# ======================= drawing =======================
class Gfx:
    def __init__(self):
        self.buf = bytearray(bytes(BG) * (W * H))
        self.bgfull = bytes(self.buf)
        self.fonts = json.load(open(os.path.join(HERE, "assets", "font.json")))
        self.atlas = load_bin(os.path.join(HERE, "assets", "font.bin"))
        self.logo_s = load_bin(os.path.join(HERE, "assets", "logo_small.bin"))
        self.icon = load_bin(os.path.join(HERE, "assets", "icon_big.bin"))
        self.cache = {}; self.luts = {}

    def clear(self): self.buf[:] = self.bgfull

    def rect(self, x, y, w, h, col):
        x0, y0 = max(0, int(x)), max(0, int(y)); x1, y1 = min(W, int(x + w)), min(H, int(y + h))
        if x1 <= x0 or y1 <= y0: return
        row = bytes(col) * (x1 - x0); b = self.buf
        for yy in range(y0, y1):
            o = (yy * W + x0) * 3; b[o:o + len(row)] = row

    def rrect(self, x, y, w, h, r, col):
        r = min(r, h // 2, w // 2)
        for yy in range(h):
            if yy < r: dy = r - yy - 0.5
            elif yy >= h - r: dy = yy - (h - r) + 0.5
            else: dy = 0
            ins = int(round(r - math.sqrt(max(0, r * r - dy * dy)))) if dy else 0
            self.rect(x + ins, y + yy, w - 2 * ins, 1, col)

    def blit(self, img, x, y, sw=None):
        iw, ih, d = img
        sw = iw if sw is None else max(0, min(iw, sw))
        x0 = max(0, x); x1 = min(W, x + sw)
        if x1 <= x0: return
        b = self.buf
        for yy in range(ih):
            ty = y + yy
            if 0 <= ty < H:
                b[(ty*W + x0)*3:(ty*W + x1)*3] = d[(yy*iw + x0 - x)*3:(yy*iw + x1 - x)*3]

    def vspan(self, x, y0, y1, col, thick=2):
        if y0 > y1: y0, y1 = y1, y0
        self.rect(x, y0, thick, y1 - y0 + thick, col)

    def line(self, x0, y0, x1, y1, col, thick=2):
        dx = x1 - x0; dy = y1 - y0
        n = max(abs(dx), abs(dy), 1)
        for i in range(n + 1):
            self.rect(int(x0 + dx * i / n), int(y0 + dy * i / n), thick, thick, col)

    def circle(self, cx, cy, r, col):
        for yy in range(-r, r + 1):
            w = int(math.sqrt(max(0, r * r - yy * yy)))
            self.rect(cx - w, cy + yy, 2 * w + 1, 1, col)

    # ---------- text ----------
    def text_img(self, s, size="m", fg=WHITE, bg=BG):
        key = (s, size, fg, bg)
        img = self.cache.get(key)
        if img: return img
        f = self.fonts[size]; ch = f["chars"]; lh = f["h"]; ay = f["y"]
        aw, _, ad = self.atlas
        glyphs = [ch.get(str(ord(c)), ch["63"]) for c in s]
        tw = max(1, sum(g[1] for g in glyphs))
        out = bytearray(bytes(bg) * (tw * lh))
        lut = self.luts.get((fg, bg))
        if lut is None:
            lut = self.luts[(fg, bg)] = [bytes(mix(bg, fg, a / 255.0)) for a in range(256)]
        x = 0
        for gx, gw in glyphs:
            for yy in range(lh):
                row = ad[(ay + yy) * aw + gx:(ay + yy) * aw + gx + gw]
                if any(row):
                    o = (yy * tw + x) * 3
                    out[o:o + gw * 3] = b"".join(lut[a] for a in row)
            x += gw
        img = (tw, lh, out)
        if len(self.cache) > 600: self.cache.clear()
        self.cache[key] = img
        return img

    def width(self, s, size="m"):
        ch = self.fonts[size]["chars"]; return sum(ch.get(str(ord(c)), ch["63"])[1] for c in s)

    def fit(self, s, size, maxw):
        if self.width(s, size) <= maxw: return s
        while s and self.width(s + "…", size) > maxw: s = s[:-1]
        return s + "…"

    def text(self, s, x, y, size="m", fg=WHITE, bg=BG, align="left", maxw=None):
        if maxw: s = self.fit(s, size, maxw)
        img = self.text_img(s, size, fg, bg)
        if align == "center": x -= img[0] // 2
        elif align == "right": x -= img[0]
        self.blit(img, int(x), int(y)); return img[0]

def ease(t): t = max(0.0, min(1.0, t)); return 1 - (1 - t) ** 3
