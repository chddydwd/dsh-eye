
import io, json, os, threading, time, subprocess, collections, ctypes
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import numpy as np
from PIL import Image, ImageDraw, ImageFont

FF = r"C:\Users\Ddy\.dsh\.dsh-wallpaper-engine\ffmpeg\ffmpeg.exe"
W, H = 1920, 1080
FPS_HI = 20          # 有人在动（鼠标/键盘最近 1.2 秒内有过）时的采样率
FPS_LO = 2           # 屏幕闲着时的采样率：没人动的时候画面本来就不变，2fps 足够，CPU 再砍一半
SPAN = 30.0          # 近期稠密层：20fps × 30 秒
Q = 82
SS = 2               # 4:2:0，编码快一倍、体积小一半；1:1 读字几乎无差
IDLE_HOLD_MS = 600000  # 没人动超过 10 分钟就彻底停采集（CPU 归零），一动立刻醒
CFG_PATH = r"C:\Users\Ddy\.dsh\eye-runtime.json"   # 面板改的参数存这儿，重启采集也记得
DEFAULTS = {"near_fps": 20, "idle_fps": 2, "near_span": 30.0, "far_step": 2.0, "far_sec": 3600, "quality": 82}
mode = {"fps": FPS_LO, "paused": False}
ring = collections.deque(maxlen=int(FPS_HI * SPAN) + 5)
SLOW_STEP = 2.0        # 远期层：每 2 秒一张，全是原分辨率原画质，字照样清
SLOW_SIZE = None       # None = 不缩放，直接存原帧（还省一次重编码）
SLOW_Q = 68
SLOW_MAX = 1800        # 1800 张 × 2 秒 = 一小时
slow = collections.deque(maxlen=SLOW_MAX)
lock = threading.Lock()
stats = {"fps": 0.0, "n": 0, "err": ""}
trail = collections.deque(maxlen=1200)      # (ts, x, y)
clicks = collections.deque(maxlen=80)       # dict(ts,x,y,hwnd,title)
last_btn = 0
act = {"score": 0.0, "box": None, "at": 0.0, "idle_ms": 0, "title": "", "fg": None, "fg_at": 0.0, "fg_changed": False}   # 最近一次活动检测（供插件主动叫醒）
FG_LAST = {"hwnd": 0, "at": 0.0}
ACT_TICK = 0.5        # 每 0.5 秒量一次
ACT_SCALE = (160, 90) # 缩到这个尺寸比，便宜且对整屏变化敏感
THUMBS = collections.OrderedDict()   # ts -> int16 缩小灰度图（活动检测用，别每次解码整张 JPEG）
th_lock = threading.Lock()
TH_KEEP = 90          # 只留最近 90 帧的缩略（20fps 下约 4.5 秒，够 2.6 秒回看）

def _thumb(im):
    try:
        return np.asarray(im.resize(ACT_SCALE).convert("L"), dtype=np.int16)
    except Exception:
        return None

def _put_thumb(ts, im):
    t = _thumb(im)
    if t is None:
        return
    with th_lock:
        THUMBS[ts] = t
        while len(THUMBS) > TH_KEEP:
            THUMBS.popitem(last=False)
# 对话框：不经过 QQ，跟鲸鲸实时说话（看视频/一起玩的时候用）。只放内存，不落盘。
CHAT = collections.deque(maxlen=400)
CHAT_ID = [0]
chat_lock = threading.Lock()

def chat_add(frm, text, kind="chat"):
    with chat_lock:
        CHAT_ID[0] += 1
        m = {"id": CHAT_ID[0], "ts": round(time.time(), 2), "from": frm, "text": str(text)[:4000], "kind": kind}
        CHAT.append(m)
        return m
try:
    FONT = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 9)
except Exception:
    FONT = ImageFont.load_default()

user32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(ctypes.c_bool, ctypes.c_void_p, ctypes.c_void_p)

class POINT(ctypes.Structure):
    _fields_ = [("x", ctypes.c_long), ("y", ctypes.c_long)]

class LASTINPUTINFO(ctypes.Structure):
    _fields_ = [("cbSize", ctypes.c_uint), ("dwTime", ctypes.c_uint)]

def idle_ms():
    try:
        li = LASTINPUTINFO(); li.cbSize = ctypes.sizeof(LASTINPUTINFO)
        if not user32.GetLastInputInfo(ctypes.byref(li)):
            return -1
        return (ctypes.windll.kernel32.GetTickCount() - li.dwTime) & 0x7FFFFFFF
    except Exception:
        return -1

def fg_title():
    try:
        return win_title(user32.GetForegroundWindow())
    except Exception:
        return ""

def fg_probe():
    """前台窗口（hwnd, 标题），并标记「这一拍刚换过前台窗口」——窗口切换是硬事件，屏幕画面变化是软信号。"""
    try:
        h = user32.GetForegroundWindow()
        t = win_title(h) if h else ""
        now = time.time()
        changed = bool(h) and h != FG_LAST["hwnd"]
        if changed:
            FG_LAST["hwnd"] = h
            FG_LAST["at"] = now
        return {"hwnd": int(h or 0), "title": t, "at": round(now, 3),
                "changed": changed, "since": round(now - FG_LAST["at"], 2)}
    except Exception:
        return None

def get_cursor():
    p = POINT(); user32.GetCursorPos(ctypes.byref(p)); return p.x, p.y

def win_title(hwnd):
    try:
        n = user32.GetWindowTextLengthW(hwnd)
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value
    except Exception:
        return ""

def _popen(fps):
    cmd = [FF, "-hide_banner", "-loglevel", "error", "-f", "gdigrab", "-framerate", str(fps),
           "-i", "desktop", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"]
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=W * H * 3 * 2)

def capture():
    """首选 mss 直接抓帧：比 ffmpeg gdigrab 便宜一半左右，切采样率也不用重启进程。

    mss 不可用时退回 ffmpeg（capture_ffmpeg），行为一样。
    """
    try:
        import mss
        s = mss.MSS()
        mon = s.monitors[1]
    except Exception as e:
        stats["err"] = "mss-unavailable: " + repr(e)[:120]
        return capture_ffmpeg()
    fps = FPS_LO
    mode["fps"] = fps; stats["mode"] = fps
    cnt = 0; t0 = time.time()
    while True:
        # 久无人动就停采集：只剩 1 秒一次的 idle 查询，CPU 基本归零
        while True:
            v = idle_ms()
            if v < 0 or v < IDLE_HOLD_MS:
                break
            mode["paused"] = True
            stats["paused"] = True
            stats["fps"] = 0.0
            time.sleep(1.0)
        mode["paused"] = False
        stats["paused"] = False
        want = FPS_HI if (0 <= idle_ms() < 1200) else FPS_LO
        if want != fps:
            fps = want; mode["fps"] = fps; stats["mode"] = fps
        t_start = time.time()
        try:
            raw = s.grab(mon)
            im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            b = io.BytesIO(); im.save(b, "JPEG", quality=Q, subsampling=SS)
            ts = time.time()
            with lock:
                ring.append((ts, b.getvalue())); stats["n"] = len(ring)
            _put_thumb(ts, im)
        except Exception as e:
            stats["err"] = repr(e)[:200]; time.sleep(0.5); continue
        cnt += 1
        if cnt % 20 == 0:
            stats["fps"] = round(cnt / max(1e-6, time.time() - t0), 1)
        dt = time.time() - t_start
        stats["ms"] = round(dt * 1000, 1)
        gap = 1.0 / fps - dt
        if gap > 0:
            time.sleep(gap)

def capture_ffmpeg():
    """兜底：ffmpeg gdigrab 抓帧（mss 装不上时用）。切档要重开进程，所以最少 4 秒切一次。"""
    n = W * H * 3
    fps = FPS_LO
    while True:
        # 久无人动就停采集：python 只剩 1 秒一次的 idle 查询，CPU 基本归零。
        while True:
            v = idle_ms()
            if v < 0 or v < IDLE_HOLD_MS:
                break
            mode["paused"] = True
            stats["paused"] = True
            stats["fps"] = 0.0
            time.sleep(1.0)
        mode["paused"] = False
        stats["paused"] = False
        try:
            p = _popen(fps)
        except Exception as e:
            stats["err"] = repr(e)[:200]; time.sleep(2); continue
        mode["fps"] = fps; stats["mode"] = fps
        cnt = 0; t0 = time.time(); started = t0; last_chk = 0.0
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                stats["err"] = "ffmpeg eof"; break
            ts = time.time()
            arr = np.frombuffer(buf, dtype=np.uint8).reshape(H, W, 3)
            im = Image.fromarray(arr[:, :, ::-1], "RGB")
            b = io.BytesIO(); im.save(b, "JPEG", quality=Q, subsampling=SS)
            with lock:
                ring.append((ts, b.getvalue())); stats["n"] = len(ring)
            _put_thumb(ts, im)
            cnt += 1
            if cnt % fps == 0:
                stats["fps"] = round(cnt / (time.time() - t0), 1)
            if ts - last_chk >= 0.5:
                last_chk = ts
                idle = idle_ms()
                want = FPS_HI if (0 <= idle < 1200) else FPS_LO
                if want != fps and (ts - started) >= 4.0:
                    fps = want
                    break
        try:
            p.kill(); p.wait(timeout=1)
        except Exception:
            pass

def pointer():
    global last_btn
    while True:
        ts = time.time(); x, y = get_cursor()
        trail.append((ts, x, y))
        down = bool(user32.GetAsyncKeyState(0x01) & 0x8000) or bool(user32.GetAsyncKeyState(0x02) & 0x8000)
        if down and not last_btn:
            try:
                hwnd = user32.WindowFromPoint(POINT(x, y))
            except Exception:
                hwnd = 0
            clicks.append({"ts": ts, "x": x, "y": y, "hwnd": int(hwnd or 0), "title": win_title(hwnd or 0)[:120]})
        last_btn = down
        time.sleep(0.02)

def _clamp(v, lo, hi):
    try:
        v = float(v)
    except Exception:
        return None
    return max(lo, min(hi, v))

def load_cfg():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            d = json.load(f)
    except Exception:
        d = {}
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        v = _clamp(d.get(k, out[k]), 0.01, 100000)
        if v is not None:
            out[k] = v
    return out

CFG = load_cfg()
FPS_HI = int(CFG["near_fps"]); FPS_LO = int(CFG["idle_fps"])
SPAN = float(CFG["near_span"]); SLOW_STEP = float(CFG["far_step"])
Q = int(CFG["quality"])
SLOW_MAX = max(60, int(float(CFG["far_sec"]) / max(0.5, SLOW_STEP)))

def save_cfg():
    try:
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(CFG, f, ensure_ascii=False)
    except Exception:
        pass

def avg_frame_bytes():
    with lock:
        items = list(ring)
        sl = list(slow)
    a = (sum(len(j) for _, j in items) / len(items)) if items else 280000.0
    b = (sum(len(j) for _, j in sl) / len(sl)) if sl else a
    return a, b

def cfg_state():
    a, b = avg_frame_bytes()
    near = int(FPS_HI * SPAN) + 5
    return {"near_fps": FPS_HI, "idle_fps": FPS_LO, "near_span": SPAN,
            "far_step": SLOW_STEP, "far_sec": round(SLOW_STEP * SLOW_MAX, 1), "quality": Q,
            "near_frames": near, "far_frames": SLOW_MAX,
            "est_mem_mb": round((near * a + SLOW_MAX * b) / 1e6, 1),
            "frame_kb": round(a / 1024, 1), "defaults": DEFAULTS}

def apply_cfg(q):
    """面板传来的参数：改完立即生效（帧率下一轮重开 ffmpeg 时生效），并落盘。"""
    global FPS_HI, FPS_LO, SPAN, SLOW_STEP, SLOW_MAX, Q, ring, slow
    old_far_sec = SLOW_STEP * SLOW_MAX
    if "near_fps" in q:
        v = _clamp(q["near_fps"], 5, 30); FPS_HI = int(v) if v else FPS_HI
    if "idle_fps" in q:
        v = _clamp(q["idle_fps"], 1, 15); FPS_LO = int(v) if v else FPS_LO
    if "near_span" in q:
        v = _clamp(q["near_span"], 5, 180); SPAN = v or SPAN
    if "far_step" in q:
        v = _clamp(q["far_step"], 0.5, 30); SLOW_STEP = v or SLOW_STEP
    if "quality" in q:
        v = _clamp(q["quality"], 50, 95); Q = int(v) if v else Q
    if "far_sec" in q:
        v = _clamp(q["far_sec"], 60, 14400) or old_far_sec
    else:
        v = old_far_sec
    SLOW_MAX = max(60, int(v / max(0.5, SLOW_STEP)))
    CFG.update({"near_fps": FPS_HI, "idle_fps": FPS_LO, "near_span": SPAN,
                "far_step": SLOW_STEP, "far_sec": round(SLOW_STEP * SLOW_MAX, 1), "quality": Q})
    with lock:
        ring = collections.deque(list(ring)[-(int(FPS_HI * SPAN) + 5):], maxlen=int(FPS_HI * SPAN) + 5)
        slow = collections.deque(list(slow)[-SLOW_MAX:], maxlen=SLOW_MAX)
    save_cfg()
    return cfg_state()

def snapshot():
    with lock:
        return list(ring)

def slow_loop():
    """远期层：每秒存一张缩小的画面。变了才存，没变就压到 10 秒一张。"""
    last_g = None; last_ts = 0.0
    while True:
        time.sleep(SLOW_STEP)
        items = snapshot()
        if not items: continue
        ts, jb = items[-1]
        if time.time() - ts > 3: continue      # 采集停着，别存旧帧
        if last_g is not None and ts - last_ts < 10.0:
            try:
                g = _gray(jb)
            except Exception:
                continue
            if float(np.abs(g - last_g).mean()) < 1.2:
                continue
        try:
            im = decode(jb)
        except Exception:
            continue
        last_g = _gray(jb)
        last_ts = ts
        if SLOW_SIZE:
            b = io.BytesIO()
            im.resize(SLOW_SIZE, Image.BILINEAR).save(b, "JPEG", quality=SLOW_Q, subsampling=SS)
            slow.append((ts, b.getvalue()))
        else:
            slow.append((ts, jb))          # 原帧直接进远层，不再编码

def window(span=10.0, n=100):
    items = snapshot()
    if not items: return []
    rec = items[-1][0] - items[0][0] if len(items) > 1 else 0.0
    if span > rec * 1.25 and slow:
        sl = list(slow)
        cut = sl[-1][0] - span
        win = [x for x in sl if x[0] >= cut] or sl[-1:]
        if n and len(win) > n:
            step = (len(win) - 1) / (n - 1) if n > 1 else 0
            win = [win[int(round(i * step))] for i in range(n)]
        return win
    cut = items[-1][0] - span
    win = [x for x in items if x[0] >= cut] or items[-1:]
    if n and len(win) > n:
        step = (len(win) - 1) / (n - 1) if n > 1 else 0
        win = [win[int(round(i * step))] for i in range(n)]
    return win

def decode(jb):
    return Image.open(io.BytesIO(jb)).convert("RGB")

def render_sheet(win, cols=10, width=798, gap=2, label=True):
    if not win: return None
    sw, sh = decode(win[0][1]).size
    cw = (width - gap * (cols - 1)) // cols
    ch = max(1, int(cw * sh / sw))
    rows = (len(win) + cols - 1) // cols
    canvas = Image.new("RGB", (width, rows * (ch + gap) - gap), (14, 14, 16))
    draw = ImageDraw.Draw(canvas)
    for i, (ts, jb) in enumerate(win):
        x = (i % cols) * (cw + gap); y = (i // cols) * (ch + gap)
        canvas.paste(decode(jb).resize((cw, ch), Image.BILINEAR), (x, y))
        if label:
            t = str(i)
            draw.rectangle([x, y, x + 8 * len(t) + 2, y + 11], fill=(0, 0, 0))
            draw.text((x + 1, y + 1), t, font=FONT, fill=(255, 255, 0))
    return canvas

def diffs(win):
    out = []; prev = None
    for ts, jb in win:
        g = np.asarray(decode(jb).convert("L").resize((96, 54)), dtype=np.int16)
        out.append(0.0 if prev is None else round(float(np.abs(g - prev).mean()) / 255 * 100, 1))
        prev = g
    return out

def echo_frames(before=1.0, after=1.0):
    items = snapshot()
    if not items or not clicks: return None, None
    c = clicks[-1]
    lo = c["ts"] - before; hi = c["ts"] + after
    seg = [x for x in items if lo <= x[0] <= hi]
    if not seg:
        near = min(items, key=lambda x: abs(x[0] - c["ts"]))
        seg = [near]
    return seg, c

def _gray(jpeg, size=ACT_SCALE):
    im = Image.open(io.BytesIO(jpeg)).convert("L").resize(size)
    return np.asarray(im, dtype=np.int16)

ACT_LOOKBACK = (0.4, 0.8, 1.3, 1.9, 2.6)  # 跟这些「多少秒前」的帧各比一次，取最大
ACT_PERSIST = 2.6  # 变化最多能被记住这么久，插件靠这个窗口抓一次性切换

def activity_loop():
    """量「最近约 1.6 秒屏幕变了多少」。给插件判断要不要叫醒模型用。

    score = 灰度平均绝对差（0~255 尺度），取「当前帧 vs 过去 0.4/0.8/1.2/1.6 秒前」的最大值。
    只跟 0.45 秒前比会漏掉一次性切换（开窗、弹窗在半秒内就结束了，idle 档 4fps 更抓不到），
    拉长回忆窗口后，变化会在随后两三拍里一直可见，插件「连两拍才算」才有意义。
    box 是变化区域（全屏像素坐标），插件只拿它写进提示词。
    """
    while True:
        time.sleep(ACT_TICK)
        items = snapshot()
        if not items:
            continue
        ts, jpeg = items[-1]
        if time.time() - ts > 1.5:
            # 采集停着（休眠或异常），环里是旧帧：别拿旧帧算「刚刚变了」
            fgi = fg_probe()
            act.update({"score": 0.0, "box": None, "at": round(ts, 3),
                        "idle_ms": idle_ms(), "title": fg_title(),
                        "fg": fgi, "fg_at": fgi["at"] if fgi else 0.0,
                        "fg_changed": bool(fgi and fgi["changed"])})
            continue
        with th_lock:
            ths = list(THUMBS.items())
        a = ths[-1][1] if ths and ths[-1][0] == ts else None
        if a is None:
            try:
                a = _gray(jpeg)
            except Exception:
                continue
        olds = []
        for off in ACT_LOOKBACK:
            ref = None
            if ths:
                for t, arr in ths:
                    if t <= ts - off:
                        ref = arr
                    else:
                        break
            if ref is None:
                for t, j in items:
                    if t <= ts - off:
                        ref = j
                    else:
                        break
                if ref is not None:
                    try:
                        ref = _gray(ref)
                    except Exception:
                        ref = None
            if ref is not None:
                olds.append(ref)
        if not olds:
            continue
        best, best_box = 0.0, None
        for ref in olds:
            try:
                b = _gray(ref)
            except Exception:
                continue
            d = np.abs(a - b)
            score = float(d.mean())
            if score <= best:
                continue
            best = score
            best_box = None
            mask = d > 25
            if mask.any():
                ys, xs = np.where(mask)
                sw, sh = W / ACT_SCALE[0], H / ACT_SCALE[1]
                best_box = [int(xs.min() * sw), int(ys.min() * sh),
                            int((xs.max() - xs.min() + 1) * sw), int((ys.max() - ys.min() + 1) * sh)]
        fgi = fg_probe()
        act.update({"score": round(best, 2), "box": best_box, "at": round(ts, 3),
                    "idle_ms": idle_ms(), "title": fg_title(),
                    "fg": fgi, "fg_at": fgi["at"] if fgi else 0.0,
                    "fg_changed": bool(fgi and fgi["changed"])})

class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a): pass
    def _cors(self):
        # 面板在 DSH 页面里，跨端口来调：放开只读+参数这两个面
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Headers", "content-type, accept")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
    def do_OPTIONS(self):
        self.send_response(204); self._cors(); self.end_headers()
    def _img(self, im):
        b = io.BytesIO(); im.save(b, "PNG"); d = b.getvalue()
        self.send_response(200); self.send_header("Content-Type", "image/png"); self._cors()
        self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
    def _json(self, o):
        d = json.dumps(o, ensure_ascii=False).encode()
        self.send_response(200); self.send_header("Content-Type", "application/json"); self._cors()
        self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d)
    def _params(self, q):
        def f(k, d):
            try: return float(q.get(k, d))
            except Exception: return d
        def i_(k, d):
            try: return int(q.get(k, d))
            except Exception: return d
        return f, i_
    def do_GET(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        f, i_ = self._params(q)
        if u.path == "/state":
            items = snapshot()
            span = (items[-1][0] - items[0][0]) if len(items) > 1 else 0
            x, y = get_cursor()
            self._json({"frames": len(items), "fps": stats["fps"], "frame_ms": stats.get("ms"), "span_sec": round(span, 2),
                        "size": [W, H], "cursor": [x, y], "clicks": len(clicks),
                        "last_click_ago": round(time.time() - clicks[-1]["ts"], 2) if clicks else None,
                        "err": stats["err"], "paused": bool(mode.get("paused")),
                        "slow_frames": len(slow),
                        "slow_span_sec": round(slow[-1][0] - slow[0][0], 1) if len(slow) > 1 else 0}); return
        if u.path == "/config":
            self._json(apply_cfg(q) if q else cfg_state()); return
        if u.path == "/cursor":
            x, y = get_cursor()
            tr = [(round(t, 2), px, py) for t, px, py in list(trail)[-200:]]
            self._json({"x": x, "y": y, "trail": tr}); return
        if u.path == "/clicks":
            now = time.time()
            out = [{"ago": round(now - c["ts"], 2), "x": c["x"], "y": c["y"], "title": c["title"]} for c in list(clicks)[-20:]]
            out.reverse(); self._json({"clicks": out}); return
        if u.path == "/echo_info":
            seg, c = echo_frames(f("before", 1.0), f("after", 1.0))
            if not c: self._json({"error": "no click yet"}); return
            self._json({"click": {"x": c["x"], "y": c["y"], "title": c["title"], "ago": round(time.time() - c["ts"], 2)},
                        "frames": len(seg or [])}); return
        if u.path == "/echo":
            seg, c = echo_frames(f("before", 1.0), f("after", 1.0))
            if not seg: self._json({"error": "no click yet"}); return
            im = render_sheet(seg, i_("cols", 10))
            d = ImageDraw.Draw(im)
            d.text((2, im.size[1] - 12), "click @(%d,%d) %s" % (c["x"], c["y"], c["title"][:40]), font=FONT, fill=(0, 255, 120))
            self._img(im); return
        if u.path == "/echo_focus":
            seg, c = echo_frames(f("before", 1.0), f("after", 1.0))
            if not c: self._json({"error": "no click yet"}); return
            fw = i_("fw", 700); fh = i_("fh", 393)
            items = snapshot()
            pre = [x for x in items if c["ts"] - f("before", 1.0) <= x[0] <= c["ts"]]
            post = [x for x in items if c["ts"] <= x[0] <= c["ts"] + f("after", 1.0)]
            def pick2(lst):
                if not lst: return []
                if len(lst) == 1: return lst * 2
                return [lst[0], lst[-1]]
            cells = [(frm[0], frm[1], frm[0] - c["ts"]) for frm in pick2(pre)] + [(frm[0], frm[1], frm[0] - c["ts"]) for frm in pick2(post)]
            if not cells: self._json({"error": "no frames around click"}); return
            gap = 2; cw = (798 - gap) // 2; ch = max(1, int(cw * fh / fw))
            canvas = Image.new("RGB", (798, 2 * (ch + gap) - gap), (14, 14, 16))
            draw = ImageDraw.Draw(canvas)
            x0 = max(0, min(W - fw, c["x"] - fw // 2)); y0 = max(0, min(H - fh, c["y"] - fh // 2))
            for k, (ts, jb, dt) in enumerate(cells[:4]):
                im = decode(jb).crop((x0, y0, x0 + fw, y0 + fh)).resize((cw, ch), Image.BILINEAR)
                cx2 = (k % 2) * (cw + gap); cy2 = (k // 2) * (ch + gap)
                canvas.paste(im, (cx2, cy2))
                tag = ("%+.2fs" % dt)
                draw.rectangle([cx2, cy2, cx2 + 8 * len(tag) + 4, cy2 + 12], fill=(0, 0, 0))
                draw.text((cx2 + 2, cy2 + 1), tag, font=FONT, fill=(0, 255, 120))
            draw.text((4, canvas.size[1] - 13), "click @(%d,%d) %s" % (c["x"], c["y"], c["title"][:50]), font=FONT, fill=(255, 255, 0))
            self._img(canvas); return
        if u.path in ("/window", "/sheet", "/peripheral"):
            win = window(f("span", 10.0), i_("n", 100))
            if not win: self._json({"error": "no frames"}); return
            self._img(render_sheet(win, i_("cols", 10))); return
        if u.path == "/index":
            win = window(f("span", 10.0), i_("n", 100))
            if not win: self._json({"error": "no frames"}); return
            t_last = snapshot()[-1][0]
            self._json({"n": len(win), "cells": [round(t_last - ts, 2) for ts, _ in win]}); return
        if u.path == "/diff":
            win = window(f("span", 10.0), i_("n", 100))
            if not win: self._json({"error": "no frames"}); return
            d = diffs(win)
            self._json({"n": len(win), "diffs": d, "hot_cells": [i for i, v in enumerate(d) if v >= 1.0][:60]}); return
        if u.path in ("/cell", "/fovea", "/fovea_at_cursor"):
            items = snapshot()
            if not items: self._json({"error": "no frames"}); return
            if u.path == "/cell" and "i" in q:
                win = window(f("span", 10.0), i_("n", 100))
                best = win[max(0, min(len(win) - 1, i_("i", 0)))]
            else:
                target = items[-1][0] - f("t", 0)
                best = min(items, key=lambda x: abs(x[0] - target))
            im = decode(best[1])
            if u.path.startswith("/fovea") or "fw" in q:
                fw = i_("fw", 700); fh = i_("fh", 393)
                if u.path == "/fovea_at_cursor":
                    cx, cy = get_cursor()
                else:
                    cx = i_("cx", W // 2); cy = i_("cy", H // 2)
                x0 = max(0, min(W - fw, cx - fw // 2)); y0 = max(0, min(H - fh, cy - fh // 2))
                im = im.crop((x0, y0, x0 + fw, y0 + fh))
            self._img(im); return
        if u.path == "/shot":
            items = snapshot()
            if not items: self._json({"error": "no frames"}); return
            target = items[-1][0] - f("t", 0)
            best = min(items, key=lambda x: abs(x[0] - target))
            d = best[1]
            self.send_response(200); self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d); return
        if u.path == "/activity":
            a = dict(act)
            a["ago"] = round(time.time() - a["at"], 2) if a["at"] else None
            a["frames"] = len(snapshot())
            self._json(a); return
        if u.path == "/chat":
            since = i_("since", 0)
            with chat_lock:
                msgs = [m for m in CHAT if m["id"] > since]
                last = CHAT_ID[0]
            self._json({"msgs": msgs, "last": last}); return
        if u.path == "/clear":
            with lock: ring.clear()
            slow.clear()
            trail.clear(); clicks.clear()
            self._json({"cleared": True}); return
        self._json({"error": "unknown", "paths": ["/state", "/window", "/index", "/diff", "/cell",
                    "/fovea", "/fovea_at_cursor", "/shot", "/cursor", "/clicks", "/echo", "/echo_info", "/activity", "/clear"]})

    def do_POST(self):
        u = urlparse(self.path)
        try:
            n = int(self.headers.get("Content-Length") or 0)
        except Exception:
            n = 0
        raw = self.rfile.read(n) if n > 0 else b""
        if u.path == "/chat":
            try:
                j = json.loads(raw.decode() or "{}")
            except Exception:
                j = {}
            text = str(j.get("text") or "").strip()
            frm = "me" if j.get("from") == "me" else "user"
            if not text:
                self._json({"ok": False, "error": "empty"}); return
            kind = "status" if j.get("kind") == "status" else "chat"
            m = chat_add(frm, text, kind)
            self._json({"ok": True, "msg": m}); return
        self._json({"error": "unknown"})

if __name__ == "__main__":
    threading.Thread(target=capture, daemon=True).start()
    threading.Thread(target=pointer, daemon=True).start()
    threading.Thread(target=activity_loop, daemon=True).start()
    threading.Thread(target=slow_loop, daemon=True).start()
    time.sleep(1.5)
    ThreadingHTTPServer(("127.0.0.1", 13201), Handler).serve_forever()
