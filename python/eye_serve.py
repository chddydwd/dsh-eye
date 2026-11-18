
import io, json, os, sys, shutil, threading, time, subprocess, collections, ctypes, base64
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs
import numpy as np
from PIL import Image, ImageDraw, ImageFont

def _find_ff():
    """ffmpeg 位置：env EYE_FFMPEG → PATH → 常见安装位置 → 只写 ffmpeg 交给 PATH。"""
    cands = [os.environ.get("EYE_FFMPEG"), shutil.which("ffmpeg"),
             os.path.join(os.environ.get("LOCALAPPDATA", ""), "Programs", "ffmpeg", "bin", "ffmpeg.exe")]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    return "ffmpeg"

def _screen_size():
    """分辨率不写死：按当前主屏实际像素走（先用 mss 抓的是物理像素）。"""
    try:
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        w, h = int(u.GetSystemMetrics(0)), int(u.GetSystemMetrics(1))
        if w > 0 and h > 0:
            return w, h
    except Exception:
        pass
    return 1920, 1080

def _dpi_scale():
    try:
        u = ctypes.windll.user32
        u.SetProcessDPIAware()
        hdc = u.GetDC(0)
        dpi = ctypes.windll.gdi32.GetDeviceCaps(hdc, 88)
        u.ReleaseDC(0, hdc)
        return round(dpi / 96.0, 2) if dpi else 1.0
    except Exception:
        return 1.0

def _refresh_hz():
    """主屏刷新率（多屏时其它屏的刷新率不一定相同，这里只报主屏的）。"""
    try:
        u = ctypes.windll.user32

        class DEVMODEW(ctypes.Structure):
            _fields_ = [
                ("dmDeviceName", ctypes.c_wchar * 32), ("dmSpecVersion", ctypes.c_ushort),
                ("dmDriverVersion", ctypes.c_ushort), ("dmSize", ctypes.c_ushort),
                ("dmDriverExtra", ctypes.c_ushort), ("dmFields", ctypes.c_ulong),
                ("dmPositionX", ctypes.c_long), ("dmPositionY", ctypes.c_long),
                ("dmDisplayOrientation", ctypes.c_ulong), ("dmDisplayFixedOutput", ctypes.c_ulong),
                ("dmColor", ctypes.c_short), ("dmDuplex", ctypes.c_short),
                ("dmYResolution", ctypes.c_short), ("dmTTOption", ctypes.c_short),
                ("dmCollate", ctypes.c_short), ("dmFormName", ctypes.c_wchar * 32),
                ("dmLogPixels", ctypes.c_ushort), ("dmBitsPerPel", ctypes.c_ulong),
                ("dmPelsWidth", ctypes.c_ulong), ("dmPelsHeight", ctypes.c_ulong),
                ("dmDisplayFlags", ctypes.c_ulong), ("dmDisplayFrequency", ctypes.c_ulong),
                ("dmICMMethod", ctypes.c_ulong), ("dmICMIntent", ctypes.c_ulong),
                ("dmMediaType", ctypes.c_ulong), ("dmDitherType", ctypes.c_ulong),
                ("dmReserved1", ctypes.c_ulong), ("dmReserved2", ctypes.c_ulong),
                ("dmPanningWidth", ctypes.c_ulong), ("dmPanningHeight", ctypes.c_ulong),
            ]
        dm = DEVMODEW(); dm.dmSize = ctypes.sizeof(DEVMODEW)
        if u.EnumDisplaySettingsW(None, -1, ctypes.byref(dm)) and dm.dmDisplayFrequency:
            return int(dm.dmDisplayFrequency)
    except Exception:
        pass
    return 0

FF = _find_ff()
W, H = _screen_size()
DPI = _dpi_scale()
REFRESH = _refresh_hz()
MON = {"i": 1}            # 抓哪块屏：0 = 所有屏拼起来，1..n = 第 n 块（mss 的编号）
PORT = int(os.environ.get("EYE_PORT") or 13201)
FPS_HI = 20          # 有人在动（鼠标/键盘最近 1.2 秒内有过）时的采样率
FPS_LO = 2           # 屏幕闲着时的采样率：没人动的时候画面本来就不变，2fps 足够，CPU 再砍一半
SPAN = 30.0          # 近期稠密层：20fps × 30 秒
Q = 82
SS = 2               # 4:2:0，编码快一倍、体积小一半；1:1 读字几乎无差
IDLE_HOLD_MS = 600000  # 没人动超过 10 分钟就彻底停采集（CPU 归零），一动立刻醒
CFG_PATH = os.environ.get("EYE_RUNTIME") or os.path.join(os.path.expanduser("~"), ".dsh", "eye-runtime.json")   # 面板改的参数存这儿，重启采集也记得
DEFAULTS = {"near_fps": 20, "idle_fps": 5, "near_span": 30.0, "far_step": 2.0, "far_sec": 3600, "quality": 82}
# 自适应帧率：按「帧间变化」决定这一拍多快，而不是只看有没有人动。
# 求稳优先——下限 5fps，慢推镜/缓慢滚动也掉不下来；真静止才落到下限。
MOVE_DIFF = 5.0        # 0.6 秒间隔的平均差 ≥ 这个值 → 判「在动」，直接拉满（拖窗口实测 20~47）
SLOW_DIFF = 3.0        # ≥ 这个值 → 判「在慢慢动」，取中间档（动态壁纸实测 1~1.5，留余量当静止）
# 自动性能档：不看用户配置，按实测单帧耗时自己落档（慢机器不用懂参数）。
# 25fps 一帧的预算是 40ms；连续平均超 45ms 就退一档，余量够（平均 <26ms）且撑住 20 秒才升回去。
AUTO = {"on": True, "cap": FPS_HI, "avg_ms": 0.0, "last_check": 0.0, "up_since": 0.0, "note": "自动"}
AUTO_DOWN_MS = float(os.environ.get("EYE_AUTO_DOWN_MS") or 45.0)
AUTO_UP_MS = float(os.environ.get("EYE_AUTO_UP_MS") or 26.0)
AUTO_UP_HOLD = 20.0

def auto_tiers():
    ts = {FPS_HI, 20, 16, 12, 8}
    ts = sorted(t for t in ts if 5 <= t <= FPS_HI)
    return ts or [FPS_HI]

def auto_step(down):
    ts = auto_tiers()
    cur = min(ts, key=lambda t: abs(t - AUTO["cap"]))
    i = ts.index(cur)
    if down and i > 0:
        return ts[i - 1]
    if (not down) and i < len(ts) - 1:
        return ts[i + 1]
    return cur

mode = {"fps": FPS_LO, "paused": False}
ring = collections.deque(maxlen=int(FPS_HI * SPAN) + 5)
SLOW_STEP = 2.0        # 远期层：每 2 秒一张，全是原分辨率原画质，字照样清
SLOW_SIZE = None       # None = 不缩放，直接存原帧（还省一次重编码）
SLOW_Q = 68
SLOW_MAX = 1800        # 1800 张 × 2 秒 = 一小时
FAR_BUDGET = int(float(os.environ.get("EYE_FAR_MB") or 320) * 1024 * 1024)   # 远层总字节上限（默认 320MB，EYE_FAR_MB 可改）
slow = collections.deque()      # 不设 maxlen：张数 + 字节双预算手动裁
slow_bytes = [0]
lock = threading.Lock()

def trim_slow():
    """远层双重预算：最多 SLOW_MAX 张，且总字节不超过 FAR_BUDGET——新的留，旧的丢。"""
    while slow and (len(slow) > SLOW_MAX or (slow_bytes[0] > FAR_BUDGET and len(slow) > 1)):
        _, jb_old = slow.popleft()
        slow_bytes[0] -= len(jb_old)
    if slow_bytes[0] < 0:
        slow_bytes[0] = 0

def slow_add(item):
    slow.append(item)
    slow_bytes[0] += len(item[1])
    trim_slow()
stats = {"fps": 0.0, "n": 0, "err": "", "started": 0.0, "last_ok": 0.0}
trail = collections.deque(maxlen=1200)      # (ts, x, y)
clicks = collections.deque(maxlen=80)       # dict(ts,x,y,hwnd,title)
last_btn = 0
act = {"score": 0.0, "box": None, "at": 0.0, "idle_ms": 0, "title": "", "fg": None, "fg_at": 0.0, "fg_changed": False}   # 最近一次活动检测（供插件主动叫醒）
FG_LAST = {"hwnd": 0, "at": 0.0}
ADAPT = {"last_move": 0.0, "hold": 2.0, "win": 0.6}   # 自适应帧率：0.6 秒前的缩略图做差（跟帧率无关），动过之后保持 2 秒
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
        return None
    with th_lock:
        THUMBS[ts] = t
        while len(THUMBS) > TH_KEEP:
            THUMBS.popitem(last=False)
    return t
# 对话框：不经过 QQ，跟鲸鲸实时说话（看视频/一起玩的时候用）。只放内存，不落盘。
CHAT = collections.deque(maxlen=400)
CHAT_ID = [int(time.time() * 1000)]   # 毫秒时间戳起跳：服务重启后编号不回 1（否则小窗的 since 会把新消息全滤掉）
chat_lock = threading.Lock()
WIN = {"hwnd": 0, "at": 0.0}   # 小窗心跳：窗口由插件起还是外面起，都能认出来
# 鼠标钩子（实验，默认关）：用系统事件通知，代替「每 20ms 问一次按键」。回调跑在系统输入线程里，
# 里面只做一件事——时间戳+坐标塞队列；查窗口、抓帧全留给采集线程，不然全系统输入都被拖慢。
HOOK = {"want": False, "on": False, "ok": False, "err": "", "events": 0,
        "at": 0.0, "burst": 0.0, "stop": False, "tid": 0}
HOOK_Q = collections.deque(maxlen=200)
hook_lock = threading.Lock()
# 事件时间线：点击 / 换前台窗口 / 滚轮。只记「什么时候、在哪、哪个窗口」，不记内容。
EVENTS = collections.deque(maxlen=400)
EV_FG = {"hwnd": 0}
EV_BURST = {"at": 0.0}   # 刚换过窗口：接下来 1.2 秒拉满帧率，把切换后的画面抓清楚

def hooks_load():
    """配置里 "hooks": true 或环境变量 EYE_HOOKS=1 才开（默认关）。"""
    v = False
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            v = bool((json.load(f) or {}).get("hooks"))
    except Exception:
        pass
    if (os.environ.get("EYE_HOOKS") or "").strip().lower() in ("1", "true", "on", "yes"):
        v = True
    return v

def drain_hook_clicks():
    """采集线程里消费钩子事件：查窗口标题、打事件标记（这些开销绝不能进钩子回调）。"""
    got = 0
    while True:
        try:
            ts, hx, hy, bt = HOOK_Q.popleft()
        except IndexError:
            break
        try:
            hwnd = user32.WindowFromPoint(POINT(hx, hy))
        except Exception:
            hwnd = 0
        title = win_title(hwnd or 0)[:120]
        if bt == "W":     # 滚轮不记进 clicks（那不是点击），只进事件时间线
            EVENTS.append({"ts": ts, "kind": "scroll", "x": hx, "y": hy,
                           "hwnd": int(hwnd or 0), "title": title})
        else:
            clicks.append({"ts": ts, "x": hx, "y": hy, "btn": bt, "hwnd": int(hwnd or 0),
                           "title": title, "src": "hook"})
            EVENTS.append({"ts": ts, "kind": "click", "x": hx, "y": hy, "btn": bt,
                           "hwnd": int(hwnd or 0), "title": title})
        HOOK["burst"] = ts
        got += 1
    return got

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

class RECT(ctypes.Structure):
    _fields_ = [("left", ctypes.c_long), ("top", ctypes.c_long),
                ("right", ctypes.c_long), ("bottom", ctypes.c_long)]

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
    if (os.environ.get("EYE_CAPTURE") or "").strip().lower() == "ffmpeg":
        stats["err"] = "forced-ffmpeg"
        return capture_ffmpeg()
    try:
        import mss
        s = mss.MSS()
        mon = mon_box()
    except Exception as e:
        stats["err"] = "mss-unavailable: " + repr(e)[:120]
        return capture_ffmpeg()
    fps = FPS_LO
    stats["started"] = time.time()
    mode["fps"] = fps; stats["mode"] = fps
    cnt = 0; t0 = time.time()
    tsq = collections.deque()
    prev_thumb = [None]
    mid_fps = max(FPS_LO + 1, min(FPS_HI, (FPS_HI + FPS_LO) // 2))
    ams = collections.deque(maxlen=24)   # 最近若干帧的实际耗时，给自动性能档用
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
        d = stats.get("diff")
        now = time.time()
        cap = AUTO["cap"] if AUTO["on"] else FPS_HI   # 自动档只封顶，不改变「什么时候该快」的判据
        if now - EV_BURST["at"] < 1.2 or 0 <= idle_ms() < 1200 or (d is not None and d >= MOVE_DIFF):
            want = min(FPS_HI, cap); ADAPT["last_move"] = now
        elif d is not None and d >= SLOW_DIFF:
            want = min(mid_fps, cap); ADAPT["last_move"] = now
        elif now - ADAPT["last_move"] < ADAPT["hold"]:
            want = min(fps, cap) if AUTO["on"] else fps   # 刚动过：保持当前档，别在 5/12/20 之间来回抖
        else:
            want = FPS_LO
        stats["want"] = want
        if want != fps:
            fps = want; mode["fps"] = fps; stats["mode"] = fps
        t_start = time.time()
        try:
            mons = s.monitors
            idx = MON["i"] if 0 <= MON["i"] < len(mons) else (1 if len(mons) > 1 else 0)
            raw = s.grab(follow_box() or region_box() or mons[idx])   # 跟随/框选/选中屏每帧现读，改完立刻生效
            im = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            b = io.BytesIO(); im.save(b, "JPEG", quality=Q, subsampling=SS)
            ts = time.time()
            with lock:
                ring.append((ts, b.getvalue())); stats["n"] = len(ring)
            stats["last_ok"] = ts
        except Exception as e:
            stats["err"] = repr(e)[:200]; time.sleep(0.5); continue
        if HOOK_Q:
            drain_hook_clicks()
        try:
            sens_update()
        except Exception:
            pass
        # 换前台窗口 = 硬事件：记一笔、并让下一帧立刻抓（不等 idle 那 200ms）
        try:
            fh = int(user32.GetForegroundWindow() or 0)
        except Exception:
            fh = 0
        if fh and fh != EV_FG["hwnd"]:
            if EV_FG["hwnd"]:
                EVENTS.append({"ts": time.time(), "kind": "window", "x": -1, "y": -1,
                               "hwnd": fh, "title": win_title(fh)[:120]})
                HOOK["burst"] = time.time()
                EV_BURST["at"] = time.time()
                ADAPT["last_move"] = time.time()
            EV_FG["hwnd"] = fh
            if PWD["on"]:
                pwd_probe_async()
        past = None
        with th_lock:
            for t_, a_ in reversed(THUMBS.items()):
                if t_ <= ts - ADAPT["win"]:
                    past = a_; break
        arr = _put_thumb(ts, im)
        if arr is not None:
            if past is not None and getattr(past, "shape", None) == arr.shape:
                stats["diff"] = round(float(np.mean(np.abs(arr - past))), 2)
            prev_thumb[0] = arr
        cnt += 1
        stats["cnt"] = cnt
        tsq.append(ts)
        while tsq and tsq[0] < ts - 3.0:
            tsq.popleft()
        if cnt % 5 == 0:
            # 瞬时帧率（最近 3 秒窗口），不跟整段平均混在一起
            stats["fps"] = round((len(tsq) - 1) / max(1e-6, tsq[-1] - tsq[0]), 1)
        dt = time.time() - t_start
        stats["ms"] = round(dt * 1000, 1)
        # 自动性能档：看最近这一段的真实耗时，吃力就退、缓过来再升（带迟滞，不来回抖）
        if AUTO["on"]:
            ams.append(dt * 1000.0)
            nm = time.time()
            if len(ams) >= 10 and nm - AUTO["last_check"] >= 2.0:
                avg = sum(ams) / len(ams)
                AUTO["avg_ms"] = round(avg, 1)
                AUTO["last_check"] = nm
                cur = min(auto_tiers(), key=lambda t: abs(t - AUTO["cap"]))
                if avg > AUTO_DOWN_MS:
                    nxt = auto_step(True)
                    if nxt < cur:
                        AUTO["cap"] = nxt
                        AUTO["note"] = "单帧 %.0fms 超预算，退到 %dfps" % (avg, nxt)
                    AUTO["up_since"] = 0.0
                elif avg < AUTO_UP_MS:
                    if not AUTO["up_since"]:
                        AUTO["up_since"] = nm
                    elif nm - AUTO["up_since"] >= AUTO_UP_HOLD:
                        nxt = auto_step(False)
                        if nxt > cur:
                            AUTO["cap"] = nxt
                            AUTO["note"] = "余量够了，升回 %dfps" % nxt
                        AUTO["up_since"] = 0.0
                else:
                    AUTO["up_since"] = 0.0
        gap = 1.0 / fps - dt
        if time.time() - HOOK["burst"] < 0.35 or time.time() - EV_BURST["at"] < 1.2:
            gap = 0.0        # 刚点了鼠标 / 刚换窗口：下一帧立刻抓，别等 idle 那 200ms
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
            stats["last_ok"] = ts
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
        if not (HOOK["on"] and HOOK["ok"]):    # 钩子在工作就别轮询，免得一次点击记两条
            down = bool(user32.GetAsyncKeyState(0x01) & 0x8000) or bool(user32.GetAsyncKeyState(0x02) & 0x8000)
            if down and not last_btn:
                try:
                    hwnd = user32.WindowFromPoint(POINT(x, y))
                except Exception:
                    hwnd = 0
                clicks.append({"ts": ts, "x": x, "y": y, "hwnd": int(hwnd or 0),
                               "title": win_title(hwnd or 0)[:120], "src": "poll"})
            last_btn = down
        time.sleep(0.02)

def _hook_thread():
    """WH_MOUSE_LL：最轻的一档鼠标钩子。失败就把 err 写上直接退出，轮询自动接回来。"""
    try:
        WH_MOUSE_LL = 14
        WM_DOWN = {0x0201: "L", 0x0204: "R", 0x020B: "M"}   # 左/右/中键按下
        WM_WHEEL = 0x020A                                    # 滚轮：也只进事件时间线
        class MSLLHOOKSTRUCT(ctypes.Structure):
            _fields_ = [("pt", POINT), ("mouseData", ctypes.c_uint32),
                        ("flags", ctypes.c_uint32), ("time", ctypes.c_uint32),
                        ("dwExtraInfo", ctypes.c_void_p)]
        class MSG(ctypes.Structure):
            _fields_ = [("hwnd", ctypes.c_void_p), ("message", ctypes.c_uint32),
                        ("wParam", ctypes.c_ssize_t), ("lParam", ctypes.c_ssize_t),
                        ("time", ctypes.c_uint32), ("x", ctypes.c_long), ("y", ctypes.c_long)]
        HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t)
        # 64 位下 lParam 是 64 位指针。不声明 argtypes 时 ctypes 按 32 位 int 传，
        # CallNextHookEx 会抛 OverflowError；回调没正常返回，系统就把整条鼠标事件吞掉（表现：钩子一开鼠标卡死）。
        user32.CallNextHookEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_ssize_t, ctypes.c_ssize_t]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t
        user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, ctypes.c_void_p, ctypes.c_uint32]
        user32.GetMessageW.argtypes = [ctypes.POINTER(MSG), ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        user32.GetMessageW.restype = ctypes.c_int

        def proc(nCode, wParam, lParam):
            try:
                if nCode >= 0:
                    code = int(wParam) & 0xFFFF
                    bt = WM_DOWN.get(code) or ("W" if code == WM_WHEEL else None)
                    if bt:
                        info = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKSTRUCT)).contents
                        ts = time.time()
                        if len(HOOK_Q) < 190:
                            HOOK_Q.append((ts, int(info.pt.x), int(info.pt.y), bt))
                        HOOK["events"] += 1
                        HOOK["at"] = ts
            except Exception:
                pass
            try:
                return user32.CallNextHookEx(None, nCode, wParam, lParam)
            except Exception:
                return 0            # 兜底：宁可放行也不要把事件链卡住

        cb = HOOKPROC(proc)          # 必须留引用：回调被 GC 掉，钩子就哑了
        HOOK["tid"] = threading.get_ident()
        user32.SetWindowsHookExW.restype = ctypes.c_void_p
        h = user32.SetWindowsHookExW(WH_MOUSE_LL, cb, None, 0)
        if not h:
            HOOK["err"] = "SetWindowsHookEx failed (%s)" % ctypes.get_last_error()
            return
        HOOK["ok"] = True
        HOOK["err"] = ""
        m = MSG()
        while not HOOK["stop"]:
            r = user32.GetMessageW(ctypes.byref(m), None, 0, 0)
            if r == 0 or r == -1:
                break
            user32.TranslateMessage(ctypes.byref(m))
            user32.DispatchMessageW(ctypes.byref(m))
        user32.UnhookWindowsHookEx(ctypes.c_void_p(h))
    except Exception as e:
        HOOK["err"] = repr(e)[:200]
    finally:
        HOOK["ok"] = False
        HOOK["on"] = False          # 线程没了就降级回轮询

def hooks_start():
    if HOOK["on"]:
        return True
    HOOK.update({"on": True, "stop": False, "err": ""})
    threading.Thread(target=_hook_thread, daemon=True).start()
    t0 = time.time()
    while time.time() - t0 < 1.5 and not HOOK["ok"] and not HOOK["err"]:
        time.sleep(0.05)
    if not HOOK["ok"]:
        HOOK["on"] = False
    return HOOK["ok"]

def hooks_stop():
    HOOK["stop"] = True
    tid = HOOK["tid"]
    if tid:
        try:
            user32.PostThreadMessageW(tid, 0x0012, 0, 0)   # WM_QUIT，让消息泵退出
        except Exception:
            pass
    t0 = time.time()
    while time.time() - t0 < 1.0 and HOOK["on"]:
        time.sleep(0.05)
    HOOK["ok"] = False
    HOOK["on"] = False
    return True

HOOK["want"] = hooks_load()

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

# 框选抓取区域：只想录一块（聊天窗、视频画面）时用。w/h 为 0 = 抓整屏。
REGION = {"x": 0, "y": 0, "w": 0, "h": 0}

def _load_region():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            r = (json.load(f) or {}).get("region")
        if isinstance(r, dict):
            for k in ("x", "y", "w", "h"):
                REGION[k] = int(r.get(k) or 0)
    except Exception:
        pass
_load_region()

# 跟随鼠标：只抓光标周围一块（默认 960x540，按屏大小夹）。开着时优先于框选区域。
FOLLOW = {"on": False, "w": 960, "h": 540}

def _load_follow():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            r = (json.load(f) or {}).get("follow")
        if isinstance(r, dict):
            FOLLOW["on"] = bool(r.get("on", False))
            FOLLOW["w"] = max(240, int(r.get("w") or 960))
            FOLLOW["h"] = max(180, int(r.get("h") or 540))
    except Exception:
        pass
_load_follow()

# 隐私打码：把指定矩形糊成马赛克再往外发。矩形存的是「屏幕坐标」，出图时按当前抓取区域折算到帧内——
# 这样改过抓取范围、换过屏，框还贴在同一块屏幕上，不会跟偏。只是画面模糊，不等于加密。
MASK = {"on": True, "rects": [], "auto": []}
# 敏感窗口自动挡：前台窗口标题命中这些词（银行/支付/密码管理这类），就把整个窗口糊掉。
# 这不是识别密码框（那条实测不可靠已撤），是按窗口标题的保守规则——宁可多糊，别漏。
SENS = {"on": True, "at": 0.0, "hwnd": 0, "title": "", "box": [],
        "words": ["银行", "支付", "网银", "密码", "凭据", "支付宝", "微信支付", "钱包",
                  "bank", "payment", "password", "credential"]}
SENS_LOCK = threading.Lock()
# 密码框自动打码：开着时每次换前台窗口，用 UIA 问一下这一窗里哪些框是密码框，把矩形也糊掉。
PWD = {"on": False, "at": 0.0, "busy": False, "n": 0, "err": ""}
PWD_LOCK = threading.Lock()

def _load_mask():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            m = (json.load(f) or {}).get("mask")
        if isinstance(m, dict):
            MASK["on"] = bool(m.get("on", True))
            PWD["on"] = bool(m.get("pwd", False))
            rs = m.get("rects") or []
            if isinstance(rs, list):
                out = []
                for r in rs:
                    if isinstance(r, (list, tuple)) and len(r) >= 4:
                        out.append([int(r[0]), int(r[1]), int(r[2]), int(r[3])])
                MASK["rects"] = out[:40]
    except Exception:
        pass
_load_mask()

def _load_sens():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            v = (json.load(f) or {}).get("sensitive")
        if isinstance(v, dict):
            if isinstance(v.get("on"), bool):
                SENS["on"] = v["on"]
            ws = v.get("words")
            if isinstance(ws, list) and ws:
                SENS["words"] = [str(w) for w in ws if str(w).strip()][:40]
    except Exception:
        pass
_load_sens()

def _win_rect(hwnd):
    """窗口在屏幕上的矩形；拿不到就空。"""
    try:
        r = RECT()
        if not user32.GetWindowRect(hwnd, ctypes.byref(r)):
            return []
        w = int(r.right - r.left); h = int(r.bottom - r.top)
        if w < 40 or h < 40:
            return []
        return [int(r.left), int(r.top), w, h]
    except Exception:
        return []

def sens_update():
    """前台窗口标题命中敏感词 → 整窗打码（保守规则：命中就整个窗口糊）。"""
    now = time.time()
    if now - SENS["at"] < 0.4:
        return
    SENS["at"] = now
    try:
        h = int(user32.GetForegroundWindow() or 0)
    except Exception:
        h = 0
    if not SENS["on"] or not h:
        with SENS_LOCK:
            SENS["hwnd"] = 0; SENS["title"] = ""; SENS["box"] = []
        return
    t = win_title(h)
    low = t.lower()
    hit = any((w.lower() in low) for w in SENS["words"] if w)
    if not hit:
        with SENS_LOCK:
            SENS["hwnd"] = h; SENS["title"] = ""; SENS["box"] = []
        return
    box = _win_rect(h)
    with SENS_LOCK:
        SENS["hwnd"] = h; SENS["title"] = t[:120]; SENS["box"] = box

def sens_rects():
    with SENS_LOCK:
        return [list(SENS["box"])] if SENS["box"] else []

def all_mask_rects():
    """手动框 + 自动挡 + 敏感窗口，全部折成屏幕坐标。"""
    return mask_rects_screen() + sens_rects()

def mask_rects_screen():
    """当前所有打码矩形（屏幕坐标）。关着就是空。"""
    if not MASK["on"]:
        return []
    return [[int(v) for v in r[:4]] for r in (list(MASK["rects"]) + list(MASK["auto"]))]

def rect_hit(nd, rects):
    """这个 UIA 节点（带 x/y/w/h，屏幕坐标）跟任一打码框有重叠吗。"""
    x = int(nd.get("x") or 0); y = int(nd.get("y") or 0)
    w = int(nd.get("w") or 0); h = int(nd.get("h") or 0)
    if w <= 0 or h <= 0:
        return False
    for mx, my, mw, mh in rects:
        if x < mx + mw and mx < x + w and y < my + mh and my < y + h:
            return True
    return False

def apply_mask(im):
    """把要挡的矩形打成马赛克；没框就原样返回。矩形是屏幕坐标，这里折算到帧内。"""
    if im is None:
        return im
    rects = all_mask_rects()
    if not rects:
        return im
    bb = base_box(); ox = int(bb["left"]); oy = int(bb["top"])
    fw, fh = im.size
    for sx, sy, mw, mh in rects:
        x, y = int(sx) - ox, int(sy) - oy
        x0 = max(0, min(fw, x)); y0 = max(0, min(fh, y))
        x1 = max(0, min(fw, x + int(mw))); y1 = max(0, min(fh, y + int(mh)))
        if x1 - x0 < 4 or y1 - y0 < 4:
            continue
        box = (x0, y0, x1, y1)
        reg = im.crop(box)
        k = 14
        sm = reg.resize((max(1, reg.size[0] // k), max(1, reg.size[1] // k)), Image.BILINEAR)
        im.paste(sm.resize(reg.size, Image.NEAREST), box)
    return im

def refresh_pwd_masks(force=False):
    """问 UIA 这一窗里哪些框是密码框，把它们的矩形加进打码区（自动挡密码，不用手框）。"""
    if not PWD["on"]:
        return
    if not PWD_LOCK.acquire(blocking=False):
        return
    try:
        now = time.time()
        if not force and now - PWD["at"] < 3.0:
            return
        PWD["busy"] = True; PWD["at"] = now
        _refresh_pwd_inner()
    finally:
        PWD["busy"] = False
        PWD_LOCK.release()

def _refresh_pwd_inner():
    try:
        d = _ps_run('eye_text.ps1', [0, 150], timeout=10)
        if not d.get("ok"):
            PWD["err"] = str(d.get("err") or "uia failed")[:120]; PWD["n"] = 0; MASK["auto"] = []
            return
        out = []
        for nd in d.get("nodes") or []:
            if not nd.get("p"):
                continue
            w = int(nd.get("w") or 0); h = int(nd.get("h") or 0)
            if w < 6 or h < 6:
                continue
            out.append([int(nd.get("x") or 0) - 3, int(nd.get("y") or 0) - 3, w + 6, h + 6])
        MASK["auto"] = out[:20]; PWD["n"] = len(MASK["auto"]); PWD["err"] = ""
    except Exception as e:
        PWD["err"] = repr(e)[:120]
    finally:
        PWD["busy"] = False

def pwd_probe_async():
    if PWD["on"] and not PWD["busy"]:
        threading.Thread(target=refresh_pwd_masks, daemon=True).start()

def _load_auto():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            v = (json.load(f) or {}).get("auto")
        if isinstance(v, bool):
            AUTO["on"] = v
    except Exception:
        pass
_load_auto()

def _load_mon():
    try:
        with open(CFG_PATH, "r", encoding="utf-8") as f:
            v = (json.load(f) or {}).get("monitor")
        if isinstance(v, (int, float)) and 0 <= int(v) <= 16:
            MON["i"] = int(v)
    except Exception:
        pass
_load_mon()
AUTO["cap"] = FPS_HI   # 跟着当前性能档起跳

def region_box():
    """有效框选区域（mss 用的 dict）；全屏时返回 None。"""
    if REGION["w"] >= 60 and REGION["h"] >= 60:
        return {"left": int(REGION["x"]), "top": int(REGION["y"]),
                "width": int(REGION["w"]), "height": int(REGION["h"])}
    return None

def monitor_list():
    """mss 的显示器清单：0 = 所有屏拼起来，1..n = 每块屏（物理像素）。拿不到就退回主屏。"""
    try:
        import mss
        s = mss.MSS()
        out = []
        for i, m in enumerate(s.monitors):
            out.append({"i": i, "left": int(m["left"]), "top": int(m["top"]),
                        "width": int(m["width"]), "height": int(m["height"])})
        return out
    except Exception:
        return [{"i": 1, "left": 0, "top": 0, "width": W, "height": H}]

def mon_box():
    lst = monitor_list()
    for m in lst:
        if m["i"] == MON["i"]:
            return {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}
    for m in lst:
        if m["i"] == 1:
            return {"left": m["left"], "top": m["top"], "width": m["width"], "height": m["height"]}
    return {"left": 0, "top": 0, "width": W, "height": H}

def follow_box():
    """跟随鼠标：以光标为中心的一块（夹在选中屏内，位置按 32px 网格量子化，免得帧框每像素抖）。"""
    if not FOLLOW["on"]:
        return None
    try:
        pt = POINT()
        user32.GetCursorPos(ctypes.byref(pt))
    except Exception:
        return None
    mb = mon_box()
    fw = min(int(FOLLOW["w"]), mb["width"])
    fh = min(int(FOLLOW["h"]), mb["height"])
    left = int(pt.x) - fw // 2
    top = int(pt.y) - fh // 2
    left = max(mb["left"], min(left, mb["left"] + mb["width"] - fw))
    top = max(mb["top"], min(top, mb["top"] + mb["height"] - fh))
    left -= left % 32
    top -= top % 32
    left = max(mb["left"], min(left, mb["left"] + mb["width"] - fw))
    top = max(mb["top"], min(top, mb["top"] + mb["height"] - fh))
    return {"left": left, "top": top, "width": fw, "height": fh}

def base_box():
    """这一帧实际抓的矩形：跟随鼠标 > 框选区域 > 当前选中的那块屏。"""
    return follow_box() or region_box() or mon_box()

def frame_size():
    b = base_box()
    return (b["width"], b["height"])

def save_cfg():
    try:
        payload = dict(CFG); payload["region"] = dict(REGION); payload["hooks"] = bool(HOOK["want"])
        payload["auto"] = bool(AUTO["on"])
        payload["monitor"] = int(MON["i"])
        payload["mask"] = {"on": bool(MASK["on"]), "rects": [list(r) for r in MASK["rects"]],
                           "pwd": bool(PWD["on"])}
        payload["sensitive"] = {"on": bool(SENS["on"]), "words": list(SENS["words"])}
        payload["follow"] = {"on": bool(FOLLOW["on"]), "w": int(FOLLOW["w"]), "h": int(FOLLOW["h"])}
        with open(CFG_PATH, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
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
            "near_frames": near, "far_frames": len(slow), "far_max": SLOW_MAX,
            "far_mb": round(slow_bytes[0] / 1e6, 1), "far_budget_mb": round(FAR_BUDGET / 1e6, 1),
            "est_mem_mb": round((near * a + slow_bytes[0]) / 1e6, 1),
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
    if "monitor" in q:
        v = _clamp(q["monitor"], 0, 16)
        if v is not None:
            MON["i"] = int(v)
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
        slow = collections.deque(list(slow)[-SLOW_MAX:])
        slow_bytes[0] = sum(len(j) for _, j in slow)
        trim_slow()
    AUTO["cap"] = FPS_HI; AUTO["avg_ms"] = 0.0; AUTO["up_since"] = 0.0
    AUTO["note"] = "自动" if AUTO["on"] else "关（按你设的档跑）"
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
            slow_add((ts, b.getvalue()))
        else:
            slow_add((ts, jb))             # 原帧直接进远层，不再编码

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
        canvas.paste(apply_mask(decode(jb)).resize((cw, ch), Image.BILINEAR), (x, y))
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

_PS_SEQ = [0]

def _ps_run(script, args, timeout=30):
    """Run one bundled PowerShell helper, passing an output JSON path; returns parsed dict."""
    ps = shutil.which('powershell') or shutil.which('pwsh')
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), script)
    if not ps or not os.path.exists(path):
        return {"ok": False, "err": "missing " + script}
    _PS_SEQ[0] += 1
    out = os.path.join(os.environ.get('TEMP') or '.',
                       'dsh-eye-ps-%d-%d-%d.json' % (os.getpid(), _PS_SEQ[0], int(time.time() * 1000) % 100000))
    try:
        p = subprocess.run([ps, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', path] + [str(a) for a in args] + [out],
                           capture_output=True, timeout=timeout)
        if not os.path.exists(out):
            raw = (p.stderr or b'') or (p.stdout or b'')
            try:
                msg = raw.decode('utf-8', 'replace')
            except Exception:
                msg = raw.decode('gbk', 'replace')
            msg = ' '.join(msg.split())[:200]
            return {"ok": False, "err": "ps: " + (msg or 'no output file')}
        with open(out, 'r', encoding='utf-8') as fh:
            return json.loads(fh.read() or '{}')
    except Exception as e:
        return {"ok": False, "err": str(e)[:160]}
    finally:
        try:
            os.remove(out)
        except Exception:
            pass


def text_from_window(hwnd=0, maxn=120):
    """UI Automation: real control names / values / document text of a window (no pixels, no tokens until asked)."""
    d = _ps_run('eye_text.ps1', [int(hwnd or 0), max(5, min(400, int(maxn)))])
    if not d.get('ok'):
        return d
    # 打码框挡住的字不往外给：先按屏幕坐标把节点滤掉，再拼文本。
    mr = all_mask_rects()
    d['masked'] = 0
    if mr:
        keep = []
        for nd in d.get('nodes') or []:
            if rect_hit(nd, mr):
                d['masked'] += 1
                continue
            keep.append(nd)
        d['nodes'] = keep
        if isinstance(d.get('pwds'), list):
            d['pwds'] = [p for p in d['pwds'] if not rect_hit(p, mr)]
    words = []
    for nd in d.get('nodes') or []:
        t = (nd.get('t') or '').strip()
        if t:
            words.append(t[:2000])
            continue
        v = (nd.get('v') or '').strip()
        if v:
            words.append(v[:400])
            continue
        nm = (nd.get('n') or '').strip()
        if nm:
            words.append(nm[:200])
    d['text'] = '\n'.join(words)[:8000]
    d['readable'] = len([w for w in words if len(w) > 1])
    return d


def text_from_pixels(jb, maxn=80):
    """OCR one JPEG frame with the Windows built-in engine (offline). Quality is rough on small UI text."""
    tmp = os.path.join(os.environ.get('TEMP') or '.', 'dsh-eye-ocr-%d.jpg' % int(time.time() * 1000))
    try:
        with open(tmp, 'wb') as fh:
            fh.write(jb)
        d = _ps_run('eye_ocr.ps1', [tmp, max(1, min(400, int(maxn)))])
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    if d.get('ok'):
        d['text'] = '\n'.join((l.get('t') or '') for l in d.get('lines') or [])[:8000]
    return d


def range_hits(hwnd=0, q="", maxn=10):
    """TextPattern: the exact on-screen rectangle of that text (Chromium/Electron trees are too shallow)."""
    q = (q or "").strip()
    if not q:
        return {"ok": False, "err": "need q", "hits": []}
    b64 = base64.b64encode(q.encode("utf-8")).decode("ascii")
    d = _ps_run("eye_find.ps1", [int(hwnd or 0), b64, int(maxn)], timeout=15)
    if not d.get("ok"):
        return {"ok": False, "err": d.get("err") or "eye_find failed", "hits": []}
    rects = all_mask_rects()
    hits = [h for h in (d.get("hits") or []) if not rect_hit(h, rects)]
    d["hits"] = hits
    d["n"] = len(hits)
    return d


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
        # 任何一条 GET 出错都别把连接掐了——回一段 JSON 带 traceback，面板/curl 都能看见原因
        try:
            self._do_get()
        except Exception:
            import traceback as _tb
            t = _tb.format_exc()
            try:
                self._json({"ok": False, "error": "handler crashed", "trace": t[-1800:]})
            except Exception:
                pass

    def _do_get(self):
        u = urlparse(self.path); q = {k: v[0] for k, v in parse_qs(u.query).items()}
        f, i_ = self._params(q)
        if u.path == "/state":
            items = snapshot()
            span = (items[-1][0] - items[0][0]) if len(items) > 1 else 0
            x, y = get_cursor()
            self._json({"frames": len(items), "fps": stats["fps"], "frame_ms": stats.get("ms"), "span_sec": round(span, 2),
                        "size": list(frame_size()), "screen": [W, H], "region": dict(REGION), "follow": {"on": bool(FOLLOW["on"]), "w": int(FOLLOW["w"]), "h": int(FOLLOW["h"])}, "cursor": [x, y], "clicks": len(clicks),
                        "monitor": dict({"i": MON["i"]}, **mon_box()), "monitors": monitor_list(), "dpi": DPI, "refresh": REFRESH,
                        "mask": {"on": bool(MASK["on"]), "count": len(MASK["rects"]), "rects": [list(r) for r in MASK["rects"]],
                                 "coord": "screen", "pwd": bool(PWD["on"]), "auto": len(MASK["auto"]), "auto_err": PWD["err"],
                                 "sens": {"on": bool(SENS["on"]), "hit": bool(SENS["box"]),
                                          "title": SENS["title"], "box": list(SENS["box"])}},
                        "last_click_ago": round(time.time() - clicks[-1]["ts"], 2) if clicks else None,
                        "err": stats["err"], "paused": bool(mode.get("paused")), "diff": stats.get("diff"), "want": stats.get("want"), "idle_ms": idle_ms(), "cnt": stats.get("cnt"),
                        "hooks": {"want": bool(HOOK["want"]), "on": bool(HOOK["on"]), "ok": bool(HOOK["ok"]),
                                  "events": HOOK["events"], "err": HOOK["err"],
                                  "last_event_ago": round(time.time() - HOOK["at"], 2) if HOOK["at"] else None},
                        "auto": {"on": bool(AUTO["on"]), "cap": AUTO["cap"], "avg_ms": AUTO["avg_ms"], "note": AUTO["note"]},
                        "events": {"n": len(EVENTS), "last": (EVENTS[-1]["kind"] if EVENTS else ""),
                                   "last_ago": (round(time.time() - EVENTS[-1]["ts"], 2) if EVENTS else None)},
                        "slow_frames": len(slow),
                        "slow_span_sec": round(slow[-1][0] - slow[0][0], 1) if len(slow) > 1 else 0}); return
        if u.path == "/monitors":
            self._json({"monitors": monitor_list(), "current": MON["i"], "dpi": DPI, "refresh": REFRESH,
                        "hint": "0 = 所有屏拼起来，1..n = 第 n 块屏（按左上角坐标排序）；换屏后近层会清空重新抓"}); return
        if u.path == "/monitor":
            if "i" in q:
                v = _clamp(q.get("i"), 0, 16)
                if v is not None:
                    MON["i"] = int(v)
                with lock:
                    ring.clear()
                slow.clear()
                save_cfg()
            self._json(dict({"i": MON["i"], "monitors": monitor_list()}, **mon_box())); return
        if u.path == "/auto":
            if "on" in q:
                v = str(q.get("on")).strip().lower() in ("1", "true", "on", "yes")
                AUTO["on"] = v
                AUTO["cap"] = FPS_HI; AUTO["up_since"] = 0.0; AUTO["avg_ms"] = 0.0
                AUTO["note"] = "自动" if v else "关（按你设的档跑）"
                save_cfg()
            self._json({"on": bool(AUTO["on"]), "cap": AUTO["cap"], "avg_ms": AUTO["avg_ms"], "note": AUTO["note"],
                        "hint": "开着时按实测单帧耗时自己落档/升回，用户不用懂参数；关掉就完全按面板设的帧率跑"}); return
        if u.path == "/hooks":
            if "on" in q:
                v = str(q.get("on")).strip().lower() in ("1", "true", "on", "yes")
                HOOK["want"] = v
                if v:
                    hooks_start()
                else:
                    hooks_stop()
                save_cfg()
            self._json({"want": bool(HOOK["want"]), "on": bool(HOOK["on"]), "ok": bool(HOOK["ok"]),
                        "events": HOOK["events"], "err": HOOK["err"],
                        "hint": "默认关。开着时由系统鼠标事件触发抓帧：点下去那一刻有帧、坐标就是真坐标；"
                                "钩子是系统级的，个别安全软件会提示，接受不了就关掉（关掉立刻回到轮询，功能不丢）"}); return
        if u.path == "/follow":
            if "off" in q:
                FOLLOW["on"] = False
            elif "on" in q:
                FOLLOW["on"] = str(q.get("on")).strip().lower() not in ("0", "false", "off", "no")
            if "w" in q and "h" in q:
                FOLLOW["w"] = max(240, i_("w", 960))
                FOLLOW["h"] = max(180, i_("h", 540))
            with lock:
                ring.clear(); stats["n"] = 0
            slow.clear(); slow_bytes[0] = 0
            act["box"] = None; act["score"] = 0.0
            save_cfg()
            fmode = "follow" if FOLLOW["on"] else ("region" if region_box() else "full")
            self._json({"ok": True, "follow": dict(FOLLOW), "size": list(frame_size()), "mode": fmode,
                        "hint": ("跟随鼠标：每帧按光标位置抓一块（" + str(FOLLOW["w"]) + "x" + str(FOLLOW["h"]) + "），"
                                 "光标走到哪儿眼就到哪儿；比全屏省，位置按 32 像素对齐不抖")
                                if FOLLOW["on"] else "跟随关掉了，回到框选区域/整屏"}); return
        if u.path == "/region":
            if "off" in q:
                REGION.update({"x": 0, "y": 0, "w": 0, "h": 0})
            elif "w" in q and "h" in q:
                rw = i_("w", 0); rh = i_("h", 0)
                if rw >= 60 and rh >= 60:
                    REGION.update({"x": i_("x", 0), "y": i_("y", 0), "w": rw, "h": rh})
            else:
                self._json({"region": dict(REGION), "size": list(frame_size()), "screen": [W, H]}); return
            with lock:
                ring.clear(); stats["n"] = 0
            slow.clear(); slow_bytes[0] = 0
            act["box"] = None; act["score"] = 0.0
            save_cfg()
            box = region_box()
            self._json({"ok": True, "region": dict(REGION), "size": list(frame_size()),
                        "mode": "region" if box else "full"}); return
        if u.path == "/region/pick":
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                subprocess.Popen([sys.executable, os.path.join(here, "eye_region.py")],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._json({"ok": True, "hint": "拖一个框，松手生效；点一下不拖或按 Esc = 恢复全屏"}); return
            except Exception as e:
                self._json({"ok": False, "error": repr(e)}); return
        if u.path == "/mask":
            if "off" in q:
                MASK["on"] = False
            elif "on" in q:
                MASK["on"] = str(q.get("on")).strip().lower() not in ("0", "false", "off", "no")
            elif "clear" in q:
                MASK["rects"] = []
            elif "w" in q and "h" in q:
                mw = i_("w", 0); mh = i_("h", 0)
                if mw >= 8 and mh >= 8:
                    # 一律按屏幕坐标存；出图/读字时再按当前抓取区域折算到帧内（换区域不会跟偏）
                    MASK["rects"].append([i_("x", 0), i_("y", 0), mw, mh])
                    MASK["rects"] = MASK["rects"][-40:]
                    MASK["on"] = True
            else:
                self._json({"on": bool(MASK["on"]), "rects": [list(r) for r in MASK["rects"]],
                            "count": len(MASK["rects"]), "size": list(frame_size()), "coord": "screen",
                            "hint": "坐标是屏幕像素（/state 的 cursor、clicks 都是屏幕坐标）。打码同时挡住出图和读字：框住的地方既不进图、也不进 eye_text。只是糊掉，不等于加密；原始帧只在内存里、不落盘"}); return
            save_cfg()
            self._json({"ok": True, "on": bool(MASK["on"]), "count": len(MASK["rects"]),
                        "rects": [list(r) for r in MASK["rects"]],
                        "hint": "开着的图上，这些区域会被打成马赛克"}); return
        if u.path == "/sensitive":
            if "on" in q:
                SENS["on"] = str(q.get("on")).strip().lower() not in ("0", "false", "off", "no")
                if not SENS["on"]:
                    with SENS_LOCK:
                        SENS["box"] = []; SENS["title"] = ""
                else:
                    SENS["at"] = 0.0
                save_cfg()
            self._json({"on": bool(SENS["on"]), "words": list(SENS["words"]),
                        "hit": bool(SENS["box"]), "title": SENS["title"], "box": list(SENS["box"]),
                        "hint": "开着时前台窗口标题命中敏感词（银行/支付/密码…）就把整个窗口糊掉；想加词改 " + CFG_PATH + " 里 sensitive.words"}); return
        if u.path == "/mask/pick":
            try:
                here = os.path.dirname(os.path.abspath(__file__))
                subprocess.Popen([sys.executable, os.path.join(here, "eye_mask.py")],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                self._json({"ok": True, "hint": "拖一个框，松手就把这块加进打码区；按 Esc 取消"}); return
            except Exception as e:
                self._json({"ok": False, "error": repr(e)}); return
        if u.path == "/mask/pwd":
            if "on" in q:
                PWD["on"] = str(q.get("on")).strip().lower() not in ("0", "false", "off", "no")
                if PWD["on"]:
                    pwd_probe_async()
                else:
                    MASK["auto"] = []; PWD["n"] = 0
                save_cfg()
            self._json({"pwd": bool(PWD["on"]), "auto": [list(r) for r in MASK["auto"]], "n": PWD["n"],
                        "err": PWD["err"],
                        "hint": "开着时每次换前台窗口会用无障碍接口问一遍密码框，自动糊掉；认不出就自己框。只是画面模糊，不是加密"}); return
        if u.path == "/config":
            self._json(apply_cfg(q) if q else cfg_state()); return
        if u.path == "/cursor":
            x, y = get_cursor()
            tr = [(round(t, 2), px, py) for t, px, py in list(trail)[-200:]]
            self._json({"x": x, "y": y, "trail": tr}); return
        if u.path == "/clicks":
            now = time.time()
            out = [{"ago": round(now - c["ts"], 2), "x": c["x"], "y": c["y"], "title": c["title"],
                    "src": c.get("src", "poll")} for c in list(clicks)[-20:]]
            out.reverse(); self._json({"clicks": out}); return
        if u.path == "/events":
            n = i_("n", 30)
            now = time.time()
            out = [{"ago": round(now - e["ts"], 2), "kind": e["kind"], "x": e["x"], "y": e["y"],
                    "title": e.get("title", "")} for e in list(EVENTS)[-n:]]
            out.reverse()
            self._json({"events": out, "n": len(EVENTS),
                        "hint": "kind = click / scroll / window；时间从近到远，ago 单位秒"}); return
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
                im = apply_mask(decode(jb)).crop((x0, y0, x0 + fw, y0 + fh)).resize((cw, ch), Image.BILINEAR)
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
            im = apply_mask(decode(best[1]))
            if u.path.startswith("/fovea") or "fw" in q:
                fw = i_("fw", 700); fh = i_("fh", 393)
                FW, FH = frame_size()
                if u.path == "/fovea_at_cursor":
                    cx, cy = get_cursor()
                    bb = base_box()           # 屏幕坐标 → 帧内坐标（框选区域或选中屏的左上角）
                    cx -= int(bb["left"]); cy -= int(bb["top"])
                else:
                    cx = i_("cx", FW // 2); cy = i_("cy", FH // 2)
                x0 = max(0, min(FW - fw, cx - fw // 2)); y0 = max(0, min(FH - fh, cy - fh // 2))
                im = im.crop((x0, y0, x0 + fw, y0 + fh))
            self._img(im); return
        if u.path in ("/live", "/peek"):
            items = snapshot()
            if not items: self._json({"error": "no frames"}); return
            try:
                im = apply_mask(decode(items[-1][1]))
            except Exception:
                self._json({"error": "decode"}); return
            tw = max(80, min(1280, i_("w", 480)))
            if im.size[0] > tw:
                im = im.resize((tw, max(1, int(im.size[1] * tw / im.size[0]))), Image.BILINEAR)
            b = io.BytesIO(); im.save(b, "JPEG", quality=max(30, min(95, i_("q", 65)))); d = b.getvalue()
            self.send_response(200); self.send_header("Content-Type", "image/jpeg"); self._cors()
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d); return
        if u.path == "/shot":
            items = snapshot()
            if not items: self._json({"error": "no frames"}); return
            target = items[-1][0] - f("t", 0)
            best = min(items, key=lambda x: abs(x[0] - target))
            if all_mask_rects():
                self._img(apply_mask(decode(best[1]))); return
            d = best[1]
            self.send_response(200); self.send_header("Content-Type", "image/jpeg")
            self.send_header("Content-Length", str(len(d))); self.end_headers(); self.wfile.write(d); return
        if u.path == "/text":
            hwnd = i_("hwnd", 0)
            if not hwnd:
                try:
                    hwnd = int(ctypes.windll.user32.GetForegroundWindow())
                except Exception:
                    hwnd = 0
            mx = max(5, min(400, i_("max", 120)))
            tmode = (q.get("mode") or ["auto"])[0]
            d = {"ok": False, "err": "skipped"}
            if tmode != "ocr":
                d = text_from_window(hwnd, mx)
            got = int(d.get("readable") or 0) if d.get("ok") else 0
            if tmode == "ocr" or (tmode == "auto" and got < 3):
                items = snapshot()
                jb = items[-1][1] if items else None
                if jb and all_mask_rects():
                    # OCR 走像素，也得先糊一遍再喂进去，否则打码对读字形同虚设
                    try:
                        buf = io.BytesIO(); apply_mask(decode(jb)).save(buf, "JPEG", quality=85); jb = buf.getvalue()
                    except Exception:
                        pass
                ocr = text_from_pixels(jb, min(120, mx)) if jb else {"ok": False, "err": "no frames"}
                if tmode == "ocr":
                    d = ocr
                elif got == 0:
                    d = ocr
                else:
                    d["ocr"] = ocr
            self._json(d); return
        if u.path == "/find":
            fq = (q.get("q") or [""])[0].strip()
            if not fq:
                self._json({"ok": False, "err": "need q"}); return
            hwnd = i_("hwnd", 0)
            if not hwnd:
                try:
                    hwnd = int(ctypes.windll.user32.GetForegroundWindow())
                except Exception:
                    hwnd = 0
            mx = max(10, min(400, i_("max", 200)))
            d = text_from_window(hwnd, mx)
            if not d.get("ok"):
                self._json({"ok": False, "err": d.get("err") or "uia failed"}); return
            key = fq.lower()
            rects = all_mask_rects()
            hits = []
            for nd in (d.get("nodes") or []):
                blob = (" ".join([str(nd.get("n") or ""), str(nd.get("v") or ""), str(nd.get("t") or "")])).lower()
                if key not in blob:
                    continue
                if rect_hit(nd, rects):
                    continue
                x = int(nd.get("x") or 0); y = int(nd.get("y") or 0)
                w = int(nd.get("w") or 0); h = int(nd.get("h") or 0)
                if w <= 0 or h <= 0:
                    continue
                nm = (nd.get("n") or nd.get("v") or (nd.get("t") or "")[:60]).strip()
                hits.append({"name": nm[:90], "role": str(nd.get("r") or ""), "src": "uia",
                             "x": x, "y": y, "w": w, "h": h, "cx": x + w // 2, "cy": y + h // 2})
                if len(hits) >= 40:
                    break
            src = "uia"
            note = ""
            wr = _win_rect(hwnd) or []
            warea = (int(wr[2]) * int(wr[3])) if len(wr) >= 4 else 0
            blunt = [h for h in hits
                     if ("Document" in h["role"]) or ("Window" in h["role"]) or ("Pane" in h["role"])
                     or (warea and h["w"] * h["h"] > warea * 0.15)]
            if (not hits) or (len(blunt) == len(hits)):
                # Chromium/Electron: ControlView tree is one window-sized Document; use document text ranges instead
                rd = range_hits(hwnd, fq, 12)
                rh = rd.get("hits") or []
                if rh:
                    hits = [{"name": fq, "role": "文字", "src": "uia-range",
                             "x": int(h["x"]), "y": int(h["y"]), "w": int(h["w"]), "h": int(h["h"]),
                             "cx": int(h["cx"]), "cy": int(h["cy"])} for h in rh]
                    src = "uia-range"
                    note = "（按文档里的文字定位，坐标是那段字在屏幕上的矩形）"
            ocr_note = ""
            if not hits:
                # 无障碍树里找不到（Qt / 自绘界面 / 游戏）：退回本地 OCR，按屏幕文字找坐标。
                items = snapshot()
                jb = items[-1][1] if items else None
                if jb:
                    try:
                        if all_mask_rects():
                            buf = io.BytesIO(); apply_mask(decode(jb)).save(buf, "JPEG", quality=85); jb = buf.getvalue()
                        ocr = text_from_pixels(jb, 160)
                    except Exception as ex:
                        ocr = {"ok": False, "err": str(ex)}
                    norm = lambda s: "".join(str(s or "").split()).lower()
                    key2 = norm(fq)
                    for ln in (ocr.get("lines") or []):
                        if key2 and key2 in norm(ln.get("t")):
                            x = int(ln.get("x") or 0); y = int(ln.get("y") or 0)
                            w = int(ln.get("w") or 0); h = int(ln.get("h") or 0)
                            if w <= 0 or h <= 0:
                                continue
                            hits.append({"name": str(ln.get("t"))[:90], "role": "OCR", "src": "ocr",
                                         "x": x, "y": y, "w": w, "h": h, "cx": x + w // 2, "cy": y + h // 2})
                            if len(hits) >= 20:
                                break
                    if hits:
                        src = "ocr"
                        ocr_note = "（无障碍树里没有，这是本地 OCR 按屏幕文字找的，整屏坐标，小字可能错）"
                    else:
                        ocr_note = "（无障碍树和本地 OCR 都没找到）"
            self._json({"ok": True, "q": fq, "hwnd": hwnd, "title": d.get("title"), "ms": d.get("ms"),
                        "count": len(hits), "items": hits, "masked": d.get("masked") or 0,
                        "src": src, "note": note or ocr_note}); return
        if u.path == "/activity":
            a = dict(act)
            a["ago"] = round(time.time() - a["at"], 2) if a["at"] else None
            a["frames"] = len(snapshot())
            self._json(a); return
        if u.path == "/chat/win":
            self._json({"hwnd": WIN["hwnd"], "at": round(WIN["at"], 2),
                        "alive": bool(WIN["at"] and time.time() - WIN["at"] < 30)}); return
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
        if u.path == "/chat/win":
            try:
                j = json.loads(raw.decode() or "{}")
            except Exception:
                j = {}
            WIN["hwnd"] = int(j.get("hwnd") or 0)
            WIN["at"] = time.time()
            self._json({"ok": True}); return
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

def _capture_supervisor():
    """采集线程掉了就再起一个，别安静地没了。"""
    while True:
        try:
            capture()
        except Exception as e:
            stats["err"] = "capture crashed: " + repr(e)[:160]
            try:
                sys.stdout.write("[eye] capture crashed: %r\n" % (e,)); sys.stdout.flush()
            except Exception:
                pass
        stats["started"] = 0.0
        time.sleep(1.0)


def capture_watchdog():
    """采集心跳：25 秒没新帧就当卡死，重启进程（HTTP 服务跟着重起），别让画面悄悄消失。"""
    time.sleep(8.0)
    while True:
        time.sleep(5.0)
        try:
            if stats.get("paused"):
                continue
            t0 = float(stats.get("started") or 0)
            if t0 <= 0:
                continue
            lo = max(float(stats.get("last_ok") or 0), t0)
            gap = time.time() - lo
            if gap > 25:
                stats["err"] = "capture stalled %.0fs: restarting" % gap
                try:
                    sys.stdout.write("[eye] capture stalled %.0fs, restarting\n" % gap); sys.stdout.flush()
                except Exception:
                    pass
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except Exception:
            pass


if __name__ == "__main__":
    if HOOK["want"]:
        hooks_start()
    threading.Thread(target=_capture_supervisor, daemon=True).start()
    threading.Thread(target=capture_watchdog, daemon=True).start()
    threading.Thread(target=pointer, daemon=True).start()
    threading.Thread(target=activity_loop, daemon=True).start()
    threading.Thread(target=slow_loop, daemon=True).start()
    time.sleep(1.5)
    print("eye_serve listening on %d, capture=%s" % (PORT, "mss" if not (os.environ.get("EYE_CAPTURE") or "").strip() else os.environ.get("EYE_CAPTURE")), flush=True)
    ThreadingHTTPServer(("127.0.0.1", PORT), Handler).serve_forever()
