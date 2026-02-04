#!/usr/bin/env python3
"""
═══════════════════════════════════════════════════════════════
 ANIMARA RAG Proxy v12.2 — UPGRADE PATCH
═══════════════════════════════════════════════════════════════

 Три главных изменения:
 1. Smart Router — простые запросы мимо Qwen-Agent (~1-2 сек)
 2. Lazy MCP — инструменты подключаются ТОЛЬКО когда нужны
 3. Tool Selection — передаём LLM только релевантные tools

 ПРИМЕНЕНИЕ:
   Файл содержит готовые классы для замены/вставки в
   ~/animara_rag_proxy_v12.py на Thor.

 Автор: Animara Project, 2026-02-04
═══════════════════════════════════════════════════════════════
"""

import re
import time
import logging
import asyncio
from typing import Literal, Optional, List, Dict, Set, Tuple
from dataclasses import dataclass, field

try:
    import aiohttp
except ImportError:
    aiohttp = None  # На Thor будет установлен

logger = logging.getLogger("animara.v12_2")


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 1: SMART ROUTER
# ═══════════════════════════════════════════════════════════════
#
#  Проблема из чекпоинта 2026-02-04:
#    Qwen-Agent делает 2-3 LLM вызова на "привет" = 40-60 сек
#    потому что agent loop перебирает инструменты
#
#  Решение:
#    Классифицируем запрос ДО Qwen-Agent
#    Простые → прямой vLLM (1 вызов, ~1-2 сек)
#    Сложные → Qwen-Agent но с ОТФИЛЬТРОВАННЫМИ tools
# ═══════════════════════════════════════════════════════════════

RouteType = Literal["direct", "agent"]


@dataclass
class RouteResult:
    """Результат классификации запроса"""
    route: RouteType                    # direct или agent
    needed_tools: Set[str] = field(default_factory=set)  # какие MCP нужны
    confidence: float = 0.0            # уверенность 0-1
    reason: str = ""                   # для логов


class SmartRouter:
    """
    Двухуровневый классификатор:
      Level 1: Regex — мгновенный, для очевидных паттернов
      Level 2: Keyword scoring — для неочевидных запросов
    
    Важно: при сомнении → agent (лучше медленнее, чем неправильно)
    """

    # ── Regex Level 1: Точные паттерны → direct ──
    DIRECT_PATTERNS = [
        # Приветствия
        r"^(?:привет|здравствуй|хай|хеллоу|hello|hi|hey|добр(?:ое|ый|ого)|yo)\b",
        r"^(?:доброе утро|добрый (?:день|вечер)|good (?:morning|evening|night))\b",
        # Благодарности / прощания
        r"^(?:спасибо|благодарю|thanks|thank you|пока|до свидания|bye|good ?bye)\b",
        # Мета-вопросы о боте
        r"(?:кто ты|что (?:ты )?умеешь|как тебя зовут|what (?:are|can) you)",
        r"(?:расскажи о себе|представься|who are you)",
        # Простые знаниевые вопросы (без привязки к данным/инструментам)
        r"(?:что такое|объясни|explain|what is|define|как работает)\s+\w+",
        # Просьбы общего характера
        r"(?:напиши|сочини|придумай|переведи|translate|summarize|перескажи)",
        r"(?:помоги (?:мне )?(?:с |написать|разобраться|понять))",
        # Код / программирование (LLM знает, инструменты не нужны)
        r"(?:код|code|python|javascript|функци[яю]|алгоритм|баг|ошибк[ау])",
        r"(?:как (?:написать|сделать|реализовать|исправить))",
        # Мнения / советы
        r"(?:что думаешь|как считаешь|посоветуй|suggest|recommend)",
    ]

    # ── Regex Level 1: Точные паттерны → agent + конкретный tool ──
    TOOL_PATTERNS: List[Tuple[str, Set[str]]] = [
        # YouGile — задачи
        (r"(?:задач[аиу]|таск|task|todo|канбан|доск[аеу]|колонк|yougile|югайл)", {"yougile"}),
        (r"(?:создай|добавь|удали|перенеси|закрой)\s+задач", {"yougile"}),
        (r"(?:мои задачи|что.*(?:сделать|запланирован))", {"yougile"}),

        # BrightData — интернет
        (r"(?:найди в (?:интернет|сети)|поищи|загугли|search online)", {"brightdata"}),
        (r"(?:погод[аеу]|weather)\s", {"brightdata"}),
        (r"(?:новост[иь]|news)\s+(?:про|о|about)", {"brightdata"}),
        (r"(?:курс\s+(?:доллар|биткоин|крипт|валют))", {"brightdata"}),
        (r"(?:что (?:случилось|произошло|нового))", {"brightdata"}),

        # Filesystem — файлы
        (r"(?:прочитай|открой|покажи)\s+(?:файл|/)", {"filesystem"}),
        (r"(?:сохрани|запиши)\s+(?:\w+\s+)*(?:в\s+)?файл", {"filesystem"}),
        (r"(?:содержимое|cat|ls)\s+(?:/|~/|animara)", {"filesystem"}),

        # Memory — долгосрочная память
        (r"(?:запомни|remember)\b", {"memory"}),
        (r"(?:что (?:ты )?помнишь|помнишь ли|вспомни|recall)\b", {"memory", "milvus"}),
        (r"(?:забудь|forget)\b", {"memory"}),
        (r"(?:мы (?:обсуждали|говорили|решили))", {"memory", "milvus"}),

        # Time — время
        (r"(?:который час|текущее время|сколько времени|what time)", {"time"}),
        (r"(?:какая.*дата|сегодняшн(?:яя|ее)|today['']?s date)", {"time"}),

        # Exec — системные
        (r"(?:nvidia[- ]?smi|gpu\b)", {"exec"}),
        (r"(?:состояние (?:систем|сервер|gpu)|system status|uptime)", {"exec"}),
        (r"(?:disk|место на|свободн\w+ памят)", {"exec"}),
        (r"(?:запусти|выполни|exec|run)\s+(?:команд|command)", {"exec"}),
        (r"(?:docker|systemctl|процесс)", {"exec"}),

        # Google Calendar
        (r"(?:календар[ьея]|calendar)\b", {"google_calendar"}),
        (r"(?:встреч[аеу]|event|расписани|schedule)\b", {"google_calendar"}),
        (r"(?:запланируй|создай (?:встреч|событ))", {"google_calendar"}),
        (r"(?:что у меня.*(?:сегодня|завтра|на неделе))", {"google_calendar", "time"}),

        # Gmail
        (r"(?:почт[аеу]|письм[аоу]|email|gmail|inbox)\b", {"gmail"}),
        (r"(?:отправь|напиши)\s+(?:письмо|email|mail)", {"gmail"}),
        (r"(?:непрочитанн\w+ (?:письм|сообщ)|unread)", {"gmail"}),

        # Milvus — семантический поиск
        (r"(?:найди в памят|поиск по памят|semantic search)", {"milvus"}),
        (r"(?:похож(?:ие|ее) на|similar to)", {"milvus"}),

        # Комбинированные
        (r"(?:утренн(?:ий|яя) сводк|morning (?:brief|summary))",
         {"time", "google_calendar", "gmail", "yougile"}),
        (r"(?:дай отчёт|full report|полный (?:статус|отчёт))",
         {"exec", "yougile", "google_calendar"}),
        (r"(?:отчёт о (?:систем|сервер))", {"exec"}),
    ]

    def __init__(self):
        # Компилируем regex для скорости
        self._direct_compiled = [re.compile(p, re.IGNORECASE) for p in self.DIRECT_PATTERNS]
        self._tool_compiled = [
            (re.compile(p, re.IGNORECASE), tools)
            for p, tools in self.TOOL_PATTERNS
        ]
        # Статистика
        self.stats = {"direct": 0, "agent": 0, "total": 0}

    def classify(self, user_input: str, person_id: str = "") -> RouteResult:
        """
        Классифицирует запрос.
        
        Returns:
            RouteResult с маршрутом и набором нужных tools
        """
        self.stats["total"] += 1
        text = user_input.strip()

        # ── God mode фразы → direct (обрабатываются до agent) ──
        if re.match(r"(?:режим бога|god mode|/god|/local)$", text, re.IGNORECASE):
            return RouteResult(route="direct", confidence=1.0, reason="god mode toggle")

        # ── Slash-команды всегда → agent ──
        if text.startswith("/"):
            return self._agent_result(set(), 1.0, f"slash command: {text[:20]}")

        # ── Level 1: Проверяем tool-паттерны ──
        needed_tools: Set[str] = set()
        tool_reasons: List[str] = []

        for pattern, tools in self._tool_compiled:
            if pattern.search(text):
                needed_tools.update(tools)
                tool_reasons.append(f"matched:{list(tools)}")

        if needed_tools:
            self.stats["agent"] += 1
            return RouteResult(
                route="agent",
                needed_tools=needed_tools,
                confidence=0.9,
                reason=f"tool patterns: {', '.join(tool_reasons)}"
            )

        # ── Level 2: Проверяем direct-паттерны ──
        for pattern in self._direct_compiled:
            if pattern.search(text):
                self.stats["direct"] += 1
                return RouteResult(
                    route="direct",
                    confidence=0.85,
                    reason=f"direct pattern match"
                )

        # ── Level 3: Keyword scoring для неоднозначных ──
        score = self._keyword_score(text)
        if score > 0.5:
            self.stats["agent"] += 1
            return RouteResult(
                route="agent",
                needed_tools=self._guess_tools(text),
                confidence=score,
                reason=f"keyword score: {score:.2f}"
            )

        # ── Default: direct для коротких, agent для длинных ──
        if len(text.split()) <= 8:
            self.stats["direct"] += 1
            return RouteResult(route="direct", confidence=0.6, reason="short message, default direct")
        else:
            self.stats["agent"] += 1
            return RouteResult(
                route="agent",
                needed_tools=set(),  # все tools
                confidence=0.5,
                reason="long message, default agent"
            )

    def _keyword_score(self, text: str) -> float:
        """Оценка вероятности что нужны инструменты (0-1)"""
        tool_keywords = {
            "задач", "таск", "найди", "поищи", "файл", "запомни",
            "помнишь", "время", "час", "gpu", "nvidia", "docker",
            "календар", "встреч", "почт", "письм", "команд",
            "запусти", "выполни", "статус", "систем", "сервер",
            "сводк", "отчёт", "мониторинг"
        }
        words = set(re.findall(r'\w+', text.lower()))
        overlap = words & tool_keywords
        if not overlap:
            return 0.0
        return min(len(overlap) / 3.0, 1.0)

    def _guess_tools(self, text: str) -> Set[str]:
        """Угадать какие tools могут понадобиться по ключевым словам"""
        tools = set()
        text_lower = text.lower()
        mapping = {
            "yougile": ["задач", "таск", "доск", "канбан"],
            "brightdata": ["найди", "поищи", "интернет", "погод", "новост", "курс"],
            "filesystem": ["файл", "прочитай", "сохрани", "каталог"],
            "memory": ["запомни", "помнишь", "вспомни", "забудь"],
            "time": ["время", "час", "дата"],
            "exec": ["gpu", "nvidia", "docker", "систем", "сервер", "команд"],
            "google_calendar": ["календар", "встреч", "расписан", "событ"],
            "gmail": ["почт", "письм", "email"],
            "milvus": ["поиск", "памят", "семантик", "похож"],
        }
        for tool, keywords in mapping.items():
            for kw in keywords:
                if kw in text_lower:
                    tools.add(tool)
                    break
        return tools

    def _agent_result(self, tools: Set[str], confidence: float, reason: str) -> RouteResult:
        self.stats["agent"] += 1
        return RouteResult(route="agent", needed_tools=tools, confidence=confidence, reason=reason)


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 2: DIRECT LLM CALL (быстрый путь)
# ═══════════════════════════════════════════════════════════════
#
#  Вместо Qwen-Agent → прямой POST к vLLM
#  Один вызов, без tools, без agent loop
#  Результат: ~1-2 сек вместо ~40-60 сек
# ═══════════════════════════════════════════════════════════════

async def call_llm_direct(
    system_prompt: str,
    messages: List[dict],
    config: dict,
    max_tokens: int = 2048,
    temperature: float = 0.7,
) -> Optional[str]:
    """
    Прямой вызов vLLM без MCP tools.
    
    Используется для:
      - Приветствий
      - Общих вопросов
      - Кодинга
      - Переводов
      - Всего что не требует инструментов
    
    Returns:
        Текст ответа или None (→ fallback на agent)
    """
    api_url = f"{config['llm_api']}/chat/completions"

    # Формируем messages для vLLM
    api_messages = [{"role": "system", "content": system_prompt}]
    api_messages.extend(messages)

    payload = {
        "model": config["llm_model"],
        "messages": api_messages,
        "max_tokens": max_tokens,
        "temperature": temperature,
        "stream": False,
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(api_url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    content = data["choices"][0]["message"]["content"]
                    # Убираем <think>...</think> если есть
                    content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
                    return content
                else:
                    logger.error(f"Direct LLM error: HTTP {resp.status}")
                    return None
    except asyncio.TimeoutError:
        logger.error("Direct LLM timeout (60s)")
        return None
    except Exception as e:
        logger.error(f"Direct LLM exception: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 3: TOOL FILTER — передаём агенту ТОЛЬКО нужные MCP
# ═══════════════════════════════════════════════════════════════
#
#  Проблема: 9 MCP серверов = ~14K токенов tool descriptions
#  Qwen-Agent вставляет ВСЕ descriptions в каждый LLM вызов
#
#  Решение: если Smart Router определил что нужны только
#  yougile + time, передаём агенту только эти 2 сервера
#  Это уменьшает system prompt с 14K до 2-3K токенов
#  → быстрее prefill, меньше шансов на лишние итерации
# ═══════════════════════════════════════════════════════════════

def filter_mcp_config(
    full_config: dict,
    needed_tools: Set[str]
) -> dict:
    """
    Фильтрует mcp_config.json оставляя только нужные серверы.
    
    Args:
        full_config: полный mcp_config.json (9 серверов)
        needed_tools: {"yougile", "time"} — какие нужны
    
    Returns:
        Отфильтрованный конфиг только с нужными серверами
    
    Если needed_tools пустой → возвращает ВСЕ серверы (fallback)
    """
    if not needed_tools:
        return full_config  # не знаем что нужно → все

    servers = full_config.get("mcpServers", {})
    filtered = {
        name: config
        for name, config in servers.items()
        if name in needed_tools
    }

    if not filtered:
        # Если фильтр убрал всё (ошибка в классификации) → все серверы
        logger.warning(f"Tool filter removed all servers! needed={needed_tools}, using all")
        return full_config

    logger.info(f"Tool filter: {len(servers)} → {len(filtered)} servers ({list(filtered.keys())})")
    return {"mcpServers": filtered}


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 4: DYNAMIC MAX_TOKENS
# ═══════════════════════════════════════════════════════════════
#
#  Проблема из чекпоинта 2026-02-02 (баг #1):
#    YouGile возвращает ~16K токенов + system 14K = 30K+ из 32K
#    → context overflow, обрезанный или пустой ответ
#
#  Решение:
#    max_tokens = context_window - input_tokens - 512 (запас)
#    + обрезка tool результатов если они слишком большие
# ═══════════════════════════════════════════════════════════════

def calculate_dynamic_max_tokens(
    system_prompt: str,
    messages: List[dict],
    context_window: int = 32768,
    reserve: int = 512,
    min_tokens: int = 256,
) -> int:
    """
    Рассчитывает max_tokens для ответа на основе входных данных.
    
    Используем грубую оценку: 1 символ ≈ 0.4 токена (для русского ~0.5)
    Точнее было бы через tiktoken, но для нашего случая достаточно.
    """
    # Оценка входных токенов
    total_chars = len(system_prompt)
    for msg in messages:
        content = msg.get("content", "")
        if isinstance(content, str):
            total_chars += len(content)
        elif isinstance(content, list):
            for part in content:
                if isinstance(part, dict) and "text" in part:
                    total_chars += len(part["text"])

    # Для русского текста: ~0.5 токенов на символ (в среднем)
    est_input_tokens = int(total_chars * 0.5)

    max_tokens = context_window - est_input_tokens - reserve
    max_tokens = max(max_tokens, min_tokens)
    max_tokens = min(max_tokens, 4096)  # cap на 4096 — длиннее редко нужно

    logger.debug(f"Dynamic max_tokens: input≈{est_input_tokens}, max={max_tokens}")
    return max_tokens


def truncate_tool_result(result: str, max_chars: int = 8000) -> str:
    """
    Обрезает слишком длинные tool результаты (YouGile, brightdata).
    Сохраняет начало + конец для контекста.
    """
    if len(result) <= max_chars:
        return result

    half = max_chars // 2
    truncated = (
        result[:half]
        + f"\n\n... [обрезано {len(result) - max_chars} символов] ...\n\n"
        + result[-half:]
    )
    logger.warning(f"Tool result truncated: {len(result)} → {len(truncated)} chars")
    return truncated


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 5: GRACEFUL DEGRADATION для Qwen-Agent
# ═══════════════════════════════════════════════════════════════
#
#  Проблема из чекпоинта 2026-02-02 (баг #2):
#    Один сбойный MCP сервер роняет ВСЕ tools в Qwen-Agent
#
#  Решение: обёртка которая пробует подключить каждый сервер
#  отдельно, пропуская сломанные
# ═══════════════════════════════════════════════════════════════

async def init_mcp_with_degradation(
    mcp_config: dict,
    timeout_per_server: float = 10.0,
) -> Tuple[dict, List[str]]:
    """
    Пробует подключить каждый MCP сервер отдельно.
    Сломанные — пропускает, но продолжает с остальными.
    
    Returns:
        (working_config, failed_servers)
    """
    servers = mcp_config.get("mcpServers", {})
    working = {}
    failed = []

    for name, config in servers.items():
        try:
            # Проверяем SSE endpoint если это URL
            url = config.get("url", "")
            if url:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url.replace("/sse", "/health") if "/sse" in url else url,
                        timeout=aiohttp.ClientTimeout(total=timeout_per_server)
                    ) as resp:
                        if resp.status < 500:
                            working[name] = config
                            logger.info(f"MCP {name}: ✅ OK")
                        else:
                            failed.append(name)
                            logger.warning(f"MCP {name}: ❌ HTTP {resp.status}")
            else:
                # STDIO — просто добавляем, проверить сложнее
                working[name] = config
                logger.info(f"MCP {name}: ✅ (STDIO, assumed OK)")

        except asyncio.TimeoutError:
            failed.append(name)
            logger.warning(f"MCP {name}: ❌ timeout ({timeout_per_server}s)")
        except Exception as e:
            failed.append(name)
            logger.warning(f"MCP {name}: ❌ {e}")

    return {"mcpServers": working}, failed


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 6: ИНТЕГРАЦИЯ В RAG PROXY v12 — ИНСТРУКЦИЯ
# ═══════════════════════════════════════════════════════════════
#
#  Ниже — точные инструкции где и что менять в
#  ~/animara_rag_proxy_v12.py
#
#  Вместо ручного патчинга 809-строчного файла,
#  можно использовать этот файл как import
# ═══════════════════════════════════════════════════════════════

INTEGRATION_GUIDE = """
═══════════════════════════════════════════════════════════════
 ИНСТРУКЦИЯ ПО ИНТЕГРАЦИИ v12.2
═══════════════════════════════════════════════════════════════

ВАРИАНТ A: Импорт (рекомендуется)
─────────────────────────────────
1. Скопировать animara_v12_2_upgrade.py в ~/animara/
2. В начале animara_rag_proxy_v12.py добавить:

   from animara_v12_2_upgrade import (
       SmartRouter, RouteResult,
       call_llm_direct,
       filter_mcp_config,
       calculate_dynamic_max_tokens,
       truncate_tool_result,
   )

3. В __init__ класса AnimaraProcessor добавить:

   self.smart_router = SmartRouter()

4. В методе process() — ЗАМЕНИТЬ основную логику:

   ─── БЫЛО (v12.1): ───────────────────────────────────
   
   # Всегда идём через Qwen-Agent
   response = self.orchestrator.run(system_prompt, messages)
   
   ─── СТАЛО (v12.2): ──────────────────────────────────
   
   # 1. Классифицируем запрос
   route = self.smart_router.classify(user_input, person_id)
   logger.info(f"Route: {route.route} | tools: {route.needed_tools} | "
               f"confidence: {route.confidence:.2f} | {route.reason}")
   
   # 2. Выбираем путь
   if route.route == "direct":
       # Быстрый путь — прямой LLM без MCP
       response = await call_llm_direct(
           system_prompt, messages, CONFIG
       )
       if response is None:
           # Fallback на agent если direct сломался
           logger.warning("Direct LLM failed, fallback to agent")
           route = RouteResult(route="agent", needed_tools=set())
           response = None
   
   if route.route == "agent":
       # Полный путь — но с отфильтрованными tools!
       if route.needed_tools:
           filtered_config = filter_mcp_config(
               self.full_mcp_config, route.needed_tools
           )
       else:
           filtered_config = self.full_mcp_config
       
       # Dynamic max_tokens
       max_tokens = calculate_dynamic_max_tokens(
           system_prompt, messages, CONFIG["context_window"]
       )
       
       response = self.orchestrator.run(
           system_prompt, messages,
           mcp_config=filtered_config,
           max_tokens=max_tokens,
       )
   
   ─────────────────────────────────────────────────────

5. В /health endpoint добавить:

   "smart_router": self.processor.smart_router.stats,


ВАРИАНТ B: Полная замена (если хочешь чистый код)
─────────────────────────────────────────────────
Создать animara_rag_proxy_v12_2.py — новый файл на основе v12
с уже встроенным Smart Router. Это безопаснее — старый файл
остаётся как fallback.

═══════════════════════════════════════════════════════════════
"""


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 7: ТЕСТЫ
# ═══════════════════════════════════════════════════════════════

def run_tests():
    """Тестирование Smart Router — 30+ тестов"""
    router = SmartRouter()
    
    tests = [
        # ── Direct (простые) ──
        ("привет", "direct", set()),
        ("Привет, как дела?", "direct", set()),
        ("здравствуйте", "direct", set()),
        ("добрый вечер", "direct", set()),
        ("hi there", "direct", set()),
        ("спасибо!", "direct", set()),
        ("пока", "direct", set()),
        ("кто ты?", "direct", set()),
        ("что ты умеешь?", "direct", set()),
        ("что такое нейронная сеть?", "direct", set()),
        ("объясни квантовые вычисления", "direct", set()),
        ("напиши стихотворение про зиму", "direct", set()),
        ("переведи на английский: я люблю кофе", "direct", set()),
        ("как написать сортировку на python", "direct", set()),
        ("помоги мне разобраться с git rebase", "direct", set()),
        ("ок", "direct", set()),

        # ── Agent + конкретные tools ──
        ("покажи мои задачи", "agent", {"yougile"}),
        ("создай задачу: купить молоко", "agent", {"yougile"}),
        ("найди в интернете про Бали", "agent", {"brightdata"}),
        ("какая погода на Бали?", "agent", {"brightdata"}),
        ("прочитай файл /animara/SOUL.md", "agent", {"filesystem"}),
        ("сохрани это в файл", "agent", {"filesystem"}),
        ("запомни что я люблю кофе", "agent", {"memory"}),
        ("что ты помнишь обо мне?", "agent", {"memory", "milvus"}),
        ("который час?", "agent", {"time"}),
        ("покажи nvidia-smi", "agent", {"exec"}),
        ("какое состояние GPU?", "agent", {"exec"}),
        ("покажи мой календарь", "agent", {"google_calendar"}),
        ("создай встречу на завтра в 15:00", "agent", {"google_calendar"}),
        ("проверь почту", "agent", {"gmail"}),
        ("отправь письмо Ульяне", "agent", {"gmail"}),
        
        # ── Agent + несколько tools ──
        ("утренняя сводка", "agent", {"time", "google_calendar", "gmail", "yougile"}),
        ("дай полный отчёт о системе", "agent", {"exec", "yougile", "google_calendar"}),
        
        # ── Slash commands → agent ──
        ("/god", "direct", set()),  # god mode — special case
        ("/status", "agent", set()),
        ("/tasks", "agent", set()),
    ]

    passed = 0
    failed = 0

    print("═" * 60)
    print(" SMART ROUTER TESTS")
    print("═" * 60)

    for text, expected_route, expected_tools in tests:
        result = router.classify(text)
        
        route_ok = result.route == expected_route
        # Для tools: проверяем что нужные tools включены (могут быть лишние — ок)
        tools_ok = expected_tools.issubset(result.needed_tools) if expected_tools else True
        
        ok = route_ok and tools_ok

        if ok:
            passed += 1
            status = "✅"
        else:
            failed += 1
            status = "❌"
            print(f"  {status} '{text}'")
            print(f"     Expected: route={expected_route}, tools={expected_tools}")
            print(f"     Got:      route={result.route}, tools={result.needed_tools}")
            print(f"     Reason:   {result.reason}")

    if failed == 0:
        print(f"  ✅ ALL {passed} TESTS PASSED")
    else:
        print(f"\n  Results: {passed}/{passed+failed} passed, {failed} failed")

    print(f"\n  Stats: {router.stats}")
    print("═" * 60)
    
    return failed == 0


# ═══════════════════════════════════════════════════════════════
#  ЧАСТЬ 8: ТЕСТ DYNAMIC MAX_TOKENS
# ═══════════════════════════════════════════════════════════════

def test_dynamic_tokens():
    """Тест dynamic max_tokens"""
    print("\n═ DYNAMIC MAX_TOKENS TESTS ═")
    
    # Маленький prompt
    small = calculate_dynamic_max_tokens(
        "Ты — Animara",
        [{"role": "user", "content": "привет"}],
        context_window=32768
    )
    print(f"  Small prompt → max_tokens={small}")
    assert small > 3000, f"Too low: {small}"
    
    # Огромный prompt (YouGile scenario)
    big_system = "x" * 20000  # ~10K токенов
    big_messages = [{"role": "user", "content": "y" * 10000}]
    big = calculate_dynamic_max_tokens(
        big_system, big_messages,
        context_window=32768
    )
    print(f"  Big prompt (30K chars) → max_tokens={big}")
    assert big >= 256, f"Below minimum: {big}"
    assert big <= 4096, f"Above cap: {big}"
    
    # Обрезка tool результатов
    huge_result = "z" * 20000
    truncated = truncate_tool_result(huge_result, max_chars=8000)
    print(f"  Truncate 20K → {len(truncated)} chars")
    assert len(truncated) <= 8500  # 8000 + overhead
    assert "обрезано" in truncated
    
    print("  ✅ All dynamic token tests passed")


if __name__ == "__main__":
    all_ok = run_tests()
    test_dynamic_tokens()
    print(INTEGRATION_GUIDE)
    
    if all_ok:
        print("\n✅ Все тесты пройдены. Готово к деплою на Thor!")
    else:
        print("\n⚠️  Есть ошибки в тестах, проверь паттерны.")
