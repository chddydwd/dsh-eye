# -*- coding: utf-8 -*-
"""隐私打码：全屏半透明遮罩上拖一个框，松手就把这块加进打码区（以后所有出图都糊掉它）。
点一下不拖 / 按 Esc = 取消。"""
import ctypes, os, traceback, tkinter as tk, urllib.request

LOG = os.path.join(os.path.expanduser("~"), ".dsh", "eye-mask.log")

def log(msg):
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(msg + "\n")
    except Exception:
        pass

try:
    ctypes.windll.shcore.SetProcessDpiAwareness(1)
except Exception:
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except Exception:
        pass

BASE = ("http://127.0.0.1:" + os.environ["EYE_PORT"]) if os.environ.get("EYE_PORT") else "http://127.0.0.1:13201"

def send(qs):
    try:
        urllib.request.urlopen(BASE + "/mask?" + qs, timeout=3).read()
        log("sent " + qs)
    except Exception as e:
        log("send failed " + repr(e))

def main():
    log("start")
    root = tk.Tk()
    root.overrideredirect(True)
    sw = root.winfo_screenwidth(); sh = root.winfo_screenheight()
    root.geometry("%dx%d+0+0" % (sw, sh))
    root.attributes("-topmost", True)
    root.attributes("-alpha", 0.35)
    root.configure(bg="black")
    cv = tk.Canvas(root, bg="black", highlightthickness=0, cursor="crosshair")
    cv.pack(fill="both", expand=True)
    cv.create_text(sw // 2, 40, text="拖一个框：这块以后在眼睛的输出里打码（Esc 取消）",
                   fill="#ffe066", font=("Microsoft YaHei UI", 16, "bold"))
    st = {"x0": 0, "y0": 0, "rect": None, "dim": None, "moved": False}

    def on_press(e):
        st["x0"], st["y0"] = e.x, e.y
        st["moved"] = False

    def on_drag(e):
        x0, y0 = st["x0"], st["y0"]
        if abs(e.x - x0) > 4 or abs(e.y - y0) > 4:
            st["moved"] = True
        if st["rect"]:
            cv.delete(st["rect"])
        if st["dim"]:
            cv.delete(st["dim"])
        st["rect"] = cv.create_rectangle(x0, y0, e.x, e.y, outline="#ff9e64", width=3, fill="#66331b")
        st["dim"] = cv.create_text(x0 + 8, min(y0, e.y) - 16, text="%d x %d" % (abs(e.x - x0), abs(e.y - y0)),
                                   fill="#ffe9d6", anchor="w", font=("Consolas", 11))

    def on_release(e):
        x0, y0 = st["x0"], st["y0"]
        x1, y1 = e.x, e.y
        left, top = min(x0, x1), min(y0, y1)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if st["moved"] and w >= 8 and h >= 8:
            send("x=%d&y=%d&w=%d&h=%d" % (left, top, w, h))
        root.destroy()

    cv.bind("<ButtonPress-1>", on_press)
    cv.bind("<B1-Motion>", on_drag)
    cv.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", lambda e: root.destroy())
    root.lift()
    root.attributes("-topmost", True)
    log("window %dx%d shown" % (sw, sh))
    root.mainloop()
    log("closed")

try:
    main()
except Exception:
    log(traceback.format_exc())
    raise
