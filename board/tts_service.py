#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""端侧 TTS 服务辅助模块：Piper 本地合成 + OpenAI 兼容外部语音 API。"""
import json
import logging
import os
import re
import shutil
import subprocess
import tempfile
import time
import zipfile
from pathlib import Path

import requests

log = logging.getLogger('tts_service')

PIPER_DIR = Path('/opt/ai/piper')
PIPER_BIN = PIPER_DIR / 'piper'
PIPER_ESPEAK = PIPER_DIR / 'espeak-ng-data'
VOICES_DIR = Path('/opt/ai/voices')
PROTECTED_VOICES = {'zh_CN-huayan-medium'}   # 内置基座音色，禁止删除
TTS_CACHE_DIR = Path('/www/tts_cache')
TRAINING_DIR = Path('/opt/ai/voice_training')


def ensure_dirs():
    for p in (VOICES_DIR, TTS_CACHE_DIR, TRAINING_DIR):
        p.mkdir(parents=True, exist_ok=True)


def safe_name(name, default='voice'):
    name = re.sub(r'[^A-Za-z0-9_.-]+', '_', str(name or default)).strip('._')
    return name or default


def list_voices():
    ensure_dirs()
    voices = []
    for d in sorted(VOICES_DIR.iterdir()):
        if not d.is_dir():
            continue
        model = d / 'model.onnx'
        config = d / 'model.onnx.json'
        if not config.exists():
            config = d / 'config.json'
        meta = {}
        meta_file = d / 'voice.json'
        if meta_file.exists():
            try:
                meta = json.loads(meta_file.read_text(encoding='utf-8'))
            except Exception:
                meta = {}
        voices.append({
            'id': d.name,
            'name': meta.get('name') or d.name,
            'model': str(model),
            'config': str(config) if config.exists() else '',
            'ready': model.exists() and config.exists(),
            'size': model.stat().st_size if model.exists() else 0,
            'language': meta.get('language', 'zh-CN'),
            'description': meta.get('description', ''),
        })
    return voices


def piper_speak(text, voice_id, out_path):
    voice_id = safe_name(voice_id)
    voice_dir = VOICES_DIR / voice_id
    model = voice_dir / 'model.onnx'
    config = voice_dir / 'model.onnx.json'
    if not config.exists():
        config = voice_dir / 'config.json'
    if not model.exists() or not config.exists():
        raise FileNotFoundError(f'本地音色包不完整：{voice_id}')
    if not PIPER_BIN.exists():
        raise FileNotFoundError(f'Piper 未安装：{PIPER_BIN}')
    env = os.environ.copy()
    env['LD_LIBRARY_PATH'] = str(PIPER_DIR) + (':' + env.get('LD_LIBRARY_PATH', '') if env.get('LD_LIBRARY_PATH') else '')
    cmd = [
        str(PIPER_BIN),
        '--model', str(model),
        '--config', str(config),
        '--output_file', str(out_path),
        '--espeak_data', str(PIPER_ESPEAK),
    ]
    proc = subprocess.run(cmd, input=text.encode('utf-8'), cwd=str(PIPER_DIR),
                          env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
    if proc.returncode != 0 or not Path(out_path).exists():
        raise RuntimeError('Piper 合成失败: ' + (proc.stderr.decode('utf-8', errors='replace')[-500:]))
    return str(out_path)


def _openai_speech_url(base_url):
    """（已下线）外部 TTS 兼容层保留占位，当前不再被调用。"""
    base = (base_url or '').strip().rstrip('/')
    if not base:
        return ''
    if base.endswith('/audio/speech'):
        return base
    if base.endswith('/v1'):
        return base + '/audio/speech'
    return base + '/v1/audio/speech'


def find_external_api(apis, name):
    """（已下线）外部 TTS API 查找，保留以兼容旧数据。"""
    if not isinstance(apis, list):
        return None
    for item in apis:
        if isinstance(item, dict) and item.get('name') == name:
            return item
    return None


def synthesize(text, provider, voice_id, model=None, external_apis=None):
    """本地 Piper 合成。

    说明：按需求已下线外部 OpenAI 兼容 TTS，本函数只走板端本地模型；
    为兼容旧调用方，provider / model / external_apis 参数保留但会被忽略。
    """
    ensure_dirs()
    text = (text or '').strip()
    if not text:
        raise ValueError('文本不能为空')
    out_path = TTS_CACHE_DIR / f'tts_{time.strftime("%Y%m%d_%H%M%S")}_{os.getpid()}.wav'
    piper_speak(text, voice_id, out_path)
    return str(out_path)



def delete_voice(voice_id):
    """删除 /opt/ai/voices/<voice_id>；内置基座音色受保护。"""
    vid = safe_name(voice_id)
    if vid != voice_id:
        raise ValueError('音色 ID 非法')
    target = VOICES_DIR / vid
    if not target.is_dir():
        raise ValueError(f'音色不存在：{vid}')
    if vid in PROTECTED_VOICES:
        raise ValueError(f'内置音色不可删除：{vid}')
    shutil.rmtree(target)
    return {'id': vid, 'deleted': True}


def concat_wavs(paths, out_path, gap_ms=120):
    """把多段 22050Hz/单声道/16bit WAV 顺序拼接（段间插静音）。"""
    import wave as _wave
    frames = []
    rate = None
    for p in paths:
        with _wave.open(str(p), 'rb') as w:
            if rate is None:
                rate = w.getframerate()
            else:
                rate = max(rate, w.getframerate())
            frames.append((w.getframerate(), w.readframes(w.getnframes())))
    out = Path(out_path)
    with _wave.open(str(out), 'wb') as o:
        o.setnchannels(1); o.setsampwidth(2); o.setframerate(rate or 22050)
        gap = bytes(2 * int((rate or 22050) * gap_ms / 1000.0))  # 段间静音（16bit）
        for i, (sr, data) in enumerate(frames):
            if sr != rate:      # 采样率不一致时用最近邻拉伸（正常不会走到）
                import numpy as _np
                a = _np.frombuffer(data, dtype=_np.int16)
                a = a[_np.linspace(0, len(a) - 1, int(len(a) * rate / sr)).astype(_np.int64)]
                data = a.tobytes()
            if i:
                o.writeframes(gap)
            o.writeframes(data)
    return str(out)


def split_by_language(text):
    """把中英混排文本切成 [(lang, seg)]，标点/数字跟随当前段。"""
    segs = []
    cur, cur_lang = '', None
    for ch in text:
        if '一' <= ch <= '鿿':
            lang = 'zh'
        elif ('a' <= ch <= 'z') or ('A' <= ch <= 'Z'):
            lang = 'en'
        else:
            lang = cur_lang or 'zh'
        if cur_lang is None:
            cur_lang = lang
        if lang != cur_lang and ch.strip():
            segs.append((cur_lang, cur))
            cur, cur_lang = ch, lang
        else:
            cur += ch
    if cur.strip():
        segs.append((cur_lang or 'zh', cur))
    return segs


ICAO_WORDS = {
    'A': 'Alpha', 'B': 'Bravo', 'C': 'Charlie', 'D': 'Delta', 'E': 'Echo', 'F': 'Foxtrot',
    'G': 'Golf', 'H': 'Hotel', 'I': 'India', 'J': 'Juliett', 'K': 'Kilo', 'L': 'Lima',
    'M': 'Mike', 'N': 'November', 'O': 'Oscar', 'P': 'Papa', 'Q': 'Quebec', 'R': 'Romeo',
    'S': 'Sierra', 'T': 'Tango', 'U': 'Uniform', 'V': 'Victor', 'W': 'Whiskey',
    'X': 'X-ray', 'Y': 'Yankee', 'Z': 'Zulu',
}
ICAO_DIGITS = {'0': 'Zero', '1': 'One', '2': 'Two', '3': 'Three', '4': 'Four',
               '5': 'Five', '6': 'Six', '7': 'Seven', '8': 'Eight', '9': 'Nine'}
ICAO_DIGITS_AVIATION = {'3': 'Tree', '4': 'Fower', '5': 'Fife', '9': 'Niner'}


def expand_icao(text, aviation_digits=False, mark=False):
    """把呼号/单字母按 ICAO 字母解释法展开，便于电台口报清晰。

    规则（保守，避免误伤正常单词）：
      1) 含数字的大写呼号：BG7XYZ / B7X  -> Bravo Golf Seven X-ray Yankee Zulu
      2) 中文旁边(可带空格)的全大写字母组：呼号 ABC 收到 -> Alpha Bravo Charlie
      3) 孤立的单个大写字母：A -> Alpha（不会碰 X-ray 里的 X）
    所有规则放在「一轮」里替换，避免展开结果被后续规则再次命中（如 X-ray -> X-ray-ray）。
    """
    import re as _re
    digits = dict(ICAO_DIGITS)
    if aviation_digits:
        digits.update(ICAO_DIGITS_AVIATION)

    def spell(tok):
        out = ' '.join(ICAO_WORDS.get(c, digits.get(c, c)) for c in tok)
        # mark=True 时给展开片段加上 .. 标记，便于换用专门的 ICAO 音色
        return ('' + out + '') if mark else out

    # 规则2 先单独跑一次（要吃掉中文与字母之间的空格，同时保留空格）
    t = _re.sub(r'(?<=[\u4e00-\u9fff])(\s*)([A-Z]{2,6})(?![\u4e00-\u9fffA-Za-z0-9])',
                lambda m: m.group(1) + spell(m.group(2)), text)
    # 规则1 + 规则3 一轮完成
    pat = _re.compile(
        r'(?P<call>\b(?=[A-Z0-9]{2,10}\b)(?=[A-Z0-9]*[0-9])[A-Z][A-Z0-9]*\b)'
        r'|(?P<one>(?<![A-Za-z0-9-])[A-Z](?![A-Za-z0-9-]))'
    )
    return pat.sub(lambda m: spell(m.group(0)), t)


def _split_marked(text):
    """按语言切段；.. 包住的 ICAO 展开片段单独成段（kind='icao'）。"""
    import re as _re
    segs = []
    for part in _re.split(r'([^]*)', text or ''):
        if not part:
            continue
        if part.startswith('') and part.endswith(''):
            seg = part[1:-1].strip()
            if seg:
                segs.append(('icao', seg))
        else:
            for lang, seg in split_by_language(part):
                seg = seg.strip()
                if seg:
                    segs.append((lang, seg))
    return segs


def synthesize_multilingual(text, zh_voice, en_voice=None, icao=False, aviation_digits=False,
                            icao_voice=None):
    """中英混读：按语言分段，各自用对应音色合成后拼接。

    - 中文段：zh_voice
    - 英文段：en_voice（留空自动挑 language=en* 的音色）
    - ICAO 展开出的字母串（如 Bravo Golf Seven …）：icao_voice（留空自动优先 lessac
      等官方英文音色，咬字更清楚；都没有则退回 en_voice）
    """
    ensure_dirs()
    text = (text or '').strip()
    if not text:
        raise ValueError('文本不能为空')
    if icao:
        text = expand_icao(text, aviation_digits=aviation_digits, mark=True)
    en_voice = en_voice or pick_english_voice()
    icao_voice = icao_voice or pick_icao_voice()
    segs = _split_marked(text)
    if not segs:
        raise ValueError('没有可合成的片段')
    out_path = TTS_CACHE_DIR / f'tts_{time.strftime("%Y%m%d_%H%M%S")}_{os.getpid()}.wav'
    parts = []
    used = []
    for kind, seg in segs:
        if kind == 'zh':
            voice = zh_voice
        elif kind == 'icao':
            voice = icao_voice or en_voice or zh_voice
        else:
            voice = en_voice or zh_voice
        p = TTS_CACHE_DIR / f'seg_{time.strftime("%H%M%S")}_{len(parts)}_{os.getpid()}.wav'
        piper_speak(seg, voice, p)
        parts.append(p)
        used.append((kind, voice, seg))
    if len(parts) == 1:
        shutil.copyfile(str(parts[0]), str(out_path))
    else:
        concat_wavs(parts, out_path)
    for p in parts:
        try:
            Path(p).unlink()
        except Exception:
            pass
    try:
        log.info('multilingual 分段音色: %s', [(k, v) for k, v, _ in used])
    except Exception:
        pass
    return str(out_path)


def pick_icao_voice():
    """挑一个专门读 ICAO 字母串的音色：优先 lessac 等官方英文音色（咬字清晰）。"""
    try:
        voices = [v for v in list_voices() if v.get('ready')]
        for key in ('lessac', 'en_us', 'en-us'):
            for v in voices:
                if key in str(v.get('id', '')).lower():
                    return v['id']
    except Exception:
        pass
    return None


def pick_english_voice():
    """自动挑一个 language 以 en 开头的音色；没有则返回 None（回退中文音色）。"""
    try:
        for v in list_voices():
            if str(v.get('language', '')).lower().startswith('en') and v.get('ready'):
                return v['id']
    except Exception:
        pass
    return None

def extract_zip_safely(zip_stream, target_dir):
    target_dir = Path(target_dir)
    target_dir.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp) / 'upload.zip'
        zip_stream.save(str(tmp_path))
        with zipfile.ZipFile(tmp_path) as zf:
            for member in zf.infolist():
                name = member.filename
                if name.startswith('/') or '..' in Path(name).parts:
                    raise ValueError('压缩包包含非法路径')
                zf.extract(member, target_dir)
    return target_dir


def save_voice_zip(zip_stream, voice_id):
    voice_id = safe_name(voice_id)
    target = VOICES_DIR / voice_id
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True, exist_ok=True)
    extract_zip_safely(zip_stream, target)
    # 兼容压缩包内多一层目录
    candidates = list(target.rglob('model.onnx'))
    if len(candidates) == 1 and candidates[0].parent != target:
        src = candidates[0].parent
        for item in src.iterdir():
            shutil.move(str(item), str(target / item.name))
        try:
            src.rmdir()
        except OSError:
            pass
    model = target / 'model.onnx'
    config = target / 'model.onnx.json'
    if not config.exists():
        config = target / 'config.json'
    if not model.exists() or not config.exists():
        raise ValueError('音色包必须包含 model.onnx 和 model.onnx.json')

    # 板端 piper 是 2023 版 C++ 实现，phoneme_id_map 的键必须是「单个 Unicode 码点」；
    # 新版 piper 训练出的模型常带 "aɪ" / "aʊ" 这类多码点键，会导致 piper 直接崩溃：
    #   [piper] [error] "aɪ" is not a single codepoint
    # 这些多码点键在中文场景不会被板端 espeak 输出，直接剔除即可（不改变其它 id）。
    fixed = _sanitize_voice_config(config)
    return {'id': voice_id, 'voice_dir': str(target), 'ready': True, 'phoneme_fix': fixed}


def _sanitize_voice_config(config_path):
    """剔除 phoneme_id_map 里的多码点键，返回被剔除的键列表。"""
    try:
        data = json.loads(Path(config_path).read_text(encoding='utf-8'))
    except Exception:
        return []
    pid_map = data.get('phoneme_id_map')
    if not isinstance(pid_map, dict):
        return []
    bad = [k for k in pid_map if not isinstance(k, str) or len(k) != 1]
    if not bad:
        return []
    for k in bad:
        pid_map.pop(k, None)
    try:
        shutil.copyfile(str(config_path), str(config_path) + '.bak_multicodepoint')
    except Exception:
        pass
    Path(config_path).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    return bad


def save_training_zip(zip_stream, dataset_id):
    dataset_id = safe_name(dataset_id, 'dataset')
    target = TRAINING_DIR / dataset_id
    target.mkdir(parents=True, exist_ok=True)
    extract_zip_safely(zip_stream, target)
    mark = target / 'UPLOAD_INFO.txt'
    mark.write_text(
        f'上传时间：{time.strftime("%Y-%m-%d %H:%M:%S")}\n'
        '说明：RK3588 板端不直接进行神经网络 TTS 训练。\n'
        '建议在 PC/服务器上使用 Piper 训练流程或 GPT-SoVITS 等方案完成微调，\n'
        '导出为 Piper ONNX 音色包后，通过“上传音色包”部署到 /opt/ai/voices。\n',
        encoding='utf-8')
    return {'dataset_id': dataset_id, 'path': str(target)}


def list_training_jobs():
    ensure_dirs()
    jobs = []
    for d in sorted(TRAINING_DIR.iterdir()):
        if d.is_dir():
            jobs.append({'id': d.name, 'path': str(d), 'mtime': d.stat().st_mtime})
    return jobs
