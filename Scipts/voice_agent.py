# Scipts/voice_agent.py
from __future__ import annotations
import json
import queue
import threading
import time
from dataclasses import dataclass
from typing import Callable, Optional

import sounddevice as sd
from vosk import Model, KaldiRecognizer  # pip install vosk sounddevice

# ------------ Настройки ------------
WAKE_WORDS = ("джарвис", "jarvis")   # ключевое слово
SAMPLE_RATE = 16000                  # 16kHz моно
BLOCK_SIZE = 8000                    # ~0.5s блок
COMMAND_TIMEOUT = 6.0                # сколько секунд слушаем команду после ключевого слова

@dataclass
class VoiceConfig:
    vosk_model_path: str  # путь к распакованной модели Vosk (ru)
    wake_words: tuple = WAKE_WORDS


class VoiceAgent:
    """
    Всегда слушаем микрофон, ждём ключевое слово.
    После "джарвис ..." — собираем следующую фразу как команду
    и отдаём её в on_command(text).
    """
    def __init__(self, cfg: VoiceConfig, on_status: Optional[Callable[[str], None]] = None,
                 on_command: Optional[Callable[[str], None]] = None,
                 on_wake: Optional[Callable[[], None]] = None): 
        self.cfg = cfg
        self.on_status = on_status or (lambda s: None)
        self.on_command = on_command or (lambda t: None)
        self.on_wake = on_wake or (lambda: None)

        self._audio_q: "queue.Queue[bytes]" = queue.Queue()
        self._stream: Optional[sd.InputStream] = None
        self._rec: Optional[KaldiRecognizer] = None
        self._model: Optional[Model] = None

        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._awaiting_command = False
        self._last_wake_ts = 0.0
        self._buffered_text = ""

    # ---------- Публичное ----------
    def start(self):
        if self._running:
            return
        self._running = True
        self.on_status("инициализация…")
        self._model = Model(self.cfg.vosk_model_path)
        self._rec = KaldiRecognizer(self._model, SAMPLE_RATE)
        self._rec.SetWords(False)

        self._stream = sd.InputStream(
            samplerate=SAMPLE_RATE,
            channels=1,
            dtype="int16",
            blocksize=BLOCK_SIZE,
            callback=self._audio_callback,
        )
        self._stream.start()

        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.on_status("слушаю (ожидаю «джарвис»)")

    def stop(self):
        self._running = False
        try:
            if self._stream:
                self._stream.stop()
                self._stream.close()
        finally:
            self._stream = None
        self.on_status("голос остановлен")

    # ---------- Внутреннее ----------
    def _audio_callback(self, indata, frames, time_info, status):
        if status:
            self.on_status(f"аудио статус: {status}")
        self._audio_q.put(bytes(indata))

    def _loop(self):
        assert self._rec is not None
        while self._running:
            try:
                data = self._audio_q.get(timeout=0.5)
            except queue.Empty:
                # таймаут командного окна
                self._check_timeout()
                continue

            if self._rec.AcceptWaveform(data):
                result = self._try_parse(self._rec.Result())
                if result:
                    self._handle_text(result)
            else:
                partial = self._try_parse(self._rec.PartialResult(), partial=True)
                if partial:
                    self._handle_partial(partial)

            self._check_timeout()

    def _try_parse(self, s: str, partial: bool = False) -> Optional[str]:
        try:
            j = json.loads(s)
            txt = j.get("partial" if partial else "text", "").strip().lower()
            return txt or None
        except Exception:
            return None

    def _handle_partial(self, txt: str):
        # можно подсвечивать статус
        pass

    def _handle_text(self, txt: str):
        if not txt:
            return
        # если ждали ключевое слово
        if not self._awaiting_command:
            if any(w in txt for w in self.cfg.wake_words):
                try:
                    self.on_wake()                                # <--- добавили
                except Exception:
                    pass
                self._awaiting_command = True
                self._last_wake_ts = time.time()
                self._buffered_text = ""
                self.on_status("ключевое слово! говори команду…")
            return

        # тут мы уже в режиме ожидания команды
        self._buffered_text += (" " + txt).strip()

        # команда готова — отдать сразу
        if self._buffered_text:
            cmd = self._strip_wake(self._buffered_text).strip()
            if cmd:
                self.on_command(cmd)
            self._awaiting_command = False
            self._buffered_text = ""
            self.on_status("слушаю (ожидаю «джарвис»)")
            self._last_wake_ts = 0.0

    def _strip_wake(self, s: str) -> str:
        out = s
        for w in self.cfg.wake_words:
            out = out.replace(w, "")
        return out.strip()

    def _check_timeout(self):
        if self._awaiting_command and (time.time() - self._last_wake_ts > COMMAND_TIMEOUT):
            # не дождались команды
            self._awaiting_command = False
            self._buffered_text = ""
            self._last_wake_ts = 0.0
            self.on_status("таймаут команды — слушаю (ожидаю «джарвис»)")
