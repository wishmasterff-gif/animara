#!/usr/bin/env python3
"""
🌐 Browser Skill
Браузерная автоматизация через Playwright
"""

import os
import asyncio
from datetime import datetime
from typing import Dict, List, Optional

# Проверяем наличие playwright
try:
    from playwright.async_api import async_playwright, Browser, Page
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False
    print("⚠️ Playwright не установлен. Установи: pip install playwright && playwright install chromium")

# Директории
SCREENSHOTS_DIR = os.path.expanduser("~/animara/screenshots")
os.makedirs(SCREENSHOTS_DIR, exist_ok=True)

# User-Agent для обхода простых блокировок
USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"


class BrowserAgent:
    """Асинхронный браузерный агент"""
    
    def __init__(self):
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None
    
    async def start(self, headless: bool = True):
        """Запустить браузер"""
        if not PLAYWRIGHT_AVAILABLE:
            raise RuntimeError("Playwright не установлен")
        
        self.playwright = await async_playwright().start()
        self.browser = await self.playwright.chromium.launch(
            headless=headless,
            args=[
                '--no-sandbox',
                '--disable-dev-shm-usage',
                '--disable-blink-features=AutomationControlled'
            ]
        )
        
        context = await self.browser.new_context(
            user_agent=USER_AGENT,
            viewport={'width': 1920, 'height': 1080}
        )
        
        self.page = await context.new_page()
        self.page.set_default_timeout(60000)  # 60 сек таймаут
        
        print("🌐 Браузер запущен")
    
    async def stop(self):
        """Закрыть браузер"""
        if self.browser:
            await self.browser.close()
        if self.playwright:
            await self.playwright.stop()
        print("🌐 Браузер закрыт")
    
    async def open_page(self, url: str, wait_for: str = "domcontentloaded") -> Dict:
        """
        Открыть страницу и получить содержимое.
        
        Args:
            url: URL страницы
            wait_for: Событие ожидания (domcontentloaded, networkidle, load)
            
        Returns:
            Dict с данными страницы
        """
        if not self.page:
            return {"success": False, "error": "Браузер не запущен"}
        
        try:
            await self.page.goto(url, wait_until=wait_for)
            await self.page.wait_for_timeout(2000)  # Дополнительное ожидание
            
            title = await self.page.title()
            text = await self.page.inner_text("body")
            
            # Делаем скриншот
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_path = f"{SCREENSHOTS_DIR}/page_{timestamp}.png"
            await self.page.screenshot(path=screenshot_path)
            
            return {
                "success": True,
                "url": self.page.url,
                "title": title,
                "text": text[:5000],  # Ограничиваем размер
                "screenshot": screenshot_path
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def screenshot(self, url: str, name: str) -> str:
        """
        Сделать скриншот страницы.
        
        Args:
            url: URL страницы
            name: Имя файла (без расширения)
            
        Returns:
            Путь к скриншоту
        """
        if not self.page:
            return "❌ Браузер не запущен"
        
        try:
            await self.page.goto(url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(2000)
            
            # Очищаем имя файла
            safe_name = "".join(c for c in name if c.isalnum() or c in "._-")[:50]
            path = f"{SCREENSHOTS_DIR}/{safe_name}.png"
            
            await self.page.screenshot(path=path, full_page=True)
            return f"✅ Скриншот сохранён: {path}"
            
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def get_text(self, url: str) -> str:
        """
        Получить текстовое содержимое страницы.
        
        Args:
            url: URL страницы
            
        Returns:
            Текст страницы
        """
        result = await self.open_page(url)
        if result["success"]:
            return result["text"]
        else:
            return f"❌ Ошибка: {result.get('error', 'Unknown')}"
    
    async def search_google(self, query: str) -> List[Dict]:
        """
        Поиск в Google (осторожно — может быть капча!).
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Список результатов
        """
        if not self.page:
            return [{"error": "Браузер не запущен"}]
        
        try:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            await self.page.goto(url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(3000)
            
            # Проверяем на капчу
            content = await self.page.content()
            if "captcha" in content.lower() or "recaptcha" in content.lower():
                return [{"error": "Google показал капчу. Используй web_search skill вместо этого."}]
            
            # Парсим результаты
            results = []
            items = await self.page.query_selector_all("div.g")
            
            for item in items[:10]:
                try:
                    title_el = await item.query_selector("h3")
                    link_el = await item.query_selector("a")
                    desc_el = await item.query_selector("div[data-sncf]")
                    
                    if title_el and link_el:
                        title = await title_el.inner_text()
                        href = await link_el.get_attribute("href")
                        desc = await desc_el.inner_text() if desc_el else ""
                        
                        results.append({
                            "title": title,
                            "url": href,
                            "description": desc[:200]
                        })
                except:
                    continue
            
            return results if results else [{"error": "Результаты не найдены"}]
            
        except Exception as e:
            return [{"error": str(e)}]
    
    async def search_yandex(self, query: str) -> List[Dict]:
        """
        Поиск в Яндексе.
        
        Args:
            query: Поисковый запрос
            
        Returns:
            Список результатов
        """
        if not self.page:
            return [{"error": "Браузер не запущен"}]
        
        try:
            url = f"https://yandex.ru/search/?text={query.replace(' ', '+')}"
            await self.page.goto(url, wait_until="domcontentloaded")
            await self.page.wait_for_timeout(3000)
            
            results = []
            items = await self.page.query_selector_all("li.serp-item")
            
            for item in items[:10]:
                try:
                    title_el = await item.query_selector("h2 a, .OrganicTitle-Link")
                    desc_el = await item.query_selector(".OrganicText, .text-container")
                    
                    if title_el:
                        title = await title_el.inner_text()
                        href = await title_el.get_attribute("href")
                        desc = await desc_el.inner_text() if desc_el else ""
                        
                        results.append({
                            "title": title,
                            "url": href,
                            "description": desc[:200]
                        })
                except:
                    continue
            
            return results if results else [{"error": "Результаты не найдены"}]
            
        except Exception as e:
            return [{"error": str(e)}]


# Синхронные обёртки для удобства
def open_page_sync(url: str) -> Dict:
    """Синхронная обёртка для open_page"""
    async def _run():
        agent = BrowserAgent()
        await agent.start()
        result = await agent.open_page(url)
        await agent.stop()
        return result
    
    return asyncio.run(_run())


def screenshot_sync(url: str, name: str) -> str:
    """Синхронная обёртка для screenshot"""
    async def _run():
        agent = BrowserAgent()
        await agent.start()
        result = await agent.screenshot(url, name)
        await agent.stop()
        return result
    
    return asyncio.run(_run())


def get_text_sync(url: str) -> str:
    """Синхронная обёртка для get_text"""
    async def _run():
        agent = BrowserAgent()
        await agent.start()
        result = await agent.get_text(url)
        await agent.stop()
        return result
    
    return asyncio.run(_run())


# CLI интерфейс для тестирования
if __name__ == "__main__":
    import sys
    
    if not PLAYWRIGHT_AVAILABLE:
        print("❌ Playwright не установлен!")
        print("Установи: pip install playwright && playwright install chromium")
        sys.exit(1)
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python main.py open <url>       - открыть страницу")
        print("  python main.py screenshot <url> - сделать скриншот")
        print("  python main.py text <url>       - получить текст")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "open" and len(sys.argv) > 2:
        url = sys.argv[2]
        result = open_page_sync(url)
        print(f"URL: {result.get('url')}")
        print(f"Title: {result.get('title')}")
        print(f"Screenshot: {result.get('screenshot')}")
        print(f"\nText (first 500 chars):\n{result.get('text', '')[:500]}")
    
    elif cmd == "screenshot" and len(sys.argv) > 2:
        url = sys.argv[2]
        name = sys.argv[3] if len(sys.argv) > 3 else "screenshot"
        result = screenshot_sync(url, name)
        print(result)
    
    elif cmd == "text" and len(sys.argv) > 2:
        url = sys.argv[2]
        result = get_text_sync(url)
        print(result[:2000])
    
    else:
        print(f"Неизвестная команда: {cmd}")
