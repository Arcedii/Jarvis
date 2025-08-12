# -*- coding: utf-8 -*-
"""
agent_executor.py — GUI-агент для Qwen-VL (один шаг = один клик)

Шаги:
1) Скриншот экрана.
2) Отправка в LLM (Qwen-VL через LM Studio OpenAI-compatible) цели + скрина.
3) Ждём СТРОГО JSON:
   {"click":{"x":int,"y":int},"reason":"..."}  или  {"done":true,"reason":"..."}
4) Кликаем, ждём, повторяем до успеха или лимита шагов.

Запуск:
  python agent_executor.py "усыпить компьютер"

ENV:
  LMSTUDIO_API_URL  (default: http://192.168.100.8:1234/v1/chat/completions)
  LMSTUDIO_MODEL    (default: Qwen/Qwen2.5-VL-7B-Instruct)
  TEMPERATURE       (default: 0.1)
  MAX_TOKENS        (default: 250)
  MAX_STEPS         (default: 6)
  STEP_SLEEP_SEC    (default: 1.2)
  DRY_RUN           (default: "0")   # "1" = не кликать, только лог
"""

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
API_URL    = os.getenv("LMSTUDIO_API_URL", "http://192.168.100.8:1234/v1/chat/completions")
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

2) НИКАКИХ клавиш, двойных кликов, перетаскиваний — ТОЛЬКО один одиночный ЛЕВЫЙ клик за шаг.
3) Координаты — абсолютные пиксели активного дисплея, в пределах [0..width) и [0..height).
4) Если клик неочевиден — верни {"done":true,...} с объяснением.
5) Видишь только текущий скриншот. История ниже — только текстовая.
6) Будь консервативен: избегай кликов по перезагрузке/выключению, если цель достигается безопаснее.
7) reason — коротко и по делу, по-русски.

ОТВЕЧАЙ ТОЛЬКО В УКАЗАННОМ JSON-ФОРМАТЕ.
"""

USER_PROMPT_TEMPLATE = """ЦЕЛЬ: {goal}

Контекст:
- ОС: Windows/macOS/Linux, разрешение/масштаб неизвестны.
- Разрешено: только ОДИН ЛЕВЫЙ клик за шаг.
- Скриншот ниже.

Верни СТРОГО один JSON:
- Либо {{"click":{{"x":INT,"y":INT}},"reason":"..."}}
- Либо {{"done":true,"reason":"..."}}

Без другого текста, без форматирования, без кода.
Если целесообразно — начни с системной кнопки/меню, ведущих к цели.
"""

# --- спец-подсказка для Windows цели "Сон" (не обязательно) ---
if sys.platform.startswith("win"):
    SYSTEM_PROMPT += """
СПЕЦИАЛЬНО ДЛЯ WINDOWS:
- Если цель — усыпить компьютер, предпочтительный маршрут:
  1) Клик по кнопке «Пуск» (значок Windows).
  2) Клик по кнопке «Питание».
  3) Клик по пункту «Сон».
"""

# ----------------- ВСПОМОГАТЕЛЬНОЕ -----------------
def b64_png_from_screenshot(image: Image.Image) -> Tuple[str, Tuple[int, int]]:
    """Даунскейлим до 1280px по ширине, чтобы data URL был короче.

    Возвращает base64 PNG и фактический размер использованного изображения.
    """
    max_w = 1280
    w, h = image.size
    if w > max_w:
        new_h = int(h * (max_w / float(w)))
        image = image.resize((max_w, new_h), Image.LANCZOS)
    buf = io.BytesIO()
    image.save(buf, format="PNG", optimize=True)
    b64 = base64.b64encode(buf.getvalue()).decode("ascii")
    return b64, image.size

def make_screenshot() -> Image.Image:
    """Делаем скриншот активного экрана."""
    return pyautogui.screenshot()

def sanitize_json(s: str) -> str:
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        s = re.sub(r'^\s*(json|JSON)\s*\n', '', s.strip())
    m1 = s.find("{"); m2 = s.rfind("}")
    if m1 != -1:
        if m2 != -1 and m2 > m1:
            s = s[m1:m2+1]
        else:
            s = s[m1:]
    opens = s.count("{"); closes = s.count("}")
    if closes < opens:
        s += "}" * (opens - closes)
    return " ".join(s.splitlines())

def to_vision_history(parts: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Преобразуем текстовую историю в формат частей [{type:'text',...}] (без картинок)."""
    out = []
    for m in parts:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": [{"type": "text", "text": content}]})
        else:
            out.append(m)
    return out

# ----------------- ВЗАИМОДЕЙСТВИЕ С LLM -----------------
def call_llm_with_image(goal: str, screenshot_b64: str, history: List[Dict[str, Any]]) -> str:
    """
    Для Qwen-VL: отправляем system (строкой), историю (parts: text), и user (parts: text + image_url)
    """
    user_parts = [
        {"type": "text", "text": USER_PROMPT_TEMPLATE.format(goal=goal)},
        {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{screenshot_b64}"}},
    ]

    payload = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            *to_vision_history(history),
            {"role": "user", "content": user_parts},
        ],
        "temperature": TEMP,
        "max_tokens": MAX_TOKENS,
    }

    # 1 повтор при 5xx
    for attempt in range(2):
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=120)
        if resp.status_code >= 500 and attempt == 0:
            time.sleep(0.8)
            continue
        if resp.status_code >= 400:
            try:
                print("[LLM ERROR BODY]:", resp.text[:1200])
            except Exception:
                pass
            resp.raise_for_status()
        break

    j = resp.json()
    content = (((j.get("choices") or [{}])[0]).get("message") or {}).get("content")
    if not content:
        raise RuntimeError("LLM вернул пустой ответ")
    if isinstance(content, list):
        text = "".join(p.get("text", "") for p in content if p.get("type") == "text")
    else:
        text = str(content)
    return text.strip()

def parse_action(text: str, img_size: Tuple[int, int]) -> Tuple[Optional[Tuple[int, int]], Optional[str], bool]:
    text = sanitize_json(text)
    if not JSON_CLICK_RE.match(text):
        return None, "Ответ не похож на ожидаемый JSON", False
    try:
        data = json.loads(text)
    except Exception:
        return None, "JSON не распарсился", False

    if isinstance(data, dict) and data.get("done") is True:
        return None, data.get("reason") or "Готово", True

    click = data.get("click") if isinstance(data, dict) else None
    if not isinstance(click, dict):
        return None, "Нет объекта 'click'", False

    x = click.get("x"); y = click.get("y")
    if not (isinstance(x, int) and isinstance(y, int)):
        return None, "Координаты неполные/нецелые", False

    w, h = img_size
    if not (0 <= x < w and 0 <= y < h):
        return None, f"Координаты вне изображения ({w}x{h})", False

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
            img = make_screenshot()
            display_size = pyautogui.size()
            b64, resized_size = b64_png_from_screenshot(img)
            scale_x = display_size[0] / resized_size[0]
            scale_y = display_size[1] / resized_size[1]

            print("[AGENT] Запрашиваю LLM решение (ожидаю строго JSON)...")
            llm_text = call_llm_with_image(goal, b64, history)
            print(f"[LLM RAW]: {llm_text[:500]}{'...' if len(llm_text)>500 else ''}")

            coords, reason, done = parse_action(llm_text, resized_size)
            if done:
                print(f"[AGENT] Готово: {reason}")
                break

            if coords is None:
                print(f"[AGENT] Ошибка разбора/валидации: {reason}")
                history.append({"role": "assistant", "content": f"Не распарсил JSON/координаты: {reason}. Дай корректный JSON."})
                time.sleep(0.6)
                continue

            scaled_coords = (int(coords[0] * scale_x), int(coords[1] * scale_y))

            if last_click == scaled_coords:
                repeat_clicks += 1
            else:
                repeat_clicks = 0
            last_click = scaled_coords
            if repeat_clicks >= 2:
                print("[AGENT] Координаты трижды повторяются — вероятна петля. Останавливаюсь.")
                break

            print(f"[AGENT] Кликаю по {scaled_coords}. Причина: {reason}")
            do_click(scaled_coords)

            executed_commands.append({"step": step, "x": scaled_coords[0], "y": scaled_coords[1], "reason": reason})

            history.append({"role": "assistant", "content": f"Кликнул по {scaled_coords}. {('Причина: ' + reason) if reason else ''}"})
            time.sleep(STEP_SLEEP)

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
