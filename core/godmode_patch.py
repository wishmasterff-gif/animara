#!/usr/bin/env python3
"""
⚡ ANIMARA GOD MODE PATCH v10.5
Codex CLI integration
"""

import os
import re
import asyncio
from typing import List, Optional

GODMODE_CONFIG = {
    "model": "gpt-5.2-codex",
    "timeout": 180,
}

def check_godmode_command(text: str) -> Optional[str]:
    text_lower = text.lower().strip()
    
    for pattern in [r"отключи.*бога", r"выключи.*бога", r"/local", r"/godmode\s+off"]:
        if re.search(pattern, text_lower):
            return "deactivate"
    
    for pattern in [r"режим\s+бога", r"god\s*mode", r"/god$", r"/godmode$", r"включи.*бога", r"активируй.*бога"]:
        if re.search(pattern, text_lower):
            return "activate"
    
    return None


async def call_chatgpt_codex(messages: List[dict], system_prompt: str = "") -> dict:
    """Вызывает GPT-5.2 через Codex CLI."""
    
    user_query = "Привет"
    for msg in reversed(messages):
        if msg.get("role") == "user":
            user_query = msg.get("content", "Привет")
            break
    
    escaped_query = user_query.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
    
    if len(escaped_query) > 4000:
        escaped_query = escaped_query[:4000]
    
    try:
        # Используем bash -c с полным путём к codex
        codex_path = os.path.expanduser("~/.nvm/versions/node/v20.20.0/bin/codex")
        cmd = f'{codex_path} exec "{escaped_query}" --model {GODMODE_CONFIG["model"]} --skip-git-repo-check 2>&1'
        
        print(f"🚀 God Mode: {user_query[:50]}...")
        
        process = await asyncio.create_subprocess_shell(
            cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            executable="/bin/bash"
        )
        
        stdout, stderr = await asyncio.wait_for(
            process.communicate(),
            timeout=GODMODE_CONFIG["timeout"]
        )
        
        output = stdout.decode('utf-8').strip()
        
        if not output:
            error = stderr.decode('utf-8').strip()
            return {"choices": [{"message": {"content": f"❌ Codex error: {error}"}}]}
        
        response_text = parse_codex_output(output)
        
        print(f"✅ God Mode: {response_text[:80]}...")
        
        return {
            "choices": [{"message": {"content": f"⚡ {response_text}", "role": "assistant"}}],
            "model": GODMODE_CONFIG["model"],
            "god_mode": True
        }
        
    except asyncio.TimeoutError:
        return {"choices": [{"message": {"content": "❌ Таймаут (3 мин)"}}]}
    except Exception as e:
        print(f"❌ God Mode error: {e}")
        return {"choices": [{"message": {"content": f"❌ Ошибка: {e}"}}]}


def parse_codex_output(output: str) -> str:
    """Извлекает ответ из вывода Codex CLI."""
    lines = output.split('\n')
    
    in_response = False
    response_lines = []
    
    for line in lines:
        stripped = line.strip()
        
        if stripped == 'codex':
            in_response = True
            continue
        
        if stripped.startswith('tokens used'):
            break
        
        if in_response and stripped:
            if stripped.startswith(('workdir:', 'model:', 'provider:', 'sandbox:', 'session id:')):
                continue
            response_lines.append(line)
    
    result = '\n'.join(response_lines).strip()
    
    if not result:
        for line in reversed(lines):
            stripped = line.strip()
            if stripped and not stripped.startswith(('tokens used', 'workdir:', 'model:', 'provider')):
                result = stripped
                break
    
    return result or "Нет ответа"


if __name__ == "__main__":
    print("✅ God Mode patch loaded")
