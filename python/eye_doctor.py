# -*- coding: utf-8 -*-
"""眼睛体检：一次拉齐采集端 / 插件端 / 参数 / 进程开销，打印一行结论 + 细节。
用法：python eye_doctor.py [DSH端口]   （默认 58860，端口不对就传当前 GUI 的端口）
"""
import json, sys, urllib.request, subprocess, re

def get(url, timeout=3):
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode('utf-8', 'replace'))
    except Exception as e:
        return {"__err": str(e)}

def procs():
    out = {}
    try:
        raw = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq python.exe', '/FO', 'CSV', '/NH'],
                             capture_output=True, text=True, timeout=8).stdout
        for line in raw.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 5:
                out.setdefault('python', []).append(parts[4])
        raw2 = subprocess.run(['tasklist', '/FI', 'IMAGENAME eq ffmpeg.exe', '/FO', 'CSV', '/NH'],
                              capture_output=True, text=True, timeout=8).stdout
        for line in raw2.splitlines():
            parts = [p.strip('"') for p in line.split('","')]
            if len(parts) >= 5:
                out.setdefault('ffmpeg', []).append(parts[4])
    except Exception as e:
        out['err'] = str(e)
    return out

port = sys.argv[1] if len(sys.argv) > 1 else '58860'
eye = get('http://127.0.0.1:13201/state')
act = get('http://127.0.0.1:13201/activity')
cfg = get('http://127.0.0.1:13201/config')
plg = get('http://127.0.0.1:%s/dsh-eye/state' % port)

problems = []
alive = bool(plg.get('alive'))
if not alive: problems.append('采集进程不在了')
if eye.get('__err'): problems.append('采集端 /state 读不到：' + str(eye.get('__err'))[:60])
if eye.get('err'): problems.append('采集端报错：' + str(eye.get('err'))[:80])
fps = eye.get('fps')
if alive and isinstance(fps, (int, float)) and fps <= 0.2: problems.append('fps 跌到 %s（可能卡住）' % fps)
w = (plg.get('watch') or {})
if w.get('lastErr'): problems.append('提醒端报错：' + str(w.get('lastErr'))[:80])
if not w.get('on'): problems.append('主动提醒关着（也许是你自己关的）')

verdict = 'OK' if not problems else '注意：' + '；'.join(problems)
print('结论：' + verdict)
print('采集：' + json.dumps({k: eye.get(k) for k in ('frames', 'fps', 'span_sec', 'slow_frames', 'slow_span_sec', 'paused', 'err')}, ensure_ascii=False))
print('活动：' + json.dumps({k: act.get(k) for k in ('score', 'idle_ms', 'title', 'ago')}, ensure_ascii=False))
print('参数：' + json.dumps({k: cfg.get(k) for k in ('near_fps', 'near_span', 'quality', 'est_mem_mb', 'frame_kb')}, ensure_ascii=False))
print('提醒：' + json.dumps({k: w.get(k) for k in ('on', 'mode', 'threshold', 'gapSec', 'lastScore', 'lastErr')}, ensure_ascii=False)
      + ' 事件数=' + str(len(w.get('events') or [])))
print('进程：' + json.dumps(procs(), ensure_ascii=False))
