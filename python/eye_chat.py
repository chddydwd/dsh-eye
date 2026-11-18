# -*- coding: utf-8 -*-
"""眼睛的对话框小窗（画中画风格）：不经过 QQ，跟鲸鲸实时说话（看视频/一起玩的时候用）。

消息存在 eye_serve.py 的内存里（/chat 端点），这个窗口只负责：
  1) 你打字 → POST /chat（from=user）
  2) 每 0.7 秒拉一次新消息，把鲸鲸的回话（from=me）显示出来
纯本地（127.0.0.1:13201），不落盘、不联网。窗口可以拖、右下角可以拉大小，位置和大小记着。
"""
import ctypes
import json
import os
import urllib.request
import tkinter as tk

_u32 = ctypes.windll.user32
_k32 = ctypes.windll.kernel32

BASE = "http://127.0.0.1:13201"
GEO_PATH = os.path.join(os.path.expanduser("~"), ".dsh", "eye-chat.json")
BG = "#0d1219"
BORDER = "#2f5b7a"
FG = "#d8e6f5"
DIM = "#7d90a6"
ME = "#9be7b4"
YOU = "#8fc6ff"
FONT = ("Microsoft YaHei UI", 9)
SMALL = ("Microsoft YaHei UI", 8)
MINW, MINH = 280, 200


def api(path, data=None, timeout=3):
    try:
        if data is None:
            req = urllib.request.Request(BASE + path)
        else:
            body = json.dumps(data, ensure_ascii=False).encode()
            req = urllib.request.Request(BASE + path, data=body,
                                         headers={"content-type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode() or "{}")
    except Exception as e:
        return {"error": str(e)}


def load_geo(sw, sh):
    try:
        g = json.load(open(GEO_PATH, "r", encoding="utf-8"))
        w = max(MINW, min(1400, int(g.get("w") or 380)))
        h = max(MINH, min(1000, int(g.get("h") or 320)))
        x = int(g.get("x", sw - w - 24))
        y = int(g.get("y", sh - h - 72))
        x = max(0, min(sw - w, x))
        y = max(0, min(sh - h, y))
        return w, h, x, y
    except Exception:
        return 380, 320, sw - 404, sh - 392


class ChatWin:
    def __init__(self):
        self.last = 0
        self.alive = None
        self.root = tk.Tk()
        self.root.title("鲸鲸 · 对话框")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        self.root.attributes("-alpha", 0.97)
        self.root.configure(bg=BORDER)
        sw = self.root.winfo_screenwidth()
        sh = self.root.winfo_screenheight()
        self.w, self.h, self.x, self.y = load_geo(sw, sh)
        self.root.geometry("%dx%d+%d+%d" % (self.w, self.h, self.x, self.y))

        inner = tk.Frame(self.root, bg=BG)
        inner.pack(fill="both", expand=True, padx=1, pady=1)

        head = tk.Frame(inner, bg="#111c28")
        head.pack(fill="x", side="top")
        self.title = tk.Label(head, text="鲸鲸 · 对话框", bg="#111c28", fg="#8fc6ff",
                              font=("Microsoft YaHei UI", 9, "bold"), anchor="w", padx=8)
        self.title.pack(side="left", fill="x", expand=True, pady=3)
        self.dot = tk.Label(head, text="●", bg="#111c28", fg="#ff8a7a", font=SMALL)
        self.dot.pack(side="left", padx=(0, 3))
        self.status = tk.Label(head, text="没接上", bg="#111c28", fg=DIM, font=SMALL)
        self.status.pack(side="left")
        close = tk.Label(head, text=" × ", bg="#111c28", fg=DIM, font=("Microsoft YaHei UI", 10, "bold"))
        close.pack(side="right", padx=2)
        close.bind("<Button-1>", lambda e: self.close())

        foot = tk.Frame(inner, bg=BG)
        foot.pack(fill="x", side="bottom", padx=(6, 18), pady=(0, 6))
        self.entry = tk.Entry(foot, bg="#101a24", fg=FG, font=FONT, bd=0,
                              insertbackground="#8fc6ff", highlightthickness=1,
                              highlightbackground="#1e2c3c", highlightcolor="#3a6f9c",
                              relief="flat")
        self.entry.pack(side="left", fill="x", expand=True, ipady=4, padx=(0, 6))
        self.entry.bind("<Return>", lambda e: self.send())
        send = tk.Label(foot, text="发", bg=BG, fg="#5f7d99", font=("Microsoft YaHei UI", 9),
                        padx=6, cursor="hand2")
        send.pack(side="right")
        send.bind("<Button-1>", lambda e: self.send())
        send.bind("<Enter>", lambda e: send.configure(fg="#9fd0ff"))
        send.bind("<Leave>", lambda e: send.configure(fg="#5f7d99"))

        # 先给底部输入栏留位置，再让消息区吃掉剩下的高度（顺序反了输入栏会被挤没）
        body = tk.Frame(inner, bg=BG)
        body.pack(fill="both", expand=True, padx=6, pady=(4, 2))
        self.txt = tk.Text(body, bg="#0f1620", fg=FG, font=FONT, bd=0, wrap="word", height=6,
                           padx=6, pady=5, insertbackground=FG, selectbackground="#25476b",
                           highlightthickness=0)
        self.txt.pack(fill="both", expand=True)
        self.txt.tag_configure("you", foreground=YOU, font=("Microsoft YaHei UI", 9, "bold"))
        self.txt.tag_configure("me", foreground=ME, font=("Microsoft YaHei UI", 9, "bold"))
        self.txt.tag_configure("dim", foreground=DIM, font=SMALL)
        self.txt.configure(state="disabled")

        # 画中画：右下角留一个拉大小的把手
        self.grip = tk.Frame(inner, bg="#1a2a3c", width=13, height=13, cursor="bottom_right_corner")
        self.grip.place(relx=1.0, rely=1.0, anchor="se", x=-2, y=-2)
        self.grip.bind("<Button-1>", self._size_press)
        self.grip.bind("<B1-Motion>", self._size_drag)
        self.grip.bind("<ButtonRelease-1>", lambda e: self.save_geo())

        for w in (head, self.title, self.status):
            w.bind("<Button-1>", self._press)
            w.bind("<B1-Motion>", self._drag)
        self.root.bind("<ButtonRelease-1>", lambda e: self.save_geo())
        # 点窗口任何地方都把光标放回输入框（普通窗口的键盘焦点由系统给，这里只管输入框）
        self.root.bind_all("<Button-1>", self._focus_typing, add="+")
        self.root.bind("<FocusIn>", lambda e: self.entry.focus_force())
        # 调试：把键盘/焦点事件写文件，确认按键到底进没进来
        self._dbg = os.path.join(os.path.expanduser("~"), ".dsh", "eye-chat-keys.log")
        self.root.bind_all("<Key>", self._log_key, add="+")
        self.root.bind_all("<FocusIn>", self._log_focus, add="+")

        self.say_line("dim", "这里直接跟我说话，回车发出。我可以拉大小、拖着放哪都行。")
        try:
            with open(os.path.join(os.path.expanduser("~"), ".dsh", "eye-chat-hwnd.txt"), "w") as f:
                f.write(str(self._hwnd()))
        except Exception:
            pass
        self.root.after(120, self._dark_title)
        self.root.after(300, self.poll)
        self.root.after(400, self._focus_typing)
        self.root.after(600, self._assert_focus)

    def _hwnd(self):
        try:
            child = self.root.winfo_id()
            root = _u32.GetAncestor(child, 2)  # GA_ROOT
            return int(root or child)
        except Exception:
            return int(self.root.winfo_id())

    def _log(self, line):
        try:
            with open(self._dbg, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass

    def _log_key(self, e):
        self._log("KEY %s widget=%s focus=%s" % (e.keysym, e.widget, self.root.focus_get()))

    def _log_focus(self, e):
        self._log("FOCUS widget=%s focus=%s" % (e.widget, self.root.focus_get()))
        try:
            self.entry.focus_force()
            self._log("  -> focus now %s" % self.root.focus_get())
        except Exception as ex:
            self._log("  -> focus err %s" % ex)

    def _dark_title(self):
        """标题栏染成深色，跟窗口一套衣服。"""
        try:
            hwnd = self._hwnd()
            on = ctypes.c_int(1)
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_int(20), ctypes.byref(on), ctypes.sizeof(on))
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_int(19), ctypes.byref(on), ctypes.sizeof(on))
        except Exception:
            pass

    def _focus_typing(self, e=None):
        """无边框置顶窗点一下不会变成前台窗口，键盘就进不来；这里硬掰成前台。"""
        try:
            self.root.attributes("-topmost", True)
            hwnd = self._hwnd()
            fg = _u32.GetForegroundWindow()
            tid_fg = _u32.GetWindowThreadProcessId(fg, None)
            tid_me = _k32.GetCurrentThreadId()
            if tid_fg and tid_fg != tid_me:
                _u32.AttachThreadInput(tid_fg, tid_me, True)
                _u32.SetForegroundWindow(hwnd)
                _u32.AttachThreadInput(tid_fg, tid_me, False)
            else:
                _u32.SetForegroundWindow(hwnd)
            _u32.SetFocus(hwnd)
            self.root.focus_force()
            self.entry.focus_set()
            self.entry.focus_force()
        except Exception:
            pass

    def _assert_focus(self):
        """窗口在前台时，每 0.6 秒把键盘焦点按回输入框（无边框/置顶窗常丢焦点）。"""
        try:
            if _u32.GetForegroundWindow() == self._hwnd() and self.root.focus_get() is not self.entry:
                self.entry.focus_force()
        except Exception:
            pass
        try:
            self.root.after(600, self._assert_focus)
        except Exception:
            pass

    def _raise_me(self, e=None):
        try:
            self.root.lift()
        except Exception:
            pass

    # ---- 拖动窗口 ----
    def _press(self, e):
        self._ox, self._oy = e.x_root, e.y_root
        self._gx, self._gy = self.root.winfo_x(), self.root.winfo_y()

    def _drag(self, e):
        self.x = self._gx + e.x_root - self._ox
        self.y = self._gy + e.y_root - self._oy
        self.root.geometry("+%d+%d" % (self.x, self.y))

    # ---- 右下角拉大小 ----
    def _size_press(self, e):
        self._sx, self._sy = e.x_root, e.y_root
        self._sw, self._sh = self.root.winfo_width(), self.root.winfo_height()

    def _size_drag(self, e):
        self.w = max(MINW, self._sw + e.x_root - self._sx)
        self.h = max(MINH, self._sh + e.y_root - self._sy)
        self.root.geometry("%dx%d+%d+%d" % (self.w, self.h, self.root.winfo_x(), self.root.winfo_y()))

    def save_geo(self):
        try:
            self.x, self.y = self.root.winfo_x(), self.root.winfo_y()
            self.w, self.h = self.root.winfo_width(), self.root.winfo_height()
            os.makedirs(os.path.dirname(GEO_PATH), exist_ok=True)
            json.dump({"w": self.w, "h": self.h, "x": self.x, "y": self.y},
                      open(GEO_PATH, "w", encoding="utf-8"))
        except Exception:
            pass

    def close(self):
        self.save_geo()
        self.root.destroy()

    def set_alive(self, ok):
        if ok == self.alive:
            return
        self.alive = ok
        if ok:
            self.dot.configure(fg="#35c07a")
            self.status.configure(text="连着")
        else:
            self.dot.configure(fg="#ff8a7a")
            self.status.configure(text="眼睛没开")

    def say_line(self, tag, text):
        self.txt.configure(state="normal")
        self.txt.insert("end", ("我： " if tag == "me" else "你： " if tag == "you" else "") + text + "\n", tag)
        self.txt.configure(state="disabled")
        self.txt.see("end")

    def send(self):
        t = self.entry.get().strip()
        if not t:
            return
        r = api("/chat", {"text": t, "from": "user"})
        if not r.get("ok"):
            self.set_alive(False)
            return
        self.entry.delete(0, "end")
        self.last = max(self.last, int((r.get("msg") or {}).get("id") or 0))
        self.say_line("you", t)

    def poll(self):
        r = api("/chat?since=%d" % self.last, timeout=2)
        if "error" in r:
            self.set_alive(False)
        else:
            self.set_alive(True)
            for m in r.get("msgs") or []:
                mid = int(m.get("id") or 0)
                if mid <= self.last:
                    continue
                self.last = mid
                if m.get("from") == "me":
                    self.say_line("me", str(m.get("text") or ""))
                else:
                    self.say_line("you", str(m.get("text") or ""))
        try:
            self.root.after(700, self.poll)
        except Exception:
            pass


if __name__ == "__main__":
    import traceback
    try:
        ChatWin().root.mainloop()
    except Exception:
        with open(os.path.join(os.path.expanduser("~"), ".dsh", "eye-chat.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
