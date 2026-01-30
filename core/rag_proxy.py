#!/usr/bin/env python3
"""
🚀 ANIMARA RAG PROXY v9.3

Новое в v9.1:
1. ✅ ТОКЕНЫ В ОТВЕТЕ — видно в каждом ответе
2. ✅ SESSION PRUNING — обрезка старых tool results
3. ✅ MEMORY FLUSH — автосохранение перед переполнением
4. ✅ Всё из v8: Workspace, Hybrid Search, BM25, Streaming
"""

import os
import re
import json
import time
import asyncio
import hashlib
from typing import Optional, Dict, List
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

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "llm_api": "http://127.0.0.1:8010",
    "milvus_uri": "http://localhost:19530",
    "embedding_model": "/home/agx-thor/models/embeddings/bge-m3",
    "workspace_path": "/home/agx-thor/animara/workspace",
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
    # Session Pruning (NEW!)
    "prune_after_messages": 3,      # Обрезать tool results старше N assistant-сообщений
    "prune_tool_max_chars": 200,    # Макс символов для старых tool results
}

embedder = None
milvus = None
bm25_index = None
bm25_docs = []
bm25_ids = []

# ═══════════════════════════════════════════════════════════════
# TOKEN COUNTER
# ═══════════════════════════════════════════════════════════════

def count_tokens(text: str) -> int:
    """Примерный подсчёт токенов (3 символа ≈ 1 токен для русского)"""
    if not text:
        return 0
    return len(text) // 3

def count_messages_tokens(messages: List[dict]) -> int:
    """Подсчёт токенов во всех сообщениях"""
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
    
    # v9.4: BM25 only for owner (security fix)
    if person_id == "owner_sergey":
        bm25_results = bm25_search(query, top_k * 2)
    else:
        bm25_results = []  # Friends use Vector only
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
# SESSION WITH MEMORY FLUSH + PRUNING
# ═══════════════════════════════════════════════════════════════

class Session:
    def __init__(self, person_id: str):
        self.person_id = person_id
        self.session_id = f"s_{int(time.time())}_{hashlib.md5(os.urandom(4)).hexdigest()[:6]}"
        self.messages: List[dict] = []  # Изменили на List для pruning
        self.created_at = time.time()
        self.last_activity = time.time()
        self.facts_extracted: List[str] = []
        self.total_tokens = 0
        self.flush_done = False
    
    def add_message(self, role: str, content: str, is_tool: bool = False):
        tokens = count_tokens(content)
        self.messages.append({
            "role": role, 
            "content": content, 
            "ts": time.time(), 
            "tokens": tokens,
            "is_tool": is_tool  # Помечаем tool results
        })
        self.last_activity = time.time()
        self.total_tokens += tokens
        
        # Автоматический pruning
        self._prune_old_tool_results()
        
        # Лимит сообщений
        if len(self.messages) > CONFIG["session_max_messages"]:
            removed = self.messages.pop(0)
            self.total_tokens -= removed.get("tokens", 0)
    
    def _prune_old_tool_results(self):
        """
        🔪 SESSION PRUNING
        Обрезает tool results старше N assistant-сообщений
        """
        # Считаем assistant сообщения с конца
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
        
        # Обрезаем tool results до prune_before_idx
        tokens_saved = 0
        for i in range(prune_before_idx):
            msg = self.messages[i]
            if msg.get("is_tool") and len(msg["content"]) > CONFIG["prune_tool_max_chars"]:
                old_tokens = msg["tokens"]
                # Обрезаем контент
                msg["content"] = msg["content"][:CONFIG["prune_tool_max_chars"]] + "... [pruned]"
                msg["tokens"] = count_tokens(msg["content"])
                tokens_saved += old_tokens - msg["tokens"]
        
        if tokens_saved > 0:
            self.total_tokens -= tokens_saved
            print(f"🔪 Pruned {tokens_saved} tokens from old tool results")
    
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
        # Оставляем только последние 3 сообщения
        self.messages = self.messages[-3:]
        self.total_tokens = sum(m.get("tokens", 0) for m in self.messages)
        # self.flush_done = True  # v9.2: allow multiple flushes
        self.flush_count = getattr(self, "flush_count", 0) + 1
        print(f"🗜️ Session compacted (flush #{self.flush_count}): {len(self.messages)} messages, {self.total_tokens} tokens")
    
    def get_stats(self) -> dict:
        """Статистика сессии для отображения"""
        return {
            "session_id": self.session_id,
            "messages": len(self.messages),
            "total_tokens": self.total_tokens,
            "flush_threshold": CONFIG["flush_threshold"],
            "needs_flush": self.needs_flush(),
            "flush_done": self.flush_done
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
        if False:  # v9.2: disabled, allow multiple flushes
            return False
        
        print(f"🧠 Memory Flush triggered! Tokens: {session.total_tokens}")
        
        context = session.get_full_context()
        
        flush_prompt = f"""Сессия близка к лимиту памяти. Выдели ТОЛЬКО важные факты, решения или задачи.

ДИАЛОГ:
{context}

ИНСТРУКЦИИ:
- Только ВАЖНОЕ (факты, решения, задачи)
- Игнорируй мелочи
- Формат: краткий список (3-7 пунктов)
- Если ничего важного: НЕТ_ВАЖНОГО

ВАЖНЫЕ ФАКТЫ:"""

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
                
                print(f"✅ Memory Flush complete")
            else:
                print(f"ℹ️ Memory Flush: nothing important")
            
            session.compact()
            return True
            
        except Exception as e:
            print(f"⚠️ Memory Flush error: {e}")
            session.flush_done = True
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
        # Имя
        (r"меня зовут\s+([А-Яа-яA-Za-z]+)", "fact", "Пользователя зовут {0}"),
        # Место жительства
        (r"я живу\s+(?:в|на)\s+(.+?)(?:\.|,|$)", "fact", "Пользователь живёт в {0}"),
        # Работа
        (r"я работаю\s+(.+?)(?:\.|,|$)", "fact", "Пользователь работает {0}"),
        # Предпочтения
        (r"я люблю\s+(.+?)(?:\.|,|$)", "preference", "Пользователь любит {0}"),
        (r"мне нравится\s+(.+?)(?:\.|,|$)", "preference", "Пользователю нравится {0}"),
        # Проекты
        (r"мой проект\s+(.+?)(?:\.|,|$)", "project", "Проект пользователя: {0}"),
        # === СПОРТ И ХОББИ ===
        (r"я занимаюсь\s+(.+?)(?:\.|,|!|$)", "hobby", "Пользователь занимается {0}"),
        (r"занимаюсь\s+(.+?)\s+уже", "hobby", "Пользователь занимается {0}"),
        (r"я увлекаюсь\s+(.+?)(?:\.|,|$)", "hobby", "Пользователь увлекается {0}"),
        # === НАВЫКИ ===
        (r"я умею\s+(.+?)(?:\.|,|$)", "skill", "Пользователь умеет {0}"),
        # === ПЛАНЫ ===
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
    global embedder, milvus, workspace
    print("🚀 Loading RAG v9.1 (with Pruning + Token Display)...")
    
    embedder = SentenceTransformer(CONFIG["embedding_model"], trust_remote_code=True)
    print("✅ Embedder ready")
    
    milvus = MilvusClient(CONFIG["milvus_uri"])
    print(f"✅ Milvus ready: {milvus.list_collections()}")
    
    workspace = WorkspaceLoader(CONFIG["workspace_path"])
    ws_ctx = workspace.get_context()
    print(f"✅ Workspace ready: {len(ws_ctx)} chars (~{len(ws_ctx)//4} tokens)")
    
    build_bm25_index()
    
    print(f"⚙️ Flush threshold: {CONFIG['flush_threshold']} tokens")
    print(f"⚙️ Prune after: {CONFIG['prune_after_messages']} assistant messages")

@asynccontextmanager
async def lifespan(app: FastAPI):
    init_services()
    print("🎉 RAG Proxy v9.1 ready on :8015!")
    yield
    for pid in list(session_manager.sessions.keys()):
        session_manager.end_session(pid)

app = FastAPI(lifespan=lifespan, title="Animara RAG Proxy v9.1")

@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "9.4",
        "features": ["workspace", "hybrid_search", "bm25", "memory_flush", "session_pruning", "token_display"],
        "active_sessions": len(session_manager.sessions),
        "bm25_docs": len(bm25_docs),
        "config": {
            "flush_threshold": CONFIG["flush_threshold"],
            "prune_after_messages": CONFIG["prune_after_messages"]
        }
    }

@app.get("/v1/models")
async def list_models():
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{CONFIG['llm_api']}/v1/models")
        return resp.json()

# ═══════════════════════════════════════════════════════════════
# MAIN ENDPOINT (с токенами в ответе!)
# ═══════════════════════════════════════════════════════════════

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    person_id = body.get("person_id", CONFIG["default_person_id"])
    show_stats = body.get("show_stats", True)  # NEW: показывать статистику
    
    session = session_manager.get_or_create(person_id)
    
    # === CHECK MEMORY FLUSH ===
    if session.needs_flush():
        await session_manager.memory_flush(session)
    
    # Последнее сообщение
    user_message = ""
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_message = msg.get("content", "")
            break
    
    # Логируем с токенами
    print(f"\n🔍 [{session.session_id}] 📊 {session.total_tokens}/{CONFIG['flush_threshold']} tok | {user_message[:50]}...")
    
    # === WORKSPACE CONTEXT ===
    # v9.2: Не показываем workspace незнакомцам
    if person_id != "owner_sergey":
        workspace_ctx = "Ты — Animara, AI-ассистент. Представься и спроси чем помочь."
        workspace_tokens = count_tokens(workspace_ctx)
    else:
        workspace_ctx = workspace.get_context()
        workspace_tokens = count_tokens(workspace_ctx)
    
    # === HYBRID SEARCH ===
    rag_context = ""
    rag_tokens = 0
    if user_message and ("?" in user_message or any(w in user_message.lower() 
        for w in ["что", "как", "где", "когда", "помнишь", "знаешь", "расскажи"])):
        relevant = hybrid_search(user_message, person_id, CONFIG["search_top_k"])
        if relevant:
            rag_context = "\n\nРЕЛЕВАНТНОЕ ИЗ ПАМЯТИ:\n" + "\n".join(f"• {r[:200]}" for r in relevant)
            rag_tokens = count_tokens(rag_context)
            print(f"📚 Found {len(relevant)} docs (+{rag_tokens} tok)")
    
    # === SESSION CONTEXT ===
    session_ctx = session.get_context(6)
    session_ctx_tokens = count_tokens(session_ctx)
    
    # === SYSTEM PROMPT ===
    system_content = f"""{workspace_ctx}
{rag_context}

{"НЕДАВНИЙ ДИАЛОГ:" + chr(10) + session_ctx if session_ctx else ""}

ИНСТРУКЦИИ:
- Отвечай кратко (1-3 предложения)
- Говори как друг
- Не упоминай память/систему
- Математику считай точно"""

    system_tokens = count_tokens(system_content)
    
    # Сохраняем в сессию
    if user_message:
        session.add_message("user", user_message)
        asyncio.create_task(asyncio.to_thread(extract_and_save_facts, user_message, person_id, session))
    
    # Запрос к LLM
    llm_messages = [{"role": "system", "content": system_content}] + messages
    llm_body = {**body, "messages": llm_messages, "chat_template_kwargs": {"enable_thinking": False}}
    
    # Убираем наши кастомные поля
    llm_body.pop("person_id", None)
    llm_body.pop("show_stats", None)
    
    if stream:
        async def generate():
            full_response = ""
            async with httpx.AsyncClient(timeout=120) as client:
                async with client.stream("POST", f"{CONFIG['llm_api']}/v1/chat/completions", json=llm_body) as resp:
                    async for chunk in resp.aiter_bytes():
                        yield chunk
                        try:
                            for line in chunk.decode().split("\n"):
                                if line.startswith("data: ") and "content" in line:
                                    data = json.loads(line[6:])
                                    delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                                    full_response += delta
                        except:
                            pass
            if full_response:
                session.add_message("assistant", full_response)
        return StreamingResponse(generate(), media_type="text/event-stream")
    else:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{CONFIG['llm_api']}/v1/chat/completions", json=llm_body)
            result = resp.json()
            
            content = result.get("choices", [{}])[0].get("message", {}).get("content", "")
            if content:
                session.add_message("assistant", content)
            
            # === ДОБАВЛЯЕМ СТАТИСТИКУ В ОТВЕТ ===
            if show_stats:
                result["animara_stats"] = {
                    "session": session.get_stats(),
                    "context_breakdown": {
                        "workspace_tokens": workspace_tokens,
                        "rag_tokens": rag_tokens,
                        "session_context_tokens": session_ctx_tokens,
                        "system_prompt_tokens": system_tokens,
                    },
                    "total_context_tokens": system_tokens + count_messages_tokens(messages)
                }
            
            return result

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
        session.flush_done = False
        await session_manager.memory_flush(session)
        return {"status": "flushed", "tokens_after": session.total_tokens}
    return {"error": "no session"}

@app.get("/session/{person_id}")
async def get_session(person_id: str):
    if person_id in session_manager.sessions:
        s = session_manager.sessions[person_id]
        return {
            **s.get_stats(),
            "facts": s.facts_extracted,
            "duration_min": (time.time() - s.created_at) / 60
        }
    return {"error": "no session"}

@app.get("/workspace")
async def get_workspace():
    ctx = workspace.get_context()
    return {"chars": len(ctx), "tokens": count_tokens(ctx), "preview": ctx[:500]}

@app.post("/workspace/write")
async def write_workspace(request: Request):
    body = await request.json()
    content = body.get("content", "")
    if workspace.write_memory(content):
        return {"status": "ok"}
    return {"status": "error"}

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
