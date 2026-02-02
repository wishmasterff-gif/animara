#!/usr/bin/env python3
"""
🤖 ANIMARA RAG PROXY v12.1 — Patched Edition

Версия: 12.1.0
Дата: 2026-02-02

Изменения по сравнению с v12.0:
- ✅ FIX #1: Graceful degradation — один сбойный MCP не роняет все tools
- ✅ FIX #2: Dynamic max_tokens — защита от context overflow (400 error)
- ✅ FIX #3: Убраны дубликаты сообщений в messages
- ✅ FIX #4: Think cleanup в _fallback_llm
- ✅ FIX #5: /health показывает статус каждого MCP сервера
- ✅ FIX #6: Подсчёт токенов для русского (//3 вместо //4)
- ✅ FIX #7: Осмысленный auto-flush (ключевые темы вместо "20 сообщений")
- ✅ FIX #8: person_id из extra_body
- ✅ FIX #9-10: Импорты на уровне модуля
- ✅ FIX #11: Один MilvusClient вместо двух
- ✅ FIX #12: lifespan вместо deprecated on_event

Запуск:
    python3 animara_rag_proxy_v12.py

API:
    POST /v1/chat/completions
    GET  /health
    GET  /session/{person_id}
    POST /session/{person_id}/flush
    POST /bm25/rebuild
"""

import os
import re
import json
import time
import hashlib
import logging
import requests  # FIX #10: импорт на уровне модуля
from datetime import datetime, timedelta
from pathlib import Path
from collections import deque
from contextlib import asynccontextmanager  # FIX #12
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any

# Web framework
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
import uvicorn

# Qwen-Agent
try:
    from qwen_agent.agents import Assistant
    from qwen_agent.llm import get_chat_model
    QWEN_AGENT_AVAILABLE = True
except ImportError:
    print("⚠️ Qwen-Agent not installed. Run: pip install qwen-agent[mcp]")
    QWEN_AGENT_AVAILABLE = False

# Milvus
from pymilvus import MilvusClient

# Embeddings
from FlagEmbedding import BGEM3FlagModel

# BM25
from rank_bm25 import BM25Okapi

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "llm_api": "http://localhost:8010/v1",
    "llm_model": "qwen3",
    "milvus_uri": "http://localhost:19530",
    "embedding_model": "/home/agx-thor/models/embeddings/bge-m3",
    "workspace_dir": "/home/agx-thor/animara/workspace",
    "mcp_config_path": "/home/agx-thor/animara/mcp_config.json",
    "session_timeout_minutes": 30,
    "session_max_messages": 20,
    "flush_threshold_tokens": 28000,
    "context_window": 32768,
    "rag_top_k": 5,
    "vector_weight": 0.7,
    "bm25_weight": 0.3,
    "host": "0.0.0.0",
    "port": 8015,
}

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('/home/agx-thor/animara/logs/rag_v12.log')
    ]
)
logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════
# TOKEN UTILITIES (FIX #2, #6)
# ═══════════════════════════════════════════════════════════════

def estimate_tokens(text: str) -> int:
    """Подсчёт токенов. //3 для русского текста (FIX #6)"""
    if not text:
        return 0
    return max(1, len(text) // 3)


def estimate_messages_tokens(messages: list) -> int:
    total = 0
    for msg in messages:
        content = msg.get('content', '')
        if isinstance(content, str):
            total += estimate_tokens(content)
        total += 4
    return total


def calculate_dynamic_max_tokens(messages: list, context_window: int = 32768,
                                  desired_max: int = 2048, reserve: int = 512) -> int:
    """FIX #2: input_tokens + max_tokens + reserve <= context_window"""
    input_tokens = estimate_messages_tokens(messages)
    available = context_window - input_tokens - reserve
    result = max(256, min(desired_max, available))
    if result < desired_max:
        logger.warning(f"⚠️ Dynamic max_tokens: {result} (input≈{input_tokens})")
    return result


def truncate_context_if_needed(system_prompt: str, messages: list,
                                 context_window: int = 32768,
                                 min_response_tokens: int = 768) -> tuple:
    """Обрезает контекст. Приоритет: RAG → history → system prompt."""
    total = estimate_tokens(system_prompt) + estimate_messages_tokens(messages)
    budget = context_window - min_response_tokens

    if total <= budget:
        return system_prompt, messages

    overflow = total - budget
    logger.warning(f"⚠️ Context overflow: ≈{total} > {budget}. Trimming ≈{overflow}...")

    # 1. Обрезать RAG
    rag_marker = "## Релевантная информация из памяти:"
    if rag_marker in system_prompt:
        parts = system_prompt.split(rag_marker, 1)
        if len(parts) == 2:
            next_section = re.search(r'\n## ', parts[1][1:])
            if next_section:
                rag_content = parts[1][:next_section.start() + 1]
                rest = parts[1][next_section.start() + 1:]
            else:
                rag_content = parts[1]
                rest = ""
            rag_tokens = estimate_tokens(rag_content)
            if rag_tokens > overflow:
                target = max(100, (rag_tokens - overflow) * 3)
                system_prompt = parts[0] + rag_marker + rag_content[:target] + "\n[...обрезано]\n" + rest
                logger.info(f"  Trimmed RAG: ≈{rag_tokens} → ≈{estimate_tokens(rag_content[:target])}")
                return system_prompt, messages
            else:
                system_prompt = parts[0] + rag_marker + "\nОбрезано.\n" + rest
                overflow -= rag_tokens

    # 2. Убрать старые сообщения
    if overflow > 0 and len(messages) > 2:
        while overflow > 0 and len(messages) > 2:
            removed = messages.pop(1)
            overflow -= estimate_tokens(removed.get('content', ''))

    # 3. Обрезать system prompt
    if overflow > 0:
        target_len = max(500, len(system_prompt) - overflow * 3)
        system_prompt = system_prompt[:target_len] + "\n[...обрезано]"

    return system_prompt, messages


def clean_think_blocks(text: str) -> str:
    """Убирает <think> блоки. Если пусто — возвращает содержимое think."""
    if not text or '<think>' not in text.lower():
        return text.strip() if text else ""

    think_match = re.search(r'<think>(.*?)</think>', text, flags=re.DOTALL)
    unclosed = re.search(r'<think>(.*)', text, flags=re.DOTALL)

    clean = re.sub(r'<think>.*?</think>\s*', '', text, flags=re.DOTALL).strip()
    clean = re.sub(r'<think>.*', '', clean, flags=re.DOTALL).strip()

    if clean:
        return clean
    if think_match:
        logger.info("Think cleanup: used closed think content")
        return think_match.group(1).strip()
    if unclosed:
        logger.info("Think cleanup: used unclosed think content")
        return unclosed.group(1).replace('</think>', '').strip()
    return ""


# ═══════════════════════════════════════════════════════════════
# WORKSPACE LOADER
# ═══════════════════════════════════════════════════════════════

class WorkspaceLoader:
    def __init__(self, workspace_dir: str):
        self.workspace_dir = Path(workspace_dir)
        self.cache = {}
        self.cache_time = {}
        self.cache_ttl = 60

    def _read_file(self, filename: str) -> str:
        filepath = self.workspace_dir / filename
        now = time.time()
        if filename in self.cache and (now - self.cache_time.get(filename, 0)) < self.cache_ttl:
            return self.cache[filename]
        if filepath.exists():
            content = filepath.read_text(encoding='utf-8')
            self.cache[filename] = content
            self.cache_time[filename] = now
            return content
        return ""

    def load(self, person_id: str) -> str:
        parts = []
        soul = self._read_file("SOUL.md")
        if soul:
            parts.append(f"# ДУША ANIMARA\n{soul}")
        identity = self._read_file("IDENTITY.md")
        if identity:
            parts.append(f"# ИДЕНТИЧНОСТЬ\n{identity}")

        if person_id == "owner_sergey":
            user = self._read_file("USER.md")
            if user:
                parts.append(f"# ДАННЫЕ О ВЛАДЕЛЬЦЕ\n{user}")
            today = datetime.now().strftime("%Y-%m-%d")
            yesterday = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
            t = self._read_file(f"memory/{today}.md")
            if t:
                parts.append(f"# ЗАМЕТКИ СЕГОДНЯ ({today})\n{t}")
            y = self._read_file(f"memory/{yesterday}.md")
            if y:
                parts.append(f"# ЗАМЕТКИ ВЧЕРА ({yesterday})\n{y}")
        else:
            parts.append("Ты — Animara, AI-ассистент. Представься и спроси чем помочь.")
        return "\n\n".join(parts)

    def write_memory(self, content: str):
        today = datetime.now().strftime("%Y-%m-%d")
        memory_dir = self.workspace_dir / "memory"
        memory_dir.mkdir(exist_ok=True)
        filepath = memory_dir / f"{today}.md"
        entry = f"\n## {datetime.now().strftime('%H:%M')}\n{content}\n"
        with open(filepath, "a", encoding="utf-8") as f:
            f.write(entry)
        self.cache.pop(f"memory/{today}.md", None)


# ═══════════════════════════════════════════════════════════════
# HYBRID SEARCH
# ═══════════════════════════════════════════════════════════════

class HybridSearch:
    def __init__(self):
        self.milvus = MilvusClient(uri=CONFIG["milvus_uri"])
        self.embedder = BGEM3FlagModel(CONFIG["embedding_model"], use_fp16=True)
        self.bm25 = None
        self.bm25_docs = []
        self._build_bm25_index()

    def _build_bm25_index(self):
        try:
            results = self.milvus.query(
                collection_name="memories",
                filter='person_id == "owner_sergey"',
                output_fields=["content"],
                limit=1000
            )
            self.bm25_docs = [r["content"] for r in results if r.get("content")]
            if self.bm25_docs:
                tokenized = [doc.lower().split() for doc in self.bm25_docs]
                self.bm25 = BM25Okapi(tokenized)
                logger.info(f"BM25 index: {len(self.bm25_docs)} docs")
        except Exception as e:
            logger.error(f"BM25 build error: {e}")

    def search(self, query: str, person_id: str) -> str:
        if not query or len(query) < 3:
            return ""
        results = []

        try:
            qe = self.embedder.encode([query])['dense_vecs'][0].tolist()
            vr = self.milvus.search(
                collection_name="memories", data=[qe],
                filter=f'person_id == "{person_id}"',
                limit=CONFIG["rag_top_k"],
                output_fields=["content", "memory_type"]
            )
            for hits in vr:
                for hit in hits:
                    results.append({
                        "content": hit["entity"].get("content", ""),
                        "score": hit["distance"] * CONFIG["vector_weight"],
                        "source": "vector"
                    })
        except Exception as e:
            logger.error(f"Vector search error: {e}")

        if person_id == "owner_sergey" and self.bm25 and self.bm25_docs:
            try:
                scores = self.bm25.get_scores(query.lower().split())
                top = sorted(range(len(scores)), key=lambda i: scores[i], reverse=True)[:CONFIG["rag_top_k"]]
                for idx in top:
                    if scores[idx] > 0:
                        results.append({
                            "content": self.bm25_docs[idx],
                            "score": scores[idx] * CONFIG["bm25_weight"],
                            "source": "bm25"
                        })
            except Exception as e:
                logger.error(f"BM25 search error: {e}")

        seen = set()
        unique = []
        for r in sorted(results, key=lambda x: x["score"], reverse=True):
            h = hashlib.md5(r["content"].encode()).hexdigest()
            if h not in seen:
                seen.add(h)
                unique.append(r)

        if not unique:
            return ""
        return "\n".join(f"• {r['content'][:300]}" for r in unique[:CONFIG["rag_top_k"]])


# ═══════════════════════════════════════════════════════════════
# SESSION MANAGER
# ═══════════════════════════════════════════════════════════════

@dataclass
class Session:
    session_id: str
    person_id: str
    messages: deque = field(default_factory=lambda: deque(maxlen=CONFIG["session_max_messages"]))
    total_tokens: int = 0
    created_at: float = field(default_factory=time.time)
    last_activity: float = field(default_factory=time.time)
    god_mode: bool = False
    flush_done: bool = False


class SessionManager:
    def __init__(self):
        self.sessions: Dict[str, Session] = {}

    def get_or_create(self, person_id: str) -> Session:
        self._cleanup()
        if person_id not in self.sessions:
            sid = f"s_{int(time.time())}_{hashlib.md5(person_id.encode()).hexdigest()[:6]}"
            self.sessions[person_id] = Session(session_id=sid, person_id=person_id)
            logger.info(f"New session: {sid} for {person_id}")
        s = self.sessions[person_id]
        s.last_activity = time.time()
        return s

    def _cleanup(self):
        timeout = CONFIG["session_timeout_minutes"] * 60
        now = time.time()
        expired = [pid for pid, s in self.sessions.items() if (now - s.last_activity) > timeout]
        for pid in expired:
            logger.info(f"Session expired: {self.sessions[pid].session_id}")
            del self.sessions[pid]

    def add_message(self, person_id: str, role: str, content: str):
        s = self.get_or_create(person_id)
        s.messages.append({"role": role, "content": content})
        s.total_tokens += len(content) // 3  # FIX #6

    def get_history(self, person_id: str) -> List[dict]:
        return list(self.get_or_create(person_id).messages)


# ═══════════════════════════════════════════════════════════════
# FACT EXTRACTOR
# ═══════════════════════════════════════════════════════════════

class FactExtractor:
    PATTERNS = [
        (r"меня зовут\s+([А-ЯA-Z][а-яa-z]{2,})", "fact", "Пользователя зовут {0}"),
        (r"я живу в\s+(.+?)(?:\.|,|$)", "fact", "Пользователь живёт в {0}"),
        (r"живу в\s+(.+?)(?:\.|,|$)", "fact", "Пользователь живёт в {0}"),
        (r"я работаю\s+(.+?)(?:\.|,|$)", "fact", "Пользователь работает {0}"),
        (r"работаю\s+(.+?)(?:\.|,|$)", "fact", "Пользователь работает {0}"),
        (r"мне нравится\s+(.+?)(?:\.|,|$)", "preference", "Пользователю нравится {0}"),
        (r"я люблю\s+(.+?)(?:\.|,|$)", "preference", "Пользователь любит {0}"),
        (r"я предпочитаю\s+(.+?)(?:\.|,|$)", "preference", "Пользователь предпочитает {0}"),
    ]

    def extract(self, text: str) -> List[dict]:
        facts = []
        for pattern, ft, template in self.PATTERNS:
            for match in re.findall(pattern, text, re.IGNORECASE):
                if len(match) >= 3 and match.lower() not in ["и", "а", "но", "или", "что", "как"]:
                    facts.append({"type": ft, "content": template.format(match.strip())})
        return facts


# ═══════════════════════════════════════════════════════════════
# QWEN-AGENT ORCHESTRATOR v2 (FIX #1: Graceful Degradation)
# ═══════════════════════════════════════════════════════════════

class QwenAgentOrchestrator:

    def __init__(self):
        self.llm_cfg = {
            'model': CONFIG["llm_model"],
            'model_server': CONFIG["llm_api"],
            'api_key': 'EMPTY',
            'generate_cfg': {
                'temperature': 0.7,
                'top_p': 0.8,
                'max_tokens': 2048,
            }
        }
        self.agent = None
        self.tools = None
        self.healthy_servers = []
        self.failed_servers = []

        full_config = self._load_mcp_config_raw()
        if QWEN_AGENT_AVAILABLE and full_config:
            self._init_with_graceful_degradation(full_config)
        else:
            logger.warning("Qwen-Agent not available, falling back to direct LLM")

    def _load_mcp_config_raw(self) -> dict:
        config_path = Path(CONFIG["mcp_config_path"])
        if not config_path.exists():
            logger.warning(f"MCP config not found: {config_path}")
            return {}
        try:
            with open(config_path) as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"MCP config load error: {e}")
            return {}

    def _init_with_graceful_degradation(self, full_config: dict):
        """FIX #1: Пробуем все → если падает → по одному"""
        servers = full_config.get("mcpServers", {})
        if not servers:
            return

        # Быстрый путь
        try:
            self.tools = [full_config]
            self.agent = Assistant(
                llm=self.llm_cfg, function_list=self.tools,
                name='Animara', description='AI ассистент'
            )
            self.healthy_servers = list(servers.keys())
            logger.info(f"✅ All {len(servers)} MCP servers OK: {', '.join(servers.keys())}")
            return
        except Exception as e:
            logger.warning(f"⚠️ Failed all-at-once: {e}")
            logger.info("Trying one by one...")

        # По одному
        self.healthy_servers = []
        self.failed_servers = []
        for name, cfg in servers.items():
            try:
                test = Assistant(
                    llm=self.llm_cfg,
                    function_list=[{"mcpServers": {name: cfg}}],
                    name='test', description='test'
                )
                self.healthy_servers.append(name)
                logger.info(f"  ✅ {name}")
                del test
            except Exception as e:
                self.failed_servers.append(name)
                logger.warning(f"  ❌ {name}: {e}")

        if self.healthy_servers:
            healthy_cfg = {"mcpServers": {n: servers[n] for n in self.healthy_servers}}
            try:
                self.tools = [healthy_cfg]
                self.agent = Assistant(
                    llm=self.llm_cfg, function_list=self.tools,
                    name='Animara', description='AI ассистент'
                )
                logger.info(f"✅ Agent: {len(self.healthy_servers)}/{len(servers)} servers")
                if self.failed_servers:
                    logger.warning(f"⚠️ Skipped: {', '.join(self.failed_servers)}")
            except Exception as e:
                logger.error(f"❌ Failed even with healthy servers: {e}")
                self.agent = None
        else:
            logger.error("❌ ALL MCP servers failed!")

    def get_status(self) -> dict:
        return {
            "agent_available": self.agent is not None,
            "healthy_servers": self.healthy_servers,
            "failed_servers": self.failed_servers,
            "total": len(self.healthy_servers) + len(self.failed_servers),
        }

    def run(self, messages: List[dict]) -> str:
        if self.agent:
            try:
                response_text = ""
                for responses in self.agent.run(messages=messages):
                    if responses:
                        last = responses[-1]
                        if isinstance(last, dict):
                            if last.get('role') in ('tool', 'function'):
                                continue
                            response_text = last.get('content', '')
                        else:
                            response_text = str(last)

                clean = clean_think_blocks(response_text)
                if not clean:
                    logger.warning("Empty after think cleanup → fallback")
                    return self._fallback_llm(messages)
                return clean

            except Exception as e:
                logger.error(f"Qwen-Agent error: {e}")
                return self._fallback_llm(messages)
        else:
            return self._fallback_llm(messages)

    def _fallback_llm(self, messages: List[dict]) -> str:
        try:
            # FIX #2: dynamic max_tokens
            max_tok = calculate_dynamic_max_tokens(messages, CONFIG["context_window"])
            resp = requests.post(
                f"{CONFIG['llm_api']}/chat/completions",
                json={
                    "model": CONFIG["llm_model"],
                    "messages": messages,
                    "max_tokens": max_tok,
                    "temperature": 0.7
                },
                timeout=120
            )
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                return clean_think_blocks(content) or content.strip()  # FIX #4
            else:
                logger.error(f"LLM {resp.status_code}: {resp.text[:200]}")
                return f"❌ LLM Error: {resp.status_code}"
        except Exception as e:
            return f"❌ LLM Error: {e}"


# ═══════════════════════════════════════════════════════════════
# ГЛАВНЫЙ ПРОЦЕССОР
# ═══════════════════════════════════════════════════════════════

class AnimaraProcessor:
    def __init__(self):
        logger.info("Initializing Animara Processor v12.1...")
        self.workspace = WorkspaceLoader(CONFIG["workspace_dir"])
        self.search = HybridSearch()
        self.sessions = SessionManager()
        self.facts = FactExtractor()
        self.orchestrator = QwenAgentOrchestrator()
        self.milvus = self.search.milvus      # FIX #11
        self.embedder = self.search.embedder
        logger.info("Animara Processor v12.1 ready!")

    def process(self, user_input: str, person_id: str) -> dict:
        session = self.sessions.get_or_create(person_id)

        # God Mode — разные варианты фраз
        _input_lower = user_input.strip().lower()
        _god_phrases = ["/god", "god mode", "режим бога", "включи режим бога", "включи god mode"]
        _local_phrases = ["/local", "local mode", "локальный режим", "выключи режим бога", "обычный режим", "включи локальный"]
        if _input_lower in _god_phrases or any(p in _input_lower for p in _god_phrases):
            session.god_mode = True
            return {"content": "🔮 God Mode включён. Используется OpenAI.", "god_mode": True}
        if _input_lower in _local_phrases or any(p in _input_lower for p in _local_phrases):
            session.god_mode = False
            return {"content": "🏠 Local Mode включён. Используется Qwen3.", "god_mode": False}

        # FIX #3: Сохраняем user СРАЗУ (до формирования messages)
        self.sessions.add_message(person_id, "user", user_input)

        workspace_context = self.workspace.load(person_id)
        rag_context = self.search.search(user_input, person_id)

        system_prompt = f"""/no_think
{workspace_context}

## Релевантная информация из памяти:
{rag_context if rag_context else "Нет релевантной информации."}

## Текущее время: {datetime.now().strftime('%Y-%m-%d %H:%M')} (Asia/Makassar, Бали)

## Инструкции:
- Отвечай кратко и по делу
- Используй инструменты когда нужно (задачи, поиск, время)
- Если не знаешь — скажи честно
"""
        # FIX #3: history уже содержит текущий user_input — НЕ добавляем дубль
        messages = [{"role": "system", "content": system_prompt}]
        history = self.sessions.get_history(person_id)
        if history:
            messages.extend(history[-6:])

        # FIX #2: Обрезаем контекст если overflow
        messages[0]['content'], messages = truncate_context_if_needed(
            messages[0]['content'], messages, CONFIG["context_window"]
        )

        response_text = self.orchestrator.run(messages)

        # Сохраняем ответ (user уже сохранён выше)
        self.sessions.add_message(person_id, "assistant", response_text)

        for fact in self.facts.extract(user_input):
            self._save_fact(person_id, fact)

        if session.total_tokens > CONFIG["flush_threshold_tokens"] and not session.flush_done:
            self._auto_flush(session)

        return {
            "content": response_text,
            "session": {
                "session_id": session.session_id,
                "messages": len(session.messages),
                "total_tokens": session.total_tokens,
                "god_mode": session.god_mode
            }
        }

    def _save_fact(self, person_id: str, fact: dict):
        try:
            emb = self.embedder.encode([fact["content"]])['dense_vecs'][0].tolist()
            self.milvus.insert(collection_name="memories", data=[{
                "person_id": person_id,
                "memory_type": fact["type"],
                "content": fact["content"],
                "content_embedding": emb,
                "confidence": 0.9,
                "is_active": True,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }])
            logger.info(f"Saved fact: {fact['content'][:50]}...")
        except Exception as e:
            logger.error(f"Save fact error: {e}")

    def _auto_flush(self, session: Session):
        """FIX #7: Осмысленный flush"""
        try:
            history = list(session.messages)
            if not history:
                return
            user_msgs = [m["content"] for m in history if m["role"] == "user"]
            topics = "; ".join(msg[:80] for msg in user_msgs[-5:])
            summary = f"Темы: {topics}"

            self.workspace.write_memory(summary)
            emb = self.embedder.encode([summary])['dense_vecs'][0].tolist()
            self.milvus.insert(collection_name="memories", data=[{
                "person_id": session.person_id,
                "memory_type": "session_summary",
                "content": summary[:1000],
                "content_embedding": emb,
                "confidence": 0.8,
                "is_active": True,
                "created_at": int(time.time()),
                "updated_at": int(time.time()),
            }])
            session.flush_done = True
            logger.info(f"Auto-flush: {session.session_id} — {summary[:100]}")
        except Exception as e:
            logger.error(f"Auto-flush error: {e}")


# ═══════════════════════════════════════════════════════════════
# FASTAPI (FIX #12: lifespan)
# ═══════════════════════════════════════════════════════════════

processor: Optional[AnimaraProcessor] = None

@asynccontextmanager
async def lifespan(app: FastAPI):
    global processor
    processor = AnimaraProcessor()
    yield
    logger.info("Shutting down...")

app = FastAPI(title="Animara RAG Proxy v12.1", version="12.1.0", lifespan=lifespan)


@app.get("/health")
async def health():
    """FIX #5: MCP статус"""
    mcp = processor.orchestrator.get_status() if processor else {}
    return {"status": "ok", "version": "12.1.0", "mcp": mcp, "timestamp": datetime.now().isoformat()}


@app.post("/v1/chat/completions")
async def chat(request: Request):
    if not processor:
        return JSONResponse({"error": "Not initialized"}, status_code=503)
    try:
        data = await request.json()
        # FIX #8: person_id из extra_body
        person_id = data.get("person_id") or data.get("extra_body", {}).get("person_id") or "owner_sergey"
        messages = data.get("messages", [])
        if not messages:
            return JSONResponse({"error": "No messages"}, status_code=400)

        result = processor.process(messages[-1].get("content", ""), person_id)
        return {
            "choices": [{"message": {"role": "assistant", "content": result["content"]}}],
            "animara_stats": {"version": "12.1.0", "session": result.get("session", {})}
        }
    except Exception as e:
        logger.error(f"Chat error: {e}")
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/session/{person_id}")
async def get_session(person_id: str):
    if not processor:
        return JSONResponse({"error": "Not initialized"}, status_code=503)
    s = processor.sessions.get_or_create(person_id)
    return {
        "session_id": s.session_id, "person_id": s.person_id,
        "messages": len(s.messages), "total_tokens": s.total_tokens,
        "god_mode": s.god_mode, "flush_done": s.flush_done,
        "created_at": datetime.fromtimestamp(s.created_at).isoformat(),
        "last_activity": datetime.fromtimestamp(s.last_activity).isoformat()
    }


@app.post("/session/{person_id}/flush")
async def flush_session(person_id: str):
    if not processor:
        return JSONResponse({"error": "Not initialized"}, status_code=503)
    s = processor.sessions.get_or_create(person_id)
    processor._auto_flush(s)
    return {"status": "flushed", "session_id": s.session_id}


@app.post("/bm25/rebuild")
async def rebuild_bm25():
    if not processor:
        return JSONResponse({"error": "Not initialized"}, status_code=503)
    processor.search._build_bm25_index()
    return {"status": "rebuilt", "docs": len(processor.search.bm25_docs)}


# ═══════════════════════════════════════════════════════════════
if __name__ == "__main__":
    print("=" * 60)
    print("🤖 ANIMARA RAG PROXY v12.1")
    print("   MCP + Qwen-Agent + Graceful Degradation")
    print("=" * 60)
    print(f"   Port: {CONFIG['port']}")
    print(f"   LLM: {CONFIG['llm_api']}")
    print(f"   MCP: {CONFIG['mcp_config_path']}")
    print(f"   Qwen-Agent: {'✅' if QWEN_AGENT_AVAILABLE else '❌'}")
    print("=" * 60)
    uvicorn.run(app, host=CONFIG["host"], port=CONFIG["port"], log_level="info")
