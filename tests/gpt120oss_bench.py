#!/usr/bin/env python3
"""GPT-120-OSS Benchmark for Jetson AGX Thor"""

import requests
import time
from datetime import datetime

API_URL = "http://127.0.0.1:8010/v1/chat/completions"
MODEL = "gpt120oss"

def chat(messages, max_tokens=256, temperature=0.7, reasoning=None):
    if reasoning and messages[0]["role"] == "system":
        messages[0]["content"] = f"Reasoning: {reasoning}\n\n" + messages[0]["content"]
    
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens, "temperature": temperature, "stream": False}
    
    start = time.time()
    try:
        resp = requests.post(API_URL, json=payload, timeout=120)
        data = resp.json()
    except Exception as e:
        return None, 0, 0, str(e)
    
    total_time = time.time() - start
    content = data["choices"][0]["message"]["content"]
    tokens = data.get("usage", {}).get("completion_tokens", 0)
    tps = tokens / total_time if total_time > 0 else 0
    return content, total_time, tokens, tps

def run():
    print("=" * 60)
    print("🚀 GPT-120-OSS BENCHMARK")
    print("=" * 60)
    
    # Check API
    try:
        r = requests.get("http://127.0.0.1:8010/v1/models", timeout=10)
        print(f"✅ API OK: {r.json()['data'][0]['id']}")
    except Exception as e:
        print(f"❌ API Error: {e}")
        return
    
    tests = [
        ("Greeting", [{"role":"system","content":"Be concise."},{"role":"user","content":"Привет!"}], 50, None),
        ("Reasoning LOW", [{"role":"system","content":"Assistant"},{"role":"user","content":"What is 15% of 3400?"}], 100, "low"),
        ("Reasoning MED", [{"role":"system","content":"Assistant"},{"role":"user","content":"A train leaves at 9AM at 80km/h. Another leaves 700km away at 10AM at 100km/h toward it. When do they meet?"}], 300, "medium"),
        ("Reasoning HIGH", [{"role":"system","content":"Think step by step."},{"role":"user","content":"A,B,C have red,blue,green hats. A:'not red' B:'not blue' C:'not green'. One lies. Who has what?"}], 500, "high"),
        ("Code Gen", [{"role":"system","content":"Python expert"},{"role":"user","content":"Write Sieve of Eratosthenes in Python"}], 400, "medium"),
        ("Long 500tok", [{"role":"system","content":"Assistant"},{"role":"user","content":"Explain voice AI architecture: ASR, NLU, TTS in detail."}], 500, "low"),
        ("Russian", [{"role":"system","content":"Отвечай на русском."},{"role":"user","content":"Расскажи про Animara - голосового робота на Jetson."}], 200, None),
    ]
    
    results = []
    for name, msgs, max_tok, reason in tests:
        print(f"\n📝 {name}...")
        content, t, tok, tps = chat(msgs, max_tok, reasoning=reason)
        print(f"   ⏱️ {t:.2f}s | {tok} tok | {tps:.1f} t/s")
        print(f"   💬 {content[:80] if content else 'ERROR'}...")
        results.append((name, t, tok, tps))
    
    print("\n" + "=" * 60)
    print("📊 SUMMARY")
    print("=" * 60)
    total_t, total_tok = 0, 0
    for name, t, tok, tps in results:
        print(f"{name:<16} {t:>6.2f}s {tok:>5} tok {tps:>6.1f} t/s")
        total_t += t; total_tok += tok
    print("-" * 50)
    print(f"{'TOTAL':<16} {total_t:>6.2f}s {total_tok:>5} tok {total_tok/total_t:.1f} t/s")

if __name__ == "__main__":
    run()
