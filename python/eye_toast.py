# -*- coding: utf-8 -*-
"""眼睛的小提示条：屏幕大幅变化时，在最前面闪一条，不经过聊天框。
用法：python eye_toast.py "标题" "细节" [秒]
"""
import sys, tkinter as tk

title = sys.argv[1] if len(sys.argv) > 1 else '眼睛'
detail = sys.argv[2] if len(sys.argv) > 2 else ''
life = float(sys.argv[3]) if len(sys.argv) > 3 else 4.5

W = 430
root = tk.Tk()
root.overrideredirect(True)
root.attributes('-topmost', True)
root.attributes('-alpha', 0.95)
root.configure(bg='#0d1219')

sw = root.winfo_screenwidth()
frame = tk.Frame(root, bg='#0d1219', highlightbackground='#4aa8ff', highlightthickness=1)
frame.pack(fill='both', expand=True)
tk.Label(frame, text=title, bg='#0d1219', fg='#8fc6ff', font=('Microsoft YaHei UI', 10, 'bold'),
         anchor='w', justify='left', wraplength=W - 30).pack(fill='x', padx=12, pady=(8, 0))
if detail:
    tk.Label(frame, text=detail, bg='#0d1219', fg='#d8e6f5', font=('Microsoft YaHei UI', 9),
             anchor='w', justify='left', wraplength=W - 30).pack(fill='x', padx=12, pady=(3, 9))
else:
    tk.Frame(frame, bg='#0d1219', height=2).pack()

root.update_idletasks()
H = frame.winfo_reqheight()
root.geometry('%dx%d+%d+%d' % (W, H, sw - W - 24, 54))

def close(*_):
    try: root.destroy()
    except Exception: pass

frame.bind('<Button-1>', close)
for w in frame.winfo_children():
    w.bind('<Button-1>', close)
root.after(int(life * 1000), close)
root.mainloop()
