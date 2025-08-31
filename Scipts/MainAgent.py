# Scipts/MainAgent.py
from __future__ import annotations
import os
import sys
from typing import Optional

# === Файл по умолчанию для команды "приветствие" (как раньше) ===
DEFAULT_GREETING_MP3 = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "JarvisVoice", "Здравствуйте сэр.mp3")
)

# --- Универсальный проигрыватель MP3 ---
def play_mp3(path: str) -> str:
    """
    Проигрывает MP3 из указанного пути.
    Возвращает строку-результат для GUI/логов.
    Поддерживает unicode-пути (кириллица) на Windows.
    """
    if not path:
        return "Путь к mp3 не указан."
    path = os.path.abspath(path)
    if not os.path.exists(path):
        return f"Файл не найден: {path}"

    try:
        if sys.platform.startswith("win"):
            return _play_mp3_windows(path)
        else:
            # На Linux/macOS можно подключить playsound или VLC.
            try:
                from playsound import playsound  # type: ignore
            except Exception:
                return "Для Linux/macOS установи: pip install playsound==1.2.2 (или подключи VLC/pydub)."
            try:
                playsound(path)
                return f"Проиграл: {os.path.basename(path)}"
            except Exception as e:
                return f"Ошибка при проигрывании (playsound): {e}"
    except Exception as e:
        return f"Ошибка при проигрывании: {e}"

def _play_mp3_windows(path: str) -> str:
    import ctypes
    mci = ctypes.windll.winmm.mciSendStringW
    alias = "jarvis_mp3_alias"

    # Закрыть предыдущий alias, если остался
    mci(f"close {alias}", None, 0, None)

    rc = mci(f'open "{path}" type mpegvideo alias {alias}', None, 0, None)
    if rc != 0:
        return f"MCI open error code: {rc}"

    try:
        rc = mci(f"play {alias} wait", None, 0, None)
        if rc != 0:
            return f"MCI play error code: {rc}"
    finally:
        mci(f"close {alias}", None, 0, None)

    return f"Проиграл: {os.path.basename(path)}"


# ---------- Совместимость с LLM-командами ----------
def handle_command(cmd: str) -> Optional[str]:
    """
    Точка входа для команд от LLM.
    СНОВА поддерживает 'приветствие' (как раньше).
    """
    if not cmd:
        return None

    c = cmd.strip().lower()
    if c in ("приветствие", "greeting", "hello_voice"):
        # играем стандартный файл по умолчанию
        return play_mp3(DEFAULT_GREETING_MP3)

    return f"Неизвестная команда: {cmd}"