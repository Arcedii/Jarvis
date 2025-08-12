import os
import sys
import time
import json
import base64
import io
import re
import traceback
from typing import Tuple, Optional, List, Dict, Any

import requests
import pyautogui
from PIL import Image

# ---- Конфиг из env ----
API_URL    = os.getenv("LMSTUDIO_API_URL", "http://127.0.0.1:1234/v1/chat/completions")
MODEL      = os.getenv("LMSTUDIO_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
TEMP       = float(os.getenv("TEMPERATURE", "0.1"))
MAX_TOKENS = int(os.getenv("MAX_TOKENS", "250"))
MAX_STEPS  = int(os.getenv("MAX_STEPS", "6"))
STEP_SLEEP = float(os.getenv("STEP_SLEEP_SEC", "1.2"))
DRY_RUN    = os.getenv("DRY_RUN", "0") == "1"
COMMAND_LOG_PATH = os.getenv("AGENT_COMMAND_LOG", "agent_commands.json")

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer lm-studio",  # для LM Studio это ок
}

# ---- Безопасность pyautogui ----
pyautogui.FAILSAFE = True  # левый верхний угол = аварийная остановка
pyautogui.PAUSE = 0.1

# ---- Валидатор JSON-ответа ----
JSON_CLICK_RE = re.compile(
    r'^\s*\{\s*(?:"done"\s*:\s*true|"(?:click|done)"\s*:)', re.IGNORECASE | re.DOTALL
)

SYSTEM_PROMPT = """Ты — честный и строгий UI-навигационный ассистент.
Твоя задача: вести пользователя к цели ПОШАГОВО, по одному клику за шаг.

ПРАВИЛА:
1) На КАЖДОМ шаге отвечай СТРОГО одним JSON без лишнего текста:
   Вариант A (сказать клик):
     {"click":{"x":123,"y":456},"reason":"короткое объяснение на русском"}
   Вариант B (цель достигнута / дальше кликов не надо):
     {"done":true,"reason":"короткое объяснение на русском"}

@@ -213,72 +214,84 @@ def parse_action(text: str, screen_size: Tuple[int, int]) -> Tuple[Optional[Tupl

    reason = data.get("reason") or ""
    return (x, y), reason, False

def do_click(pt: Tuple[int, int]):
    x, y = pt
    if DRY_RUN:
        print(f"[DRY_RUN] клик по ({x},{y})")
        return
    pyautogui.moveTo(x, y, duration=0.15)
    pyautogui.click(x, y)

# ----------------- MAIN LOOP -----------------
def main():
    if len(sys.argv) < 2:
        print("Использование: python agent_executor.py \"ваша цель\"")
        sys.exit(2)

    goal = sys.argv[1].strip()
    print(f"[AGENT] Цель: {goal}")
    print(f"[AGENT] API_URL={API_URL} MODEL={MODEL} TEMP={TEMP} MAX_TOKENS={MAX_TOKENS} MAX_STEPS={MAX_STEPS} DRY_RUN={DRY_RUN}")

    history: List[Dict[str, Any]] = []  # только текст, без картинок
    last_click: Optional[Tuple[int, int]] = None
    repeat_clicks = 0
    executed_commands: List[Dict[str, Any]] = []

    try:
        for step in range(1, MAX_STEPS + 1):
            print(f"\n[AGENT] Шаг {step}/{MAX_STEPS}: делаю скрин...")
            img, screen_size = make_screenshot()
            b64 = b64_png_from_screenshot(img)

            print("[AGENT] Запрашиваю LLM решение (ожидаю строго JSON)...")
            llm_text = call_llm_with_image(goal, b64, history)
            print(f"[LLM RAW]: {llm_text[:500]}{'...' if len(llm_text)>500 else ''}")

            coords, reason, done = parse_action(llm_text, screen_size)
            if done:
                print(f"[AGENT] Готово: {reason}")
                return
                break

            if coords is None:
                print(f"[AGENT] Ошибка разбора/валидации: {reason}")
                history.append({"role": "assistant", "content": f"Не распарсил JSON/координаты: {reason}. Дай корректный JSON."})
                time.sleep(0.6)
                continue

            if last_click == coords:
                repeat_clicks += 1
            else:
                repeat_clicks = 0
            last_click = coords
            if repeat_clicks >= 2:
                print("[AGENT] Координаты трижды повторяются — вероятна петля. Останавливаюсь.")
                return
                break

            print(f"[AGENT] Кликаю по {coords}. Причина: {reason}")
            do_click(coords)

            executed_commands.append({"step": step, "x": coords[0], "y": coords[1], "reason": reason})

            history.append({"role": "assistant", "content": f"Кликнул по {coords}. {('Причина: ' + reason) if reason else ''}"})
            time.sleep(STEP_SLEEP)

        print("[AGENT] Достигнут лимит шагов, выхожу.")
        else:
            print("[AGENT] Достигнут лимит шагов, выхожу.")
    except pyautogui.FailSafeException:
        print("[AGENT] Аварийная остановка (курсор в левом верхнем углу).")
    except KeyboardInterrupt:
        print("[AGENT] Прервано пользователем.")
    except Exception as e:
        print(f"[AGENT] Ошибка: {e}\n{traceback.format_exc()}")
    finally:
        if executed_commands:
            try:
                with open(COMMAND_LOG_PATH, "w", encoding="utf-8") as f:
                    json.dump(executed_commands, f, ensure_ascii=False, indent=2)
                print(f"[AGENT] Лог команд сохранён в {COMMAND_LOG_PATH}")
            except Exception as e:
                print(f"[AGENT] Не удалось сохранить лог команд: {e}")

if __name__ == "__main__":
    main()