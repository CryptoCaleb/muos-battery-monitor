#!/usr/bin/env python3
# Battery Monitor v1.0 for muOS - created by Caleb Hinton
import os, sys, time, math, threading, traceback

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import batt
from ui import *

VERSION = "1.0"
AUTHOR = "Caleb Hinton"
DATA = os.path.join(HERE, "data")
LOGFILE = os.path.join(DATA, "battery.csv")
SETTINGS = os.path.join(DATA, "settings.json")
INIT_DIRS = ["/mnt/mmc/MUOS/init"]
INIT_NAME = "batterymonitor_log.sh"
TABS = ["Overview", "History", "Sessions", "Health", "Settings"]
RANGES = [("6 hours", 6), ("24 hours", 24), ("3 days", 72), ("7 days", 168)]
CAPS = [2000, 2600, 3000, 3200, 3300, 3500, 4000, 4500, 5000, 6000]
TOP, BOT = 104, 426          # content area


def level_col(c):
    if c is None: return GREY
    return GREEN if c > 50 else (YELLOW if c > 20 else RED)

def hm(t):
    return time.strftime("%a %H:%M", time.localtime(t))


class App:
    def __init__(self, display_cls=None):
        open(LOG, "w").close()
        self.g = Gfx(); self.inp = Input(); self.disp = None
        for cls in ([display_cls] if display_cls else [SDLDisplay, FBDisplay]):
            try: self.disp = cls(self.g.buf); log("display:", cls.__name__); break
            except Exception as e: log("display", cls.__name__, "failed:", e)
        if not self.disp: self.disp = DumpDisplay(self.g.buf)
        self.bat, self.ext = batt.find_supplies()
        self.info = batt.battery_info(self.bat)
        log("battery:", self.bat, "chargers:", self.ext, "info:", self.info)
        self.settings = batt.load_settings(SETTINGS)
        if "design_mah" not in self.settings:
            self.settings["design_mah"] = int(self.info.get("charge_full_design") or batt.DEFAULT_DESIGN_MAH)
        self.live = batt.read_now(self.bat, self.ext)
        self.rows = []; self.loaded = False; self.an = None
        self.tab = 0; self.range = 1; self.scroll = 0; self.sel = 0; self.confirm = False
        self.dirty = True; self.last_read = 0; self.last_an = 0
        threading.Thread(target=self.load_history, daemon=True).start()

    # ---------- data ----------
    def load_history(self):
        try:
            self.rows = batt.load(LOGFILE, since=time.time() - 30 * 86400)
            log("history rows:", len(self.rows))
        except Exception as e:
            log("history load failed", e)
        self.loaded = True; self.analyse()

    def analyse(self):
        rows = list(self.rows)
        if self.live and self.live.cap is not None:
            # ignore samples stamped after "now" (e.g. the clock was reset) so trends stay correct
            rows = [r for r in rows if r.t <= self.live.t + 60] + [self.live]
        rows.sort(key=lambda r: r.t)
        self.an = batt.Analysis(rows, self.live, self.settings["design_mah"], self.info)
        self.last_an = time.time(); self.dirty = True

    def tick(self):
        now = time.time()
        if now - self.last_read >= 2:
            self.last_read = now
            r = batt.read_now(self.bat, self.ext)
            if r:
                changed = (not self.live or r.cap != self.live.cap or r.status != self.live.status)
                self.live = r
                if self.tab == 0: self.dirty = True
                # keep history while the app is open (background logger does it the rest of the time)
                lt = batt.last_time(LOGFILE)
                if r.cap is not None and (lt is None or now - lt >= 58):
                    try: batt.append(LOGFILE, r); self.rows.append(r)
                    except OSError as e: log("append failed", e)
                if self.loaded and (changed or now - self.last_an > 30): self.analyse()

    def logging_on(self):
        return any(os.path.exists(os.path.join(d, INIT_NAME)) for d in INIT_DIRS)

    def set_logging(self, on):
        for d in INIT_DIRS:
            p = os.path.join(d, INIT_NAME)
            try:
                if on:
                    os.makedirs(d, exist_ok=True)
                    with open(p, "w") as f:
                        f.write("#!/bin/sh\n# Battery Monitor background logger (created by the Battery Monitor app)\n"
                                "( for i in $(seq 1 60); do\n"
                                "    for a in /run/muos/storage/application/BatteryMonitor /mnt/sdcard/MUOS/application/BatteryMonitor /mnt/mmc/MUOS/application/BatteryMonitor; do\n"
                                "      [ -f \"$a/logger.sh\" ] && exec sh \"$a/logger.sh\"\n"
                                "    done; sleep 5\n"
                                "  done ) >/dev/null 2>&1 &\n")
                    os.chmod(p, 0o755)
                    os.system("setsid sh '%s' >/dev/null 2>&1 < /dev/null &" % os.path.join(HERE, "logger.sh"))
                elif os.path.exists(p):
                    os.remove(p)
                    os.system("pkill -f BatteryMonitor/logger.sh >/dev/null 2>&1")
            except OSError as e:
                log("logging toggle failed", e)

    def frame(self): self.disp.present()

    # ---------- common chrome ----------
    def header(self):
        g = self.g; g.clear()
        g.blit(g.logo_s, 24, 18)
        r = self.live
        if r and r.cap is not None:
            col = level_col(r.cap)
            label = {"chg": "Charging", "full": "Full", "dis": "On battery"}[r.mode]
            txt = "%s  %d%%" % (label, r.cap)
            w = g.width(txt, "s")
            g.rrect(W - 24 - w - 44, 22, w + 44, 28, 14, PANEL)
            g.circle(W - 24 - w - 26, 36, 5, GREEN if r.mode != "dis" else col)
            g.text(txt, W - 36, 27, "s", WHITE, bg=PANEL, align="right")
        x = 24
        for i, t in enumerate(TABS):
            on = i == self.tab
            w = g.width(t, "m")
            g.text(t, x, 70, "m", WHITE if on else DIM)
            if on: g.rect(x, 94, w, 3, ACC)
            x += w + 26
        g.rect(24, 97, W - 48, 1, LINE)

    def footer(self, hint):
        g = self.g
        g.rect(24, 434, W - 48, 1, LINE)
        g.text(hint, W // 2, 446, "s", DIM, align="center")

    def card(self, x, y, w, h, title, value, sub=None, vcol=WHITE):
        g = self.g
        g.rrect(x, y, w, h, 14, PANEL)
        g.text(title, x + 16, y + 12, "s", GREY, bg=PANEL)
        g.text(value, x + 16, y + 34, "l", vcol, bg=PANEL, maxw=w - 28)
        if sub: g.text(sub, x + 16, y + h - 26, "s", DIM, bg=PANEL, maxw=w - 28)

    def battery_icon(self, x, y, w, h, level, col, charging=False, frac=None):
        g = self.g
        g.rrect(x, y, w, h, 16, WHITE)
        g.rrect(x + 5, y + 5, w - 10, h - 10, 12, BG)
        g.rrect(x + w, y + h // 2 - 18, 12, 36, 5, WHITE)
        k = (level or 0) / 100.0 if frac is None else frac
        fw = int((w - 20) * max(0.0, min(1.0, k)))
        if fw >= 6: g.rrect(x + 10, y + 10, fw, h - 20, 8, col)
        if charging:   # lightning bolt
            cx, cy = x + w // 2, y + h // 2
            pts = [(cx + 8, cy - 30), (cx - 14, cy + 4), (cx + 2, cy + 4), (cx - 8, cy + 30), (cx + 16, cy - 6), (cx, cy - 6), (cx + 8, cy - 30)]
            for (ax, ay), (bx, by) in zip(pts, pts[1:]): g.line(ax, ay, bx, by, WHITE, 4)

    # ---------- chart ----------
    def chart(self, x, y, w, h, rows, t0, t1, getv, vmin, vmax, col, fill=True, shade_chg=True, grid=None, yfmt=None):
        g = self.g
        g.rrect(x - 8, y - 8, w + 16, h + 16, 12, PANEL)
        gys = [(gv, y + h - int((gv - vmin) / (vmax - vmin) * h)) for gv in (grid or [])]
        for gv, gy in gys: g.rect(x, gy, w, 1, LINE)
        def labels():
            if yfmt:
                for gv, gy in gys:
                    lab = yfmt(gv); lw = g.width(lab, "s")
                    ly = gy + 2 if gv == vmax else gy - 18
                    g.rect(x + 2, ly, lw + 6, 17, PANEL); g.text(lab, x + 5, ly, "s", DIM, bg=PANEL)
        if t1 <= t0: labels(); return
        span = t1 - t0
        cols = [None] * w; chg = [False] * w; sums = [0.0] * w; cnt = [0] * w
        for r in rows:
            if r.t < t0 or r.t > t1: continue
            v = getv(r)
            if v is None: continue
            c = min(w - 1, int((r.t - t0) / span * w))
            sums[c] += v; cnt[c] += 1
            if r.mode == "chg": chg[c] = True
        for c in range(w):
            if cnt[c]: cols[c] = sums[c] / cnt[c]
        # bridge columns between samples unless the gap means the device was off
        gap_cols = max(2, int(batt.GAP / span * w))
        last = None
        for c in range(w):
            if cols[c] is not None:
                if last is not None and 1 < c - last <= gap_cols:
                    for k in range(last + 1, c):
                        f = (k - last) / (c - last)
                        cols[k] = cols[last] + (cols[c] - cols[last]) * f; chg[k] = chg[last] and chg[c]
                last = c
        fillc = mix(PANEL, col, 0.22); chgc = mix(PANEL, GREEN, 0.16)
        prev = None
        for c in range(w):
            v = cols[c]
            if v is None: prev = None; continue
            py = y + h - int((max(vmin, min(vmax, v)) - vmin) / (vmax - vmin) * h)
            if shade_chg and chg[c]: g.rect(x + c, y, 1, py - y, chgc)
            if fill: g.rect(x + c, py, 1, y + h - py, fillc)
            g.vspan(x + c, prev if prev is not None else py, py, col, 2)
            prev = py
        labels()

    def time_axis(self, x, y, w, t0, t1, hours):
        g = self.g
        n = 4
        for i in range(n + 1):
            t = t0 + (t1 - t0) * i / n
            if hours <= 24: lab = time.strftime("%H:%M", time.localtime(t))
            else: lab = time.strftime("%a %H:%M", time.localtime(t))
            if i == n: lab = "now"
            al = "left" if i == 0 else ("right" if i == n else "center")
            g.text(lab, x + int(w * i / n), y, "s", DIM, align=al)

    # ---------- screens ----------
    def draw_overview(self):
        g = self.g; r = self.live; an = self.an
        if not r or r.cap is None:
            g.text("No battery found", W // 2, 220, "l", WHITE, align="center")
            g.text("Details are in last_run.log in the app folder.", W // 2, 256, "s", GREY, align="center")
            return
        col = level_col(r.cap)
        self.battery_icon(36, 122, 196, 104, r.cap, col, charging=(r.mode == "chg"))
        g.text("%d%%" % r.cap, 140, 240, "x", WHITE, align="center")
        sub = {"chg": "Charging", "full": "Fully charged", "dis": "On battery"}[r.mode]
        g.text(sub, 140, 292, "m", col if r.mode == "dis" else GREEN, align="center")
        cx, cw, ch = 270, 168, 90
        if r.mode == "chg":
            ttf = an.time_to_full() if an else None
            self.card(cx, 112, cw, ch, "Full in", batt.fmt_dur(ttf), "estimated", GREEN)
            rate = an.charge_now() if an else None
            self.card(cx + cw + 10, 112, cw, ch, "Charge rate", ("%.0f%%/h" % rate) if rate else "--",
                      ("%.1f W in" % r.watts) if r.watts else "measuring…")
        elif r.mode == "full":
            self.card(cx, 112, cw, ch, "Status", "Full", "unplug any time", GREEN)
            fr = an.full_runtime() if an else None
            self.card(cx + cw + 10, 112, cw, ch, "Full charge lasts", batt.fmt_dur(fr), "typical use")
        else:
            tl = an.time_left() if an else None
            self.card(cx, 112, cw, ch, "Time left", batt.fmt_dur(tl), "at current drain", col)
            rate = an.drain_now() if an else None
            parts = []
            if r.watts: parts.append("%.1f W" % r.watts)
            if r.ma is not None: parts.append("%d mA" % abs(r.ma))
            self.card(cx + cw + 10, 112, cw, ch, "Drain now", ("%.0f%%/h" % rate) if rate else "--",
                      " · ".join(parts) or "measuring…")
        self.card(cx, 212, cw, ch, "Voltage", ("%.2f V" % (r.mv / 1000)) if r.mv else "--",
                  ("Temp %.0f°C" % r.temp) if r.temp is not None else None)
        if r.mode == "dis":
            fr = an.full_runtime() if an else None
            self.card(cx + cw + 10, 212, cw, ch, "Full charge lasts", batt.fmt_dur(fr), "typical use")
        else:
            h = an.health if an else None
            self.card(cx + cw + 10, 212, cw, ch, "Battery health", ("%d%%" % round(h * 100)) if h else "--",
                      an.grade()[0] if an else None)
        # last 6 hours sparkline
        now = r.t
        g.text("Last 6 hours", 24, 318, "s", GREY)
        if self.loaded:
            rows = [x for x in self.rows if x.t >= now - 6 * 3600] + [r]
            self.chart(32, 346, W - 64, 70, rows, now - 6 * 3600, now, lambda q: q.cap, 0, 100, col, shade_chg=True)
        else:
            g.rrect(24, 338, W - 48, 86, 12, PANEL); g.text("Loading history…", W // 2, 370, "s", DIM, bg=PANEL, align="center")

    def draw_history(self):
        g = self.g; now = self.live.t if self.live else time.time()
        name, hours = RANGES[self.range]
        t0 = now - hours * 3600
        rows = [x for x in self.rows if x.t >= t0] + ([self.live] if self.live else [])
        g.text("Battery level · " + name, 24, 108, "m", WHITE)
        g.text("↑↓ change range", W - 24, 110, "s", DIM, align="right")
        self.chart(56, 148, W - 88, 130, rows, t0, now, lambda q: q.cap, 0, 100, ACC,
                   grid=[0, 50, 100], yfmt=lambda v: "%d%%" % v)
        self.time_axis(56, 290, W - 88, t0, now, hours)
        # legend
        g.rect(24, 318, 12, 12, mix(PANEL, GREEN, 0.5)); g.text("charging", 42, 315, "s", GREY)
        watts = [x.watts for x in rows if x.watts is not None and x.mode == "dis"]
        if watts:
            top = max(1.0, math.ceil(max(watts)))
            g.text("Power draw on battery (W)", 140, 315, "s", GREY)
            self.chart(56, 346, W - 88, 70, [x for x in rows if x.mode == "dis"], t0, now, lambda q: q.watts,
                       0, top, ORANGE, shade_chg=False, grid=[0, top], yfmt=lambda v: "%.0fW" % v)
        else:
            temps = [x.temp for x in rows if x.temp is not None]
            if temps:
                lo, hi = math.floor(min(temps)) - 2, math.ceil(max(temps)) + 2
                g.text("Temperature (°C)", 140, 315, "s", GREY)
                self.chart(56, 346, W - 88, 70, rows, t0, now, lambda q: q.temp, lo, hi, RED, shade_chg=False,
                           grid=[lo, hi], yfmt=lambda v: "%d°" % v)
            else:
                g.rrect(48, 338, W - 72, 86, 12, PANEL)
                g.text("No power or temperature data from this battery driver", W // 2, 370, "s", DIM, bg=PANEL, align="center")

    def draw_sessions(self):
        g = self.g; an = self.an
        ss = list(reversed(an.sessions)) if an else []
        g.text("Recent sessions", 24, 108, "m", WHITE)
        if not ss:
            g.rrect(24, 140, W - 48, 270, 14, PANEL)
            g.text("No sessions yet", W // 2, 230, "l", WHITE, bg=PANEL, align="center")
            g.text("Turn on Background logging in Settings, then play and charge as usual.", W // 2, 266, "s", GREY, bg=PANEL, align="center")
            return
        # bar chart: newest on the right
        bars = list(reversed(ss[:16]))
        top = max(10, math.ceil(max(s.rate for s in bars) / 10.0) * 10)
        bx, by, bw, bh = 40, 146, W - 80, 88
        g.rrect(24, 136, W - 48, bh + 34, 12, PANEL)
        slot = bw / len(bars)
        for i, s in enumerate(bars):
            hh = max(2, int(s.rate / top * bh))
            c = GREEN if s.mode == "chg" else ORANGE
            g.rrect(int(bx + i * slot + slot * 0.18), by + bh - hh, max(4, int(slot * 0.64)), hh, 3, c)
        g.text("%d%%/h" % top, W - 32, 140, "s", DIM, bg=PANEL, align="right")
        g.rect(28, 252, 10, 10, ORANGE); g.text("play (drain %/h)", 44, 249, "s", GREY)
        g.rect(196, 252, 10, 10, GREEN); g.text("charge (%/h)", 212, 249, "s", GREY)
        g.text("↑↓ scroll", W - 24, 249, "s", DIM, align="right")
        # list
        y = 276; self.scroll = max(0, min(self.scroll, len(ss) - 5))
        for s in ss[self.scroll:self.scroll + 5]:
            g.rrect(24, y, W - 48, 28, 8, PANEL)
            c = GREEN if s.mode == "chg" else ORANGE
            g.circle(40, y + 14, 5, c)
            g.text(hm(s.t0), 54, y + 5, "s", WHITE, bg=PANEL)
            g.text("Charge" if s.mode == "chg" else "Play", 170, y + 5, "s", c, bg=PANEL)
            g.text("%d%% → %d%%" % (s.c0, s.c1), 250, y + 5, "s", WHITE, bg=PANEL)
            g.text(batt.fmt_dur(s.hours), 380, y + 5, "s", GREY, bg=PANEL)
            g.text("%.0f%%/h" % s.rate, W - 40, y + 5, "s", WHITE, bg=PANEL, align="right")
            y += 31

    def draw_health(self):
        g = self.g; an = self.an
        if not an: return
        grade, why = an.grade(); h = an.health
        gc = GREEN if h and h >= 0.9 else (TEAL if h and h >= 0.8 else (YELLOW if h and h >= 0.7 else (RED if h else GREY)))
        g.rrect(24, 108, 300, 132, 14, PANEL)
        g.text("Battery health", 40, 118, "s", GREY, bg=PANEL)
        g.text(grade, 40, 138, "l", gc, bg=PANEL)
        if h: g.text("%d%%" % round(h * 100), 308, 132, "x", WHITE, bg=PANEL, align="right")
        g.rrect(40, 186, 268, 12, 6, PANEL2)
        if h: g.rrect(40, 186, max(12, int(268 * min(1, h))), 12, 6, gc)
        g.text(why, 40, 208, "s", DIM, bg=PANEL, maxw=270)
        # stats
        y = 252
        cap = an.est_capacity
        stats = [
            ("Estimated capacity", ("%d mAh" % cap) if cap else "learning…", "design %d mAh" % an.design),
            ("Charge cycles", "%.1f" % an.cycles if an.cycles else "0", "full 100% equivalents logged"),
            ("Typical drain", ("%.0f%%/h" % an.typ_drain) if an.typ_drain else "--",
             ("full charge lasts " + batt.fmt_dur(an.full_runtime())) if an.typ_drain else "last 7 days"),
            ("Typical charge", ("%.0f%%/h" % an.typ_charge) if an.typ_charge else "--",
             ("0-100% in about " + batt.fmt_dur(an.full_charge_time())) if an.typ_charge else "last 7 days"),
            ("Temperature", ("avg %.0f°  max %.0f°C" % (an.temp_avg, an.temp_max)) if an.temp_avg is not None else "--", None),
        ]
        for label, val, sub in stats:
            g.text(label, 24, y, "s", GREY)
            g.text(val, 324, y, "s", WHITE, align="right")
            if sub: g.text(sub, 24, y + 17, "s", DIM, maxw=300)
            y += 36 if sub else 26
        # discharge curve: voltage vs %
        x0, y0, cw, ch = 360, 116, 252, 250
        g.rrect(x0 - 12, 108, cw + 24, ch + 50, 14, PANEL)
        g.text("Discharge curve", x0, 118, "s", GREY, bg=PANEL)
        pts = [(r.cap, r.mv) for r in an.rows if r.mode == "dis" and r.mv]
        px0, py0, pw, ph = x0 + 6, 148, cw - 12, ch - 66
        for gv in (3.4, 3.7, 4.0, 4.3):
            gy = py0 + ph - int((gv - 3.3) / 1.0 * ph)
            g.rect(px0, gy, pw, 1, LINE); g.text("%.1fV" % gv, px0 + 2, gy - 16, "s", DIM, bg=PANEL)
        if pts:
            step = max(1, len(pts) // 1500)
            for c, mv in pts[::step]:
                v = mv / 1000.0
                if 3.3 <= v <= 4.3:
                    g.rect(px0 + int(c / 100.0 * (pw - 3)), py0 + ph - int((v - 3.3) * ph), 3, 3, TEAL)
        else:
            g.text("no voltage data yet", x0 + cw // 2, py0 + ph // 2, "s", DIM, bg=PANEL, align="center")
        g.text("0%", px0, py0 + ph + 6, "s", DIM, bg=PANEL); g.text("100%", px0 + pw, py0 + ph + 6, "s", DIM, bg=PANEL, align="right")
        g.text("Lower, steeper curves mean wear", x0 + cw // 2, py0 + ph + 30, "s", DIM, bg=PANEL, align="center")
        if self.info.get("cycle_count") or self.info.get("health"):
            extra = "Driver reports: " + " · ".join(x for x in (
                ("%s cycles" % self.info["cycle_count"]) if self.info.get("cycle_count") else "",
                self.info.get("health", "")) if x)
            g.text(extra, 24, 410, "s", DIM)

    SETTINGS_ITEMS = ["logging", "capacity", "clear", "credits", "exit"]
    def setting_label(self, k):
        if k == "logging": return "Background logging: " + ("On" if self.logging_on() else "Off")
        if k == "capacity": return "Battery design capacity: %d mAh" % self.settings["design_mah"]
        if k == "clear": return "Really clear all history? Press A again" if self.confirm else "Clear battery history"
        if k == "credits": return "Credits"
        return "Exit"
    SETTING_DESC = {"logging": "Records one reading a minute in the background, even while you play.",
                    "capacity": "A steps through common sizes. RG35XX Pro ships with 3300 mAh.",
                    "clear": "Deletes all logged battery data.", "credits": "Who made Battery Monitor.",
                    "exit": "Go back to muOS."}
    def draw_settings(self):
        g = self.g
        y = 112
        for i, k in enumerate(self.SETTINGS_ITEMS):
            on = i == self.sel
            col = (RED if (k == "clear" and self.confirm) else ACC) if on else PANEL
            g.rrect(24, y, W - 48, 42, 12, col)
            g.text(self.setting_label(k), 44, y + 10, "m", WHITE, bg=col)
            y += 50
        g.text(self.SETTING_DESC[self.SETTINGS_ITEMS[self.sel]], W // 2, 368, "s", GREY, align="center")
        n = len(self.rows)
        since = ("logging since " + time.strftime("%b %d", time.localtime(self.rows[0].t))) if n else "no history yet"
        size = os.path.getsize(LOGFILE) / 1024.0 if os.path.exists(LOGFILE) else 0
        g.text("%d readings · %s · %.0f KB" % (n, since, size), W // 2, 394, "s", DIM, align="center")

    def draw_intro(self, t):
        g = self.g; g.clear()
        k = ease(t / 0.9)
        lvl = k
        col = RED if lvl < 0.25 else (YELLOW if lvl < 0.55 else GREEN)
        self.battery_icon(W // 2 - 110, 118, 220, 116, lvl * 100, col, frac=lvl)
        k2 = ease((t - 0.6) / 0.4)
        if k2 > 0:
            title = g.text_img("Battery Monitor", "x")
            g.blit(title, W // 2 - title[0] // 2, 270 + int(20 * (1 - k2)), sw=int(title[0] * min(1, k2 * 1.3)))
        k3 = ease((t - 0.9) / 0.4)
        if k3 > 0:
            sub = g.text_img("created by " + AUTHOR, "m", GREY)
            g.blit(sub, W // 2 - sub[0] // 2, 336, sw=int(sub[0] * k3))

    def draw_credits(self, t):
        g = self.g; g.clear()
        bob = int(4 * math.sin(t * 2.2))
        g.blit(g.icon, W // 2 - 60, 34 + bob)
        g.text("Battery Monitor", W // 2, 170, "x", WHITE, align="center")
        g.text("Version " + VERSION, W // 2, 222, "s", ACC, align="center")
        g.text("Created by " + AUTHOR, W // 2, 258, "l", WHITE, align="center")
        for i, l in enumerate(["Made for muOS on the Anbernic RG35XX Pro",
                               "Battery stats, graphs and health at a glance",
                               "Built with Claude"]):
            g.text(l, W // 2, 304 + i * 24, "s", GREY, align="center")
        k = (math.sin(t * 1.5) + 1) / 2
        bw = int(80 + 480 * k)
        g.rrect(W // 2 - 280, 398, 560, 8, 4, PANEL2)
        g.rrect(W // 2 - 280, 398, bw, 8, 4, mix(RED, GREEN, k))
        g.text("Press any button to go back", W // 2, 440, "s", DIM, align="center")

    def draw(self):
        self.header()
        [self.draw_overview, self.draw_history, self.draw_sessions, self.draw_health, self.draw_settings][self.tab]()
        hints = ["L1/R1 or ←→  Tabs     Menu  Quit",
                 "←→ Tabs     ↑↓ Range     Menu  Quit",
                 "←→ Tabs     ↑↓ Scroll     Menu  Quit",
                 "←→ Tabs     Menu  Quit",
                 "↑↓ Move     A  Select     ←→ Tabs"]
        self.footer(hints[self.tab])

    # ---------- flows ----------
    def intro(self):
        t0 = time.time()
        while True:
            t = time.time() - t0
            self.draw_intro(t); self.frame()
            if self.inp.poll() and t > 0.15: return
            if t > 1.6 and self.loaded: return
            if t > 4: return
            time.sleep(1 / 40)

    def credits(self):
        t0 = time.time(); time.sleep(0.15); self.inp.poll()
        while True:
            self.draw_credits(time.time() - t0); self.frame()
            if self.inp.poll(): return
            time.sleep(1 / 30)

    def handle(self, a):
        self.dirty = True
        if a in (Input.LEFT, Input.L1): self.tab = (self.tab - 1) % len(TABS); self.confirm = False; return
        if a in (Input.RIGHT, Input.R1): self.tab = (self.tab + 1) % len(TABS); self.confirm = False; return
        if a == Input.BACK: return "quit"
        if self.tab == 1:
            if a == Input.UP: self.range = min(len(RANGES) - 1, self.range + 1)
            elif a == Input.DOWN: self.range = max(0, self.range - 1)
        elif self.tab == 2:
            if a == Input.UP: self.scroll = max(0, self.scroll - 1)
            elif a == Input.DOWN: self.scroll += 1
        elif self.tab == 4:
            if a == Input.UP: self.sel = (self.sel - 1) % len(self.SETTINGS_ITEMS); self.confirm = False
            elif a == Input.DOWN: self.sel = (self.sel + 1) % len(self.SETTINGS_ITEMS); self.confirm = False
            elif a == Input.OK:
                k = self.SETTINGS_ITEMS[self.sel]
                if k == "exit": return "quit"
                if k == "logging": self.set_logging(not self.logging_on())
                elif k == "capacity":
                    cur = self.settings["design_mah"]
                    nxt = [c for c in CAPS if c > cur]
                    self.settings["design_mah"] = nxt[0] if nxt else CAPS[0]
                    batt.save_settings(SETTINGS, self.settings); self.analyse()
                elif k == "clear":
                    if self.confirm:
                        try: open(LOGFILE, "w").close()
                        except OSError: pass
                        self.rows = []; self.confirm = False; self.analyse()
                    else: self.confirm = True
                elif k == "credits":
                    self.credits()

    def main(self):
        self.intro()
        while True:
            self.tick()
            if self.dirty:
                self.draw(); self.frame(); self.dirty = False
            for a in self.inp.poll():
                if self.handle(a) == "quit": return
            self.disp.idle(); time.sleep(0.03)


if __name__ == "__main__":
    app = None
    try:
        app = App(); app.main()
    except Exception:
        log(traceback.format_exc())
    finally:
        if app and app.disp: app.disp.close()
