# jarvis_client_gui.py
from __future__ import annotations
import base64, mimetypes, os, json, threading
from dataclasses import asdict
from datetime import datetime
from typing import List, Dict, Any, Optional
import tkinter as tk
from tkinter import ttk, filedialog, messagebox



from Scipts.OpenAiGPTBrain import LLMClient, LLMConfig
from Scipts.MainAgent import handle_command, play_mp3
from Scipts.voice_agent import VoiceAgent, VoiceConfig

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "jarvis_client_config.json")
HISTORY_PATH = os.path.join(os.path.dirname(__file__), "jarvis_chat_history.json")
MAX_TURNS_TO_SEND = 2

# ---------- конфиг/история ----------
def load_config() -> LLMConfig:
    # читаем только поля LLMConfig для инициализации клиента
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            return LLMConfig(**{k: v for k, v in data.items() if k in LLMConfig.__annotations__})
        except Exception:
            pass
    return LLMConfig()

def load_extra() -> dict:
    """Читаем доп.поля из конфига (wake_mp3_path, vosk_model_path)."""
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {}

def save_config(cfg: LLMConfig, extra: Optional[dict] = None) -> None:
    payload = asdict(cfg)
    if extra:
        payload.update(extra)
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)

def load_history() -> List[Dict[str, Any]]:
    if os.path.exists(HISTORY_PATH):
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return []

def save_history(messages: List[dict]) -> None:
    try:
        with open(HISTORY_PATH, "w", encoding="utf-8") as f:
            json.dump(messages, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# -------- Голосовое мини-окно --------
class VoiceWindow(tk.Toplevel):
    def __init__(self, master: "JarvisClientApp"):
        super().__init__(master)
        self.title("Голос")
        self.geometry("280x120")
        self.resizable(False, False)
        self.configure(bg="#0b1220")
        self.master_app = master

        self.status_var = tk.StringVar(value="голос остановлен")
        self.btn_text   = tk.StringVar(value="Старт")

        frame = ttk.Frame(self, padding=10); frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Wake word: «джарвис»", style="Tiny.TLabel").pack(anchor="w", pady=(0,6))
        ttk.Label(frame, textvariable=self.status_var).pack(anchor="w", pady=(0,10))
        ttk.Button(frame, textvariable=self.btn_text, command=self._toggle).pack(anchor="center")

        self.protocol("WM_DELETE_WINDOW", self._close)

    def set_status(self, s: str):
        self.status_var.set(s)

    def _toggle(self):
        if self.master_app.voice_running:
            self.master_app.stop_voice()
            self.btn_text.set("Старт")
        else:
            ok = self.master_app.start_voice()
            if ok:
                self.btn_text.set("Стоп")

    def _close(self):
        self.withdraw()

# ---------- GUI ----------
class JarvisClientApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Jarvis Client — LM Studio")
        self.geometry("980x720")
        self.minsize(820, 600)
        self.configure(bg="#0b1220")

        self.cfg: LLMConfig = load_config()
        self.extras: dict = load_extra()  # тут лежат vosk_model_path и wake_mp3_path
        self.llm = LLMClient(self.cfg)
        self.messages: List[Dict[str, Any]] = load_history()

        # voice
        self.vosk_model_path: str = self.extras.get("vosk_model_path", "")
        self.wake_mp3_path: str = self.extras.get("wake_mp3_path", "")  # <-- новый параметр
        self.voice_win: Optional[VoiceWindow] = None
        self.voice_agent: Optional[VoiceAgent] = None
        self.voice_running: bool = False

        # вложения
        self.attached_image_b64: Optional[str] = None
        self.attached_image_mime: Optional[str] = None
        self.attached_image_name: Optional[str] = None

        self._init_styles()
        self._init_menu()
        self._init_header()
        self._init_chat_area()
        self._init_input_panel()
        self.after(50, self._bootstrap)

    # --- UI ---
    def _init_styles(self):
        s = ttk.Style()
        try: s.theme_use("clam")
        except tk.TclError: pass
        s.configure("TButton", padding=6, relief="flat")
        s.configure("Accent.TButton", padding=8, relief="flat")
        s.configure("TLabel", foreground="#e6eaf2", background="#0b1220")
        s.configure("Header.TLabel", font=("Segoe UI Semibold", 14))
        s.configure("Tiny.TLabel", font=("Segoe UI", 9), foreground="#9aa4b2")
        s.configure("TFrame", background="#0b1220")
        s.configure("Card.TFrame", background="#121a2b")
        s.configure("Input.TFrame", background="#0f1729")
        s.configure("TEntry", fieldbackground="#101827", foreground="#e6eaf2")

    def _init_menu(self):
        m = tk.Menu(self)
        f = tk.Menu(m, tearoff=0)
        f.add_command(label="Сохранить историю…", command=self._export_history)
        f.add_separator(); f.add_command(label="Выход", command=self.destroy)
        m.add_cascade(label="Файл", menu=f)

        s = tk.Menu(m, tearoff=0)
        s.add_command(label="Настройки…", command=self._open_settings)
        s.add_command(label="Сбросить диалог", command=self._reset_chat)
        s.add_command(label="Окно голоса…", command=self._open_voice_window)
        m.add_cascade(label="Настройки", menu=s)

        h = tk.Menu(m, tearoff=0)
        h.add_command(label="О программе…", command=self._about)
        m.add_cascade(label="Справка", menu=h)
        self.config(menu=m)

    def _init_header(self):
        header = ttk.Frame(self, style="TFrame"); header.pack(fill="x", padx=14, pady=(12,8))
        left = ttk.Frame(header, style="TFrame"); left.pack(side="left", fill="x", expand=True)
        ttk.Label(left, text="Jarvis Client", style="Header.TLabel").pack(anchor="w")
        self.status_label = ttk.Label(left, text="Готов", style="Tiny.TLabel"); self.status_label.pack(anchor="w", pady=(2,0))
        right = ttk.Frame(header, style="TFrame"); right.pack(side="right")
        ttk.Button(right, text="Настройки", command=self._open_settings).pack(side="right", padx=(6,0))
        ttk.Button(right, text="Сброс", command=self._reset_chat).pack(side="right", padx=(6,6))
        ttk.Button(right, text="📎 Фото", command=self._attach_image).pack(side="right", padx=(6,6))

    def _init_chat_area(self):
        wrap = ttk.Frame(self, style="Card.TFrame"); wrap.pack(fill="both", expand=True, padx=14, pady=(0,10))
        self.chat = tk.Text(wrap, wrap="word", bg="#121a2b", fg="#e6eaf2", insertbackground="#e6eaf2",
                            relief="flat", padx=14, pady=12, state="disabled")
        self.chat.pack(fill="both", expand=True, side="left")
        scroll = ttk.Scrollbar(wrap, command=self.chat.yview); scroll.pack(side="right", fill="y")
        self.chat["yscrollcommand"] = scroll.set
        self.chat.tag_configure("user_name", foreground="#9dd6ff", spacing3=4, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("user_msg", lmargin1=10, lmargin2=10, spacing1=2, spacing3=10)
        self.chat.tag_configure("asst_name", foreground="#bfa3ff", spacing3=4, font=("Segoe UI", 9, "bold"))
        self.chat.tag_configure("asst_msg", lmargin1=10, lmargin2=10, spacing1=2, spacing3=12)
        self.chat.tag_configure("time", foreground="#93a0b5", font=("Segoe UI", 8))

    def _init_input_panel(self):
        bar = ttk.Frame(self, style="Input.TFrame"); bar.pack(fill="x", padx=14, pady=(0,12))
        self.input = tk.Text(bar, height=3, wrap="word", bg="#0f1729", fg="#e6eaf2", relief="flat")
        self.input.pack(side="left", fill="x", expand=True, padx=(8,8), pady=8)
        self.input.bind("<Control-Return>", lambda e: self._send_message())
        self.input.bind("<Shift-Return>", lambda e: self._insert_newline())
        btns = ttk.Frame(bar, style="Input.TFrame"); btns.pack(side="right", padx=(0,8), pady=8)
        self.send_btn = ttk.Button(btns, text="Отправить", style="Accent.TButton", command=self._send_message); self.send_btn.grid(row=0, column=0, sticky="ew")
        self.clear_btn = ttk.Button(btns, text="Очистить ввод", command=lambda: self.input.delete("1.0","end")); self.clear_btn.grid(row=1, column=0, sticky="ew", pady=(6,0))

    # --- helpers ---
    def _bootstrap(self):
        if not self.messages:
            self._append_assistant("Привет! Я Jarvis. Скажи «джарвис …», чтобы продиктовать команду. Звук подтверждения можно выбрать в настройках (Wake MP3).")
        else:
            for m in self.messages:
                if m.get("role") == "user": self._append_user(m.get("content",""))
                elif m.get("role") == "assistant": self._append_assistant(m.get("content",""))
        self.input.focus_set()

    def _insert_newline(self): self.input.insert("insert","\n"); return "break"

    def _append_user(self, text: str):
        self.chat.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.chat.insert("end", f"Вы  ·  {ts}\n", ("user_name","time"))
        self.chat.insert("end", text.strip()+"\n\n", ("user_msg",))
        self.chat.configure(state="disabled"); self.chat.see("end")

    def _append_assistant(self, text: str):
        self.chat.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.chat.insert("end", f"Jarvis  ·  {ts}\n", ("asst_name","time"))
        self.chat.insert("end", text.strip()+"\n\n", ("asst_msg",))
        self.chat.configure(state="disabled"); self.chat.see("end")

    def _append_system(self, text: str):
        self.chat.configure(state="normal")
        ts = datetime.now().strftime("%H:%M:%S")
        self.chat.insert("end", f"Система  ·  {ts}\n", ("time",))
        self.chat.insert("end", text.strip()+"\n\n")
        self.chat.configure(state="disabled"); self.chat.see("end")

    def _set_status(self, text: str):
        self.status_label.configure(text=text); self.update_idletasks()

    def _reset_chat(self):
        if messagebox.askyesno("Сброс диалога", "Удалить текущую историю и начать заново?"):
            self.messages = []; save_history(self.messages)
            self.chat.configure(state="normal"); self.chat.delete("1.0","end")
            self.chat.configure(state="disabled"); self._append_assistant("История очищена. Готов к новому диалогу.")

    def _export_history(self):
        path = filedialog.asksaveasfilename(defaultextension=".txt", filetypes=[("Text","*.txt"),("All","*.*")], title="Сохранить историю как…")
        if not path: return
        lines = [f"[{m.get('role','?')}] {m.get('content','')}" for m in self.messages]
        try:
            with open(path,"w",encoding="utf-8") as f: f.write("\n\n".join(lines))
            messagebox.showinfo("Готово","История сохранена.")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось сохранить файл: {e}")

    def _about(self):
        messagebox.showinfo("О программе","Jarvis Client — GUI к LM Studio.\nГолос: wake word «джарвис», звук подтверждения — настраиваемый mp3.")

    # --- Голос ---
    def _open_voice_window(self):
        if self.voice_win and tk.Toplevel.winfo_exists(self.voice_win):
            self.voice_win.deiconify(); self.voice_win.lift(); return
        self.voice_win = VoiceWindow(self); self.voice_win.lift()

    def start_voice(self) -> bool:
        if not self.vosk_model_path or not os.path.isdir(self.vosk_model_path):
            messagebox.showwarning("Голос", "Укажи путь к модели Vosk в настройках.")
            return False

        def on_status(msg: str):
            if self.voice_win: self.voice_win.set_status(msg)

        def on_command(text: str):
            self.after(10, lambda: self._send_text_from_voice(text))

        def on_wake():
            self.after(10, self._play_wake_sound)  # <-- играем mp3 при слове «джарвис»

        vc = VoiceConfig(vosk_model_path=self.vosk_model_path)
        self.voice_agent = VoiceAgent(vc, on_status=on_status, on_command=on_command, on_wake=on_wake)
        try:
            self.voice_agent.start()
            self.voice_running = True
            return True
        except Exception as e:
            messagebox.showerror("Голос", f"Не удалось запустить: {e}")
            self.voice_agent = None; self.voice_running = False
            return False

    def stop_voice(self):
        if self.voice_agent:
            try: self.voice_agent.stop()
            except Exception: pass
        self.voice_agent = None
        self.voice_running = False
        if self.voice_win: self.voice_win.set_status("голос остановлен")

    def _play_wake_sound(self):
        """Проигрываем выбранный wake-mp3 (слушаю, сэр)."""
        if not self.wake_mp3_path:
            self._append_system("Wake word: mp3 не задан (Настройки → Wake MP3).")
            return
        self._append_system("Wake word: проигрываю подтверждение…")
        def run():
            try:
                result = play_mp3(self.wake_mp3_path)
            except Exception as e:
                result = f"Ошибка агента: {e}"
            self.after(10, lambda: self._append_system(f"АГЕНТ: {result}"))
        threading.Thread(target=run, daemon=True).start()

    # --- Настройки ---
    def _open_settings(self):
        win = tk.Toplevel(self); win.title("Настройки"); win.configure(bg="#0b1220"); win.geometry("640x460")
        win.transient(self); win.grab_set()
        frm = ttk.Frame(win, padding=16); frm.pack(fill="both", expand=True)

        ttk.Label(frm, text="LM Studio Chat Completions URL:").grid(row=0, column=0, sticky="w")
        api_var = tk.StringVar(value=self.cfg.api_url)
        ttk.Entry(frm, textvariable=api_var, width=64).grid(row=1, column=0, columnspan=3, sticky="ew", pady=(4,12))

        ttk.Label(frm, text="Модель (model):").grid(row=2, column=0, sticky="w")
        model_var = tk.StringVar(value=self.cfg.model)
        ttk.Entry(frm, textvariable=model_var, width=48).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(4,12))

        ttk.Label(frm, text="Температура:").grid(row=4, column=0, sticky="w")
        temp_var = tk.DoubleVar(value=self.cfg.temperature)
        ttk.Scale(frm, variable=temp_var, from_=0.0, to=1.5).grid(row=5, column=0, columnspan=3, sticky="ew", pady=(4,12))

        ttk.Label(frm, text="System prompt:").grid(row=6, column=0, sticky="w")
        sys_text = tk.Text(frm, height=6, wrap="word"); sys_text.insert("1.0", self.cfg.system_prompt)
        sys_text.grid(row=7, column=0, columnspan=3, sticky="nsew")

        # Vosk модель
        ttk.Label(frm, text="Vosk model (папка):").grid(row=8, column=0, sticky="w", pady=(8,0))
        vosk_var = tk.StringVar(value=self.vosk_model_path)
        ttk.Entry(frm, textvariable=vosk_var, width=48).grid(row=9, column=0, sticky="ew")
        ttk.Button(frm, text="Выбрать…", command=lambda: self._pick_dir(vosk_var)).grid(row=9, column=1, padx=6)

        # Wake MP3 (любой файл — «Слушаю, сэр»)
        ttk.Label(frm, text="Wake MP3 (звук подтверждения):").grid(row=10, column=0, sticky="w", pady=(8,0))
        wake_var = tk.StringVar(value=self.wake_mp3_path)
        ttk.Entry(frm, textvariable=wake_var, width=48).grid(row=11, column=0, sticky="ew")
        ttk.Button(frm, text="Выбрать…", command=lambda: self._pick_file(wake_var, [("MP3","*.mp3"),("All","*.*")])).grid(row=11, column=1, padx=6)

        frm.columnconfigure(0, weight=1); frm.rowconfigure(7, weight=1)
        btns = ttk.Frame(frm); btns.grid(row=12, column=0, columnspan=3, sticky="e", pady=(12,0))

        def on_test():
            self._set_status("Проверка подключения…")
            try:
                res = self.llm.test_api(api_var.get(), model_var.get())
                if "pong" in (res.get("text") or "").lower():
                    self._set_status("Подключение OK ✨"); messagebox.showinfo("Успех","Подключение работает.")
                else:
                    self._set_status("Подключение есть, но ответ необычный")
                    messagebox.showwarning("Внимание", f"Ответ: {res.get('text','')[:200]}")
            except Exception as e:
                self._set_status("Ошибка подключения"); messagebox.showerror("Ошибка", f"Не удалось подключиться: {e}")

        ttk.Button(btns, text="Тест соединения", command=on_test).pack(side="left", padx=(0,8))

        def on_save():
            self.llm.set_config(
                api_url=api_var.get().strip(),
                model=model_var.get().strip(),
                temperature=float(temp_var.get()),
                system_prompt=sys_text.get("1.0","end").strip(),
            )
            self.cfg = self.llm.get_config()
            self.vosk_model_path = vosk_var.get().strip()
            self.wake_mp3_path = wake_var.get().strip()
            save_config(self.cfg, extra={
                "vosk_model_path": self.vosk_model_path,
                "wake_mp3_path": self.wake_mp3_path
            })
            self._set_status("Настройки сохранены"); win.destroy()

        ttk.Button(btns, text="Сохранить", style="Accent.TButton", command=on_save).pack(side="left")

    def _pick_dir(self, var: tk.StringVar):
        path = filedialog.askdirectory(title="Выберите папку")
        if path: var.set(path)

    def _pick_file(self, var: tk.StringVar, types):
        path = filedialog.askopenfilename(title="Выберите файл", filetypes=types)
        if path: var.set(path)

    # --- Вложения ---
    def _attach_image(self):
        path = filedialog.askopenfilename(
            title="Выберите изображение",
            filetypes=[("Images","*.png;*.jpg;*.jpeg;*.webp;*.bmp"), ("All files","*.*")],
        )
        if not path: return
        try:
            mime, _ = mimetypes.guess_type(path); mime = mime or "image/png"
            with open(path,"rb") as f: b = f.read()
            self.attached_image_b64 = base64.b64encode(b).decode("utf-8")
            self.attached_image_mime = mime
            self.attached_image_name = os.path.basename(path)
            self._set_status(f"Прикреплено: {self.attached_image_name}")
            self._append_system(f"📎 Вложение: {self.attached_image_name}")
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось прикрепить файл: {e}")

    def _clear_attachment(self):
        self.attached_image_b64 = None; self.attached_image_mime = None; self.attached_image_name = None

    # --- Отправка и приём ---
    def _send_text_from_voice(self, text: str):
        self.input.delete("1.0", "end")
        self.input.insert("1.0", text)
        self._send_message()

    def _send_message(self):
        text = self.input.get("1.0","end").strip()
        if not text: return
        self._append_user(text)

        attachment = None
        if self.attached_image_b64:
            attachment = {"b64": self.attached_image_b64, "mime": self.attached_image_mime or "image/png",
                          "name": self.attached_image_name or "image"}

        req_messages = self.llm.build_messages(
            system_prompt=self.cfg.system_prompt,
            history=self.messages,
            user_text=text,
            attachment=attachment,
            max_turns_to_send=MAX_TURNS_TO_SEND,
            force_text_only=False,
        )

        self.send_btn.state(["disabled"]); self._set_status("Запрос к модели…")

        def on_success(*args):
            if len(args) == 3: answer_text, latency, meta = args
            elif len(args) == 2: answer_text, latency = args; meta = {}
            else: answer_text, latency, meta = "(пустой ответ)", 0.0, {}

            def _apply():
                self.send_btn.state(["!disabled"])
                self._append_assistant((answer_text or "").strip() or "(пустой ответ)")
                self._set_status(f"Готов  ·  {latency:.2f}s")
                # история
                last_user = {"role":"user","content": req_last_user_from_ui(self.chat)}
                if last_user["content"]: self.messages.append(last_user)
                self.messages.append({"role":"assistant","content": answer_text})
                save_history(self.messages)
                # если когда-нибудь снова понадобятся LLM-команды, тут их можно обработать:
                cmd = (meta or {}).get("command") or ""
                if cmd:
                    self._append_system(f"Команда от LLM: {cmd}")
                    def run():
                        try:
                            result = handle_command(cmd)
                        except Exception as e:
                            result = f"Ошибка агента: {e}"
                        self.after(10, lambda: self._append_system(f"АГЕНТ: {result}" if result else "АГЕНТ: OK"))
                    threading.Thread(target=run, daemon=True).start()
                # ... внутри def _apply() после if cmd: ... else:
                else:
                    # озвучиваем обычный текст (без команд) клонированным голосом
                    sample_voice_path = os.path.abspath(
                        os.path.join(os.path.dirname(__file__), "JarvisVoice", "instruction.wav")
                    )
                    def speak_async():
                        try:
                            # ленивый импорт, чтобы TTS не грузился при старте GUI
                            from Scipts.voice_clone_remote import speak_clone_remote
                            result = speak_clone_remote(
                                    answer_text,
                                    sample_voice_path,   # твой Compilation2.wav / .mp3
                                    lang="ru",
                                    speed=0.88,
                                    sample_rate=0,       # сервер вернёт нативный SR (обычно 24000)
                                    voice_id="jarvis",   # фиксировано или опусти — сгенерится от хэша файла
                                    do_play=True
                            )
                        except Exception as e:
                            result = f"Ошибка TTS: {e}"
                        self.after(10, lambda: self._append_system(f"ОЗВУЧКА: {result}"))
                    threading.Thread(target=speak_async, daemon=True).start()

            self.after(10, _apply)

        def on_error(err_text: str):
            self.after(10, lambda: self._apply_error(err_text))

        self.llm.send_chat_async(req_messages, on_success, on_error)
        self.input.delete("1.0","end"); self._clear_attachment()

    def _apply_error(self, err: str):
        self.send_btn.state(["!disabled"]); self._set_status("Ошибка: " + err)
        messagebox.showerror("Ошибка запроса", err)

# вытащить последний ввод пользователя из Text
def req_last_user_from_ui(chat_text: tk.Text) -> str:
    content = chat_text.get("1.0","end")
    lines = [l.rstrip("\n") for l in content.splitlines()]
    for i in range(len(lines)-1, -1, -1):
        if lines[i].startswith("Вы  ·  "):
            msg = []
            for j in range(i+1, len(lines)):
                if lines[j].strip() == "": break
                msg.append(lines[j])
            return "\n".join(msg).strip()
    return ""

if __name__ == "__main__":
    app = JarvisClientApp()
    app.mainloop()
