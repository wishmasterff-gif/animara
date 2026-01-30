#!/usr/bin/env python3
"""
🔬 ANIMARA: Тест голоса БЕЗ RAG
   LLM напрямую (порт 8010) + Piper TTS
"""

import time
import json
import asyncio
import httpx
import re

try:
    from wyoming.client import AsyncTcpClient
    from wyoming.tts import Synthesize
    from wyoming.audio import AudioChunk, AudioStop
    HAS_WYOMING = True
except ImportError:
    HAS_WYOMING = False
    print("⚠️  Wyoming не установлен, TTS тесты пропущены")

LLM_URL = "http://localhost:8010/v1/chat/completions"
PIPER_HOST = "localhost"
PIPER_PORT = 10201

TESTS = [
    ("Привет", "простой"),
    ("Как дела?", "простой"),
    ("Спасибо!", "простой"),
    ("Сколько будет 17 * 23?", "математика"),
    ("Посчитай 15% от 3400", "математика"),
    ("Что такое Python?", "средний"),
    ("Расскажи короткий анекдот", "креатив"),
    ("Придумай название для кофейни", "креатив"),
    ("Объясни как работает нейросеть в 2 предложениях", "сложный"),
]

async def test_llm_streaming(query: str):
    payload = {
        "model": "qwen3",
        "messages": [
            {"role": "system", "content": "Ты краткий помощник. Отвечай по-русски, кратко."},
            {"role": "user", "content": query}
        ],
        "max_tokens": 300,
        "stream": True,
        "temperature": 0.7,
        "chat_template_kwargs": {"enable_thinking": False}
    }
    
    start = time.time()
    ttft = None
    first_sentence_time = None
    buffer = ""
    full_response = ""
    token_count = 0
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", LLM_URL, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                token_count += 1
                                if ttft is None:
                                    ttft = time.time() - start
                                full_response += delta
                                buffer += delta
                                if first_sentence_time is None:
                                    if re.search(r'[.!?]\s*', buffer) and len(buffer) > 5:
                                        first_sentence_time = time.time() - start
                        except:
                            pass
    except Exception as e:
        return {"error": str(e)}
    
    total = time.time() - start
    clean = re.sub(r'<think>.*?</think>', '', full_response, flags=re.DOTALL).strip()
    
    return {
        "ttft": ttft or total,
        "first_sentence": first_sentence_time or total,
        "total": total,
        "response": clean,
        "tokens": token_count
    }

async def test_full_pipeline(query: str):
    start = time.time()
    
    payload = {
        "model": "qwen3",
        "messages": [
            {"role": "system", "content": "Ты краткий помощник. Отвечай по-русски, кратко."},
            {"role": "user", "content": query}
        ],
        "max_tokens": 300,
        "stream": True,
        "temperature": 0.7,
        "chat_template_kwargs": {"enable_thinking": False}
    }
    
    ttft = None
    first_sentence_text = ""
    buffer = ""
    
    try:
        async with httpx.AsyncClient(timeout=60) as client:
            async with client.stream("POST", LLM_URL, json=payload) as resp:
                async for line in resp.aiter_lines():
                    if line.startswith("data: ") and line != "data: [DONE]":
                        try:
                            data = json.loads(line[6:])
                            delta = data.get("choices", [{}])[0].get("delta", {}).get("content", "")
                            if delta:
                                if ttft is None:
                                    ttft = time.time() - start
                                buffer += delta
                                match = re.search(r'[.!?]\s*', buffer)
                                if match and len(buffer) > 5:
                                    first_sentence_text = buffer[:match.end()].strip()
                                    break
                        except:
                            pass
    except Exception as e:
        return {"error": f"LLM: {e}"}
    
    first_sentence_time = time.time() - start
    
    if not first_sentence_text:
        first_sentence_text = buffer[:50] if buffer else "Ошибка"
    
    first_sound = None
    if HAS_WYOMING and first_sentence_text:
        try:
            async with AsyncTcpClient(PIPER_HOST, PIPER_PORT) as client:
                await client.write_event(Synthesize(text=first_sentence_text).event())
                while True:
                    event = await client.read_event()
                    if event is None or AudioStop.is_type(event.type):
                        break
                    if AudioChunk.is_type(event.type):
                        first_sound = time.time() - start
                        break
        except Exception as e:
            return {"error": f"TTS: {e}"}
    
    return {
        "ttft": ttft,
        "first_sentence": first_sentence_time,
        "first_sound": first_sound,
        "text": first_sentence_text[:50]
    }

async def run_benchmark():
    print("=" * 70)
    print("🔬 ANIMARA: ТЕСТ ГОЛОСА БЕЗ RAG")
    print("   LLM Direct (8010) + Piper TTS (10201)")
    print("=" * 70)
    
    # Проверка LLM
    print("\n📡 Проверка сервисов...")
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get("http://localhost:8010/v1/models")
            print("   ✅ LLM (8010) - OK")
    except:
        print("   ❌ LLM недоступен!")
        return
    
    if HAS_WYOMING:
        try:
            async with AsyncTcpClient(PIPER_HOST, PIPER_PORT) as c:
                print(f"   ✅ Piper TTS ({PIPER_PORT}) - OK")
        except:
            print(f"   ⚠️  Piper недоступен")
    
    # ТЕСТ 1: LLM Streaming
    print("\n" + "=" * 70)
    print("📊 ТЕСТ 1: LLM STREAMING (без RAG)")
    print("=" * 70)
    
    results = []
    for query, category in TESTS:
        r = await test_llm_streaming(query)
        if "error" in r:
            print(f"\n❌ [{category}] \"{query}\" - {r['error']}")
            continue
        
        results.append({"query": query, "category": category, **r})
        print(f"\n📍 [{category}] \"{query}\"")
        print(f"   ⚡ TTFT: {r['ttft']:.3f}s | 1st Sent: {r['first_sentence']:.3f}s | Total: {r['total']:.2f}s")
        print(f"   💬 {r['response'][:60]}...")
        await asyncio.sleep(0.2)
    
    # ТЕСТ 2: Полный Pipeline
    if HAS_WYOMING:
        print("\n" + "=" * 70)
        print("📊 ТЕСТ 2: ПОЛНЫЙ PIPELINE (LLM + TTS)")
        print("=" * 70)
        
        results_full = []
        for query, category in TESTS[:5]:
            r = await test_full_pipeline(query)
            if "error" in r:
                print(f"\n❌ [{category}] \"{query}\" - {r['error']}")
                continue
            
            results_full.append(r)
            print(f"\n📍 [{category}] \"{query}\"")
            print(f"   ⚡ TTFT: {r['ttft']:.3f}s | 1st Sent: {r['first_sentence']:.3f}s")
            print(f"   🔊 ПЕРВЫЙ ЗВУК: {r['first_sound']:.3f}s")
            print(f"   💬 \"{r['text']}\"")
            await asyncio.sleep(0.2)
    
    # ИТОГИ
    print("\n" + "=" * 70)
    print("📈 ИТОГОВАЯ ТАБЛИЦА")
    print("=" * 70)
    print(f"\n{'Запрос':<35} {'TTFT':>7} {'1st':>7} {'Total':>7}")
    print("-" * 60)
    for r in results:
        print(f"{r['query'][:33]:<35} {r['ttft']:.3f}s {r['first_sentence']:.3f}s {r['total']:.2f}s")
    
    if results:
        avg_ttft = sum(r["ttft"] for r in results) / len(results)
        avg_first = sum(r["first_sentence"] for r in results) / len(results)
        avg_total = sum(r["total"] for r in results) / len(results)
        print("-" * 60)
        print(f"{'СРЕДНЕЕ':<35} {avg_ttft:.3f}s {avg_first:.3f}s {avg_total:.2f}s")
    
    print("\n" + "=" * 70)
    print("🏆 ФИНАЛЬНЫЙ ВЕРДИКТ (БЕЗ RAG)")
    print("=" * 70)
    if results:
        print(f"\n   ⚡ TTFT:              {avg_ttft:.3f}s")
        print(f"   📝 Первое предложение: {avg_first:.3f}s")
        print(f"   ⏱️  Общее время:       {avg_total:.2f}s")
    
    if HAS_WYOMING and 'results_full' in dir() and results_full:
        avg_sound = sum(r["first_sound"] for r in results_full if r.get("first_sound")) / len([r for r in results_full if r.get("first_sound")])
        print(f"\n   🔊 ПЕРВЫЙ ЗВУК (с TTS): {avg_sound:.3f}s")
        print(f"\n   ✅ Пользователь слышит через ~{avg_sound:.2f}s")
    
    print("\n" + "=" * 70)

if __name__ == "__main__":
    asyncio.run(run_benchmark())
