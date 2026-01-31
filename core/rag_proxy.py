#!/usr/bin/env python3
"""
🚀 ANIMARA RAG PROXY v10.4 — GOD MODE через OAuth (ChatGPT Plus/Pro подписка)

Новое в v10.4:
1. ✅ GOD MODE через OAuth (НЕ платный API!)
   - Использует ~/.codex/auth.json от OpenAI Codex CLI
   - ChatGPT Plus ($20/мес) или Pro ($200/мес) подписка
   - Модели: gpt-4o, o4-mini, gpt-5.2-codex (когда доступны)
   - Контекст: 128K-400K токенов
   
2. ✅ Команды:
   - "Активируй режим бога" / "/god" → включить
   - "Отключи режим бога" / "/local" → выключить
   
3. ✅ Автообновление токенов через refresh_token

4. ✅ Всё из v10.1: tools, ReAct, workspace, hybrid search, thinking mode

НАСТРОЙКА:
1. На машине с браузером: npm install -g @openai/codex && codex login
2. Скопировать ~/.codex/auth.json на Jetson Thor
3. Готово! Токены автообновляются
"""

import os
import re
import json
import time
import asyncio
import hashlib
import sys
from typing import Optional, Dict, List, Any
from contextlib import asynccontextmanager
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse, JSONResponse
from sentence_transformers import SentenceTransformer
from pymilvus import MilvusClient
from rank_bm25 import BM25Okapi
# God Mode via Codex CLI
from animara_godmode_patch import check_godmode_command, call_chatgpt_codex, GODMODE_CONFIG

# Добавляем путь к skills
sys.path.insert(0, os.path.expanduser("~/animara"))

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "version": "10.4",
    
    # Local LLM (Qwen3)
    "llm_api": "http://127.0.0.1:8010",
    "llm_model": "qwen3",
    "llm_max_tokens": 2000,
    "llm_context": 32768,  # 32K для Qwen3
    
    # Milvus
    "milvus_uri": "http://localhost:19530",
    
    # Embedding
    "embedding_model": "/home/agx-thor/models/embeddings/bge-m3",
    
    # Paths
    "workspace_path": "/home/agx-thor/animara/workspace",
    "skills_path": "/home/agx-thor/animara/skills",
    
    # Users
    "default_person_id": "owner_sergey",
    "owner_person_id": "owner_sergey",
    
    # Cache
    "profile_cache_ttl": 300,
    
    # Session
    "session_max_messages": 20,
    "session_timeout": 1800,
    
    # Hybrid Search
    "vector_weight": 0.7,
    "bm25_weight": 0.3,
    "search_top_k": 5,
    
    # Memory Flush
    "context_limit": 32000,
    "flush_threshold": 28000,
    "reserve_tokens": 4000,
    
    # Session Pruning
    "prune_after_messages": 3,
    "prune_tool_max_chars": 200,
    
    # Tools
    "max_tool_iterations": 5,
    "tool_timeout": 30,
    
    # ═══════════════════════════════════════════════════════════════
    # GOD MODE — OAuth через ChatGPT Plus/Pro подписку
    # ═══════════════════════════════════════════════════════════════
    "godmode_auth_file": os.path.expanduser("~/.codex/auth.json"),
    "godmode_model": "gpt-4o",  # Основная модель (128K контекст)
    "godmode_model_reasoning": "o4-mini",  # Для сложных задач (если доступна)
    "godmode_max_tokens": 16384,  # Лимит на ответ
    "godmode_context": 128000,  # 128K контекст для gpt-4o
    "godmode_api_url": "https://api.openai.com/v1/chat/completions",
    "godmode_auth_url": "https://auth.openai.com/oauth/token",
}

embedder = None
milvus = None
bm25_index = None
bm25_docs = []
bm25_ids = []

# ═══════════════════════════════════════════════════════════════
# OAUTH PROVIDER — ChatGPT через Codex CLI
# ═══════════════════════════════════════════════════════════════

class ChatGPTAuthProvider:
    """
    Провайдер OAuth токенов для ChatGPT Plus/Pro.
    Использует токены от OpenAI Codex CLI.
    
    Установка:
        npm install -g @openai/codex
        codex login
        scp ~/.codex/auth.json agx-thor@192.168.1.12:~/.codex/
    """
    
    def __init__(self, auth_file: str = None):
        self.auth_file = Path(auth_file or CONFIG["godmode_auth_file"])
        self._tokens = None
        self._load_time = 0
    
    def is_configured(self) -> bool:
        """Проверяет настроен ли OAuth"""
        return self.auth_file.exists()
    
    def _load_tokens(self) -> Optional[dict]:
        """Загружает токены из файла (поддержка формата Codex CLI)"""
        if not self.auth_file.exists():
            return None
        
        try:
            with open(self.auth_file, 'r') as f:
                data = json.load(f)
            
            # Codex CLI сохраняет токены в data["tokens"]
            if "tokens" in data:
                tokens = data["tokens"]
            else:
                tokens = data
            
            # Если нет expires_at, ставим +1 час от сейчас
            if "expires_at" not in tokens and "access_token" in tokens:
                tokens["expires_at"] = int(time.time()) + 3600
            
            self._tokens = tokens
            self._load_time = time.time()
            return tokens
        except Exception as e:
            print(f"⚠️ Ошибка загрузки OAuth токенов: {e}")
            return None
    
    def _save_tokens(self, tokens: dict):
        """Сохраняет обновлённые токены"""
        try:
            self.auth_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.auth_file, 'w') as f:
                json.dump(tokens, f, indent=2)
            self._tokens = tokens
            print(f"✅ OAuth токены обновлены: {self.auth_file}")
        except Exception as e:
            print(f"⚠️ Ошибка сохранения токенов: {e}")
    
    async def _refresh_token(self) -> bool:
        """Обновляет access_token через refresh_token"""
        if not self._tokens or "refresh_token" not in self._tokens:
            return False
        
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(
                    CONFIG["godmode_auth_url"],
                    data={
                        "grant_type": "refresh_token",
                        "refresh_token": self._tokens["refresh_token"],
                        "client_id": "pdlLIX2Y72MIl2rhLhTE9VV9bN905kBh",  # Codex client_id
                    },
                    headers={"Content-Type": "application/x-www-form-urlencoded"}
                )
                
                if response.status_code == 200:
                    new_tokens = response.json()
                    # Сохраняем новые токены
                    self._tokens["access_token"] = new_tokens.get("access_token", self._tokens["access_token"])
                    if "refresh_token" in new_tokens:
                        self._tokens["refresh_token"] = new_tokens["refresh_token"]
                    self._tokens["expires_at"] = int(time.time()) + new_tokens.get("expires_in", 3600)
                    self._save_tokens(self._tokens)
                    print("✅ OAuth токен обновлён")
                    return True
                else:
                    print(f"⚠️ Ошибка обновления токена: {response.status_code}")
                    return False
        except Exception as e:
            print(f"⚠️ Ошибка refresh: {e}")
            return False
    
    async def get_access_token(self) -> Optional[str]:
        """Получает действующий access_token"""
        # Загружаем токены если нужно
        if not self._tokens or (time.time() - self._load_time > 60):
            self._load_tokens()
        
        if not self._tokens:
            return None
        
        # Проверяем срок действия (обновляем за 5 минут до истечения)
        expires_at = self._tokens.get("expires_at", 0)
        if expires_at - time.time() < 300:
            print("🔄 Обновляем OAuth токен...")
            await self._refresh_token()
        
        return self._tokens.get("access_token")
    
    def get_status(self) -> dict:
        """Статус OAuth авторизации"""
        if not self._load_tokens():
            return {
                "configured": False,
                "error": f"Файл {self.auth_file} не найден. Выполни: codex login"
            }
        
        expires_at = self._tokens.get("expires_at", 0)
        expires_in = int(expires_at - time.time())
        
        return {
            "configured": True,
            "expires_in_seconds": max(0, expires_in),
            "expires_in_human": f"{expires_in // 60} мин" if expires_in > 0 else "Истёк",
            "has_refresh_token": "refresh_token" in self._tokens
        }

# Глобальный провайдер OAuth
oauth_provider = None

# ═══════════════════════════════════════════════════════════════
# GOD MODE SYSTEM — вызов ChatGPT через OAuth
# ═══════════════════════════════════════════════════════════════

def check_godmode_command(text: str) -> Optional[str]:
    """
    Проверяет является ли сообщение командой God Mode.
    Returns: "activate", "deactivate", или None
    """
    text_lower = text.lower().strip()
    
    # Команды активации
    activate_patterns = [
        r"^активируй режим бога$",
        r"^режим бога$",
        r"^включи режим бога$",
        r"^/god$",
        r"^/godmode$",
        r"^godmode$",
        r"^god mode$",
        r"^god$",
    ]
    
    # Команды деактивации
    deactivate_patterns = [
        r"^отключи режим бога$",
        r"^выключи режим бога$",
        r"^локальный режим$",
        r"^/local$",
        r"^local$",
        r"^выход$",
        r"^выйди из режима бога$",
    ]
    
    for pattern in activate_patterns:
        if re.match(pattern, text_lower):
            return "activate"
    
    for pattern in deactivate_patterns:
        if re.match(pattern, text_lower):
            return "deactivate"
    
    return None

async def _old_call_chatgpt_oauth_DISABLED(messages: List[dict], system_prompt: str = "") -> dict:
    """
    Вызывает ChatGPT через OAuth (подписка Plus/Pro).
    
    Преимущества:
    - Бесплатно в рамках подписки ($20-200/мес)
    - 128K контекст (gpt-4o)
    - Автообновление токенов
    """
    global oauth_provider
    
    # Получаем access_token
    access_token = await oauth_provider.get_access_token()
    
    if not access_token:
        return {
            "choices": [{
                "message": {
                    "content": """❌ **God Mode недоступен: OAuth не настроен**

**Как настроить:**
1. На компьютере с браузером:
   ```
   npm install -g @openai/codex
   codex login
   ```
2. Залогиниться в ChatGPT через браузер
3. Скопировать токены на Jetson Thor:
   ```
   scp ~/.codex/auth.json agx-thor@192.168.1.12:~/.codex/
   ```
4. Готово! Токены автообновляются.

**Требуется:** ChatGPT Plus ($20/мес) или Pro ($200/мес)"""
                }
            }]
        }
    
    # Формируем messages для OpenAI
    openai_messages = []
    
    # System prompt
    if system_prompt:
        openai_messages.append({"role": "system", "content": system_prompt})
    else:
        openai_messages.append({
            "role": "system", 
            "content": """Ты — Animara, мощный AI-ассистент в режиме бога (God Mode).
Отвечай на русском языке.
У тебя огромный контекст (128K токенов) — используй его для глубокого анализа.
Ты можешь решать сложные задачи, писать код, анализировать и рассуждать.
Если нужно думать пошагово — думай пошагово."""
        })
    
    # User/Assistant messages
    for msg in messages:
        role = msg.get("role", "user")
        content = msg.get("content", "")
        
        if role == "system":
            continue
        elif role in ["user", "assistant"]:
            openai_messages.append({"role": role, "content": content})
    
    # Если нет сообщений, добавляем дефолтное
    if len(openai_messages) <= 1:
        openai_messages.append({"role": "user", "content": "Привет"})
    
    try:
        async with httpx.AsyncClient(timeout=180) as client:
            response = await client.post(
                CONFIG["godmode_api_url"],
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {access_token}"
                },
                json={
                    "model": CONFIG["godmode_model"],
                    "messages": openai_messages,
                    "max_tokens": CONFIG["godmode_max_tokens"],
                    "temperature": 0.7,
                }
            )
            
            if response.status_code == 401:
                # Токен истёк — пробуем обновить
                print("🔄 Токен истёк, обновляем...")
                await oauth_provider._refresh_token()
                new_token = await oauth_provider.get_access_token()
                
                if new_token:
                    # Повторяем запрос
                    response = await client.post(
                        CONFIG["godmode_api_url"],
                        headers={
                            "Content-Type": "application/json",
                            "Authorization": f"Bearer {new_token}"
                        },
                        json={
                            "model": CONFIG["godmode_model"],
                            "messages": openai_messages,
                            "max_tokens": CONFIG["godmode_max_tokens"],
                            "temperature": 0.7,
                        }
                    )
                
                if response.status_code == 401:
                    return {
                        "choices": [{
                            "message": {
                                "content": "❌ OAuth токен недействителен. Выполни `codex login` заново."
                            }
                        }]
                    }
            
            if response.status_code == 429:
                return {
                    "choices": [{
                        "message": {
                            "content": "❌ Превышен лимит запросов ChatGPT. Подожди немного (Plus: ~50 запросов/час)."
                        }
                    }]
                }
            
            if response.status_code != 200:
                error_text = response.text[:500]
                return {
                    "choices": [{
                        "message": {
                            "content": f"❌ ChatGPT ошибка {response.status_code}: {error_text}"
                        }
                    }]
                }
            
            result = response.json()
            
            # Извлекаем текст из ответа
            response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            
            # Статистика токенов
            usage = result.get("usage", {})
            
            return {
                "choices": [{
                    "message": {
                        "role": "assistant",
                        "content": f"⚡ {response_text}"  # Префикс для God Mode
                    }
                }],
                "model": CONFIG["godmode_model"],
                "godmode": True,
                "usage": usage
            }
            
    except httpx.TimeoutException:
        return {
            "choices": [{
                "message": {
                    "content": "❌ Таймаут ChatGPT. Модель долго думает — попробуй ещё раз или упрости запрос."
                }
            }]
        }
    except Exception as e:
        return {
            "choices": [{
                "message": {
                    "content": f"❌ God Mode ошибка: {str(e)}"
                }
            }]
        }

# ═══════════════════════════════════════════════════════════════
# TOOLS SYSTEM
# ═══════════════════════════════════════════════════════════════

class ToolsManager:
    """Менеджер инструментов (skills)"""
    
    def __init__(self, skills_path: str):
        self.skills_path = Path(skills_path)
        self.tools = {}
        self._load_tools()
    
    def _load_tools(self):
        """Загружает доступные tools из skills"""
        
        # Web Search
        self.tools["web_search"] = {
            "name": "web_search",
            "description": "Поиск информации в интернете через Brave Search API. Используй когда нужна актуальная информация, погода, новости, цены, контакты.",
            "parameters": {
                "query": "Поисковый запрос на русском или английском"
            },
            "execute": self._execute_web_search
        }
        
        # YouGile Tasks
        self.tools["yougile_tasks"] = {
            "name": "yougile_tasks",
            "description": "Получить список задач из YouGile. Используй когда спрашивают о задачах, планах, todo.",
            "parameters": {},
            "execute": self._execute_yougile_tasks
        }
        
        self.tools["yougile_find"] = {
            "name": "yougile_find",
            "description": "Найти конкретную задачу по названию в YouGile.",
            "parameters": {
                "search_term": "Часть названия задачи"
            },
            "execute": self._execute_yougile_find
        }
        
        # YouGile Create
        self.tools["yougile_create"] = {
            "name": "yougile_create",
            "description": "Создать новую задачу в YouGile. ОБЯЗАТЕЛЬНО используй этот инструмент когда просят добавить/создать задачу!",
            "parameters": {
                "title": "Название задачи",
                "description": "Описание задачи (опционально)"
            },
            "execute": self._execute_yougile_create
        }
        
        # System Check
        self.tools["system_check"] = {
            "name": "system_check",
            "description": "Проверить статус системы: Docker контейнеры, диск, память. Используй когда спрашивают о состоянии системы.",
            "parameters": {},
            "execute": self._execute_system_check
        }
        
        print(f"🔧 Loaded {len(self.tools)} tools: {list(self.tools.keys())}")
    
    async def _execute_web_search(self, params: dict) -> str:
        """Выполняет web_search"""
        query = params.get("query", "")
        if not query:
            return "❌ Пустой поисковый запрос"
        
        try:
            from skills.web_search.scripts.main import search
            result = search(query, count=5)
            return result
        except ImportError:
            return await self._web_search_direct(query)
        except Exception as e:
            return f"❌ Ошибка поиска: {e}"
    
    async def _web_search_direct(self, query: str) -> str:
        """Прямой вызов Brave API"""
        import requests
        api_key = "BSA1PthqtF-a8kZj7f_xNcLGBbMDfN3"
        
        try:
            response = requests.get(
                "https://api.search.brave.com/res/v1/web/search",
                headers={"Accept": "application/json", "X-Subscription-Token": api_key},
                params={"q": query, "count": 5},
                timeout=15
            )
            
            if response.status_code != 200:
                return f"❌ Ошибка API: {response.status_code}"
            
            results = response.json().get("web", {}).get("results", [])
            if not results:
                return f"🔍 По запросу «{query}» ничего не найдено"
            
            output = []
            for i, item in enumerate(results[:5], 1):
                title = item.get("title", "")
                desc = item.get("description", "")[:200]
                url = item.get("url", "")
                output.append(f"{i}. {title}\n   {desc}\n   🔗 {url}")
            
            return "\n\n".join(output)
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _execute_yougile_tasks(self, params: dict) -> str:
        """Получает список задач из YouGile"""
        try:
            from skills.yougile.scripts.main import get_tasks
            return get_tasks(limit=10)
        except ImportError:
            return await self._yougile_tasks_direct()
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _yougile_tasks_direct(self) -> str:
        """Прямой вызов YouGile API"""
        import requests
        token = "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
        
        try:
            response = requests.get(
                "https://ru.yougile.com/api-v2/tasks",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                timeout=15
            )
            
            if response.status_code != 200:
                return f"❌ Ошибка YouGile: {response.status_code}"
            
            tasks = response.json().get("content", [])
            active = [t for t in tasks[:15] if not t.get("deleted") and not t.get("completed")]
            
            if not active:
                return "📋 Нет активных задач"
            
            output = []
            for t in active[:10]:
                output.append(f"• {t.get('title', 'Без названия')}")
            
            return "📋 Задачи:\n" + "\n".join(output)
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _execute_yougile_find(self, params: dict) -> str:
        """Ищет задачу по названию"""
        search_term = params.get("search_term", "")
        if not search_term:
            return "❌ Не указано что искать"
        
        try:
            from skills.yougile.scripts.main import find_task
            result = find_task(search_term)
            if isinstance(result, dict):
                if "error" in result:
                    return f"❌ {result['error']}"
                return f"📋 Найдено: {result.get('title')}\nОписание: {result.get('description', 'нет')}"
            return str(result)
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _execute_yougile_create(self, params: dict) -> str:
        """Создаёт новую задачу в YouGile"""
        title = params.get("title", "")
        description = params.get("description", "")
        
        if not title:
            return "❌ Не указано название задачи"
        
        try:
            from skills.yougile.scripts.main import create_task, get_columns
            
            columns_result = get_columns()
            if isinstance(columns_result, str):
                import json as json_module
                columns = json_module.loads(columns_result)
            else:
                columns = columns_result
            
            if not columns:
                return "❌ Не найдены колонки в YouGile"
            
            column_id = columns[0].get("id")
            result = create_task(title=title, column_id=column_id, description=description)
            
            if "✅" in str(result) or "Создано" in str(result):
                return f"✅ Задача создана: {title}"
            return str(result)
        except ImportError:
            return await self._yougile_create_direct(title, description)
        except Exception as e:
            return f"❌ Ошибка создания задачи: {e}"
    
    async def _yougile_create_direct(self, title: str, description: str = "") -> str:
        """Прямое создание задачи через API"""
        import requests
        token = "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        
        try:
            boards_resp = requests.get("https://ru.yougile.com/api-v2/boards", headers=headers, timeout=10)
            boards = boards_resp.json().get("content", [])
            if not boards:
                return "❌ Нет досок в YouGile"
            
            cols_resp = requests.get(f"https://ru.yougile.com/api-v2/columns?boardId={boards[0]['id']}", headers=headers, timeout=10)
            columns = cols_resp.json().get("content", [])
            if not columns:
                return "❌ Нет колонок"
            
            payload = {"title": title, "columnId": columns[0]["id"]}
            if description:
                payload["description"] = description
            
            resp = requests.post("https://ru.yougile.com/api-v2/tasks", headers=headers, json=payload, timeout=10)
            
            if resp.status_code in [200, 201]:
                task_id = resp.json().get("id", "")
                return f"✅ Задача создана: {title} (ID: {task_id[:8]}...)"
            return f"❌ Ошибка: {resp.status_code} - {resp.text}"
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _execute_system_check(self, params: dict) -> str:
        """Проверяет статус системы"""
        import subprocess
        
        try:
            # Docker
            docker_result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            docker_status = docker_result.stdout.strip() if docker_result.returncode == 0 else "❌ Не удалось проверить"
            
            # Disk
            disk_result = subprocess.run(
                ["df", "-h", "/"],
                capture_output=True, text=True, timeout=5
            )
            if disk_result.returncode == 0:
                lines = disk_result.stdout.strip().split('\n')
                if len(lines) > 1:
                    parts = lines[1].split()
                    disk_status = f"{parts[3]} свободно из {parts[1]}"
                else:
                    disk_status = "?"
            else:
                disk_status = "?"
            
            return f"🖥️ Статус системы:\n\n📦 Docker:\n{docker_status}\n\n💾 Диск: {disk_status}"
        except Exception as e:
            return f"❌ Ошибка проверки: {e}"
    
    def get_tools_prompt(self) -> str:
        """Генерирует описание tools для system prompt"""
        lines = ["ДОСТУПНЫЕ ИНСТРУМЕНТЫ:"]
        for name, tool in self.tools.items():
            params_str = ", ".join(f"{k}: {v}" for k, v in tool["parameters"].items()) if tool["parameters"] else "нет параметров"
            lines.append(f"• {name}({params_str}) — {tool['description']}")
        
        lines.append("")
        lines.append("ФОРМАТ ВЫЗОВА ИНСТРУМЕНТА:")
        lines.append('<tool>{"name": "имя_инструмента", "params": {"ключ": "значение"}}</tool>')
        lines.append("")
        lines.append("ПРАВИЛА:")
        lines.append("- Используй инструменты ТОЛЬКО когда нужна актуальная информация")
        lines.append("- Для простых вопросов (приветствия, общие знания) отвечай сразу БЕЗ инструментов")
        lines.append("- После получения результата — дай краткий ответ пользователю")
        
        return "\n".join(lines)
    
    async def execute_tool(self, name: str, params: dict) -> str:
        """Выполняет инструмент"""
        if name not in self.tools:
            return f"❌ Неизвестный инструмент: {name}"
        
        tool = self.tools[name]
        try:
            result = await asyncio.wait_for(
                tool["execute"](params),
                timeout=CONFIG["tool_timeout"]
            )
            return result
        except asyncio.TimeoutError:
            return f"❌ Таймаут инструмента {name}"
        except Exception as e:
            return f"❌ Ошибка {name}: {e}"

tools_manager = None

def parse_tool_call(text: str) -> Optional[dict]:
    """Парсит вызов инструмента из текста LLM"""
    match = re.search(r'<tool>\s*(\{.*?\})\s*</tool>', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    return None

def needs_thinking(text: str) -> bool:
    """Определяет нужен ли thinking mode для запроса"""
    text_lower = text.lower()
    
    thinking_patterns = [
        r'\d+\s*[\+\-\*\/\%]\s*\d+',
        r'сколько будет',
        r'посчитай', r'вычисли', r'реши',
        r'задач[аи]', r'головоломк',
        r'волк.*коз.*капуст',
        r'перевез', r'переправ',
        r'напиши код', r'напиши функци', r'напиши программ',
        r'алгоритм', r'оптимизир',
        r'проанализируй', r'сравни', r'объясни почему',
        r'как работает', r'в чём разница',
        r'составь план', r'пошагов', r'step by step',
        r'подумай', r'рассуди', r'логически',
    ]
    
    for pattern in thinking_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False

# ═══════════════════════════════════════════════════════════════
# TOKEN COUNTER
# ═══════════════════════════════════════════════════════════════

def count_tokens(text: str) -> int:
    if not text:
        return 0
    return len(text) // 3

def count_messages_tokens(messages: List[dict]) -> int:
    total = 0
    for msg in messages:
        content = msg.get("content", "")
        total += count_tokens(content) + 4
    return total

# ═══════════════════════════════════════════════════════════════
# WORKSPACE LOADER
# ═══════════════════════════════════════════════════════════════

class WorkspaceLoader:
    def __init__(self, workspace_path: str):
        self.workspace = Path(workspace_path)
        self.memory_dir = self.workspace / "memory"
        self.cache = {}
        self.cache_time = 0
        self.cache_ttl = 60
    
    def _read_file(self, filename: str) -> Optional[str]:
        path = self.workspace / filename
        if path.exists():
            try:
                return path.read_text(encoding='utf-8')[:4000]
            except:
                return None
        return None
    
    def _read_memory_file(self, date_str: str) -> Optional[str]:
        path = self.memory_dir / f"{date_str}.md"
        if path.exists():
            try:
                return path.read_text(encoding='utf-8')[:2000]
            except:
                return None
        return None
    
    def get_context(self) -> str:
        now = time.time()
        if self.cache and (now - self.cache_time) < self.cache_ttl:
            return self.cache.get("context", "")
        
        parts = []
        for f in ["SOUL.md", "IDENTITY.md", "OWNER.md", "MEMORY.md", "TOOLS.md"]:
            content = self._read_file(f)
            if content:
                parts.append(content)
        
        today = datetime.now().strftime("%Y-%m-%d")
        yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
        
        for date in [today, yesterday]:
            content = self._read_memory_file(date)
            if content:
                parts.append(f"<!-- {date} -->\n{content}")
        
        context = "\n\n---\n\n".join(parts)
        self.cache = {"context": context}
        self.cache_time = now
        return context
    
    def write_memory(self, content: str) -> bool:
        today = datetime.now().strftime("%Y-%m-%d")
        path = self.memory_dir / f"{today}.md"
        
        try:
            self.memory_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%H:%M")
            
            if path.exists():
                existing = path.read_text(encoding='utf-8')
                new_content = f"{existing}\n\n## [{timestamp}] Memory Flush\n\n{content}"
            else:
                new_content = f"# 📅 {today}\n\n## [{timestamp}] Memory Flush\n\n{content}"
            
            path.write_text(new_content, encoding='utf-8')
            self.cache = {}
            print(f"💾 Memory flushed to {path}")
            return True
        except Exception as e:
            print(f"⚠️ Write memory error: {e}")
            return False
    
    def invalidate_cache(self):
        self.cache = {}

workspace = None

# ═══════════════════════════════════════════════════════════════
# BM25 INDEX
# ═══════════════════════════════════════════════════════════════

def tokenize_ru(text: str) -> List[str]:
    text = text.lower()
    text = re.sub(r'[^\w\s]', ' ', text)
    return [w for w in text.split() if len(w) > 2]

def build_bm25_index():
    global bm25_index, bm25_docs, bm25_ids
    print("📚 Building BM25 index...")
    
    docs, ids = [], []
    try:
        memories = milvus.query("memories", filter="is_active == true",
                                output_fields=["id", "content"], limit=1000)
        for m in memories:
            docs.append(m["content"])
            ids.append(("memories", m["id"]))
        
        convs = milvus.query("conversations", filter="",
                            output_fields=["id", "content"], limit=500)
        for c in convs:
            if c.get("content"):
                docs.append(c["content"])
                ids.append(("conversations", c["id"]))
        
        if docs:
            tokenized = [tokenize_ru(d) for d in docs]
            bm25_index = BM25Okapi(tokenized)
            bm25_docs = docs
            bm25_ids = ids
            print(f"✅ BM25 index: {len(docs)} documents")
    except Exception as e:
        print(f"⚠️ BM25 build error: {e}")

def bm25_search(query: str, top_k: int = 10) -> List[tuple]:
    if not bm25_index:
        return []
    tokens = tokenize_ru(query)
    if not tokens:
        return []
    scores = bm25_index.get_scores(tokens)
    results = []
    for idx in scores.argsort()[-top_k:][::-1]:
        if scores[idx] > 0:
            results.append((bm25_docs[idx], float(scores[idx]), bm25_ids[idx]))
    return results

# ═══════════════════════════════════════════════════════════════
# HYBRID SEARCH
# ═══════════════════════════════════════════════════════════════

def hybrid_search(query: str, person_id: str, top_k: int = 5) -> List[str]:
    results = {}
    
    try:
        vector = embedder.encode(query, normalize_embeddings=True).tolist()
        
        mem_results = milvus.search("memories", data=[vector],
            anns_field="content_embedding", limit=top_k * 2,
            output_fields=["content"],
            filter=f'person_id == "{person_id}" and is_active == true')
        
        for hits in mem_results:
            for hit in hits:
                content = hit["entity"].get("content", "")
                if content:
                    score = 1 - hit["distance"] if hit["distance"] < 1 else 0
                    results[content] = results.get(content, 0) + score * CONFIG["vector_weight"]
        
        conv_results = milvus.search("conversations", data=[vector],
            anns_field="content_embedding", limit=top_k * 2,
            output_fields=["content", "role"],
            filter=f'person_id == "{person_id}"')
        
        for hits in conv_results:
            for hit in hits:
                content = hit["entity"].get("content", "")
                if content:
                    score = 1 - hit["distance"] if hit["distance"] < 1 else 0
                    results[content] = results.get(content, 0) + score * CONFIG["vector_weight"] * 0.5
    except Exception as e:
        print(f"⚠️ Vector search error: {e}")
    
    # BM25 only for owner (security)
    if person_id == CONFIG["owner_person_id"]:
        bm25_results = bm25_search(query, top_k * 2)
    else:
        bm25_results = []
    
    if bm25_results:
        max_bm25 = max(r[1] for r in bm25_results)
        for content, score, _ in bm25_results:
            normalized = score / max_bm25 if max_bm25 > 0 else 0
            results[content] = results.get(content, 0) + normalized * CONFIG["bm25_weight"]
    
    sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
    return [content for content, score in sorted_results[:top_k]]

# ═══════════════════════════════════════════════════════════════
# PROFILE CACHE
# ═══════════════════════════════════════════════════════════════

class ProfileCache:
    def __init__(self):
        self.profiles: Dict[str, dict] = {}
        self.timestamps: Dict[str, float] = {}
    
    def get(self, person_id: str) -> Optional[str]:
        if person_id in self.profiles:
            if time.time() - self.timestamps.get(person_id, 0) < CONFIG["profile_cache_ttl"]:
                return self.profiles[person_id]["text"]
        return None
    
    def set(self, person_id: str, profile_text: str):
        self.profiles[person_id] = {"text": profile_text}
        self.timestamps[person_id] = time.time()
    
    def invalidate(self, person_id: str):
        self.profiles.pop(person_id, None)
        self.timestamps.pop(person_id, None)

profile_cache = ProfileCache()

# ═══════════════════════════════════════════════════════════════
# SESSION
# ═══════════════════════════════════════════════════════════════

class Session:
    def __init__(self, person_id: str):
        self.person_id = person_id
        self.session_id = f"s_{int(time.time())}_{hashlib.md5(os.urandom(4)).hexdigest()[:6]}"
        self.messages: List[dict] = []
        self.created_at = time.time()
        self.last_activity = time.time()
        self.facts_extracted: List[str] = []
        self.total_tokens = 0
        self.flush_done = False
        self.tool_calls = 0
        # GOD MODE
        self.god_mode = False
    
    def add_message(self, role: str, content: str, is_tool: bool = False):
        tokens = count_tokens(content)
        self.messages.append({
            "role": role, 
            "content": content, 
            "ts": time.time(), 
            "tokens": tokens,
            "is_tool": is_tool
        })
        self.last_activity = time.time()
        self.total_tokens += tokens
        
        self._prune_old_tool_results()
        
        if len(self.messages) > CONFIG["session_max_messages"]:
            removed = self.messages.pop(0)
            self.total_tokens -= removed.get("tokens", 0)
    
    def _prune_old_tool_results(self):
        assistant_count = 0
        prune_before_idx = -1
        
        for i in range(len(self.messages) - 1, -1, -1):
            if self.messages[i]["role"] == "assistant":
                assistant_count += 1
                if assistant_count >= CONFIG["prune_after_messages"]:
                    prune_before_idx = i
                    break
        
        if prune_before_idx <= 0:
            return
        
        tokens_saved = 0
        for i in range(prune_before_idx):
            msg = self.messages[i]
            if msg.get("is_tool") and len(msg["content"]) > CONFIG["prune_tool_max_chars"]:
                old_tokens = msg["tokens"]
                msg["content"] = msg["content"][:CONFIG["prune_tool_max_chars"]] + "... [pruned]"
                msg["tokens"] = count_tokens(msg["content"])
                tokens_saved += old_tokens - msg["tokens"]
        
        if tokens_saved > 0:
            self.total_tokens -= tokens_saved
    
    def get_context(self, max_messages: int = 6) -> str:
        if not self.messages:
            return ""
        lines = []
        for msg in self.messages[-max_messages:]:
            role = "Animara" if msg["role"] == "assistant" else "User"
            content = msg["content"][:300] + "..." if len(msg["content"]) > 300 else msg["content"]
            lines.append(f"{role}: {content}")
        return "\n".join(lines)
    
    def get_full_context(self) -> str:
        if not self.messages:
            return ""
        lines = []
        for msg in self.messages:
            role = "Animara" if msg["role"] == "assistant" else "User"
            lines.append(f"{role}: {msg['content']}")
        return "\n".join(lines)
    
    def is_expired(self) -> bool:
        return time.time() - self.last_activity > CONFIG["session_timeout"]
    
    def needs_flush(self) -> bool:
        return self.total_tokens > CONFIG["flush_threshold"]
    
    def compact(self):
        self.messages = self.messages[-3:]
        self.total_tokens = sum(m.get("tokens", 0) for m in self.messages)
        self.flush_count = getattr(self, "flush_count", 0) + 1
    
    def get_stats(self) -> dict:
        return {
            "session_id": self.session_id,
            "messages": len(self.messages),
            "total_tokens": self.total_tokens,
            "flush_threshold": CONFIG["flush_threshold"],
            "needs_flush": self.needs_flush(),
            "flush_done": self.flush_done,
            "tool_calls": self.tool_calls,
            "god_mode": self.god_mode
        }

class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
    
    def get_or_create(self, person_id: str) -> Session:
        if person_id in self.sessions:
            session = self.sessions[person_id]
            if not session.is_expired():
                return session
            asyncio.create_task(self._finalize_session(session))
        
        session = Session(person_id)
        self.sessions[person_id] = session
        print(f"📝 New session: {session.session_id}")
        return session
    
    async def _finalize_session(self, session: Session):
        if len(session.messages) < 3:
            return
        try:
            context = session.get_context(10)
            prompt = f"Кратко резюмируй диалог (1-2 предложения):\n{context}\nРезюме:"
            
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post(f"{CONFIG['llm_api']}/v1/chat/completions",
                    json={"model": CONFIG["llm_model"], "messages": [{"role": "user", "content": prompt}],
                          "max_tokens": 1500, "chat_template_kwargs": {"enable_thinking": False}})
                summary = resp.json()["choices"][0]["message"]["content"]
            
            workspace.write_memory(f"Сессия завершена: {summary}")
        except Exception as e:
            print(f"⚠️ Summarize error: {e}")
    
    async def memory_flush(self, session: Session) -> bool:
        print(f"🧠 Memory Flush triggered! Tokens: {session.total_tokens}")
        
        context = session.get_full_context()
        
        flush_prompt = f"""Сессия близка к лимиту памяти. Выдели ТОЛЬКО важные факты.

ДИАЛОГ:
{context}

ВАЖНЫЕ ФАКТЫ (3-7 пунктов или НЕТ_ВАЖНОГО):"""

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(f"{CONFIG['llm_api']}/v1/chat/completions",
                    json={"model": CONFIG["llm_model"], "messages": [{"role": "user", "content": flush_prompt}],
                          "max_tokens": 1500, "temperature": 0.3,
                          "chat_template_kwargs": {"enable_thinking": False}})
                result = resp.json()["choices"][0]["message"]["content"]
            
            if "НЕТ_ВАЖНОГО" not in result and len(result) > 20:
                workspace.write_memory(result)
                
                for line in result.split("\n"):
                    line = line.strip()
                    if line and len(line) > 10 and not line.startswith("#"):
                        try:
                            vector = embedder.encode(line, normalize_embeddings=True).tolist()
                            milvus.insert("memories", [{
                                "person_id": session.person_id, "memory_type": "flush",
                                "content": line[:500], "content_embedding": vector,
                                "confidence": 0.7, "source_session_id": session.session_id,
                                "is_active": True, "superseded_by": 0,
                                "validation_count": 1, "created_at": int(time.time()),
                                "updated_at": int(time.time())
                            }])
                        except:
                            pass
            
            session.compact()
            return True
            
        except Exception as e:
            print(f"⚠️ Memory Flush error: {e}")
            return False
    
    def end_session(self, person_id: str):
        if person_id in self.sessions:
            session = self.sessions.pop(person_id)
            asyncio.create_task(self._finalize_session(session))

session_manager = SessionManager()

# ═══════════════════════════════════════════════════════════════
# FACT EXTRACTION
# ═══════════════════════════════════════════════════════════════

def extract_and_save_facts(text: str, person_id: str, session: Session):
    patterns = [
        (r"меня зовут\s+([А-Яа-яA-Za-z]+)", "fact", "Пользователя зовут {0}"),
        (r"я живу\s+(?:в|на)\s+(.+?)(?:\.|,|$)", "fact", "Пользователь живёт в {0}"),
        (r"я работаю\s+(.+?)(?:\.|,|$)", "fact", "Пользователь работает {0}"),
        (r"я люблю\s+(.+?)(?:\.|,|$)", "preference", "Пользователь любит {0}"),
        (r"мне нравится\s+(.+?)(?:\.|,|$)", "preference", "Пользователю нравится {0}"),
        (r"мой проект\s+(.+?)(?:\.|,|$)", "project", "Проект пользователя: {0}"),
        (r"я занимаюсь\s+(.+?)(?:\.|,|!|$)", "hobby", "Пользователь занимается {0}"),
        (r"я увлекаюсь\s+(.+?)(?:\.|,|$)", "hobby", "Пользователь увлекается {0}"),
        (r"я умею\s+(.+?)(?:\.|,|$)", "skill", "Пользователь умеет {0}"),
        (r"я хочу\s+(.+?)(?:\.|,|$)", "plan", "Пользователь хочет {0}"),
        (r"я планирую\s+(.+?)(?:\.|,|$)", "plan", "Пользователь планирует {0}"),
    ]
    
    for pattern, mem_type, template in patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            content = template.format(match.group(1).strip())
            if content in session.facts_extracted:
                continue
            try:
                vector = embedder.encode(content, normalize_embeddings=True).tolist()
                milvus.insert("memories", [{
                    "person_id": person_id, "memory_type": mem_type,
                    "content": content, "content_embedding": vector,
                    "confidence": 0.8, "source_session_id": session.session_id,
                    "is_active": True, "superseded_by": 0,
                    "validation_count": 1, "created_at": int(time.time()),
                    "updated_at": int(time.time())
                }])
                session.facts_extracted.append(content)
                profile_cache.invalidate(person_id)
                print(f"💾 New fact: {content}")
            except Exception as e:
                print(f"⚠️ Save fact error: {e}")

# ═══════════════════════════════════════════════════════════════
# FASTAPI
# ═══════════════════════════════════════════════════════════════

def init_services():
    global embedder, milvus, workspace, tools_manager, oauth_provider
    print(f"🚀 Loading ANIMARA RAG Proxy v{CONFIG['version']}...")
    print(f"   🧠 God Mode: ChatGPT via OAuth ({CONFIG['godmode_model']})")
    
    # Init OAuth Provider
    oauth_provider = ChatGPTAuthProvider()
    oauth_status = oauth_provider.get_status()
    if oauth_status["configured"]:
        print(f"   ✅ OAuth: настроен, expires in {oauth_status['expires_in_human']}")
    else:
        print(f"   ⚠️ OAuth: не настроен. Выполни: codex login")
    
    embedder = SentenceTransformer(CONFIG["embedding_model"], trust_remote_code=True)
    print("✅ Embedder ready")
    
    milvus = MilvusClient(CONFIG["milvus_uri"])
    print(f"✅ Milvus ready: {milvus.list_collections()}")
    
    workspace = WorkspaceLoader(CONFIG["workspace_path"])
    ws_ctx = workspace.get_context()
    print(f"✅ Workspace ready: {len(ws_ctx)} chars")
    
    tools_manager = ToolsManager(CONFIG["skills_path"])
    
    build_bm25_index()
    
    print(f"🎉 RAG Proxy v{CONFIG['version']} ready!")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_services()
    yield
    for pid in list(session_manager.sessions.keys()):
        session_manager.end_session(pid)

app = FastAPI(lifespan=lifespan, title=f"Animara RAG Proxy v{CONFIG['version']}")

@app.get("/health")
async def health():
    oauth_status = oauth_provider.get_status() if oauth_provider else {"configured": False}
    
    return {
        "status": "ok",
        "version": CONFIG["version"],
        "features": ["workspace", "hybrid_search", "bm25", "memory_flush", "session_pruning", "TOOLS", "THINKING_MODE", "GOD_MODE_OAUTH"],
        "godmode": {
            "type": "OAuth (ChatGPT Plus/Pro)",
            "configured": oauth_status.get("configured", False),
            "model": CONFIG["godmode_model"],
            "context_window": f"{CONFIG['godmode_context'] // 1000}K tokens",
            "max_output": f"{CONFIG['godmode_max_tokens']} tokens",
            "oauth_status": oauth_status
        },
        "local_llm": {
            "model": CONFIG["llm_model"],
            "context_window": f"{CONFIG['llm_context'] // 1000}K tokens",
        },
        "tools": list(tools_manager.tools.keys()) if tools_manager else [],
        "active_sessions": len(session_manager.sessions),
        "bm25_docs": len(bm25_docs),
    }

@app.get("/v1/models")
async def list_models():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONFIG['llm_api']}/v1/models")
        return resp.json()

# ═══════════════════════════════════════════════════════════════
# MAIN ENDPOINT WITH TOOLS + GOD MODE (OAuth)
# ═══════════════════════════════════════════════════════════════

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    person_id = body.get("person_id", CONFIG["default_person_id"])
    enable_tools = body.get("enable_tools", True)
    
    session = session_manager.get_or_create(person_id)
    
    # Memory flush если нужно
    if session.needs_flush():
        await session_manager.memory_flush(session)
    
    # Получаем user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    print(f"\n📝 [{session.session_id}] {session.total_tokens} tok | god={session.god_mode} | {user_message[:50]}...")
    
    # ═══════════════════════════════════════════════════════════════
    # ПРОВЕРКА КОМАНД GOD MODE
    # ═══════════════════════════════════════════════════════════════
    
    godmode_cmd = check_godmode_command(user_message)
    
    if godmode_cmd == "activate":
        # Только owner может включить God Mode
        if person_id != CONFIG["owner_person_id"]:
            return {
                "choices": [{"message": {"content": "❌ God Mode доступен только владельцу."}}],
                "animara_stats": {"session": session.get_stats(), "god_mode": False}
            }
        
        session.god_mode = True
        
        # Проверяем OAuth
        oauth_status = oauth_provider.get_status()
        if not oauth_status["configured"]:
            return {
                "choices": [{
                    "message": {
                        "content": f"""⚡ **Режим Бога активирован!**

⚠️ Но OAuth не настроен.

**Как настроить (один раз):**
1. На компьютере с браузером:
   ```
   npm install -g @openai/codex
   codex login
   ```
2. Залогиниться в ChatGPT через браузер
3. Скопировать на Jetson:
   ```
   scp ~/.codex/auth.json agx-thor@192.168.1.12:~/.codex/
   ```

**Требуется:** ChatGPT Plus ($20/мес) или Pro ($200/мес)

⚡ После настройки токены автообновляются!"""
                    }
                }],
                "animara_stats": {"session": session.get_stats(), "god_mode": True, "oauth_configured": False}
            }
        
        return {
            "choices": [{
                "message": {
                    "content": f"""⚡ **Режим Бога активирован!**

🧠 Модель: **{CONFIG['godmode_model']}**
📊 Контекст: **{CONFIG['godmode_context'] // 1000}K токенов**
🔐 OAuth: ✅ настроен (expires in {oauth_status['expires_in_human']})

Теперь ты работаешь с мощным мозгом ChatGPT.

Для возврата к локальной модели: **"Отключи режим бога"** или **/local**"""
                }
            }],
            "animara_stats": {"session": session.get_stats(), "god_mode": True}
        }
    
    if godmode_cmd == "deactivate":
        session.god_mode = False
        return {
            "choices": [{
                "message": {
                    "content": f"""✅ **Локальный режим активирован!**

🧠 Модель: **{CONFIG['llm_model']}** (локальный)
📊 Контекст: **{CONFIG['llm_context'] // 1000}K токенов**
💰 Стоимость: **$0** (всё на твоём железе)

Для включения God Mode: **"Активируй режим бога"** или **/god**"""
                }
            }],
            "animara_stats": {"session": session.get_stats(), "god_mode": False}
        }
    
    # ═══════════════════════════════════════════════════════════════
    # GOD MODE — ChatGPT через OAuth
    # ═══════════════════════════════════════════════════════════════
    
    if session.god_mode:
        # В God Mode используем ChatGPT
        workspace_ctx = workspace.get_context() if person_id == CONFIG["owner_person_id"] else ""
        
        # Формируем system prompt для ChatGPT
        system_prompt = f"""Ты — Animara, персональный AI-ассистент в режиме бога (God Mode).

{workspace_ctx}

ИНСТРУКЦИИ:
- Отвечай на русском языке
- У тебя огромный контекст ({CONFIG['godmode_context'] // 1000}K токенов) — используй его
- Ты можешь решать сложные задачи, писать код, анализировать
- Если нужно думать пошагово — думай пошагово
- Будь полезным и дружелюбным"""

        # Добавляем контекст сессии
        session_ctx = session.get_context(10)
        if session_ctx:
            system_prompt += f"\n\nНЕДАВНИЙ ДИАЛОГ:\n{session_ctx}"
        
        # Сохраняем user message в сессию
        if user_message:
            session.add_message("user", user_message)
        
        # Вызываем ChatGPT через OAuth
        result = await call_chatgpt_codex(messages, system_prompt)
        
        # Сохраняем ответ в сессию
        response_text = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        if response_text:
            session.add_message("assistant", response_text)
        
        result["animara_stats"] = {
            "session": session.get_stats(),
            "god_mode": True,
            "model": CONFIG["godmode_model"],
            "context_window": f"{CONFIG['godmode_context'] // 1000}K"
        }
        
        return result
    
    # ═══════════════════════════════════════════════════════════════
    # ОБЫЧНЫЙ РЕЖИМ (Локальный Qwen3)
    # ═══════════════════════════════════════════════════════════════
    
    # === WORKSPACE ===
    if person_id != CONFIG["owner_person_id"]:
        workspace_ctx = "Ты — Animara, AI-ассистент. Представься и спроси чем помочь."
    else:
        workspace_ctx = workspace.get_context()
    
    # === HYBRID SEARCH ===
    rag_context = ""
    if user_message and ("?" in user_message or any(w in user_message.lower() 
        for w in ["что", "как", "где", "когда", "помнишь", "знаешь", "расскажи"])):
        relevant = hybrid_search(user_message, person_id, CONFIG["search_top_k"])
        if relevant:
            rag_context = "\n\nРЕЛЕВАНТНОЕ ИЗ ПАМЯТИ:\n" + "\n".join(f"• {r[:200]}" for r in relevant)
    
    # === SESSION CONTEXT ===
    session_ctx = session.get_context(6)
    
    # === TOOLS PROMPT ===
    tools_prompt = ""
    if enable_tools and tools_manager and person_id == CONFIG["owner_person_id"]:
        tools_prompt = "\n\n" + tools_manager.get_tools_prompt()
    
    # === THINKING MODE ===
    use_thinking = needs_thinking(user_message)
    if use_thinking:
        print(f"🧠 Thinking mode: ON")
    
    # === SYSTEM PROMPT ===
    system_content = f"""{workspace_ctx}
{rag_context}
{tools_prompt}

{"НЕДАВНИЙ ДИАЛОГ:" + chr(10) + session_ctx if session_ctx else ""}

КРИТИЧЕСКИЕ ПРАВИЛА:
1. НИКОГДА не говори что сделал действие, если не вызвал инструмент!
2. Для создания задачи — ОБЯЗАТЕЛЬНО вызови yougile_create
3. Для поиска в интернете — ОБЯЗАТЕЛЬНО вызови web_search
4. Если не можешь что-то сделать — честно скажи "У меня нет такого инструмента"
5. НЕ ГАЛЛЮЦИНИРУЙ! Не выдумывай данные!

ИНСТРУКЦИИ:
- Простые вопросы → краткий ответ (1-3 предложения)
- Актуальная информация (погода, новости, цены) → web_search
- Создать/добавить задачу → yougile_create
- Список задач → yougile_tasks
- Логика, математика, код → думай пошагово

💡 Для сложных задач скажи "Активируй режим бога" — получишь 128K контекст!"""

    # Сохраняем в сессию
    if user_message:
        session.add_message("user", user_message)
        asyncio.create_task(asyncio.to_thread(extract_and_save_facts, user_message, person_id, session))
    
    # === ReAct LOOP ===
    llm_messages = [{"role": "system", "content": system_content}] + messages
    
    for iteration in range(CONFIG["max_tool_iterations"]):
        llm_body = {
            "model": body.get("model", CONFIG["llm_model"]),
            "messages": llm_messages,
            "max_tokens": body.get("max_tokens", CONFIG["llm_max_tokens"]),
            "temperature": body.get("temperature", 0.7),
            "chat_template_kwargs": {"enable_thinking": use_thinking}
        }
        
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{CONFIG['llm_api']}/v1/chat/completions", json=llm_body)
            result = resp.json()
        
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        # Проверяем на вызов инструмента
        tool_call = parse_tool_call(content)
        
        if tool_call and enable_tools and tools_manager:
            tool_name = tool_call.get("name", "")
            tool_params = tool_call.get("params", {})
            
            print(f"🔧 Tool call: {tool_name}({tool_params})")
            session.tool_calls += 1
            
            # Выполняем инструмент
            tool_result = await tools_manager.execute_tool(tool_name, tool_params)
            print(f"📤 Tool result: {tool_result[:100]}...")
            
            # Добавляем результат в контекст
            llm_messages.append({"role": "assistant", "content": content})
            llm_messages.append({"role": "user", "content": f"Результат {tool_name}:\n{tool_result}\n\nТеперь дай краткий ответ пользователю."})
            
            session.add_message("tool", tool_result, is_tool=True)
            
            continue
        else:
            # Нет вызова инструмента — финальный ответ
            content = re.sub(r'<tool>.*?</tool>', '', content, flags=re.DOTALL).strip()
            
            if content:
                session.add_message("assistant", content)
            
            result["choices"][0]["message"]["content"] = content
            result["animara_stats"] = {
                "session": session.get_stats(),
                "tools_used": session.tool_calls,
                "god_mode": False
            }
            
            return result
    
    # Достигнут лимит итераций
    return {
        "choices": [{"message": {"content": "⚠️ Превышен лимит итераций инструментов"}}],
        "animara_stats": {"session": session.get_stats(), "error": "max_iterations"}
    }

# ═══════════════════════════════════════════════════════════════
# GOD MODE ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/godmode")
async def godmode_status():
    """Статус God Mode"""
    oauth_status = oauth_provider.get_status() if oauth_provider else {"configured": False}
    
    active_sessions = []
    for pid, session in session_manager.sessions.items():
        if session.god_mode:
            active_sessions.append(pid)
    
    return {
        "type": "OAuth (ChatGPT Plus/Pro subscription)",
        "oauth_status": oauth_status,
        "model": CONFIG["godmode_model"],
        "context_window": f"{CONFIG['godmode_context'] // 1000}K tokens",
        "max_output_tokens": CONFIG["godmode_max_tokens"],
        "active_sessions": active_sessions,
        "setup_instructions": """
1. На компьютере с браузером:
   npm install -g @openai/codex
   codex login

2. Скопировать на Jetson Thor:
   scp ~/.codex/auth.json agx-thor@192.168.1.12:~/.codex/

3. Токены автообновляются!
"""
    }

@app.post("/godmode/model")
async def set_godmode_model(request: Request):
    """Сменить модель God Mode"""
    body = await request.json()
    model = body.get("model", "")
    
    valid_models = ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "o4-mini", "gpt-5.2-codex"]
    
    if model not in valid_models:
        return {"error": f"Invalid model. Choose from: {valid_models}"}
    
    CONFIG["godmode_model"] = model
    print(f"⚡ God Mode model changed to: {model}")
    
    return {"status": "ok", "model": model}

@app.post("/godmode/refresh")
async def refresh_oauth():
    """Принудительно обновить OAuth токен"""
    if oauth_provider:
        success = await oauth_provider._refresh_token()
        return {"status": "ok" if success else "error", "refreshed": success}
    return {"error": "OAuth not initialized"}

# ═══════════════════════════════════════════════════════════════
# ADDITIONAL ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.post("/session/{person_id}/end")
async def end_session(person_id: str):
    session_manager.end_session(person_id)
    return {"status": "ended"}

@app.post("/session/{person_id}/flush")
async def force_flush(person_id: str):
    if person_id in session_manager.sessions:
        session = session_manager.sessions[person_id]
        await session_manager.memory_flush(session)
        return {"status": "flushed", "tokens_after": session.total_tokens}
    return {"error": "no session"}

@app.get("/session/{person_id}")
async def get_session(person_id: str):
    if person_id in session_manager.sessions:
        s = session_manager.sessions[person_id]
        return {**s.get_stats(), "facts": s.facts_extracted}
    return {"error": "no session"}

@app.get("/workspace")
async def get_workspace():
    ctx = workspace.get_context()
    return {"chars": len(ctx), "tokens": count_tokens(ctx), "preview": ctx[:500]}

@app.get("/tools")
async def get_tools():
    if tools_manager:
        return {"tools": list(tools_manager.tools.keys())}
    return {"tools": []}

@app.post("/tools/{tool_name}")
async def execute_tool_direct(tool_name: str, request: Request):
    body = await request.json()
    params = body.get("params", {})
    if tools_manager:
        result = await tools_manager.execute_tool(tool_name, params)
        return {"result": result}
    return {"error": "tools not loaded"}

@app.post("/bm25/rebuild")
async def rebuild_bm25():
    build_bm25_index()
    return {"status": "ok", "docs": len(bm25_docs)}

@app.get("/search")
async def search(q: str, person_id: str = "owner_sergey"):
    results = hybrid_search(q, person_id, 5)
    return {"query": q, "results": results}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8015)
