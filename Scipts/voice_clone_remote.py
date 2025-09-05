# Scipts/voice_clone_remote.py
from __future__ import annotations
import os
import hashlib
import tempfile
import requests
from typing import Optional

# Адрес твоего TTS-сервера
TTS_BASE_URL = os.getenv("TTS_BASE_URL", "http://192.168.100.8:8001")
DEFAULT_VOICE_ID = os.getenv("TTS_VOICE_ID", "jarvis")

# Опционально: импорт твоей функции проигрывания
try:
    from Scipts.MainAgent import play_mp3
except Exception:
    play_mp3 = None  # если нет — просто вернём путь к файлу


def _hash_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()[:12]


def ensure_voice_cloned(sample_path: str, voice_id: Optional[str] = None, timeout: int = 60) -> str:
    """
    Гарантирует, что голос загружен на сервере под voice_id.
    Если voice_id не задан — делаем стабильный из хэша файла (чтобы не плодить дубликаты).
    """
    voice_id = voice_id or f"v_{_hash_file(sample_path)}"
    url = f"{TTS_BASE_URL}/v1/clone"
    mime = "audio/wav" if sample_path.lower().endswith(".wav") else "audio/mpeg"
    with open(sample_path, "rb") as f:
        files = {"ref_audio": (os.path.basename(sample_path), f, mime)}
        data = {"voice_id": voice_id}
        r = requests.post(url, files=files, data=data, timeout=timeout)
    r.raise_for_status()
    return voice_id


def tts_to_wav_file(
    text: str,
    voice_id: str | None = None,
    language: str = "ru",
    speed: float = 0.88,
    sample_rate: int = 0,
    pause_ms: int = 180,         # НОВОЕ
    naturalize: int = 1,         # НОВОЕ
    temperature: float = 0.8,    # НОВОЕ
    top_p: float = 0.9,          # НОВОЕ
    timeout: int = 120,
) -> str:
    url = f"{TTS_BASE_URL}/v1/tts"
    data = {
        "text": text,
        "voice_id": voice_id or DEFAULT_VOICE_ID,
        "language": language,
        "speed": str(speed),
        "sample_rate": str(sample_rate),
        "pause_ms": str(pause_ms),
        "naturalize": str(naturalize),
        "temperature": str(temperature),
        "top_p": str(top_p),
    }
    with requests.post(url, data=data, stream=True, timeout=timeout) as r:
        r.raise_for_status()
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp:
            for chunk in r.iter_content(chunk_size=8192):
                if chunk:
                    tmp.write(chunk)
            return tmp.name



def speak_clone_remote(
    text: str,
    sample_path: str,
    lang: str = "ru",
    speed: float = 0.88,
    sample_rate: int = 0,
    voice_id: Optional[str] = None,
    do_play: bool = True,
    pause_ms: int = 180,         # НОВОЕ
    naturalize: int = 1,         # НОВОЕ
    temperature: float = 0.8,    # НОВОЕ
    top_p: float = 0.9,          # НОВОЕ
) -> str:
    """
    Высокоуровневая обёртка: проверяет/регистрирует голос, синтезирует и (опционально) проигрывает.
    Возвращает строку-результат для логов GUI.
    """
    if not (text or "").strip():
        return "Пустой текст — озвучивать нечего."

    try:
        vid = ensure_voice_cloned(sample_path, voice_id=voice_id)
    except Exception as e:
        return f"Ошибка /v1/clone: {e}"

    try:
        wav_path = tts_to_wav_file(
            text=text,
            voice_id=vid,
            language=lang,
            speed=speed,
            sample_rate=sample_rate,
            pause_ms=pause_ms,             # пробрасываем на сервер
            naturalize=naturalize,
            temperature=temperature,
            top_p=top_p,
        )
    except Exception as e:
        return f"Ошибка /v1/tts: {e}"

    if do_play and play_mp3:
        try:
            return play_mp3(wav_path)  # твой плеер
        except Exception as e:
            return f"Синтез ок, но ошибка проигрывания: {e}\nФайл: {wav_path}"
    else:
        return f"Синтез ок: {wav_path}"
