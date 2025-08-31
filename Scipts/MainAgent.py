# Scipts/MainAgent.py
from __future__ import annotations
import os
import sys
from typing import Optional

# --- Путь к файлу приветствия (mp3) относительно этого файла ---
GREETING_MP3 = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "JarvisVoice", "Здравствуйте сэр.mp3")
)

def handle_command(cmd: str) -> Optional[str]:
    """
    Принимает строку команды и исполняет действие.
    Возвращает строку-результат для логов/GUI, либо None.
    """
    if not cmd:
        return None
    c = cmd.strip().lower()

    if c == "приветствие":
        return _play_greeting()

    return f"Неизвестная команда: {cmd}"

# -------------------- Реализация действий --------------------

def _play_greeting() -> str:
    if not os.path.exists(GREETING_MP3):
        return f"Файл не найден: {GREETING_MP3}"

    try:
        if sys.platform.startswith("win"):
            return _play_mp3_windows(GREETING_MP3)
        else:
            # На других ОС попробуем playsound, если установлен
            try:
                from playsound import playsound  # type: ignore
            except Exception:
                return "Для Linux/macOS установи: pip install playsound==1.2.2 (или используй VLC/pydub)."
            try:
                playsound(GREETING_MP3)
                return "Проиграл приветствие."
            except Exception as e:
                return f"Ошибка при проигрывании (playsound): {e}"
    except Exception as e:
        # Ловим любые неожиданные ошибки
        return f"Ошибка при проигрывании: {e}"

# --- Надёжное проигрывание MP3 на Windows через MCI (winmm) ---
def _play_mp3_windows(path: str) -> str:
    """
    Используем winmm.mciSendStringW — работает с путями в Unicode (кириллица).
    Никаких внешних библиотек не требуется.
    """
    import ctypes
    from ctypes import wintypes

    mci = ctypes.windll.winmm.mciSendStringW  # Unicode-версия
    alias = "jarvis_mp3"

    # Закрыть, если вдруг остался прежний alias
    mci(f"close {alias}", None, 0, None)

    # Открыть файл как mpegvideo
    rc = mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
    if rc != 0:
        return f"MCI open error code: {rc}"

    try:
        # Воспроизвести и ждать завершения
        rc = mci(f"play {alias} wait", None, 0, None)
        if rc != 0:
            return f"MCI play error code: {rc}"
    finally:
        mci(f"close {alias}", None, 0, None)

    return "Проиграл приветствие."
