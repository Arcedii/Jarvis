#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
simplified_agent_executor.py — упрощённый агент для взаимодействия с Qwen‑VL.

На каждом шаге скрипт делает скриншот, уменьшает его до 1280px по ширине,
отправляет изображение и цель в LLM и ожидает JSON-ответ либо с координатами
клика, либо с признаком завершения. Координаты, полученные от модели,
масштабируются на размер исходного экрана и используются для клика.

Код оставляет только необходимые функции и минимальные проверки, чтобы
облегчить чтение и понимание.
"""

import os
import sys
import json
import base64
import io
import time
from typing import Tuple, Optional, List, Dict

import requests
import pyautogui
from PIL import Image

# ---- Конфигурация ----
API_URL = os.getenv("LMSTUDIO_API_URL", "http://localhost:1234/v1/chat/completions")
MODEL   = os.getenv("LMSTUDIO_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
TEMP    = float(os.getenv("TEMPERATURE", "0.1"))
MAX_STEPS = int(os.getenv("MAX_STEPS", "6"))
HEADERS = {
    "Content-Type": "application/json",
    "Authorization": os.getenv("LMSTUDIO_API_KEY", "Bearer lm-studio"),
}

pyautogui.FAILSAFE = True

# ---- Промпты ----
# Системный промпт объясняет модели правила: один клик за шаг или завершение.
SYSTEM_PROMPT = (
    "Ты — честный и строгий UI-навигационный ассистент. "
    "Твоя задача: вести пользователя к цели пошагово, по одному клику за шаг. "
    "На каждом шаге возвращай строго JSON: либо {\"click\":{\"x\":INT,\"y\":INT},\"reason\":\"...\"}, "
    "либо {\"done\":true,\"reason\":\"...\"}. "
    "Никаких клавиш, двойных кликов или перетаскиваний."
)

# Шаблон пользовательского сообщения: цель и инструкция
USER_TEMPLATE = (
    "ЦЕЛЬ: {goal}\n\n"
    "Ты видишь скриншот. Выбери одну из двух опций:\n"
    "- {\"click\":{\"x\":INT,\"y\":INT},\"reason\":\"...\"}\n"
    "- {\"done\":true,\"reason\":\"...\"}"
)


def screenshot_and_downscale(max_width: int = 1280) -> Tuple[str, Tuple[int, int], Tuple[int, int]]:
    """Делает скриншот, уменьшает до max_width и возвращает base64 и размеры.

    :param max_width: максимальная ширина уменьшенного изображения
    :returns: base64 PNG, размер уменьшенного изображения (w,h), размер исходного скрина (w,h)
    """
    img = pyautogui.screenshot()
    full_w, full_h = img.size
    if full_w > max_width:
        new_h = int(full_h * (max_width / float(full_w)))
        img = img.resize((max_width, new_h), Image.LANCZOS)
    res_w, res_h = img.size
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return b64, (res_w, res_h), (full_w, full_h)


def call_llm(goal: str, image_b64: str, history: List[Dict[str, str]]) -> str:
    """Отправляет запрос в LLM с изображением и возвращает текстовый ответ."""
    user_parts = [
        {"type": "text", "text": USER_TEMPLATE.format(goal=goal)},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
    ]
    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *history,
            {"role": "user", "content": user_parts},
        ],
        "temperature": TEMP,
        "max_tokens": 100,
    }
    resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=120)
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"].strip()


def parse_response(text: str, img_size: Tuple[int, int]) -> Tuple[Optional[Tuple[int, int]], str, bool]:
    """Разбирает текст модели и возвращает координаты, причину и флаг done.

    :param text: строка от модели (ожидается JSON)
    :param img_size: размер уменьшенного изображения
    :returns: ((x,y) или None, reason, done)
    """
    # Извлекаем подстроку между { и }
    s = text.strip()
    start = s.find("{"); end = s.rfind("}")
    if start != -1 and end != -1 and end > start:
        s = s[start:end+1]
    try:
        data = json.loads(s)
    except Exception:
        return None, "invalid JSON", False
    # Если завершено
    if isinstance(data, dict) and data.get("done"):
        return None, data.get("reason") or "", True
    # Проверяем click
    click = data.get("click") if isinstance(data, dict) else None
    if not isinstance(click, dict):
        return None, "missing click", False
    x = click.get("x"); y = click.get("y")
    res_w, res_h = img_size
    if not (isinstance(x, int) and isinstance(y, int) and 0 <= x < res_w and 0 <= y < res_h):
        return None, "invalid coords", False
    reason = data.get("reason") or ""
    return (x, y), reason, False


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python simplified_agent_executor.py \"<goal>\"")
        sys.exit(1)
    goal = sys.argv[1]
    history: List[Dict[str, str]] = []
    last_click: Optional[Tuple[int, int]] = None
    for step in range(1, MAX_STEPS + 1):
        img_b64, (res_w, res_h), (full_w, full_h) = screenshot_and_downscale()
        try:
            resp_text = call_llm(goal, img_b64, history)
        except Exception as e:
            print(f"Error calling LLM: {e}")
            break
        coords, reason, done = parse_response(resp_text, (res_w, res_h))
        if done:
            print("Done:", reason)
            break
        if coords is None:
            # модель прислала некорректный JSON или некорректные координаты
            history.append({"role": "assistant", "content": f"Ошибка: {reason}. Пришли корректный JSON."})
            continue
        # Масштабируем координаты под оригинальный размер экрана
        x_full = int(coords[0] * (full_w / float(res_w)))
        y_full = int(coords[1] * (full_h / float(res_h)))
        if last_click == (x_full, y_full):
            print("Loop detected. Stopping.")
            break
        last_click = (x_full, y_full)
        print(f"Clicking at {(x_full, y_full)}. Reason: {reason}")
        if not os.getenv("DRY_RUN", "0") == "1":
            pyautogui.moveTo(x_full, y_full, duration=0.15)
            pyautogui.click(x_full, y_full)
        history.append({"role": "assistant", "content": f"Clicked at {(x_full, y_full)}. {reason}"})
        time.sleep(0.5)


if __name__ == "__main__":
    main()