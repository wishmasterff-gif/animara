#!/usr/bin/env python3
"""
🔍 Web Search Skill
Поиск в интернете через Brave Search API
"""

import os
import json
import requests
from typing import Optional

# Конфигурация
CONFIG_PATH = os.path.expanduser("~/animara/config/secrets.json")
DEFAULT_API_KEY = "BSA1PthqtF-a8kZj7f_xNcLGBbMDfN3"  # Fallback

def get_api_key() -> str:
    """Получить API ключ из конфига или использовать default"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get("brave_api_key", DEFAULT_API_KEY)
    except Exception:
        pass
    return DEFAULT_API_KEY


def search(query: str, count: int = 6) -> str:
    """
    Поиск в интернете через Brave Search API.
    
    Args:
        query: Поисковый запрос
        count: Количество результатов (1-10)
        
    Returns:
        Форматированный текст с результатами поиска
    """
    if not query or not query.strip():
        return "❌ Пустой поисковый запрос"
    
    api_key = get_api_key()
    
    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key
            },
            params={
                "q": query.strip(),
                "count": min(max(count, 1), 10)  # Ограничиваем 1-10
            },
            timeout=15
        )
        
        if response.status_code == 401:
            return "❌ Неверный API ключ Brave Search"
        elif response.status_code == 429:
            return "❌ Превышен лимит запросов Brave API"
        elif response.status_code != 200:
            return f"❌ Ошибка Brave API: {response.status_code}"
        
        data = response.json()
        results = data.get("web", {}).get("results", [])
        
        if not results:
            return f"🔍 По запросу «{query}» ничего не найдено"
        
        # Форматируем результаты
        output = []
        for i, item in enumerate(results[:count], 1):
            title = item.get("title", "Без заголовка")
            description = item.get("description", "")[:250]
            url = item.get("url", "")
            
            output.append(f"{i}. **{title}**\n   {description}\n   🔗 {url}")
        
        return "\n\n".join(output)
        
    except requests.Timeout:
        return "❌ Таймаут запроса к Brave Search"
    except requests.RequestException as e:
        return f"❌ Ошибка сети: {e}"
    except Exception as e:
        return f"❌ Ошибка поиска: {e}"


def search_news(query: str, count: int = 5) -> str:
    """
    Поиск новостей через Brave Search API.
    
    Args:
        query: Поисковый запрос
        count: Количество результатов
        
    Returns:
        Форматированный текст с новостями
    """
    api_key = get_api_key()
    
    try:
        response = requests.get(
            "https://api.search.brave.com/res/v1/news/search",
            headers={
                "Accept": "application/json",
                "X-Subscription-Token": api_key
            },
            params={
                "q": query.strip(),
                "count": min(max(count, 1), 10)
            },
            timeout=15
        )
        
        if response.status_code != 200:
            return f"❌ Ошибка Brave News API: {response.status_code}"
        
        data = response.json()
        results = data.get("results", [])
        
        if not results:
            return f"📰 Новостей по запросу «{query}» не найдено"
        
        output = []
        for i, item in enumerate(results[:count], 1):
            title = item.get("title", "Без заголовка")
            description = item.get("description", "")[:200]
            url = item.get("url", "")
            age = item.get("age", "")
            
            output.append(f"{i}. **{title}** ({age})\n   {description}\n   🔗 {url}")
        
        return "\n\n".join(output)
        
    except Exception as e:
        return f"❌ Ошибка поиска новостей: {e}"


# CLI интерфейс для тестирования
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование: python main.py <запрос>")
        print("Пример: python main.py 'погода Бали'")
        sys.exit(1)
    
    query = " ".join(sys.argv[1:])
    print(f"🔍 Ищу: {query}\n")
    print(search(query))
