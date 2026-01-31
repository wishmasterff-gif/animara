#!/usr/bin/env python3
"""
🚀 ANIMARA RAG PROXY v10.6 — GOD MODE ЧЕРЕЗ OPENAI SDK

КРИТИЧЕСКОЕ ИСПРАВЛЕНИЕ v10.6:
God Mode теперь использует OpenAI SDK с native function calling вместо Codex CLI.

БЫЛО (v10.5): Codex CLI через subprocess — не работает с tools
СТАЛО (v10.6): OpenAI SDK + native function calling — полная интеграция

Архитектура God Mode v10.6:
┌─────────────────────────────────────────────────────────────────┐
│                    ЗАПРОС                                       │
│                      │                                          │
│                      ▼                                          │
│    ┌─────────────────────────────────────────┐                 │
│    │ ОБЩАЯ ЛОГИКА (для обоих режимов)        │                 │
│    │ • Workspace injection                    │                 │
│    │ • Hybrid Search (RAG)                    │                 │
│    │ • Session context                        │                 │
│    └─────────────────────────────────────────┘                 │
│                      │                                          │
│         ┌───────────┴───────────┐                              │
│         ▼                       ▼                              │
│    ┌──────────┐          ┌───────────────────┐                │
│    │ ЛОКАЛЬНО │          │    GOD MODE       │                │
│    │  Qwen3   │          │   OpenAI SDK      │                │
│    │  :8010   │          │ + function calling│                │
│    │ <tool>   │          │ + native tools    │                │
│    └──────────┘          └───────────────────┘                │
│         │                       │                              │
│         └───────────┬───────────┘                              │
│                     ▼                                          │
│    ┌─────────────────────────────────────────┐                 │
│    │ ОБЩАЯ ПОСТОБРАБОТКА                      │                 │
│    │ • Execute tools locally                  │                 │
│    │ • Save to session                        │                 │
│    │ • Extract facts                          │                 │
│    └─────────────────────────────────────────┘                 │
└─────────────────────────────────────────────────────────────────┘
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
from datetime import datetime, timedelta
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from sentence_transformers import SentenceTransformer
from pymilvus import MilvusClient
from rank_bm25 import BM25Okapi

# OpenAI SDK для God Mode
try:
    from openai import OpenAI
    OPENAI_AVAILABLE = True
except ImportError:
    OPENAI_AVAILABLE = False
    print("⚠️ OpenAI SDK not installed. Run: pip install openai")

sys.path.insert(0, os.path.expanduser("~/animara"))

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "version": "10.6",
    
    # Local LLM (Qwen3)
    "llm_api": "http://127.0.0.1:8010",
    "llm_model": "qwen3",
    "llm_max_tokens": 2000,
    "llm_context": 32768,
    
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
    # GOD MODE — OpenAI SDK с native function calling
    # ═══════════════════════════════════════════════════════════════
    "openai_api_key": "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",
    "godmode_model": "gpt-4o-mini",  # Дешёвая модель для теста ($0.15/1M input, $0.60/1M output)
    "godmode_max_tokens": 2000,
    "godmode_timeout": 120,
}

# Global objects
embedder = None
milvus = None
bm25_index = None
bm25_docs = []
bm25_ids = []
openai_client = None

# ═══════════════════════════════════════════════════════════════
# GOD MODE — OPENAI SDK С FUNCTION CALLING
# ═══════════════════════════════════════════════════════════════

# Определение tools в формате OpenAI
OPENAI_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Поиск информации в интернете через Brave Search API. Используй когда нужна актуальная информация: погода, новости, цены, контакты, события.",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Поисковый запрос на русском или английском"
                    }
                },
                "required": ["query"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_tasks",
            "description": "Получить список активных задач из YouGile. Используй когда спрашивают о задачах, делах, todo.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_find",
            "description": "Найти конкретную задачу по названию в YouGile.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Часть названия задачи для поиска"
                    }
                },
                "required": ["search_term"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_create",
            "description": "Создать новую задачу в YouGile. ОБЯЗАТЕЛЬНО используй когда просят добавить, создать, записать задачу.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название задачи"
                    },
                    "description": {
                        "type": "string",
                        "description": "Описание задачи (опционально)"
                    }
                },
                "required": ["title"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "system_check",
            "description": "Проверить статус системы: Docker контейнеры, диск, память.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    }
]


def check_godmode_command(text: str) -> Optional[str]:
    """
    Проверяет является ли сообщение командой God Mode.
    Returns: "activate", "deactivate", или None
    """
    text_lower = text.lower().strip()
    
    activate_patterns = [
        r"^активируй режим бога$",
        r"^режим бога$",
        r"^включи режим бога$",
        r"^включи бога$",
        r"^/god$",
        r"^/godmode$",
        r"^godmode$",
        r"^god mode$",
        r"^god$",
    ]
    
    deactivate_patterns = [
        r"^отключи режим бога$",
        r"^выключи режим бога$",
        r"^выключи бога$",
        r"^отключи бога$",
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


async def call_godmode_llm(
    messages: List[dict], 
    system_prompt: str,
    tools_manager: "ToolsManager"
) -> dict:
    """
    Вызывает OpenAI API с native function calling.
    
    Принимает ГОТОВЫЙ system_prompt (уже с Workspace + RAG + Session).
    Обрабатывает tool_calls и выполняет tools локально.
    Возвращает финальный ответ.
    """
    global openai_client
    
    if not OPENAI_AVAILABLE:
        return {
            "choices": [{
                "message": {
                    "content": "❌ OpenAI SDK не установлен. Выполни: `pip install openai`"
                }
            }],
            "error": "openai_not_installed"
        }
    
    if not openai_client:
        return {
            "choices": [{
                "message": {
                    "content": "❌ OpenAI клиент не инициализирован. Проверь API ключ."
                }
            }],
            "error": "client_not_initialized"
        }
    
    try:
        # Формируем messages для OpenAI
        openai_messages = [{"role": "system", "content": system_prompt}]
        
        # Добавляем историю (только user и assistant)
        for msg in messages:
            role = msg.get("role", "user")
            content = msg.get("content", "")
            if role in ["user", "assistant"] and content:
                openai_messages.append({"role": role, "content": content})
        
        print(f"⚡ Calling OpenAI ({CONFIG['godmode_model']})...")
        print(f"   Messages: {len(openai_messages)}, System prompt: {len(system_prompt)} chars")
        
        # ReAct loop для God Mode
        for iteration in range(CONFIG["max_tool_iterations"]):
            print(f"⚡ God Mode iteration {iteration + 1}")
            
            # Вызов OpenAI с tools
            response = await asyncio.to_thread(
                openai_client.chat.completions.create,
                model=CONFIG["godmode_model"],
                messages=openai_messages,
                tools=OPENAI_TOOLS,
                tool_choice="auto",
                max_tokens=CONFIG["godmode_max_tokens"],
                temperature=0.7,
            )
            
            assistant_message = response.choices[0].message
            
            # Проверяем на tool calls
            if assistant_message.tool_calls:
                # Обрабатываем каждый tool call
                tool_results = []
                
                for tool_call in assistant_message.tool_calls:
                    tool_name = tool_call.function.name
                    try:
                        tool_args = json.loads(tool_call.function.arguments)
                    except json.JSONDecodeError:
                        tool_args = {}
                    
                    print(f"🔧 Tool call: {tool_name}({tool_args})")
                    
                    # Выполняем tool локально
                    if tools_manager:
                        tool_result = await tools_manager.execute_tool(tool_name, tool_args)
                    else:
                        tool_result = f"❌ Tools manager не инициализирован"
                    
                    print(f"📤 Tool result: {tool_result[:100]}...")
                    
                    tool_results.append({
                        "tool_call_id": tool_call.id,
                        "role": "tool",
                        "content": tool_result
                    })
                
                # Добавляем assistant message с tool_calls
                openai_messages.append({
                    "role": "assistant",
                    "content": assistant_message.content or "",
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments
                            }
                        }
                        for tc in assistant_message.tool_calls
                    ]
                })
                
                # Добавляем результаты tools
                for tr in tool_results:
                    openai_messages.append(tr)
                
                # Продолжаем loop для получения финального ответа
                continue
            
            else:
                # Нет tool calls — это финальный ответ
                final_content = assistant_message.content or ""
                
                return {
                    "choices": [{
                        "message": {
                            "role": "assistant",
                            "content": f"⚡ {final_content}"  # Префикс для God Mode
                        }
                    }],
                    "model": CONFIG["godmode_model"],
                    "god_mode": True,
                    "usage": {
                        "prompt_tokens": response.usage.prompt_tokens if response.usage else 0,
                        "completion_tokens": response.usage.completion_tokens if response.usage else 0,
                        "total_tokens": response.usage.total_tokens if response.usage else 0,
                    }
                }
        
        # Достигнут лимит итераций
        return {
            "choices": [{
                "message": {
                    "content": "⚠️ Превышен лимит итераций God Mode. Попробуй упростить запрос."
                }
            }],
            "error": "max_iterations"
        }
        
    except Exception as e:
        error_msg = str(e)
        print(f"⚠️ God Mode error: {error_msg}")
        
        # Проверяем типичные ошибки
        if "api_key" in error_msg.lower() or "authentication" in error_msg.lower():
            return {
                "choices": [{
                    "message": {
                        "content": "❌ Ошибка авторизации OpenAI. Проверь API ключ в CONFIG."
                    }
                }],
                "error": "auth_error"
            }
        
        if "rate_limit" in error_msg.lower():
            return {
                "choices": [{
                    "message": {
                        "content": "❌ Rate limit OpenAI. Подожди минуту и попробуй снова."
                    }
                }],
                "error": "rate_limit"
            }
        
        return {
            "choices": [{
                "message": {
                    "content": f"❌ God Mode ошибка: {error_msg[:200]}"
                }
            }],
            "error": str(e)
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
        """Загружает доступные tools"""
        
        self.tools["web_search"] = {
            "name": "web_search",
            "description": "Поиск информации в интернете через Brave Search API.",
            "parameters": {"query": "Поисковый запрос"},
            "execute": self._execute_web_search
        }
        
        self.tools["yougile_tasks"] = {
            "name": "yougile_tasks",
            "description": "Получить список задач из YouGile.",
            "parameters": {},
            "execute": self._execute_yougile_tasks
        }
        
        self.tools["yougile_find"] = {
            "name": "yougile_find",
            "description": "Найти задачу по названию в YouGile.",
            "parameters": {"search_term": "Часть названия"},
            "execute": self._execute_yougile_find
        }
        
        self.tools["yougile_create"] = {
            "name": "yougile_create",
            "description": "Создать новую задачу в YouGile.",
            "parameters": {"title": "Название", "description": "Описание (опционально)"},
            "execute": self._execute_yougile_create
        }
        
        self.tools["system_check"] = {
            "name": "system_check",
            "description": "Проверить статус системы.",
            "parameters": {},
            "execute": self._execute_system_check
        }
        
        print(f"🔧 Loaded {len(self.tools)} tools: {list(self.tools.keys())}")
    
    async def _execute_web_search(self, params: dict) -> str:
        """Web search через Brave API"""
        query = params.get("query", "")
        if not query:
            return "❌ Пустой поисковый запрос"
        
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
        """Список задач YouGile"""
        import requests
        token = "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
        
        try:
            response = requests.get(
                "https://ru.yougile.com/api-v2/tasks",
                headers={"Authorization": f"Bearer {token}"},
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
        """Поиск задачи YouGile"""
        import requests
        token = "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
        search = params.get("search_term", "").lower()
        
        if not search:
            return "❌ Укажи что искать"
        
        try:
            response = requests.get(
                "https://ru.yougile.com/api-v2/tasks",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )
            
            tasks = response.json().get("content", [])
            found = []
            
            for t in tasks:
                if t.get("deleted"):
                    continue
                if search in t.get("title", "").lower():
                    found.append(f"• {t.get('title')} (ID: {t.get('id')[:8]}...)")
            
            if not found:
                return f"🔍 Задача «{search}» не найдена"
            
            return "🔍 Найдено:\n" + "\n".join(found[:5])
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _execute_yougile_create(self, params: dict) -> str:
        """Создание задачи YouGile"""
        import requests
        token = "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
        
        title = params.get("title", "")
        description = params.get("description", "")
        
        if not title:
            return "❌ Укажи название задачи"
        
        try:
            # Получаем первую колонку
            boards_resp = requests.get(
                "https://ru.yougile.com/api-v2/boards",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )
            boards = boards_resp.json().get("content", [])
            
            if not boards:
                return "❌ Нет досок в YouGile"
            
            cols_resp = requests.get(
                f"https://ru.yougile.com/api-v2/columns?boardId={boards[0]['id']}",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15
            )
            columns = cols_resp.json().get("content", [])
            
            if not columns:
                return "❌ Нет колонок на доске"
            
            # Создаём задачу
            payload = {"title": title, "columnId": columns[0]["id"]}
            if description:
                payload["description"] = description
            
            create_resp = requests.post(
                "https://ru.yougile.com/api-v2/tasks",
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json=payload,
                timeout=15
            )
            
            if create_resp.status_code in [200, 201]:
                task_id = create_resp.json().get("id", "")[:8]
                return f"✅ Задача создана: «{title}» (ID: {task_id}...)"
            else:
                return f"❌ Ошибка создания: {create_resp.status_code}"
        except Exception as e:
            return f"❌ Ошибка: {e}"
    
    async def _execute_system_check(self, params: dict) -> str:
        """Проверка системы"""
        import subprocess
        
        output = ["🖥️ **Статус системы:**"]
        
        # Docker
        try:
            result = subprocess.run(
                ["docker", "ps", "--format", "{{.Names}}: {{.Status}}"],
                capture_output=True, text=True, timeout=10
            )
            containers = result.stdout.strip().split("\n")[:5]
            output.append("\n**Docker:**")
            for c in containers:
                if c:
                    output.append(f"  • {c}")
        except:
            output.append("  ⚠️ Docker недоступен")
        
        # Диск
        try:
            result = subprocess.run(
                ["df", "-h", "/media/agx-thor/SSD_AI"],
                capture_output=True, text=True, timeout=5
            )
            lines = result.stdout.strip().split("\n")
            if len(lines) > 1:
                parts = lines[1].split()
                output.append(f"\n**SSD:** {parts[2]} / {parts[1]} ({parts[4]} использовано)")
        except:
            output.append("\n**SSD:** ⚠️ не примонтирован")
        
        return "\n".join(output)
    
    def get_tools_prompt(self) -> str:
        """Генерирует промпт со списком инструментов для локального LLM"""
        lines = ["ДОСТУПНЫЕ ИНСТРУМЕНТЫ:"]
        lines.append('Чтобы вызвать инструмент, напиши: <tool>{"name": "имя", "params": {...}}</tool>')
        lines.append("")
        
        for name, tool in self.tools.items():
            params = ", ".join(f'{k}: "{v}"' for k, v in tool["parameters"].items())
            lines.append(f"• {name}({params}) — {tool['description']}")
        
        lines.append("")
        lines.append("ВАЖНО: После получения результата инструмента — дай КРАТКИЙ ответ пользователю!")
        
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
            return f"❌ Таймаут {name}"
        except Exception as e:
            return f"❌ Ошибка {name}: {e}"

tools_manager = None


def parse_tool_call(text: str) -> Optional[dict]:
    """
    Парсит вызов инструмента из текста локального LLM.
    Используется ТОЛЬКО для локального режима (Qwen3).
    God Mode использует native function calling.
    """
    # Формат 1: <tool>JSON</tool>
    match = re.search(r'<tool>\s*(\{.*?\})\s*</tool>', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except:
            pass
    
    # Формат 2: function_name() или function_name("param")
    tool_patterns = [
        (r'yougile_tasks\s*\(\s*\)', {"name": "yougile_tasks", "params": {}}),
        (r'yougile_find\s*\(\s*["\']([^"\']+)["\']\s*\)', lambda m: {"name": "yougile_find", "params": {"search_term": m.group(1)}}),
        (r'yougile_create\s*\(\s*["\']([^"\']+)["\']\s*\)', lambda m: {"name": "yougile_create", "params": {"title": m.group(1)}}),
        (r'web_search\s*\(\s*["\']([^"\']+)["\']\s*\)', lambda m: {"name": "web_search", "params": {"query": m.group(1)}}),
        (r'system_check\s*\(\s*\)', {"name": "system_check", "params": {}}),
    ]
    
    for pattern, result in tool_patterns:
        match = re.search(pattern, text)
        if match:
            if callable(result):
                return result(match)
            return result
    
    return None


def needs_thinking(text: str) -> bool:
    """Определяет нужен ли thinking mode для локального LLM"""
    text_lower = text.lower()
    
    patterns = [
        r'\d+\s*[\+\-\*\/\%]\s*\d+',
        r'сколько будет', r'посчитай', r'вычисли', r'реши',
        r'задач[аи]', r'головоломк', r'волк.*коз.*капуст',
        r'напиши код', r'напиши функци', r'алгоритм',
        r'проанализируй', r'сравни', r'объясни почему',
        r'составь план', r'пошагов',
    ]
    
    return any(re.search(p, text_lower) for p in patterns)


# ═══════════════════════════════════════════════════════════════
# TOKEN COUNTER
# ═══════════════════════════════════════════════════════════════

def count_tokens(text: str) -> int:
    return len(text) // 3 if text else 0


def count_messages_tokens(messages: List[dict]) -> int:
    return sum(count_tokens(m.get("content", "")) + 4 for m in messages)


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
            docs.append(m.get("content", ""))
            ids.append(f"mem_{m.get('id')}")
    except Exception as e:
        print(f"⚠️ BM25 memories error: {e}")
    
    try:
        convs = milvus.query("conversations", filter="",
                             output_fields=["id", "content"], limit=500)
        for c in convs:
            docs.append(c.get("content", ""))
            ids.append(f"conv_{c.get('id')}")
    except Exception as e:
        print(f"⚠️ BM25 conversations error: {e}")
    
    if docs:
        tokenized = [tokenize_ru(d) for d in docs]
        bm25_index = BM25Okapi(tokenized)
        bm25_docs = docs
        bm25_ids = ids
        print(f"📚 BM25 index: {len(docs)} documents")
    else:
        bm25_index = None
        bm25_docs = []
        bm25_ids = []
        print("⚠️ BM25 index empty")


def bm25_search(query: str, top_k: int = 5) -> List[tuple]:
    global bm25_index, bm25_docs, bm25_ids
    
    if not bm25_index or not bm25_docs:
        return []
    
    tokens = tokenize_ru(query)
    if not tokens:
        return []
    
    scores = bm25_index.get_scores(tokens)
    top_indices = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:top_k]
    
    results = []
    for i in top_indices:
        if scores[i] > 0:
            results.append((bm25_docs[i], scores[i], bm25_ids[i]))
    
    return results


def hybrid_search(query: str, person_id: str, top_k: int = 5) -> List[str]:
    """Гибридный поиск: Vector + BM25"""
    global embedder, milvus
    
    results = {}
    
    # Vector search
    try:
        query_vector = embedder.encode([query])[0].tolist()
        
        # Memories
        mem_results = milvus.search(
            collection_name="memories",
            data=[query_vector],
            filter=f'is_active == true && person_id == "{person_id}"',
            limit=top_k,
            output_fields=["content"]
        )
        
        for hits in mem_results:
            for hit in hits:
                content = hit["entity"].get("content", "")
                if content:
                    score = 1 - hit["distance"] if hit["distance"] < 1 else 0
                    results[content] = results.get(content, 0) + score * CONFIG["vector_weight"]
        
        # Conversations
        conv_results = milvus.search(
            collection_name="conversations",
            data=[query_vector],
            filter=f'person_id == "{person_id}"',
            limit=top_k,
            output_fields=["content"]
        )
        
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
        if bm25_results:
            max_bm25 = max(r[1] for r in bm25_results)
            for content, score, _ in bm25_results:
                normalized = score / max_bm25 if max_bm25 > 0 else 0
                results[content] = results.get(content, 0) + normalized * CONFIG["bm25_weight"]
    
    sorted_results = sorted(results.items(), key=lambda x: x[1], reverse=True)
    return [content for content, score in sorted_results[:top_k]]


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
    
    def is_expired(self) -> bool:
        return time.time() - self.last_activity > CONFIG["session_timeout"]
    
    def needs_flush(self) -> bool:
        return self.total_tokens > CONFIG["flush_threshold"]
    
    def compact(self):
        self.messages = self.messages[-3:]
        self.total_tokens = sum(m.get("tokens", 0) for m in self.messages)
    
    def get_stats(self) -> dict:
        return {
            "session_id": self.session_id,
            "person_id": self.person_id,
            "messages": len(self.messages),
            "total_tokens": self.total_tokens,
            "flush_threshold": CONFIG["flush_threshold"],
            "needs_flush": self.needs_flush(),
            "flush_done": self.flush_done,
            "tool_calls": self.tool_calls,
            "god_mode": self.god_mode,
        }


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}
    
    def get_or_create(self, person_id: str) -> Session:
        if person_id in self.sessions:
            session = self.sessions[person_id]
            if session.is_expired():
                print(f"♻️ Session expired for {person_id}, creating new")
                session = Session(person_id)
                self.sessions[person_id] = session
            return session
        
        session = Session(person_id)
        self.sessions[person_id] = session
        print(f"🆕 New session for {person_id}: {session.session_id}")
        return session
    
    def end_session(self, person_id: str):
        if person_id in self.sessions:
            del self.sessions[person_id]
            print(f"🔚 Session ended for {person_id}")
    
    async def memory_flush(self, session: Session):
        """Сохраняет важные факты перед очисткой сессии"""
        if not session.messages:
            return
        
        context = session.get_context(10)
        
        flush_prompt = f"""Проанализируй диалог и выдели 3-7 ВАЖНЫХ фактов для долговременной памяти.

ДИАЛОГ:
{context}

Формат ответа — только маркированный список:
• Факт 1
• Факт 2
..."""
        
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{CONFIG['llm_api']}/v1/chat/completions",
                    json={
                        "model": CONFIG["llm_model"],
                        "messages": [{"role": "user", "content": flush_prompt}],
                        "max_tokens": 500,
                        "temperature": 0.3,
                    }
                )
                
                if resp.status_code == 200:
                    facts = resp.json().get("choices", [{}])[0].get("message", {}).get("content", "")
                    if facts:
                        workspace.write_memory(facts)
                        session.flush_done = True
                        session.compact()
                        print(f"💾 Memory flushed for {session.person_id}")
        except Exception as e:
            print(f"⚠️ Memory flush error: {e}")

session_manager = SessionManager()


# ═══════════════════════════════════════════════════════════════
# FACT EXTRACTION
# ═══════════════════════════════════════════════════════════════

FACT_PATTERNS = [
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


def extract_and_save_facts(text: str, person_id: str, session: Session):
    """Извлекает факты из текста и сохраняет в Milvus"""
    global embedder, milvus
    
    if not text or len(text) < 10:
        return
    
    text_lower = text.lower()
    
    for pattern, fact_type, template in FACT_PATTERNS:
        match = re.search(pattern, text_lower)
        if match:
            try:
                fact_text = template.format(*match.groups())
                
                # Проверяем дубликаты
                if fact_text in session.facts_extracted:
                    continue
                
                session.facts_extracted.append(fact_text)
                
                # Сохраняем в Milvus
                embedding = embedder.encode([fact_text])[0].tolist()
                
                milvus.insert(
                    collection_name="memories",
                    data=[{
                        "person_id": person_id,
                        "memory_type": fact_type,
                        "content": fact_text,
                        "content_embedding": embedding,
                        "confidence": 0.8,
                        "source_session_id": session.session_id,
                        "is_active": True,
                        "created_at": int(time.time()),
                        "updated_at": int(time.time()),
                    }]
                )
                
                print(f"💡 Fact saved: {fact_text[:50]}...")
            except Exception as e:
                print(f"⚠️ Fact save error: {e}")


# ═══════════════════════════════════════════════════════════════
# FASTAPI APP
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    global embedder, milvus, workspace, tools_manager, openai_client
    
    print(f"🚀 Starting Animara RAG Proxy v{CONFIG['version']}...")
    
    # Embedder
    print("📦 Loading BGE-M3...")
    embedder = SentenceTransformer(CONFIG["embedding_model"])
    print("✅ Embedder loaded")
    
    # Milvus
    print("🔌 Connecting to Milvus...")
    milvus = MilvusClient(uri=CONFIG["milvus_uri"])
    print(f"✅ Milvus connected: {milvus.list_collections()}")
    
    # BM25
    build_bm25_index()
    
    # Workspace
    workspace = WorkspaceLoader(CONFIG["workspace_path"])
    print(f"📁 Workspace loaded: {len(workspace.get_context())} chars")
    
    # Tools
    tools_manager = ToolsManager(CONFIG["skills_path"])
    
    # OpenAI client для God Mode
    if OPENAI_AVAILABLE and CONFIG.get("openai_api_key"):
        openai_client = OpenAI(api_key=CONFIG["openai_api_key"])
        print(f"⚡ OpenAI client initialized (model: {CONFIG['godmode_model']})")
    else:
        print("⚠️ OpenAI client NOT initialized (no SDK or API key)")
    
    print(f"✅ Animara RAG Proxy v{CONFIG['version']} ready!")
    
    yield
    
    print("👋 Shutting down...")

app = FastAPI(title="Animara RAG Proxy", version=CONFIG["version"], lifespan=lifespan)


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": CONFIG["version"],
        "features": ["workspace", "hybrid_search", "bm25", "memory_flush", 
                     "session_pruning", "TOOLS", "THINKING_MODE", "GOD_MODE_OPENAI_SDK"],
        "godmode": {
            "model": CONFIG["godmode_model"],
            "openai_available": OPENAI_AVAILABLE,
            "client_initialized": openai_client is not None,
        },
        "llm": CONFIG["llm_model"],
        "milvus_collections": milvus.list_collections() if milvus else [],
        "bm25_docs": len(bm25_docs),
        "active_sessions": len(session_manager.sessions),
    }


@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    """
    ═══════════════════════════════════════════════════════════════
    ГЛАВНЫЙ ENDPOINT — ЕДИНАЯ ЛОГИКА ДЛЯ ОБОИХ РЕЖИМОВ
    ═══════════════════════════════════════════════════════════════
    
    God Mode и локальный режим используют ОДИНАКОВУЮ логику:
    1. Workspace injection
    2. Hybrid Search (RAG)
    3. Session context
    
    Разница в LLM backend и формате tools:
    - Локальный: Qwen3 + <tool>JSON</tool>
    - God Mode: OpenAI SDK + native function calling
    """
    body = await request.json()
    
    messages = body.get("messages", [])
    person_id = body.get("person_id", CONFIG["default_person_id"])
    enable_tools = body.get("enable_tools", True)
    
    # Получаем сессию
    session = session_manager.get_or_create(person_id)
    
    # Получаем user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    # ═══════════════════════════════════════════════════════════════
    # GOD MODE COMMANDS (activate/deactivate)
    # ═══════════════════════════════════════════════════════════════
    
    godmode_cmd = check_godmode_command(user_message)
    
    if godmode_cmd == "activate":
        # Только owner может включить God Mode
        if person_id != CONFIG["owner_person_id"]:
            return {
                "choices": [{"message": {"content": "❌ God Mode доступен только владельцу."}}],
                "animara_stats": {"session": session.get_stats()}
            }
        
        session.god_mode = True
        
        return {
            "choices": [{
                "message": {
                    "content": f"""⚡ **Режим Бога активирован!**

🧠 **Модель:** {CONFIG['godmode_model']}
🔧 **OpenAI SDK:** {'✅ готов' if openai_client else '❌ не инициализирован'}
📊 **Контекст:** Полный (Workspace + RAG + Session)
🛠️ **Tools:** Native function calling

**Что изменилось:**
• LLM backend: Qwen3 → OpenAI ({CONFIG['godmode_model']})
• Tools: <tool>JSON</tool> → native function calling
• Всё остальное (память, контекст) — БЕЗ ИЗМЕНЕНИЙ

**Команды:**
• `/local` — вернуться к локальному Qwen3"""
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

🧠 **Модель:** {CONFIG['llm_model']} (локальный)
📊 **Контекст:** 32K токенов
💰 **Стоимость:** $0

**Команда:** "режим бога" или `/god` — включить снова"""
                }
            }],
            "animara_stats": {"session": session.get_stats(), "god_mode": False}
        }
    
    # ═══════════════════════════════════════════════════════════════
    # ОБЩАЯ ЛОГИКА (для обоих режимов!)
    # ═══════════════════════════════════════════════════════════════
    
    # === 1. WORKSPACE ===
    if person_id != CONFIG["owner_person_id"]:
        workspace_ctx = "Ты — Animara, AI-ассистент. Представься и спроси чем помочь."
    else:
        workspace_ctx = workspace.get_context()
    
    # === 2. HYBRID SEARCH (RAG) ===
    rag_context = ""
    if user_message and ("?" in user_message or any(w in user_message.lower() 
        for w in ["что", "как", "где", "когда", "помнишь", "знаешь", "расскажи"])):
        relevant = hybrid_search(user_message, person_id, CONFIG["search_top_k"])
        if relevant:
            rag_context = "\n\nРЕЛЕВАНТНОЕ ИЗ ПАМЯТИ:\n" + "\n".join(f"• {r[:200]}" for r in relevant)
    
    # === 3. SESSION CONTEXT ===
    session_ctx = session.get_context(6)
    
    # === 4. THINKING MODE (только для локального) ===
    use_thinking = needs_thinking(user_message)
    if use_thinking and not session.god_mode:
        print(f"🧠 Thinking mode: ON")
    
    # === 5. SYSTEM PROMPT ===
    mode_indicator = f"⚡ GOD MODE ({CONFIG['godmode_model']})" if session.god_mode else f"🏠 LOCAL ({CONFIG['llm_model']})"
    
    # Для God Mode НЕ добавляем tools prompt (используем native function calling)
    if session.god_mode:
        tools_prompt = ""
    else:
        # Для локального LLM — добавляем <tool> формат
        tools_prompt = ""
        if enable_tools and tools_manager and person_id == CONFIG["owner_person_id"]:
            tools_prompt = "\n\n" + tools_manager.get_tools_prompt()
    
    system_content = f"""{workspace_ctx}
{rag_context}
{tools_prompt}

{"НЕДАВНИЙ ДИАЛОГ:" + chr(10) + session_ctx if session_ctx else ""}

[{mode_indicator}]

КРИТИЧЕСКИЕ ПРАВИЛА:
1. НИКОГДА не говори что сделал действие, если не вызвал инструмент!
2. Для создания задачи — ОБЯЗАТЕЛЬНО вызови yougile_create
3. Для поиска в интернете — ОБЯЗАТЕЛЬНО вызови web_search
4. Если не можешь что-то сделать — честно скажи "У меня нет такого инструмента"
5. НЕ ГАЛЛЮЦИНИРУЙ! Не выдумывай данные!

ИНСТРУКЦИИ:
- Простые вопросы → краткий ответ (1-3 предложения)
- Актуальная информация (погода, новости, цены) → используй инструмент
- Создать/добавить задачу → используй инструмент
- Список задач → используй инструмент
- Логика, математика, код → думай пошагово"""

    # Сохраняем user message в сессию
    if user_message:
        session.add_message("user", user_message)
        asyncio.create_task(asyncio.to_thread(extract_and_save_facts, user_message, person_id, session))
    
    # ═══════════════════════════════════════════════════════════════
    # ВЫБОР LLM BACKEND
    # ═══════════════════════════════════════════════════════════════
    
    if session.god_mode:
        # ═══════════════════════════════════════════════════════════
        # GOD MODE: OpenAI SDK с native function calling
        # ═══════════════════════════════════════════════════════════
        print(f"⚡ God Mode request from {person_id}")
        
        result = await call_godmode_llm(messages, system_content, tools_manager)
        
        content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
        
        if content:
            session.add_message("assistant", content)
        
        result["animara_stats"] = {
            "session": session.get_stats(),
            "god_mode": True,
            "model": CONFIG["godmode_model"],
            "usage": result.get("usage", {}),
        }
        
        return result
    
    else:
        # ═══════════════════════════════════════════════════════════
        # ЛОКАЛЬНЫЙ: Qwen3 с <tool>JSON</tool> форматом
        # ═══════════════════════════════════════════════════════════
        
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
            
            # Проверка на tool call
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
                # Финальный ответ
                content = re.sub(r'<tool>.*?</tool>', '', content, flags=re.DOTALL).strip()
                
                if content:
                    session.add_message("assistant", content)
                
                result["choices"][0]["message"]["content"] = content
                result["animara_stats"] = {
                    "session": session.get_stats(),
                    "tools_used": session.tool_calls,
                    "god_mode": False,
                    "model": CONFIG["llm_model"],
                }
                
                return result
        
        # Лимит итераций
        return {
            "choices": [{"message": {"content": "⚠️ Превышен лимит итераций инструментов"}}],
            "animara_stats": {"session": session.get_stats(), "error": "max_iterations"}
        }


# ═══════════════════════════════════════════════════════════════
# ADDITIONAL ENDPOINTS
# ═══════════════════════════════════════════════════════════════

@app.get("/godmode")
async def godmode_status():
    """Статус God Mode"""
    active_sessions = [pid for pid, s in session_manager.sessions.items() if s.god_mode]
    
    return {
        "version": f"{CONFIG['version']} (OpenAI SDK)",
        "model": CONFIG["godmode_model"],
        "openai_available": OPENAI_AVAILABLE,
        "client_initialized": openai_client is not None,
        "active_god_sessions": active_sessions,
        "features": [
            "✅ Full Workspace injection",
            "✅ Full RAG (Hybrid Search)",
            "✅ Native function calling (OpenAI tools)",
            "✅ Full Session context",
        ],
        "difference_from_local": "LLM: Qwen3 → OpenAI, Tools: <tool> → native"
    }


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
