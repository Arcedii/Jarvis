# jarvis_client_gui.py
from __future__ import annotations
import base64
import mimetypes
import os
import json
from dataclasses import asdict
from datetime import datetime
from typing import List, Dict, Any, Optional

import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from Scipts.OpenAiGPTBrain import LLMClient, LLMConfig

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "jarvis_client_config.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "jarvis_chat_history.json")
MAX_TURNS_TO_SEND = 2

# ---------- Вспомогательные сохранение/загрузка ---------- #
def load_config() -> LLMConfig:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return LLMConfig(**data)
        except Exception:
            pass
    return LLMConfig()


def save_config(cfg: LLMConfig) -> None:
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(asdict(cfg), f, ensure_ascii=False, indent=2)


def load_history() -> List[Dict[str, Any]]:
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []


def save_history(messages: List[Dict[str, Any]]) -> None:
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except Exception:
        pass


class JarvisClientApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jarvis Client — LM Studio")
        self.geometry("980x720")
        self.minsize(820, 600)
        self.configure(bg="#0b1220")

        # Состояние
        self.cfg: LLMConfig = load_config()
        self.llm = LLMClient(self.cfg)
        self.messages: List[Dict[str, Any]] = load_history()

        # Состояние вложения (визуальная часть)
        self.attached_image_b64: Optional[str] = None
        self.attached_image_mime: Optional[str] = None
        self.attached_image_name: Optional[str] = None

        # UI
        self._init_styles()
        self._init_menu()
        self._init_header()
        self._init_chat_area()
        self._init_input_panel()
        self.after(50, self._bootstrap)

    # ---------- UI построение ---------- #
    def _init_styles(self):
        style = ttk.Style()
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure("TButton", padding=6, relief="flat")
        style.configure("Accent.TButton", padding=8, relief="flat")
        style.configure("TLabel", foreground="#e6eaf2", background="#0b1220")
        style.configure("Header.TLabel", font=("Segoe UI Semibold", 14))
        style.configure("Tiny.TLabel", font=("Segoe UI", 9), foreground="#9aa4b2")
        style.configure("TFrame", background="#0b1220")
        style.configure("Card.TFrame", background="#121a2b", relief="flat")
        style.configure("Input.TFrame", background="#0f1729")
        style.configure("TEntry", fieldbackground="#101827", foreground="#e6eaf2")

    def _init_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=0)
        file_menu.add_command(label="Сохранить историю…", command=self._export_history)
        file_menu.add_separator()
        file_menu.add_command(label="Выход", command=self.destroy)
        menubar.add_cascade(label="Файл", menu=file_menu)

        settings_menu = tk.Menu(menubar, tearoff=0)
        settings_menu.add_command(label="Настройки…", command=self._open_settings)
        settings_menu.add_command(label="Сбросить диалог", command=self._reset_chat)
        menubar.add_cascade(label="Настройки", menu=settings_menu)

        help_menu = tk.Menu(menubar, tearoff=0)
        help_menu.add_command(label="О программе…", command=self._about)
        menubar.add_cascade(label="Справка", menu=help_menu)
        self.config(menu=menubar)

    def _init_header(self):
        header = ttk.Frame(self, style="TFrame")
        header.pack(fill="x", padx=14, pady=(12, 8))
        left = ttk.Frame(header, style="TFrame")
        left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Jarvis Client", style="Header.TLabel").pack(anchor="w")
        self.status_label = ttk.Label(left, text="Готов", style="Tiny.TLabel")
        self.status_label.pack(anchor="w", pady=(2, 0))
        right = ttk.Frame(header, style="TFrame")
        right.pack(side="right")
        ttk.Button(right, text="Настройки", command=self._open_settings).pack(side="right", padx=(6, 0))
        ttk.Button(right, text="Сброс", command=self._reset_chat).pack(side="right", padx=(6, 6))
        ttk.Button(right, text="📎 Фото", command=self._attach_image).pack(side="right", padx=(6, 6))

    def _init_chat_area(self):
        wrap = ttk.Frame(self, style="Card.TFrame")
        wrap.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.chat = tk.Text(
            wrap,
            wrap="word",
            bg="#121a2b",
            fg="#e6eaf2",
            insertbackground="#e6eaf2",
            relief="flat",
            padx=14,
            pady=12,
            state="disabled",
        )
        self.chat.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(wrap, command=self.chat.yview)
        scroll.pack(side="right", fill="y")
        self.chat["yscrollcommand"] = scroll.set
        self.chat.tag_configure("user_name", foreground="#9dd6ff", spacing3=4, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("user_msg", lmargin1=10, lmargin2=10, spacing1=2, spacing3=10)
        self.chat.tag_configure("asst_name", foreground="#bfa3ff", spacing3=4, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("asst_msg", lmargin1=10, lmargin2=10, spacing1=2, spacing3=12)
        self.chat.tag_configure("time", foreground="#93a0b5", font=("Segoe UI", 8))

    def _init_input_panel(self):
        bar = ttk.Frame(self, style="Input.TFrame")
        bar.pack(fill="x", padx=14, pady=(0, 12))
        self.input = tk.Text(bar, height=3, wrap="word", bg="#0f1729", fg="#e6eaf2", relief="flat")
        self.input.pack(side="left", fill="x", expand=True, padx=(8, 8), pady=8)
        self.input.bind("<Control-Return>", lambda e: self._send_message())
        self.input.bind("<Shift-Return>", lambda e: self._insert_newline())
        btns = ttk.Frame(bar, style="Input.TFrame")
        btns.pack(side="right", padx=(0, 8), pady=8)
        self.send_btn = ttk.Button(btns, text="Отправить", style="Accent.TButton", command=self._send_message)
        self.send_btn.grid(row=0, column=0, sticky="ew")
        self.clear_btn = ttk.Button(btns, text="Очистить ввод", command=lambda: self.input.delete("1.0", "end"))
        self.clear_btn.grid(row=1, column=0, sticky="ew", pady=(6, 0))

    # ---------- Вспомогательное UI ---------- #
    def _bootstrap(self):
        if not self.messages:
            self._append_assistant("Привет! Я Jarvis. Подключён к LM Studio. Чем помочь?")
        else:
            for m in self.messages:
                if m.get("role") == "user":
                    self._append_user(m.get("content", ""))
                elif m.get("role") == "assistant":
                    self._append_assistant(m.get("content", ""))
        self.input.focus_set()

    def _insert_newline(self):
        self.input.insert("insert", "\n")
        return "break"

    def _append_user(self, text: str):
        self.chat.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.chat.insert("end", f"Вы  ·  {ts}\n", ("user_name", "time"))
        self.chat.insert("end", text.strip() + "\n\n", ("user_msg",))
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _append_assistant(self, text: str):
        self.chat.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.chat.insert("end", f"Jarvis  ·  {ts}\n", ("asst_name", "time"))
        self.chat.insert("end", text.strip() + "\n\n", ("asst_msg",))
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _append_system(self, text: str):
        self.chat.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.chat.insert("end", f"Система  ·  {ts}\n", ("time",))
        self.chat.insert("end", text.strip() + "\n\n")
        self.chat.configure(state="disabled")
        self.chat.see("end")

    def _set_status(self, text: str):
        self.status_label.configure(text=text)
        self.update_idletasks()

    def _reset_chat(self):
        if messagebox.askyesno("Сброс диалога", "Удалить текущую историю и начать заново?"):
            self.messages = []
            save_history(self.messages)
            self.chat.configure(state="normal")
            self.chat.delete("1.0", "end")
            self.chat.configure(state="disabled")
            self._append_assistant("История очищена. Готов к новому диалогу.")

    def _export_history(self):
        path = filedialog.asksaveasfilename(
            defaultextension=".txt",
            filetypes=[("Text", "*.txt"), ("All", "*.*")],
            title="Сохранить историю как…",
        )
        if not path:
            return
        lines = []
        for m in self.messages:
            role = m.get("role", "?")
            content = m.get("content", "")
            lines.append(f"[{role}] {content}")
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n\n".join(lines))
            messagebox.showinfo("Готово", "История сохранена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")

    def _about(self):
        messagebox.showinfo(
            "О программе",
            "Jarvis Client — компактный клиент для LM Studio (OpenAI API совместимый).\n"
            "Поддерживает историю, экспорт, настройки, горячие клавиши."
        )

    # ---------- Настройки ---------- #
    def _open_settings(self):
        win = tk.Toplevel(self)
        win.title("Настройки")
        win.configure(bg="#0b1220")
        win.geometry("560x360")
        win.transient(self)
        win.grab_set()

        frm = ttk.Frame(win, padding=16)
        frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="LM Studio Chat Completions URL:").grid(row=0, column=0, sticky="w")
        api_var = tk.StringVar(value=self.cfg.api_url)
        api_entry = ttk.Entry(frm, textvariable=api_var, width=64)
        api_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(4, 12))

        ttk.Label(frm, text="Модель (model):").grid(row=2, column=0, sticky="w")
        model_var = tk.StringVar(value=self.cfg.model)
        model_entry = ttk.Entry(frm, textvariable=model_var, width=48)
        model_entry.grid(row=3, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(frm, text="Температура:").grid(row=4, column=0, sticky="w")
        temp_var = tk.DoubleVar(value=self.cfg.temperature)
        temp_scale = ttk.Scale(frm, variable=temp_var, from_=0.0, to=1.5)
        temp_scale.grid(row=5, column=0, sticky="ew", pady=(4, 12))

        ttk.Label(frm, text="System prompt:").grid(row=6, column=0, sticky="w")
        sys_text = tk.Text(frm, height=5, wrap="word")
        sys_text.insert("1.0", self.cfg.system_prompt)
        sys_text.grid(row=7, column=0, columnspan=2, sticky="nsew")

        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(7, weight=1)

        btns = ttk.Frame(frm)
        btns.grid(row=8, column=0, sticky="e", pady=(12, 0))

        def on_test():
            self._set_status("Проверка подключения…")
            try:
                res = self.llm.test_api(api_var.get(), model_var.get())
                if "pong" in (res.get("text") or "").lower():
                    self._set_status("Подключение OK ✨")
                    messagebox.showinfo("Успех", "Подключение к Jarvis Brain работает.")
                else:
                    self._set_status("Подключение проверено, но ответ необычный")
                    messagebox.showwarning("Внимание", f"Сервис отвечает: {res.get('text','')[:200]}")
            except Exception as e:
                self._set_status("Ошибка подключения")
                messagebox.showerror("Ошибка", f"Не удалось подключиться: {e}")

        ttk.Button(btns, text="Тест соединения", command=on_test).pack(side="left", padx=(0, 8))

        def on_save():
            self.llm.set_config(
                api_url=api_var.get().strip(),
                model=model_var.get().strip(),
                temperature=float(temp_var.get()),
                system_prompt=sys_text.get("1.0", "end").strip(),
            )
            self.cfg = self.llm.get_config()
            save_config(self.cfg)
            self._set_status("Настройки сохранены")
            win.destroy()

        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=on_save).pack(side="left")

    # ---------- Вложения (визуальная часть) ---------- #
    def _attach_image(self):
        path = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[
                ("Images", "*.png;*.jpg;*.jpeg;*.webp;*.bmp"),
                ("PNG", "*.png"),
                ("JPEG", "*.jpg;*.jpeg"),
                ("WEBP", "*.webp"),
                ("BMP", "*.bmp"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        try:
            mime, _ = mimetypes.guess_type(path)
            if not mime:
                mime = "image/png"
            with open(path, "rb") as f:
                b = f.read()
            self.attached_image_b64 = base64.b64encode(b).decode("utf-8")
            self.attached_image_mime = mime
            self.attached_image_name = os.path.basename(path)
            self._set_status(f"Прикреплено: {self.attached_image_name}")
            self._append_system(f"📎 Вложение: {self.attached_image_name}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прикрепить файл: {e}")

    def _clear_attachment(self):
        self.attached_image_b64 = None
        self.attached_image_mime = None
        self.attached_image_name = None

    # ---------- Отправка сообщения (только визуал + вызов LLMClient) ---------- #
    def _send_message(self):
        text = self.input.get("1.0", "end").strip()
        if not text:
            return
        self._append_user(text)

        # Готовим attachment-структуру только для визуала
        attachment = None
        if self.attached_image_b64:
            attachment = {
                "b64": self.attached_image_b64,
                "mime": self.attached_image_mime or "image/png",
                "name": self.attached_image_name or "image",
            }

        # Собираем сообщения через LLMClient
        req_messages = self.llm.build_messages(
            system_prompt=self.cfg.system_prompt,
            history=self.messages,
            user_text=text,
            attachment=attachment,
            max_turns_to_send=MAX_TURNS_TO_SEND,
            force_text_only=False,
        )

        # Блокируем кнопку и отправляем асинхронно
        self.send_btn.state(["disabled"])
        self._set_status("Запрос к модели… (короткий)")

        def on_success(answer_text: str, latency: float, meta: Dict[str, Any]):
            # Возвращаемся в UI-поток
            self.after(10, lambda: self._apply_success(answer_text, latency))

        def on_error(err_text: str):
            self.after(10, lambda: self._apply_error(err_text))

        self.llm.send_chat_async(req_messages, on_success, on_error)

        # очистка поля ввода/вложений
        self.input.delete("1.0", "end")
        self._clear_attachment()

    def _apply_success(self, text: str, latency: float):
        self.send_btn.state(["!disabled"])
        self._append_assistant(text.strip() or "(пустой ответ)")
        self._set_status(f"Готов  ·  {latency:.2f}s")
        # Обновляем историю
        last_user = {"role": "user", "content": req_last_user_from_ui(self.chat)}
        if last_user["content"]:
            self.messages.append(last_user)
        self.messages.append({"role": "assistant", "content": text})
        save_history(self.messages)

    def _apply_error(self, err: str):
        self.send_btn.state(["!disabled"])
        self._set_status("Ошибка: " + err)
        messagebox.showerror("Ошибка запроса", err)


# Хелпер: вытащить последний ввод пользователя из Text
def req_last_user_from_ui(chat_text: tk.Text) -> str:
    content = chat_text.get("1.0", "end")
    lines = [l.rstrip("\n") for l in content.splitlines()]
    for i in range(len(lines) - 1, -1, -1):
        if lines[i].startswith("Вы  ·  "):
            msg_lines = []
            for j in range(i + 1, len(lines)):
                if lines[j].strip() == "":
                    break
                msg_lines.append(lines[j])
            return "\n".join(msg_lines).strip()
    return ""


if __name__ == "__main__":
    app = JarvisClientApp()
    app.mainloop()
