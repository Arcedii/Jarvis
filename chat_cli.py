# -*- coding: utf-8 -*-
import os
import re
import sys
import json
import threading
import requests
import tkinter as tk
from tkinter import scrolledtext, messagebox
import subprocess

# ==== Конфиг ====
API_URL = os.getenv("LMSTUDIO_API_URL", "http://192.168.100.8:1234/v1/chat/completions")
MODEL   = os.getenv("LMSTUDIO_MODEL", "Qwen/Qwen2.5-VL-7B-Instruct")
TEMP    = float(os.getenv("TEMPERATURE", "0.2"))
PYTHON_EXE = os.getenv("PYTHON_EXE", sys.executable)  # запускаем агента тем же Python

HEADERS = {
    "Content-Type": "application/json",
    "Authorization": "Bearer lm-studio",  # безопасно и часто нужно для LM Studio
}

# ==== Жёсткий системный промпт-маршрутизатор ====
SYSTEM = """
Ты — маршрутизатор задач. На каждый пользовательский запрос выбирай ОДИН из двух вариантов:

A) Если запрос можно закрыть обычным текстовым ответом (объяснение, команды терминала без кликов/GUI) — верни НОРМАЛЬНЫЙ ответ без JSON.

B) Если для выполнения требуется взаимодействие с интерфейсом ОС (клики, хоткеи, ввод в окна, навигация по меню) — верни СТРОГО ОДНУ СТРОКУ JSON:
{"tool":"ui_agent","goal":"<краткая цель в повелительном наклонении>"}

Требования:
- Если выбираешь вариант B — никаких дополнительных слов, кода или комментариев. Только JSON в одну строку.
- Примеры целей для варианта B: "усыпить компьютер", "открыть диспетчер устройств", "включить тёмную тему", "подключиться к Wi‑Fi 'ACME'", "нажать 'Пуск → Питание → Сон'".
- НЕ предлагай «Alt+F4», «Win+X» и т.п. как текстовый совет — это признак варианта B (нужен агент).
""".strip()

# ==== История сообщений (VLM-совместимая) ====
messages = [{"role": "system", "content": SYSTEM}]

# ==== Эвристика GUI ====
GUI_HINT_RE = re.compile(
    r"(?:\bwin\+|\balt\+|\bctrl\+|\bshift\+|⌘|cmd\+|пуск\b|клик\w*|щёлк\w*|нажм(ит|и)\w*|"
    r"кнопк\w*|\bокн(?:о|а)\b|меню\b|панел\w*|параметр\w*|настройк\w*|ярлык\w*|"
    r"пере(?:йд|ход)\w*\s+в\s+меню)",
    re.IGNORECASE
)
def looks_like_gui(text: str) -> bool:
    return bool(text and GUI_HINT_RE.search(text))

# ==== Упаковка сообщений под vision-модели ====
def to_vision_messages(msgs):
    out = []
    for m in msgs:
        role = m.get("role")
        content = m.get("content")
        if isinstance(content, str):
            out.append({"role": role, "content": [{"type": "text", "text": content}]})
        else:
            out.append(m)  # если уже parts-список — не трогаем
    return out

# ==== Принудительный решатель: нужен ли агент ====
def force_agent_decision(user_text: str, temperature: float = 0.1) -> str:
    router_prompt = (
        "Ты — строгий решатель 'нужен ли UI‑агент'. Ответь РОВНО одной строкой:\n"
        "- Если нужны клики/горячие клавиши/навигация по окнам → верни {\"tool\":\"ui_agent\",\"goal\":\"...\"}.\n"
        "- Если нет → верни {\"tool\":\"none\"}.\n"
        "Никаких других слов. Никаких переносов строки."
    )

    payload = {
        "model": MODEL,
        "messages": to_vision_messages([
            {"role": "system", "content": router_prompt},
            {"role": "user", "content": f"Запрос: {user_text}\nОтвет:"}
        ]),
        "temperature": temperature,
        "max_tokens": 128
    }
    try:
        r = requests.post(API_URL, json=payload, headers=HEADERS, timeout=120)
        if r.status_code >= 400:
            print("[Router ERROR BODY]:", r.text[:1000])
            r.raise_for_status()
        return r.json()["choices"][0]["message"]["content"].strip()
    except Exception:
        return ""

# ==== Запуск агента (тем же Python/venv) ====
def maybe_spawn_agent(tool_json: str):
    try:
        data = json.loads(tool_json)
    except Exception:
        return False
    if isinstance(data, dict) and data.get("tool") == "ui_agent":
        goal = (data.get("goal") or "").strip()
        if goal:
            subprocess.Popen([PYTHON_EXE, "agent_executor.py", goal], close_fds=True)
            return True
    return False

# ==== Сетевая часть в отдельном потоке, чтобы не вешать UI ====
def _append_user(text):
    chat_area.config(state=tk.NORMAL); chat_area.insert(tk.END, f"Ты: {text}\n", "user")
    chat_area.config(state=tk.DISABLED); chat_area.see(tk.END)

def _append_assistant(text):
    chat_area.config(state=tk.NORMAL); chat_area.insert(tk.END, f"ИИ: {text}\n\n", "assistant")
    chat_area.config(state=tk.DISABLED); chat_area.see(tk.END)

def _append_system(text):
    chat_area.config(state=tk.NORMAL); chat_area.insert(tk.END, f"[СИСТЕМА] {text}\n\n", "assistant")
    chat_area.config(state=tk.DISABLED); chat_area.see(tk.END)

def _handle_llm_turn(user_text: str):
    global messages
    try:
        payload = {
            "model": MODEL,
            "messages": to_vision_messages(messages),
            "temperature": TEMP,
            "max_tokens": 300
        }
        resp = requests.post(API_URL, json=payload, headers=HEADERS, timeout=300)

        if resp.status_code >= 400:
            body = resp.text[:1500]
            messagebox.showerror("Ошибка HTTP", f"{resp.status_code} {resp.reason}\n\n{body}")
            _append_system(f"Ошибка {resp.status_code}: {resp.reason}\n{body}")
            return

        data = resp.json()
        answer = data["choices"][0]["message"]["content"].strip()

        launched = False
        # (1) Если уже JSON — пробуем агент
        if answer.startswith("{") and answer.endswith("}"):
            launched = maybe_spawn_agent(answer)

        # (2) Если не запустили, но похоже на GUI — жёсткий решатель
        if not launched and (looks_like_gui(answer) or looks_like_gui(user_text)):
            decision = force_agent_decision(user_text, temperature=0.1)
            if decision.startswith("{") and decision.endswith("}"):
                launched = maybe_spawn_agent(decision)
                if launched:
                    answer = decision

        if launched:
            _append_system(f"Запускаю агента: {answer}")
        else:
            _append_assistant(answer)

        messages.append({"role": "assistant", "content": answer})

    except requests.exceptions.RequestException as e:
        messagebox.showerror("Ошибка HTTP", str(e))
    except Exception as e:
        messagebox.showerror("Ошибка", str(e))

def send_message():
    user_text = entry.get("1.0", tk.END).strip()
    if not user_text:
        return
    entry.delete("1.0", tk.END)

    _append_user(user_text)
    messages.append({"role": "user", "content": user_text})

    threading.Thread(target=_handle_llm_turn, args=(user_text,), daemon=True).start()

def reset_chat():
    global messages
    messages = [{"role": "system", "content": SYSTEM}]
    chat_area.config(state=tk.NORMAL); chat_area.delete("1.0", tk.END); chat_area.config(state=tk.DISABLED)
    _append_system("История очищена.")

# ==== Быстрый ping сервера на старте ====
def ping_backend():
    try:
        base = API_URL.split("/v1/", 1)[0]
        r = requests.get(base + "/v1/models", headers=HEADERS, timeout=5)
        return r.status_code == 200
    except Exception:
        return False

# ==== Tk UI ====
root = tk.Tk()
root.title("gemini Chat")

chat_area = scrolledtext.ScrolledText(root, wrap=tk.WORD, width=100, height=26, state=tk.DISABLED)
chat_area.pack(padx=10, pady=10, fill=tk.BOTH, expand=True)
chat_area.tag_config("user", foreground="cyan")
chat_area.tag_config("assistant", foreground="lime")

entry = tk.Text(root, height=3, wrap=tk.WORD)
entry.pack(padx=10, pady=(0, 5), fill=tk.X)

btn_frame = tk.Frame(root); btn_frame.pack(pady=5)
tk.Button(btn_frame, text="Отправить", command=send_message).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="Очистить чат", command=reset_chat).pack(side=tk.LEFT, padx=5)
tk.Button(btn_frame, text="Выход", command=root.destroy).pack(side=tk.LEFT, padx=5)

# Стартовое сообщение
if ping_backend():
    _append_system(f"Подключение к LLM готово. MODEL={MODEL} TEMP={TEMP}")
else:
    _append_system("Бэкенд недоступен или не тот URL. Проверь LM Studio → Server → Base URL и порт.")

root.mainloop()
