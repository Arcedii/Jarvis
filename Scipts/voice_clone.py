# Scipts/voice_clone.py
from __future__ import annotations
import os
import re
import tempfile
import torch
from TTS.api import TTS
from Scipts.MainAgent import play_mp3

# --- FIX для PyTorch 2.6: разрешаем классы XTTS/Coqui при weights_only=True ---
try:
    from torch.serialization import add_safe_globals  # PyTorch >= 2.6
    allow = []
    # Основной конфиг XTTS
    try:
        from TTS.tts.configs.xtts_config import XttsConfig
        allow.append(XttsConfig)
    except Exception:
        pass
    # Аудио-конфиг XTTS (в разных версиях TTS встречается в разных местах)
    try:
        from TTS.tts.models.xtts import XttsAudioConfig
        allow.append(XttsAudioConfig)
    except Exception:
        try:
            from TTS.tts.configs.xtts_config import XttsAudioConfig as XttsAudioConfigCfg
            allow.append(XttsAudioConfigCfg)
        except Exception:
            pass
    # Общие конфиги Coqui, встречающиеся в чекпойнтах
    try:
        from TTS.config.shared_configs import BaseDatasetConfig
        allow.append(BaseDatasetConfig)
    except Exception:
        pass

    if allow:
        add_safe_globals(allow)
except Exception:
    # старый torch или уже разрешено — тихо пропускаем
    pass
# ------------------------------------------------------------------------

# Singleton TTS (инициализируется один раз)
_TTS = None

def _get_tts():
    global _TTS
    if _TTS is None:
        device = "cuda" if torch.cuda.is_available() else "cpu"
        # Для TTS 0.22.0 имя модели вот такое:
        _TTS = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
    return _TTS

def _ensure_wav(sample_path: str) -> str:
    """
    Возвращает путь к WAV. Если передан mp3 — конвертирует во временный wav.
    """
    sample_path = os.path.abspath(sample_path)
    ext = os.path.splitext(sample_path)[1].lower()
    if ext == ".wav":
        return sample_path

    # Конвертируем mp3 -> wav через pydub (нужен ffmpeg в PATH)
    try:
        from pydub import AudioSegment
    except Exception:
        raise RuntimeError("Для MP3 нужен pydub: pip install pydub (и ffmpeg в PATH)")
    if not os.path.exists(sample_path):
        raise FileNotFoundError(f"Эталон не найден: {sample_path}")

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".wav")
    tmp.close()
    AudioSegment.from_file(sample_path).export(tmp.name, format="wav")
    return tmp.name

def _split_sentences(text: str) -> list[str]:
    """
    Простая сегментация на предложения, чтобы не синтезировать длинные полотна.
    """
    text = (text or "").strip()
    if not text:
        return []
    # разделяем по . ! ? с сохранением знаков
    parts = re.split(r'([.!?]+)\s+', text)
    out = []
    for i in range(0, len(parts), 2):
        a = parts[i].strip()
        b = parts[i+1] if i+1 < len(parts) else ""
        s = (a + (b if b else "")).strip()
        if s:
            out.append(s)
    return out if out else [text]

def _normalize_dbfs(seg, target_dbfs: float = -14.0):
    """
    Нормализация громкости через pydub (нужно для ровного уровня).
    """
    from pydub import AudioSegment  # локальный импорт, если pydub ставили не всем
    if not isinstance(seg, AudioSegment):
        return seg
    try:
        diff = target_dbfs - seg.dBFS
    except Exception:
        return seg
    return seg.apply_gain(diff)

def speak_clone(
    text: str,
    sample_path: str | list[str],
    lang: str = "ru",
    speed: float = 0.88,
    pause_ms: int = 140,
    normalize_dbfs: float | None = -14.0
) -> str:
    """
    Синтезирует речь (клонирование из sample_path или списка путей),
    склеивает фразы с паузами, нормализует и проигрывает.
    """
    if not (text or "").strip():
        return "Пустой текст — озвучивать нечего."

    try:
        from pydub import AudioSegment  # для склейки и нормализации
    except Exception:
        return "Для аудио-склейки нужен pydub: pip install pydub (и ffmpeg в PATH)."

    try:
        tts = _get_tts()

        # 1) подготовка эталона(ов)
        sample_list = sample_path if isinstance(sample_path, list) else [sample_path]
        sample_wavs = [_ensure_wav(p) for p in sample_list]

        # 2) сегментация текста на короткие фразы
        sentences = _split_sentences(text)
        if not sentences:
            return "Пустой текст — озвучивать нечего."
        silence = AudioSegment.silent(duration=max(0, pause_ms))

        full = AudioSegment.silent(duration=0)
        for sent in sentences:
            # синтез в tmp-файл (важно: короткими кусками)
            with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
                out_path = tmp.name

            tts.tts_to_file(
                text=sent,
                speaker_wav=sample_wavs,  # список даёт устойчивее эмбеддинг
                language=lang,
                file_path=out_path,
                speed=float(speed)
            )

            seg = AudioSegment.from_file(out_path)
            full += seg + silence

            try:
                os.remove(out_path)
            except Exception:
                pass

        # 3) нормализация общей громкости (по желанию)
        if normalize_dbfs is not None:
            full = _normalize_dbfs(full, float(normalize_dbfs))

        # 4) сохраняем во временный WAV и проигрываем
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmpf:
            final_path = tmpf.name
        full.export(final_path, format="wav")

        return play_mp3(final_path)

    except Exception as e:
        return f"Ошибка синтеза: {e}"
