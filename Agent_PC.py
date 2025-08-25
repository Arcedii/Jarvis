# Agent_PC.py
import base64
import io
import requests
import pyautogui

class AgentPC:
    def __init__(self, api_url: str, model: str, temperature: float = 0.0):
        self.api_url = api_url  # например, http://192.168.100.8:1234/v1/chat/completions
        self.model = model
        self.temperature = temperature

    def capture_screen(self) -> str:
        """Сделать скриншот и вернуть его в виде base64-строки."""
        screenshot = pyautogui.screenshot()  # возвращает Pillow Image:contentReference[oaicite:5]{index=5}
        buf = io.BytesIO()
        screenshot.save(buf, format='PNG')
        b64_img = base64.b64encode(buf.getvalue()).decode('utf-8')
        return b64_img

    def ask_llm_for_action(self, prompt: str, image_b64: str) -> tuple:
        """Отправить запрос в LLM и получить координаты клика."""
        system_prompt = (
            "Вы — агент управления ПК. По текстовому запросу и изображению экрана "
            "верните координаты (x, y) для следующего клика мышью, либо "
            "сообщите, что действие не требуется."
        )
        messages = [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/png;base64,{image_b64}"}
                    }
                ]
            }
        ]
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": float(self.temperature),
        }
        response = requests.post(self.api_url, json=payload, timeout=30)
        data = response.json()
        # Предполагаем, что модель возвращает координаты в формате {"x": ..., "y": ...}
        coords = data["choices"][0]["message"]["function_call"]["arguments"]
        return coords["x"], coords["y"]

    def click(self, x: int, y: int) -> None:
        """Сделать клик по указанным координатам."""
        pyautogui.moveTo(x, y)
        pyautogui.click()

    def perform_task(self, task_description: str) -> None:
        """Основной метод: делает скрин, просит LLM определить координаты и кликает."""
        screen_b64 = self.capture_screen()
        x, y = self.ask_llm_for_action(task_description, screen_b64)
        if x is not None and y is not None:
            self.click(x, y)
