# llm_client.py
from __future__ import annotations
import time
import threading
import re
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable, Tuple
import requests

# ==== базовые настройки ====
DEFAULT_API_URL = "http://192.168.100.8:1234/v1/chat/completions"
DEFAULT_MODEL = "openai/gpt-oss-20b"
REQUEST_TIMEOUT_SEC = 1000
FORCE_MAX_TOKENS = 512
FORCE_TEMPERATURE = 0.0

# Протокол команды в ответе: <<COMMAND=приветствие>>
COMMAND_PATTERN = re.compile(r"<<\s*COMMAND\s*=\s*([\w\-А-Яа-я]+)\s*>>")

@dataclass
class LLMConfig:
    api_url: str = DEFAULT_API_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    system_prompt: str = (
        "Ты — локальный ассистент Jarvis. Отвечай коротко и по делу.\n"
        "Если пользователь здоровается (\"привет\", \"джарвис голос\", \"hello\" и т.п.) — "
        "в конце ответа добавь тег <<COMMAND=приветствие>>.\n"
        "Если команда не нужна — ничего не добавляй. Отвечай как обычно."
    )
    supports_images: bool = True

class LLMClient:
    """Вся работа с LLM/HTTP + извлечение команд из ответа."""

    def __init__(self, cfg: Optional[LLMConfig] = None):
        self.cfg = cfg or LLMConfig()

    def set_config(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self.cfg, k):
                setattr(self.cfg, k, v)

    def get_config(self) -> LLMConfig:
        return self.cfg

    # Быстрый пинг
    def test_api(self, api_url: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
        url = api_url or self.cfg.api_url
        mdl = model or self.cfg.model
        payload = {"model": mdl, "messages": [{"role": "user", "content": "ping"}], "max_tokens": 8, "temperature": 0}
        t0 = time.time()
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        txt = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        return {"ok": True, "text": txt, "latency": time.time() - t0, "raw": data}

    # Сбор messages для chat.completions
    def build_messages(
        self,
        system_prompt: str,
        history: List[Dict[str, Any]],
        user_text: str,
        attachment: Optional[Dict[str, str]] = None,  # {"mime":..., "b64":..., "name":...}
        max_turns_to_send: int = 2,
        force_text_only: bool = False,
    ) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []

        if system_prompt:
            sys_short = system_prompt.strip()
            if len(sys_short) > 900:
                sys_short = sys_short[:900] + " …"
            msgs.append({"role": "system", "content": sys_short})

        turns: List[Dict[str, Any]] = []
        for m in history:
            if m.get("role") in ("user", "assistant"):
                turns.append({"role": m["role"], "content": str(m.get("content", ""))})
        msgs.extend(turns[-(max_turns_to_send * 2):])

        if attachment and (not force_text_only) and self.cfg.supports_images and attachment.get("b64"):
            parts = [{"type": "text", "text": user_text}]
            mime = attachment.get("mime") or "image/png"
            parts.append({"type": "image_url", "image_url": {"url": f"data:{mime};base64,{attachment['b64']}"}})
            msgs.append({"role": "user", "content": parts})
        else:
            text = user_text
            if attachment and attachment.get("name"):
                text += f"\n\n[Примечание: прикреплён файл {attachment['name']}; анализ изображений временно отключён]"
            msgs.append({"role": "user", "content": text})

        return msgs

    # Извлечь команду и очистить текст
    @staticmethod
    def extract_command_and_clean(text: str) -> Tuple[str, str]:
        cmd = ""
        m = COMMAND_PATTERN.search(text or "")
        if m:
            cmd = m.group(1).strip().lower()
            text = COMMAND_PATTERN.sub("", text).strip()
        return cmd, text

    # Отправка в отдельном потоке
    def send_chat_async(
        self,
        messages: List[Dict[str, Any]],
        on_success: Callable[[str, float, Dict[str, Any]], None],
        on_error: Callable[[str], None],
    ) -> None:
        def _worker():
            try:
                payload = {
                    "model": self.cfg.model,
                    "messages": messages,
                    "max_tokens": FORCE_MAX_TOKENS,
                    "temperature": FORCE_TEMPERATURE,
                }
                t0 = time.time()
                r = requests.post(self.cfg.api_url, json=payload, timeout=REQUEST_TIMEOUT_SEC)
                preview = r.text[:500] if isinstance(r.text, str) else str(r.text)[:500]
                r.raise_for_status()
                data = r.json()
                content = ""
                if isinstance(data.get("choices"), list) and data["choices"]:
                    content = data["choices"][0].get("message", {}).get("content", "") or ""
                cmd, clean = self.extract_command_and_clean(content)
                meta = {"http_status": r.status_code, "preview": preview, "command": cmd}
                on_success(clean, time.time() - t0, meta)
            except requests.Timeout:
                on_error(f"Таймаут {REQUEST_TIMEOUT_SEC}s")
            except Exception as e:
                on_error(str(e))

        threading.Thread(target=_worker, daemon=True).start()
