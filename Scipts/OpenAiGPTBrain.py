# llm_client.py
from __future__ import annotations
import time
import threading
from dataclasses import dataclass
from typing import List, Dict, Any, Optional, Callable

import requests

# ===== Константы по умолчанию (можно менять из GUI через set_config) ===== #
DEFAULT_API_URL = "http://192.168.100.8:1234/v1/chat/completions"
DEFAULT_MODEL = "OpenAi/"
REQUEST_TIMEOUT_SEC = 1000
FORCE_MAX_TOKENS = 512
FORCE_TEMPERATURE = 0.0


@dataclass
class LLMConfig:
    api_url: str = DEFAULT_API_URL
    model: str = DEFAULT_MODEL
    temperature: float = 0.3
    system_prompt: str = (
        "Ты — ассистент Jarvis"
    )
    supports_images: bool = True


class LLMClient:
    """Изолирует всю работу с LLM/HTTP. Потокобезопасный отправитель.

    GUI передает сюда подготовленную историю и текущий ввод, а получает
    колбэками результат или ошибку, не блокируя UI-поток.
    """

    def __init__(self, cfg: Optional[LLMConfig] = None):
        self.cfg = cfg or LLMConfig()

    # --- Публичные методы конфигурации --- #
    def set_config(self, **kwargs) -> None:
        for k, v in kwargs.items():
            if hasattr(self.cfg, k):
                setattr(self.cfg, k, v)

    def get_config(self) -> LLMConfig:
        return self.cfg

    # --- Сервис: тест API (пинг) --- #
    def test_api(self, api_url: Optional[str] = None, model: Optional[str] = None) -> Dict[str, Any]:
        url = api_url or self.cfg.api_url
        mdl = model or self.cfg.model
        payload = {
            "model": mdl,
            "messages": [{"role": "user", "content": "ping"}],
            "max_tokens": 8,
            "temperature": 0,
        }
        t0 = time.time()
        r = requests.post(url, json=payload, timeout=10)
        r.raise_for_status()
        data = r.json()
        txt = (data.get("choices", [{}])[0].get("message", {}) or {}).get("content", "")
        return {"ok": True, "text": txt, "latency": time.time() - t0, "raw": data}

    # --- Сбор сообщений --- #
    def build_messages(
        self,
        system_prompt: str,
        history: List[Dict[str, Any]],  # только роли user/assistant
        user_text: str,
        attachment: Optional[Dict[str, str]] = None,  # {"mime":..., "b64":..., "name":...}
        max_turns_to_send: int = 2,
        force_text_only: bool = False,
    ) -> List[Dict[str, Any]]:
        msgs: List[Dict[str, Any]] = []

        # system
        if system_prompt:
            sys_short = system_prompt.strip()
            if len(sys_short) > 400:
                sys_short = sys_short[:400] + " …"
            msgs.append({"role": "system", "content": sys_short})

        # последние N ходов
        turns: List[Dict[str, Any]] = []
        for m in history:
            if m.get("role") in ("user", "assistant"):
                turns.append({"role": m["role"], "content": str(m.get("content", ""))})
        turns = turns[-(max_turns_to_send * 2):]
        msgs.extend(turns)

        # текущий ввод
        if (
            attachment
            and (not force_text_only)
            and self.cfg.supports_images
            and attachment.get("b64")
        ):
            parts = [{"type": "text", "text": user_text}]
            mime = attachment.get("mime") or "image/png"
            parts.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{attachment['b64']}"}
            })
            msgs.append({"role": "user", "content": parts})
        else:
            text = user_text
            if attachment and attachment.get("name"):
                text += f"\n\n[Примечание: прикреплён файл {attachment['name']}; анализ изображений временно отключён]"
            msgs.append({"role": "user", "content": text})

        return msgs

    # --- Отправка: асинхронно (в отдельном потоке) --- #
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
                body_preview = r.text[:500] if isinstance(r.text, str) else str(r.text)[:500]
                r.raise_for_status()
                data = r.json()

                raw_content = ""
                if isinstance(data.get("choices"), list) and data["choices"]:
                    raw_content = data["choices"][0].get("message", {}).get("content", "")
                text = raw_content or ""
                on_success(text, time.time() - t0, {"http_status": r.status_code, "preview": body_preview})
            except requests.Timeout:
                on_error(f"Таймаут {REQUEST_TIMEOUT_SEC}s")
            except Exception as e:
                on_error(str(e))

        th = threading.Thread(target=_worker, daemon=True)
        th.start()
