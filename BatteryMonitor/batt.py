# Battery Monitor engine - reading, logging and analytics. Pure Python standard library.
import os, time, json

SYS = os.environ.get("BATTMON_SYSFS", "/sys/class/power_supply")
GAP = 900              # seconds without a sample = device was off / asleep
DEFAULT_DESIGN_MAH = 3300   # Anbernic RG35XX Pro


# ---------------- reading ----------------
def _rd(path, name):
    try:
        with open(os.path.join(path, name)) as f:
            return f.read().strip()
    except OSError:
        return None

def _num(s):
    try:
        return float(s)
    except (TypeError, ValueError):
        return None

def norm_mv(v):
    """voltage_now is usually microvolts; accept mV or V too"""
    if v is None: return None
    if v > 100000: return v / 1000.0
    if v < 20: return v * 1000.0
    return v

def norm_ma(i):
    """current_now is usually microamps; some drivers report mA"""
    if i is None: return None
    return i / 1000.0 if abs(i) > 20000 else i

def norm_temp(t):
    """temp is usually tenths of a degree C"""
    if t is None: return None
    return t / 10.0 if abs(t) > 150 else t

def find_supplies():
    bat = None; ext = []
    try:
        names = sorted(os.listdir(SYS))
    except OSError:
        return None, []
    for n in names:
        p = os.path.join(SYS, n); typ = _rd(p, "type")
        if typ == "Battery" and bat is None and _rd(p, "capacity") is not None:
            bat = p
        elif typ in ("USB", "Mains", "USB_C", "USB_PD", "USB_DCP", "USB_CDP"):
            ext.append(p)
    return bat, ext

class Reading:
    __slots__ = ("t", "cap", "mv", "ma", "status", "temp")
    def __init__(self, t, cap, mv, ma, status, temp):
        self.t, self.cap, self.mv, self.ma, self.status, self.temp = t, cap, mv, ma, status, temp
    @property
    def mode(self):
        s = (self.status or "").lower()
        if s == "charging": return "chg"
        if s == "full": return "full"
        return "dis"
    @property
    def watts(self):
        if self.mv is None or self.ma is None: return None
        return abs(self.mv * self.ma) / 1e6

def read_now(bat, ext):
    if not bat: return None
    cap = _num(_rd(bat, "capacity"))
    status = _rd(bat, "status") or "Unknown"
    plugged = any(_rd(p, "online") == "1" for p in ext)
    if status in ("Unknown", "Not charging") and plugged:
        status = "Full" if (cap or 0) >= 99 else "Charging"
    return Reading(time.time(), cap, norm_mv(_num(_rd(bat, "voltage_now"))),
                   norm_ma(_num(_rd(bat, "current_now"))), status, norm_temp(_num(_rd(bat, "temp"))))

def battery_info(bat):
    """static facts the driver may expose"""
    info = {}
    if not bat: return info
    for key in ("charge_full_design", "charge_full", "energy_full_design", "energy_full"):
        v = _num(_rd(bat, key))
        if v: info[key] = v / 1000.0 if v > 20000 else v   # uAh -> mAh
    for key in ("cycle_count", "health", "technology", "model_name", "manufacturer"):
        v = _rd(bat, key)
        if v: info[key] = v
    info["path"] = bat
    return info


# ---------------- log ----------------
# CSV: unix_time,capacity,voltage_raw,current_raw,status,temp_raw  (raw sysfs values, normalised on load)
def append(log_path, r):
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a") as f:
        f.write("%d,%s,%s,%s,%s,%s\n" % (r.t, _fmt(r.cap), _fmt(r.mv and r.mv * 1000), _fmt(r.ma and r.ma * 1000), r.status, _fmt(r.temp and r.temp * 10)))

def _fmt(v):
    return "" if v is None else ("%d" % v)

def load(log_path, since=0):
    rows = []
    try:
        f = open(log_path, errors="ignore")
    except OSError:
        return rows
    with f:
        for line in f:
            p = line.rstrip("\n").split(",")
            if len(p) < 5: continue
            t = _num(p[0])
            if t is None or t < since: continue
            cap = _num(p[1])
            if cap is None: continue
            rows.append(Reading(t, cap, norm_mv(_num(p[2])), norm_ma(_num(p[3])), p[4] or "Unknown",
                                norm_temp(_num(p[5])) if len(p) > 5 else None))
    rows.sort(key=lambda r: r.t)
    return rows

def last_time(log_path):
    try:
        with open(log_path, "rb") as f:
            f.seek(0, 2); size = f.tell(); f.seek(max(0, size - 200))
            tail = f.read().decode(errors="ignore").strip().splitlines()
        return _num(tail[-1].split(",")[0]) if tail else None
    except OSError:
        return None


# ---------------- analytics ----------------
class Session:
    def __init__(self, mode, rows):
        self.mode = mode; self.rows = rows
        self.t0 = rows[0].t; self.t1 = rows[-1].t
        self.c0 = rows[0].cap; self.c1 = rows[-1].cap
    @property
    def hours(self): return (self.t1 - self.t0) / 3600.0
    @property
    def delta(self): return self.c1 - self.c0
    @property
    def rate(self):
        """% per hour (positive number)"""
        return abs(self.delta) / self.hours if self.hours > 0 else 0.0
    def avg(self, attr):
        vals = [getattr(r, attr) for r in self.rows if getattr(r, attr) is not None]
        return sum(vals) / len(vals) if vals else None
    def mah_used(self):
        """coulomb count from current samples; None if the driver gives no current"""
        tot = 0.0; have = False
        for a, b in zip(self.rows, self.rows[1:]):
            if a.ma is None: continue
            dt = min(b.t - a.t, 300)
            tot += abs(a.ma) * dt / 3600.0; have = True
        return tot if have else None

def sessions(rows, min_minutes=5, min_delta=2):
    out = []; cur = []
    def flush():
        if len(cur) >= 2:
            mode = "chg" if cur[0].mode in ("chg",) else ("full" if cur[0].mode == "full" else "dis")
            s = Session(mode, list(cur))
            if mode != "full" and s.hours * 60 >= min_minutes and abs(s.delta) >= min_delta:
                out.append(s)
    for r in rows:
        if cur and (r.t - cur[-1].t > GAP or r.mode != cur[-1].mode):
            flush(); cur = []
        cur.append(r)
    flush()
    return out

def slope(points):
    """least-squares slope of (t, value) in value per hour"""
    n = len(points)
    if n < 2: return None
    mt = sum(p[0] for p in points) / n; mv = sum(p[1] for p in points) / n
    den = sum((p[0] - mt) ** 2 for p in points)
    if den == 0: return None
    return sum((p[0] - mt) * (p[1] - mv) for p in points) / den * 3600.0

def trailing(rows, mode, window):
    """samples of the ongoing session of `mode`, limited to the last `window` seconds"""
    out = []
    for r in reversed(rows):
        if r.mode != mode or (out and out[-1].t - r.t > GAP): break
        out.append(r)
    out.reverse()
    if out:
        cut = out[-1].t - window
        out = [r for r in out if r.t >= cut]
    return out

def fmt_dur(hours):
    if hours is None or hours != hours or hours < 0: return "--"
    if hours > 99: return "99h+"
    m = int(round(hours * 60))
    return "%dh %02dm" % (m // 60, m % 60) if m >= 60 else "%dm" % m


class Analysis:
    def __init__(self, rows, live, design_mah, info=None):
        self.rows = rows; self.live = live; self.design = design_mah; self.info = info or {}
        week = (live.t if live else time.time()) - 7 * 86400
        self.sessions = sessions(rows)
        self.recent = [s for s in self.sessions if s.t1 >= week]
        dis = [s for s in self.recent if s.mode == "dis"]
        chg = [s for s in self.recent if s.mode == "chg"]
        # typical rates (weighted by time)
        h = sum(s.hours for s in dis)
        self.typ_drain = sum(abs(s.delta) for s in dis) / h if h > 0.3 else None
        h = sum(s.hours for s in chg)
        self.typ_charge = sum(abs(s.delta) for s in chg) / h if h > 0.2 else None
        # capacity estimate by coulomb counting over long discharges
        ests = []
        for s in self.sessions:
            if s.mode == "dis" and abs(s.delta) >= 10:
                used = s.mah_used()
                if used: ests.append(used / (abs(s.delta) / 100.0))
        ests.sort()
        self.capacity_samples = len(ests)
        self.est_capacity = ests[len(ests) // 2] if ests else None
        if self.info.get("charge_full"):
            self.est_capacity = self.info["charge_full"]
        self.cycles = sum(abs(s.delta) for s in self.sessions if s.mode == "dis") / 100.0
        temps = [r.temp for r in rows if r.temp is not None]
        self.temp_avg = sum(temps) / len(temps) if temps else None
        self.temp_max = max(temps) if temps else None
        self.span_days = (rows[-1].t - rows[0].t) / 86400.0 if len(rows) > 1 else 0

    @property
    def health(self):
        if self.est_capacity and self.design:
            return min(1.2, self.est_capacity / self.design)
        return None

    def cap_mah(self):
        return self.est_capacity or self.design

    def drain_now(self):
        """% per hour right now: from current draw if available, else recent trend"""
        live = self.live
        if live and live.mode == "dis":
            win = trailing(self.rows, "dis", 300)
            amps = [abs(r.ma) for r in win if r.ma is not None]
            if live.ma is not None: amps.append(abs(live.ma))
            if amps and self.cap_mah():
                return sum(amps) / len(amps) / self.cap_mah() * 100.0
            win = trailing(self.rows, "dis", 3600)
            if len(win) >= 3 and win[-1].t - win[0].t >= 600:
                s = slope([(r.t, r.cap) for r in win])
                if s is not None and s < 0: return -s
        return None

    def time_left(self):
        if not self.live or self.live.mode != "dis": return None
        rate = self.drain_now() or self.typ_drain
        return self.live.cap / rate if rate else None

    def charge_now(self):
        live = self.live
        if live and live.mode == "chg":
            win = trailing(self.rows, "chg", 1200)
            if len(win) >= 3 and win[-1].t - win[0].t >= 300:
                s = slope([(r.t, r.cap) for r in win])
                if s and s > 0: return s
            if live.ma is not None and self.cap_mah():
                return abs(live.ma) / self.cap_mah() * 100.0
        return None

    def time_to_full(self):
        live = self.live
        if not live or live.mode != "chg": return None
        rate = self.charge_now() or self.typ_charge
        if not rate: return None
        c = live.cap
        # lithium charging tapers above ~80%: assume half speed for the last stretch
        if c < 80:
            return (80 - c) / rate + 20 / (rate * 0.5)
        return (100 - c) / (rate * 0.5) if rate else None

    def full_runtime(self):
        """hours a 100% charge lasts at the typical drain"""
        return 100.0 / self.typ_drain if self.typ_drain else None

    def full_charge_time(self):
        return (80 / self.typ_charge + 20 / (self.typ_charge * 0.5)) if self.typ_charge else None

    def grade(self):
        h = self.health
        if h is None: return ("Learning", "Needs a few long sessions logged")
        if h >= 0.9: return ("Excellent", "Holds close to its original charge")
        if h >= 0.8: return ("Good", "Normal wear for its age")
        if h >= 0.7: return ("Fair", "Noticeably shorter run time")
        return ("Worn", "Consider a replacement")


# ---------------- settings ----------------
def load_settings(path):
    try:
        with open(path) as f: return json.load(f)
    except Exception:
        return {}

def save_settings(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".tmp", "w") as f: json.dump(data, f)
    os.replace(path + ".tmp", path)
