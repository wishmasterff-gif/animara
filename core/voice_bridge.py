#!/usr/bin/env python3
"""
ANIMARA Voice Bridge v1.0
Микрофон → Riva ASR → RAG Proxy → Piper TTS → Динамик
"""

import asyncio
import wave
import subprocess
import tempfile
import httpx
import re
import time
import os

# Wyoming для Piper
from wyoming.client import AsyncTcpClient
from wyoming.tts import Synthesize
from wyoming.audio import AudioChunk, AudioStop

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

CONFIG = {
    "riva_container": "riva-speech",
    "piper_host": "localhost",
    "piper_port": 10201,
    "rag_proxy_url": "http://localhost:8015/v1/chat/completions",
    "mic_device": "plughw:2,0",  # JETE-W7 webcam
    "record_seconds": 5,
    "sample_rate": 16000,
}

# Филлеры для быстрого ответа
FILLERS = [
    "Хм, интересно...",
    "Дай подумаю...",
    "Секунду...",
    "Так...",
]

# ═══════════════════════════════════════════════════════════════
# ASR (Speech-to-Text)
# ═══════════════════════════════════════════════════════════════

def record_audio(duration: int = 5) -> str:
    """Записать аудио с микрофона"""
    print(f"🎤 Говори {duration} секунд...")
    
    temp_file = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    temp_path = temp_file.name
    temp_file.close()
    
    cmd = [
        "arecord",
        "-D", CONFIG["mic_device"],
        "-f", "S16_LE",
        "-c", "1",
        "-r", str(CONFIG["sample_rate"]),
        "-d", str(duration),
        temp_path
    ]
    
    subprocess.run(cmd, capture_output=True)
    print("✅ Записано!")
    return temp_path

def transcribe_audio(audio_path: str) -> str:
    """Распознать речь через Riva ASR"""
    print("🔄 Распознаю речь...")
    
    # Копируем файл в контейнер
    subprocess.run([
        "docker", "cp", audio_path, 
        f"{CONFIG['riva_container']}:/tmp/audio.wav"
    ], capture_output=True)
    
    # Запускаем ASR
    result = subprocess.run([
        "docker", "exec", CONFIG["riva_container"],
        "riva_streaming_asr_client",
        "--audio_file=/tmp/audio.wav",
        "--language_code=ru-RU"
    ], capture_output=True, text=True)
    
    # Парсим результат
    output = result.stdout
    
    # Ищем "Final transcripts:"
    match = re.search(r'Final transcripts:\s*\n\d+\s*:\s*(.+?)(?:\n\n|\nTimestamps)', output, re.DOTALL)
    if match:
        text = match.group(1).strip()
        print(f"📝 Распознано: {text}")
        return text
    
    print("❌ Не удалось распознать")
    return ""

# ═══════════════════════════════════════════════════════════════
# LLM (RAG Proxy)
# ═══════════════════════════════════════════════════════════════

async def ask_llm(text: str, person_id: str = "owner_sergey") -> str:
    """Отправить вопрос в RAG Proxy"""
    print("🤔 Думаю...")
    
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            CONFIG["rag_proxy_url"],
            json={
                "model": "qwen3",
                "person_id": person_id,
                "messages": [{"role": "user", "content": text}]
            }
        )
        data = response.json()
        content = data["choices"][0]["message"]["content"]
        
        # Убираем <think> теги
        content = re.sub(r'<think>.*?</think>', '', content, flags=re.DOTALL).strip()
        
        print(f"💬 Ответ: {content[:100]}...")
        return content

# ═══════════════════════════════════════════════════════════════
# TTS (Text-to-Speech)
# ═══════════════════════════════════════════════════════════════

async def speak(text: str):
    """Озвучить текст через Piper"""
    print(f"🔊 Озвучиваю...")
    
    async with AsyncTcpClient(CONFIG["piper_host"], CONFIG["piper_port"]) as client:
        await client.write_event(Synthesize(text=text).event())
        
        audio_data = b""
        
        while True:
            event = await client.read_event()
            if event is None:
                break
            
            if AudioChunk.is_type(event.type):
                chunk = AudioChunk.from_event(event)
                audio_data += chunk.audio
            elif AudioStop.is_type(event.type):
                break
        
        if audio_data:
            # Сохраняем и проигрываем
            with wave.open("/tmp/response.wav", "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(22050)
                wav.writeframes(audio_data)
            
            subprocess.run(["aplay", "-D", "plughw:3,0", "/tmp/response.wav"], capture_output=True)

# ═══════════════════════════════════════════════════════════════
# MAIN LOOP
# ═══════════════════════════════════════════════════════════════

async def voice_loop():
    """Основной цикл голосового общения"""
    print("=" * 60)
    print("🤖 ANIMARA VOICE BRIDGE")
    print("=" * 60)
    print("Нажми Enter чтобы начать говорить (Ctrl+C для выхода)")
    print()
    
    while True:
        try:
            input(">>> Нажми Enter и говори...")
            
            # 1. Записываем голос
            audio_path = record_audio(CONFIG["record_seconds"])
            
            # 2. Распознаём речь
            text = transcribe_audio(audio_path)
            
            if not text:
                await speak("Извините, я не расслышала. Повторите, пожалуйста.")
                continue
            
            # 3. Получаем ответ от LLM
            response = await ask_llm(text)
            
            # 4. Озвучиваем ответ
            await speak(response)
            
            # Cleanup
            os.unlink(audio_path)
            
            print()
            
        except KeyboardInterrupt:
            print("\n\n👋 До свидания!")
            break
        except Exception as e:
            print(f"❌ Ошибка: {e}")

if __name__ == "__main__":
    asyncio.run(voice_loop())
