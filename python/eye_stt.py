# -*- coding: utf-8 -*-
"""眼睛小窗的本地语音转文字（faster-whisper，离线 CPU）。

不联网（模型下载只在第一次，走 hf-mirror），不落盘音频：录音直接进内存，转完就丢。
模型第一次用时加载（small 约 460MB 内存，加载 2-4 秒），之后常驻在这个进程里。
"""
import io
import os
import threading
import wave

# Whisper 的中文输出经常是繁体；装了 opencc（可选）就转简体。
try:
    from opencc import OpenCC as _OpenCC
    _T2S = _OpenCC("t2s")
except Exception:
    _T2S = None


def to_simplified(s):
    """繁体 → 简体。没装 opencc 就原样返回，不影响能用。"""
    if not s or _T2S is None:
        return s
    try:
        return _T2S.convert(s)
    except Exception:
        return s


_PROMPT = "以下是普通话的句子，用简体中文。"
# 给界面上的术语一点偏好，短句不容易听成谐音（faster-whisper 的 hotwords）。
_HOTWORDS = ("鼠标 钩子 隐私打码 敏感窗口 自动挡 跟随 整屏 框一块 灵敏度 面板 眼睛 采集 帧率 "
             "快捷键 对话框 语音 简体 开启 关闭 设置 修复")


def _norm(s):
    """去掉标点/空白，用来比对。"""
    drop = "，。,.!！?？、；;：: \u3000\"'“”‘’（）()"
    return "".join(ch for ch in (s or "") if ch not in drop).lower()


def _prompt_echo(s):
    """Whisper 在静音、噪声、极短音频上会把 initial_prompt 当正文吐出来。
    这种不是用户说的话，直接丢掉。"""
    if not s:
        return True
    import difflib
    t = _norm(s)
    if not t:
        return True
    if difflib.SequenceMatcher(None, t, _norm(_PROMPT)).ratio() >= 0.55:
        return True
    return ("用简体中文" in s) and ("普通话" in s)


MODEL_SIZE = os.environ.get("EYE_STT_MODEL", "small")
_HERE = os.path.dirname(os.path.abspath(__file__))
_MODEL = None
_LOAD_LOCK = threading.Lock()
_LOAD_ERR = ""


def model_dir():
    """本地模型目录（放了就不下载）。可选 EYE_STT_MODEL_DIR 指定。"""
    d = os.environ.get("EYE_STT_MODEL_DIR")
    if d:
        return d if os.path.isfile(os.path.join(d, "model.bin")) else None
    for cand in (os.path.join(_HERE, "models", "faster-whisper-" + MODEL_SIZE),
                 os.path.join(_HERE, "..", "models", "faster-whisper-" + MODEL_SIZE)):
        if os.path.isfile(os.path.join(cand, "model.bin")):
            return os.path.abspath(cand)
    return None


def available():
    """依赖在不在。"""
    try:
        import faster_whisper  # noqa: F401
        return True, ""
    except Exception as e:
        return False, str(e)[:160]


def load():
    """加载模型（第一次慢，之后就是现成的）。失败抛异常，错误记在 load_error() 里。"""
    global _MODEL, _LOAD_ERR
    with _LOAD_LOCK:
        if _MODEL is not None:
            return _MODEL
        try:
            os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
            os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
            os.environ.setdefault("HF_HUB_DISABLE_XET", "1")   # xet 走代理会卡 0 字节，关掉
            from faster_whisper import WhisperModel
            target = model_dir() or MODEL_SIZE
            _MODEL = WhisperModel(target, device="cpu", compute_type="int8")
            _LOAD_ERR = ""
            return _MODEL
        except Exception as e:
            _LOAD_ERR = str(e)[:200]
            raise


def load_error():
    return _LOAD_ERR


def pcm_to_wav_bytes(pcm, rate=16000):
    """int16 单声道 PCM → wav 字节（faster-whisper 要文件或 numpy）。"""
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm)
    return buf.getvalue()


def transcribe_pcm(pcm, rate=16000, language="zh"):
    """一段 int16 PCM → 文字。"""
    import numpy as np
    if pcm is None or len(pcm) < rate // 2:
        return ""   # 太短当没说话（半秒以下 Whisper 只会瞎编）
    m = load()
    audio = np.frombuffer(pcm, dtype=np.int16).astype("float32") / 32768.0
    segs, info = m.transcribe(audio, language=language, beam_size=1, vad_filter=True,
                              condition_on_previous_text=False,
                              initial_prompt=_PROMPT if language == "zh" else None,
                              hotwords=_HOTWORDS if language == "zh" else None)
    txt = to_simplified("".join(s.text for s in segs).strip())
    return "" if _prompt_echo(txt) else txt


def transcribe_file(path, language="zh"):
    """音频文件 → 文字。wav 用标准库解（不受 PyAV 版本影响），其它格式交给 faster-whisper。"""
    p = str(path)
    if p.lower().endswith(".wav"):
        try:
            with wave.open(p, "rb") as w:
                if w.getnchannels() == 1 and w.getsampwidth() == 2:
                    return transcribe_pcm(w.readframes(w.getnframes()), w.getframerate(), language)
        except Exception:
            pass
    m = load()
    segs, info = m.transcribe(p, language=language, beam_size=1, vad_filter=True,
                              condition_on_previous_text=False,
                              initial_prompt=_PROMPT if language == "zh" else None,
                              hotwords=_HOTWORDS if language == "zh" else None)
    txt = to_simplified("".join(s.text for s in segs).strip())
    return "" if _prompt_echo(txt) else txt
