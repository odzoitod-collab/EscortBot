import os
from typing import Optional, List

class Config:
    """Конфигурация для Telegram бота OneNight"""
    
    # Токен бота (получить у @BotFather)
    BOT_TOKEN: str = os.getenv("BOT_TOKEN", "8154688370:AAF4OWe9hvpvXyQA5_nryDHMFBpVG26MB1Y")
    
    # URL вашего веб-приложения
    WEB_APP_URL: str = os.getenv("WEB_APP_URL", "https://onenight-b9ft.vercel.app/")
    
    # Supabase настройки
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "https://xasyfblbgagkmtpxoiqp.supabase.co")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6Inhhc3lmYmxiZ2Fna210cHhvaXFwIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NjY5NTg0NjYsImV4cCI6MjA4MjUzNDQ2Nn0.kaT10SR7idYYZIQc1Gp8JsHXcxfmcbtz6JZqNM7UPZE")
    
    # ID администраторов (добавь свой Telegram ID)
    ADMIN_IDS: List[int] = [844012884, 8227295387, 8162019020]  # Твой ID
    
    # Настройки логирования (уменьшаем для производительности)
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "WARNING")
    
    
    @classmethod
    def validate(cls) -> bool:
        """Проверка корректности конфигурации"""
        if cls.BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
            print("❌ Ошибка: Необходимо установить BOT_TOKEN")
            return False
            
        if cls.WEB_APP_URL == "https://your-domain.com":
            print("❌ Ошибка: Необходимо установить WEB_APP_URL")
            return False
            
        return True
