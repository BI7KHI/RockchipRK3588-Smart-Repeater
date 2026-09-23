# -*- coding: utf-8 -*-
"""端侧语音识别（ASR）服务：sherpa-onnx + SenseVoice int8（中英日韩粤）。

设计要点
--------
- **离线**：模型放 `/opt/ai/asr/<model_dir>`，推理全在板端 CPU（sherpa-onnx/onnxruntime），
  不依赖任何云端 API。
- **懒加载**：首次调用才加载模型（实测 2~3 s），之后常驻；用锁串行化解码，
  避免并发把 RK3588 的内存打满。
- **输入归一**：无论前端上传 wav/webm/opus/mp3，一律先用 ffmpeg 转成
  16 kHz / 单声道 / PCM16，再用 wave+numpy 读成 float32 送 `accept_waveform`
  （sherpa-onnx 1.13 未导出 `read_wave`/`accept_wave_file`，这里自行实现）。
- 记录 RTF（实时率）与耗时：实测 5~7 s 音频 ≈ 200~310 ms，**RTF≈0.04（约 25× 实时）**。
"""
import os
import subprocess
import threading
import time
import wave
from pathlib import Path

import numpy as np

LOG = '[ASR]'
MODEL_ROOT = Path(os.environ.get('RELAY_ASR_ROOT', '/opt/ai/asr'))
DEFAULT_MODEL_DIR = os.environ.get(
    'RELAY_ASR_MODEL',
    str(MODEL_ROOT / 'sherpa-onnx-sense-voice-zh-en-ja-ko-yue-int8-2024-07-17'))
NUM_THREADS = int(os.environ.get('RELAY_ASR_THREADS', '4') or 4)
LANGUAGE = os.environ.get('RELAY_ASR_LANG', 'auto')       # auto / zh / en / yue / ja / ko
USE_ITN = os.environ.get('RELAY_ASR_ITN', '1') not in ('0', 'false', 'False')
TARGET_SR = 16000

# 运行时可覆盖语言（settings 表的 asr_language）。
# 注意：SenseVoice 用 auto 判断中文无线电语音时很容易判成英文（实测把中文通联识别成
# "Yeah."），中继台站建议固定 zh。
_LANG_GETTER = None


def set_language_getter(fn):
    """注册一个返回当前语言的回调（通常读 settings.asr_language）。"""
    global _LANG_GETTER
    _LANG_GETTER = fn


def current_language():
    if _LANG_GETTER is not None:
        try:
            v = (_LANG_GETTER() or '').strip()
            if v:
                return v
        except Exception:
            pass
    return LANGUAGE


def _model_files(model_dir):
    """返回 (model.onnx, tokens.txt)；兼容 int8 / fp32 命名。"""
    d = Path(model_dir)
    model = None
    for name in ('model.int8.onnx', 'model.onnx'):
        if (d / name).exists():
            model = d / name
            break
    tokens = d / 'tokens.txt'
    return model, (tokens if tokens.exists() else None)


def model_ready(model_dir=None):
    model, tokens = _model_files(model_dir or DEFAULT_MODEL_DIR)
    return bool(model and tokens), str(model or ''), str(tokens or '')


def to_wav16k(src, dst):
    """任意音频 → 16k/单声道/PCM16（ffmpeg）。返回 (ok, err)。"""
    cmd = ['ffmpeg', '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
           '-i', str(src), '-ar', str(TARGET_SR), '-ac', '1', '-c:a', 'pcm_s16le', str(dst)]
    try:
        p = subprocess.run(cmd, capture_output=True, timeout=180)
        if p.returncode != 0:
            return False, p.stderr.decode('utf-8', 'replace')[-300:]
        return True, ''
    except Exception as e:
        return False, '%s: %s' % (type(e).__name__, e)


def read_wav_mono(path):
    """读 WAV → (float32 波形[-1,1], 采样率)。多声道取平均。"""
    with wave.open(str(path), 'rb') as w:
        sr = w.getframerate()
        ch = w.getnchannels()
        width = w.getsampwidth()
        raw = w.readframes(w.getnframes())
    if width == 2:
        a = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    elif width == 1:
        a = (np.frombuffer(raw, dtype=np.uint8).astype(np.float32) - 128.0) / 128.0
    elif width == 4:
        a = np.frombuffer(raw, dtype=np.int32).astype(np.float32) / 2147483648.0
    else:
        raise ValueError('不支持的位宽：%d' % width)
    if ch > 1:
        a = a.reshape(-1, ch).mean(axis=1)
    return a, sr


class AsrEngine:
    """SenseVoice 识别器封装（懒加载 + 串行解码）。"""

    def __init__(self):
        self._rec = None
        self._lock = threading.Lock()
        self._decode_lock = threading.Lock()
        self._load_error = ''
        self._loaded_lang = ''
        self.model_dir = DEFAULT_MODEL_DIR
        self.version = ''
        self.last = {}

    def ensure(self):
        with self._lock:
            want_lang = current_language()
            if self._rec is not None and want_lang != self._loaded_lang:
                # 语言变了：丢掉旧识别器按新语言重建
                print('%s 语言由 %s 切换为 %s，重载模型' % (LOG, self._loaded_lang, want_lang),
                      flush=True)
                self._rec = None
                self._load_error = ''
            if self._rec is not None:
                return True
            if self._load_error:
                return False
            ok, model, tokens = model_ready(self.model_dir)
            if not ok:
                self._load_error = ('未找到模型文件（%s）：需要 model.int8.onnx + tokens.txt'
                                    % self.model_dir)
                print(LOG, self._load_error, flush=True)
                return False
            try:
                import sherpa_onnx
                t0 = time.time()
                self.version = getattr(sherpa_onnx, '__version__', '')
                self._rec = sherpa_onnx.OfflineRecognizer.from_sense_voice(
                    model=model, tokens=tokens, num_threads=NUM_THREADS,
                    use_itn=USE_ITN, language=want_lang, debug=False)
                self._loaded_lang = want_lang
                print('%s 模型加载完成 %.1fs：%s（sherpa-onnx %s, threads=%d, lang=%s）'
                      % (LOG, time.time() - t0, Path(model).name, self.version,
                         NUM_THREADS, want_lang), flush=True)
                self._load_error = ''
                return True
            except Exception as e:
                self._load_error = '%s: %s' % (type(e).__name__, e)
                print(LOG, '模型加载失败：', self._load_error, flush=True)
                return False

    def status(self):
        ok, model, tokens = model_ready(self.model_dir)
        return {
            'engine': 'sherpa-onnx + SenseVoice int8',
            'loaded': self._rec is not None,
            'files_ok': bool(ok),
            'model_dir': self.model_dir,
            'model': Path(model).name if model else '',
            'tokens': Path(tokens).name if tokens else '',
            'sherpa_onnx': self.version,
            'threads': NUM_THREADS,
            'language': self._loaded_lang or current_language(),
            'language_wanted': current_language(),
            'use_itn': USE_ITN,
            'error': self._load_error,
            'last': self.last,
        }

    def transcribe(self, audio_path, work_dir='/tmp'):
        """识别音频文件 → {'ok','text','ms','seconds','rtf','wav'}。"""
        if not self.ensure():
            return {'ok': False, 'error': self._load_error or 'ASR 引擎不可用'}
        src = Path(audio_path)
        if not src.exists():
            return {'ok': False, 'error': '音频文件不存在：%s' % src}
        wav = Path(work_dir) / ('asr_%d.wav' % int(time.time() * 1000))
        ok, err = to_wav16k(src, wav)
        if not ok:
            return {'ok': False, 'error': '音频转码失败：%s' % err}
        try:
            samples, sr = read_wav_mono(wav)
            seconds = round(len(samples) / float(sr), 2) if sr else 0.0
            with self._decode_lock:
                t0 = time.time()
                stream = self._rec.create_stream()
                stream.accept_waveform(sr, samples)
                self._rec.decode_stream(stream)
                text = (stream.result.text or '').strip()
                ms = int((time.time() - t0) * 1000)
            rtf = round(ms / 1000.0 / seconds, 3) if seconds else 0
            self.last = {'text': text, 'ms': ms, 'seconds': seconds, 'rtf': rtf,
                         'ts': time.strftime('%H:%M:%S')}
            print('%s 识别 %.2fs → %d ms（RTF %.2f）：%s' % (LOG, seconds, ms, rtf, text[:60]),
                  flush=True)
            return {'ok': True, 'text': text, 'ms': ms, 'seconds': seconds, 'rtf': rtf,
                    'wav': str(wav)}
        except Exception as e:
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}

    def transcribe_samples(self, samples, sr=16000):
        """直接识别 float32 波形数组（跳过 ffmpeg 转码）。

        供「中继语音日志」按 VAD 切好的句子逐段识别使用：录音本身已经是
        16k/单声道，再走一次 ffmpeg 转码纯属浪费，且能拿到段级时间戳。
        """
        if not self.ensure():
            return {'ok': False, 'error': self._load_error or 'ASR 引擎不可用'}
        try:
            seconds = round(len(samples) / float(sr), 2) if sr else 0.0
            with self._decode_lock:
                t0 = time.time()
                stream = self._rec.create_stream()
                stream.accept_waveform(sr, samples)
                self._rec.decode_stream(stream)
                text = (stream.result.text or '').strip()
                ms = int((time.time() - t0) * 1000)
            rtf = round(ms / 1000.0 / seconds, 3) if seconds else 0
            return {'ok': True, 'text': text, 'ms': ms, 'seconds': seconds, 'rtf': rtf}
        except Exception as e:
            return {'ok': False, 'error': '%s: %s' % (type(e).__name__, e)}


ENGINE = AsrEngine()


def status():
    return ENGINE.status()


def transcribe(path, work_dir='/tmp'):
    return ENGINE.transcribe(path, work_dir=work_dir)


def transcribe_samples(samples, sr=16000):
    """识别 float32 波形数组（语音日志分段识别用）。"""
    return ENGINE.transcribe_samples(samples, sr)


def ensure():
    return ENGINE.ensure()
