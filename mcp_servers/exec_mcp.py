#!/usr/bin/env python3
"""
🔧 ANIMARA Exec MCP Server

MCP сервер для выполнения shell команд с защитой от опасных операций.
Запуск: python3 exec_mcp.py

Функции:
- run: Выполнить shell команду
- docker_ps: Показать Docker контейнеры
- disk_usage: Показать использование диска
- memory_usage: Показать использование памяти
- gpu_status: Показать статус GPU (nvidia-smi)
"""

import os
import asyncio
import subprocess
import shlex
from typing import Optional

# MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp")
    exit(1)

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ БЕЗОПАСНОСТИ
# ═══════════════════════════════════════════════════════════════

# Команды, которые ЗАПРЕЩЕНЫ полностью
BLOCKED_COMMANDS = [
    "rm -rf /",
    "rm -rf /*",
    "mkfs",
    "> /dev/sda",
    "dd if=/dev/zero",
    ":(){:|:&};:",  # Fork bomb
    "chmod -R 777 /",
    "chown -R",
]

# Паттерны, которые требуют подтверждения (но мы их просто блокируем)
DANGEROUS_PATTERNS = [
    "rm -rf",
    "rm -r /",
    "sudo rm",
    "sudo mkfs",
    "sudo dd",
    "shutdown",
    "reboot",
    "init 0",
    "init 6",
    "systemctl stop",
    "kill -9 1",
]

# Максимальный timeout
MAX_TIMEOUT = 60

# ═══════════════════════════════════════════════════════════════
# MCP СЕРВЕР
# ═══════════════════════════════════════════════════════════════

server = Server("exec")


@server.list_tools()
async def list_tools() -> list[Tool]:
    """Список доступных инструментов"""
    return [
        Tool(
            name="run",
            description="Выполнить shell команду. Опасные команды (rm -rf, sudo rm) заблокированы для безопасности.",
            inputSchema={
                "type": "object",
                "properties": {
                    "command": {
                        "type": "string",
                        "description": "Shell команда для выполнения"
                    },
                    "timeout": {
                        "type": "integer",
                        "description": "Таймаут в секундах (default: 30, max: 60)",
                        "default": 30
                    }
                },
                "required": ["command"]
            }
        ),
        Tool(
            name="docker_ps",
            description="Показать список Docker контейнеров",
            inputSchema={
                "type": "object",
                "properties": {
                    "all": {
                        "type": "boolean",
                        "description": "Показать все контейнеры включая остановленные",
                        "default": False
                    }
                }
            }
        ),
        Tool(
            name="disk_usage",
            description="Показать использование дискового пространства",
            inputSchema={
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Путь для проверки (default: /)",
                        "default": "/"
                    }
                }
            }
        ),
        Tool(
            name="memory_usage",
            description="Показать использование оперативной памяти",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="gpu_status",
            description="Показать статус GPU через nvidia-smi",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    """Обработчик вызовов инструментов"""
    
    try:
        if name == "run":
            result = run_command(
                arguments.get("command", ""),
                arguments.get("timeout", 30)
            )
        elif name == "docker_ps":
            result = docker_ps(arguments.get("all", False))
        elif name == "disk_usage":
            result = disk_usage(arguments.get("path", "/"))
        elif name == "memory_usage":
            result = memory_usage()
        elif name == "gpu_status":
            result = gpu_status()
        else:
            result = f"❌ Unknown tool: {name}"
        
        return [TextContent(type="text", text=result)]
    
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]


# ═══════════════════════════════════════════════════════════════
# ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════

def is_command_safe(command: str) -> tuple[bool, str]:
    """Проверить безопасность команды"""
    
    cmd_lower = command.lower().strip()
    
    # Проверяем полные блокированные команды
    for blocked in BLOCKED_COMMANDS:
        if blocked in cmd_lower:
            return False, f"⛔ Команда заблокирована: содержит '{blocked}'"
    
    # Проверяем опасные паттерны
    for pattern in DANGEROUS_PATTERNS:
        if pattern in cmd_lower:
            return False, f"⛔ Опасная команда: содержит '{pattern}'. Требуется ручное выполнение."
    
    return True, ""


def run_command(command: str, timeout: int = 30) -> str:
    """Выполнить shell команду"""
    
    if not command.strip():
        return "❌ Пустая команда"
    
    # Проверка безопасности
    is_safe, error_msg = is_command_safe(command)
    if not is_safe:
        return error_msg
    
    # Ограничиваем timeout
    timeout = min(timeout, MAX_TIMEOUT)
    
    try:
        # Выполняем команду
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=os.path.expanduser("~")
        )
        
        output = ""
        if result.stdout:
            output += result.stdout
        if result.stderr:
            if output:
                output += "\n--- STDERR ---\n"
            output += result.stderr
        
        if not output:
            output = "(команда выполнена, вывод пустой)"
        
        # Ограничиваем размер вывода
        if len(output) > 5000:
            output = output[:5000] + "\n... (вывод обрезан)"
        
        return f"$ {command}\n\n{output}"
    
    except subprocess.TimeoutExpired:
        return f"❌ Таймаут: команда выполнялась дольше {timeout} секунд"
    except Exception as e:
        return f"❌ Ошибка выполнения: {e}"


def docker_ps(show_all: bool = False) -> str:
    """Показать Docker контейнеры"""
    
    cmd = "docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
    if show_all:
        cmd = "docker ps -a --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'"
    
    return run_command(cmd)


def disk_usage(path: str = "/") -> str:
    """Показать использование диска"""
    
    # Защита от путей с опасными символами
    safe_path = shlex.quote(path)
    return run_command(f"df -h {safe_path}")


def memory_usage() -> str:
    """Показать использование памяти"""
    
    return run_command("free -h")


def gpu_status() -> str:
    """Показать статус GPU"""
    
    return run_command("nvidia-smi --query-gpu=name,memory.used,memory.total,utilization.gpu --format=csv,noheader,nounits")


# ═══════════════════════════════════════════════════════════════
# ЗАПУСК
# ═══════════════════════════════════════════════════════════════

async def main():
    """Запуск MCP сервера"""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    asyncio.run(main())
