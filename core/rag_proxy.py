#!/usr/bin/env python3
"""
🚀 ANIMARA RAG PROXY v10.1 — WITH TOOLS + THINKING MODE

Новое в v10.1:
1. ✅ yougile_create — создание задач (НЕ галлюцинирует!)
2. ✅ THINKING MODE — автоматически для сложных задач
3. ✅ Честный промпт — "если не можешь — скажи честно"
4. ✅ Всё из v10: tools, ReAct, workspace, hybrid search
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

# Добавляем путь к skills
sys.path.insert(0, os.path.expanduser("~/animara"))

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "llm_api": "http://127.0.0.1:8010",
    "milvus_uri": "http://localhost:19530",
    "embedding_model": "/home/agx-thor/models/embeddings/bge-m3",
    "workspace_path": "/home/agx-thor/animara/workspace",
    "skills_path": "/home/agx-thor/animara/skills",
    "default_person_id": "owner_sergey",
    "profile_cache_ttl": 300,
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
}

embedder = None
milvus = None
bm25_index = None
bm25_docs = []
bm25_ids = []

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
        
        # YouGile Create - NEW!
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
            # Импортируем skill
            from skills.web_search.scripts.main import search
            result = search(query, count=5)
            return result
        except ImportError:
            # Fallback - прямой вызов API
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
            
            # Получаем первую колонку
            columns_result = get_columns()
            if isinstance(columns_result, str):
                import json as json_module
                columns = json_module.loads(columns_result)
            else:
                columns = columns_result
            
            if not columns:
                return "❌ Не найдены колонки в YouGile"
            
            column_id = columns[0].get("id")
            
            # Создаём задачу
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
            # Получаем колонки
            boards_resp = requests.get("https://ru.yougile.com/api-v2/boards", headers=headers, timeout=10)
            boards = boards_resp.json().get("content", [])
            if not boards:
                return "❌ Нет досок в YouGile"
            
            cols_resp = requests.get(f"https://ru.yougile.com/api-v2/columns?boardId={boards[0]['id']}", headers=headers, timeout=10)
            columns = cols_resp.json().get("content", [])
            if not columns:
                return "❌ Нет колонок"
            
            # Создаём задачу
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
        try:
            from skills.exec.scripts.main import run
            
            # Docker
            docker_result = run("docker ps --format '{{.Names}}: {{.Status}}'", timeout=10)
            docker_status = docker_result.get("stdout", "").strip() if docker_result.get("success") else "❌ Не удалось проверить"
            
            # Disk
            disk_result = run("df -h / | tail -1 | awk '{print $4 \" свободно из \" $2}'", timeout=5)
            disk_status = disk_result.get("stdout", "").strip() if disk_result.get("success") else "?"
            
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
    
    # Паттерны для thinking mode
    thinking_patterns = [
        # Математика
        r'\d+\s*[\+\-\*\/\%]\s*\d+',  # 5 + 3, 100 / 4
        r'сколько будет',
        r'посчитай', r'вычисли', r'реши',
        
        # Логические задачи
        r'задач[аи]', r'головоломк',
        r'волк.*коз.*капуст',  # классическая задача
        r'перевез', r'переправ',
        
        # Код и алгоритмы
        r'напиши код', r'напиши функци', r'напиши программ',
        r'алгоритм', r'оптимизир',
        
        # Анализ
        r'проанализируй', r'сравни', r'объясни почему',
        r'как работает', r'в чём разница',
        
        # Планирование
        r'составь план', r'пошагов', r'step by step',
        
        # Рассуждения
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
    
    # BM25 only for owner
    if person_id == "owner_sergey":
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
            "tool_calls": self.tool_calls
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
                    json={"model": "qwen3", "messages": [{"role": "user", "content": prompt}],
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
                    json={"model": "qwen3", "messages": [{"role": "user", "content": flush_prompt}],
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
    global embedder, milvus, workspace, tools_manager
    print("🚀 Loading RAG v10.0 (with TOOLS)...")
    
    embedder = SentenceTransformer(CONFIG["embedding_model"], trust_remote_code=True)
    print("✅ Embedder ready")
    
    milvus = MilvusClient(CONFIG["milvus_uri"])
    print(f"✅ Milvus ready: {milvus.list_collections()}")
    
    workspace = WorkspaceLoader(CONFIG["workspace_path"])
    ws_ctx = workspace.get_context()
    print(f"✅ Workspace ready: {len(ws_ctx)} chars")
    
    tools_manager = ToolsManager(CONFIG["skills_path"])
    
    build_bm25_index()
    
    print(f"🎉 RAG Proxy v10.0 ready!")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_services()
    yield
    for pid in list(session_manager.sessions.keys()):
        session_manager.end_session(pid)

app = FastAPI(lifespan=lifespan, title="Animara RAG Proxy v10.1")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "10.1",
        "features": ["workspace", "hybrid_search", "bm25", "memory_flush", "session_pruning", "TOOLS", "THINKING_MODE"],
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
# MAIN ENDPOINT WITH TOOLS
# ═══════════════════════════════════════════════════════════════

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    person_id = body.get("person_id", CONFIG["default_person_id"])
    enable_tools = body.get("enable_tools", True)  # NEW
    
    session = session_manager.get_or_create(person_id)
    
    if session.needs_flush():
        await session_manager.memory_flush(session)
    
    # Получаем user message
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    print(f"\n🔍 [{session.session_id}] {session.total_tokens} tok | {user_message[:50]}...")
    
    # === WORKSPACE ===
    if person_id != "owner_sergey":
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
    if enable_tools and tools_manager and person_id == "owner_sergey":
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
- Логика, математика, код → думай пошагово"""

    # Сохраняем в сессию
    if user_message:
        session.add_message("user", user_message)
        asyncio.create_task(asyncio.to_thread(extract_and_save_facts, user_message, person_id, session))
    
    # === ReAct LOOP ===
    llm_messages = [{"role": "system", "content": system_content}] + messages
    
    for iteration in range(CONFIG["max_tool_iterations"]):
        llm_body = {
            "model": body.get("model", "qwen3"),
            "messages": llm_messages,
            "max_tokens": body.get("max_tokens", 2000),
            "temperature": body.get("temperature", 0.7),
            "chat_template_kwargs": {"enable_thinking": use_thinking}  # Динамический thinking!
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
            
            continue  # Следующая итерация
        else:
            # Нет вызова инструмента — финальный ответ
            # Убираем теги tool если они остались
            content = re.sub(r'<tool>.*?</tool>', '', content, flags=re.DOTALL).strip()
            
            if content:
                session.add_message("assistant", content)
            
            result["choices"][0]["message"]["content"] = content
            result["animara_stats"] = {
                "session": session.get_stats(),
                "tools_used": session.tool_calls
            }
            
            return result
    
    # Достигнут лимит итераций
    return {
        "choices": [{"message": {"content": "⚠️ Превышен лимит итераций инструментов"}}],
        "animara_stats": {"session": session.get_stats(), "error": "max_iterations"}
    }

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
