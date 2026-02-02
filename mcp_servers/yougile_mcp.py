#!/usr/bin/env python3
"""
🔧 ANIMARA YouGile MCP Server

MCP сервер для управления задачами в YouGile.
Запуск: python3 yougile_mcp.py

Функции:
- get_tasks: Список задач
- get_columns: Список колонок
- find_task: Поиск задачи
- create_task: Создать задачу
- move_task: Переместить задачу
- set_deadline: Установить дедлайн
- complete_task: Завершить задачу
- append_to_description: Добавить текст в описание
- get_today_tasks: Задачи на сегодня
"""

import os
import json
import asyncio
from datetime import datetime
from typing import Optional
import requests

# MCP SDK
try:
    from mcp.server import Server
    from mcp.server.stdio import stdio_server
    from mcp.types import Tool, TextContent
except ImportError:
    print("ERROR: MCP SDK not installed. Run: pip install mcp")
    exit(1)

# ═══════════════════════════════════════════════════════════════
# КОНФИГУРАЦИЯ
# ═══════════════════════════════════════════════════════════════

YOUGILE_API = "https://ru.yougile.com/api-v2"
YOUGILE_TOKEN = os.environ.get(
    "YOUGILE_TOKEN", 
    "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
)
HEADERS = {
    "Authorization": f"Bearer {YOUGILE_TOKEN}",
    "Content-Type": "application/json"
}

# ═══════════════════════════════════════════════════════════════
# MCP СЕРВЕР
# ═══════════════════════════════════════════════════════════════

server = Server("yougile")


# ═══════════════════════════════════════════════════════════════
# TOOLS
# ═══════════════════════════════════════════════════════════════

@server.list_tools()
async def list_tools() -> list[Tool]:
    """Список доступных инструментов"""
    return [
        Tool(
            name="get_tasks",
            description="Получить список задач из YouGile. Возвращает ID, название и статус задач.",
            inputSchema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Максимальное количество задач (default: 25)",
                        "default": 25
                    }
                }
            }
        ),
        Tool(
            name="get_columns",
            description="Получить список колонок (статусов) из YouGile. Нужен для перемещения задач.",
            inputSchema={
                "type": "object",
                "properties": {}
            }
        ),
        Tool(
            name="find_task",
            description="Найти задачу по части названия. Возвращает ID, название и описание.",
            inputSchema={
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Текст для поиска в названии задачи"
                    }
                },
                "required": ["search_term"]
            }
        ),
        Tool(
            name="create_task",
            description="Создать новую задачу в YouGile",
            inputSchema={
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название задачи"
                    },
                    "description": {
                        "type": "string",
                        "description": "Описание задачи (опционально)"
                    },
                    "column_id": {
                        "type": "string",
                        "description": "ID колонки (опционально, иначе первая колонка)"
                    }
                },
                "required": ["title"]
            }
        ),
        Tool(
            name="move_task",
            description="Переместить задачу в другую колонку (изменить статус)",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи"
                    },
                    "column_id": {
                        "type": "string",
                        "description": "ID целевой колонки"
                    }
                },
                "required": ["task_id", "column_id"]
            }
        ),
        Tool(
            name="set_deadline",
            description="Установить дедлайн для задачи",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи"
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Дата дедлайна в формате YYYY-MM-DD"
                    }
                },
                "required": ["task_id", "deadline"]
            }
        ),
        Tool(
            name="complete_task",
            description="Отметить задачу как выполненную (переместить в колонку 'Готово')",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи"
                    }
                },
                "required": ["task_id"]
            }
        ),
        Tool(
            name="append_to_description",
            description="Добавить текст в конец описания задачи",
            inputSchema={
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "ID задачи"
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст для добавления"
                    }
                },
                "required": ["task_id", "text"]
            }
        ),
        Tool(
            name="get_today_tasks",
            description="Получить задачи с дедлайном на сегодня или просроченные",
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
        if name == "get_tasks":
            result = get_tasks(arguments.get("limit", 25))
        elif name == "get_columns":
            result = get_columns()
        elif name == "find_task":
            result = find_task(arguments.get("search_term", ""))
        elif name == "create_task":
            result = create_task(
                arguments.get("title", ""),
                arguments.get("description", ""),
                arguments.get("column_id")
            )
        elif name == "move_task":
            result = move_task(
                arguments.get("task_id", ""),
                arguments.get("column_id", "")
            )
        elif name == "set_deadline":
            result = set_deadline(
                arguments.get("task_id", ""),
                arguments.get("deadline", "")
            )
        elif name == "complete_task":
            result = complete_task(arguments.get("task_id", ""))
        elif name == "append_to_description":
            result = append_to_description(
                arguments.get("task_id", ""),
                arguments.get("text", "")
            )
        elif name == "get_today_tasks":
            result = get_today_tasks()
        else:
            result = f"❌ Unknown tool: {name}"
        
        return [TextContent(type="text", text=result)]
    
    except Exception as e:
        return [TextContent(type="text", text=f"❌ Error: {str(e)}")]


# ═══════════════════════════════════════════════════════════════
# ФУНКЦИИ YOUGILE
# ═══════════════════════════════════════════════════════════════

def get_tasks(limit: int = 25) -> str:
    """Получить список задач"""
    try:
        r = requests.get(f"{YOUGILE_API}/tasks", headers=HEADERS, timeout=10)
        
        if r.status_code != 200:
            return f"❌ API Error: {r.status_code}"
        
        tasks = []
        for t in r.json().get("content", [])[:limit]:
            if t.get("deleted"):
                continue
            tasks.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "column_id": t.get("columnId"),
            })
        
        if not tasks:
            return "📋 Задач нет"
        
        output = "📋 Задачи:\n"
        for i, t in enumerate(tasks, 1):
            output += f"{i}. {t['title']} (ID: {t['id'][:8]}...)\n"
        
        return output
    
    except Exception as e:
        return f"❌ Error: {e}"


def get_columns() -> str:
    """Получить список колонок"""
    try:
        # Сначала получаем доски
        r = requests.get(f"{YOUGILE_API}/boards", headers=HEADERS, timeout=10)
        
        if r.status_code != 200:
            return f"❌ API Error: {r.status_code}"
        
        columns = []
        for board in r.json().get("content", []):
            board_id = board.get("id")
            r2 = requests.get(
                f"{YOUGILE_API}/columns?boardId={board_id}",
                headers=HEADERS,
                timeout=10
            )
            for col in r2.json().get("content", []):
                columns.append({
                    "id": col.get("id"),
                    "title": col.get("title"),
                    "board": board.get("title")
                })
        
        if not columns:
            return "📊 Колонок нет"
        
        output = "📊 Колонки:\n"
        for col in columns:
            output += f"• {col['title']} (ID: {col['id'][:8]}...) — доска: {col['board']}\n"
        
        return output
    
    except Exception as e:
        return f"❌ Error: {e}"


def find_task(search_term: str) -> str:
    """Найти задачу по названию"""
    try:
        r = requests.get(f"{YOUGILE_API}/tasks", headers=HEADERS, timeout=10)
        
        if r.status_code != 200:
            return f"❌ API Error: {r.status_code}"
        
        for t in r.json().get("content", []):
            if t.get("deleted"):
                continue
            if search_term.lower() in t.get("title", "").lower():
                return json.dumps({
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "description": t.get("description") or "нет описания",
                    "column_id": t.get("columnId")
                }, ensure_ascii=False, indent=2)
        
        return f"❌ Задача с '{search_term}' не найдена"
    
    except Exception as e:
        return f"❌ Error: {e}"


def create_task(title: str, description: str = "", column_id: Optional[str] = None) -> str:
    """Создать задачу"""
    try:
        # Если колонка не указана — берём первую
        if not column_id:
            r = requests.get(f"{YOUGILE_API}/boards", headers=HEADERS, timeout=10)
            boards = r.json().get("content", [])
            if boards:
                r2 = requests.get(
                    f"{YOUGILE_API}/columns?boardId={boards[0]['id']}",
                    headers=HEADERS,
                    timeout=10
                )
                cols = r2.json().get("content", [])
                if cols:
                    column_id = cols[0]["id"]
        
        if not column_id:
            return "❌ Не найдена колонка для создания задачи"
        
        payload = {
            "title": title,
            "columnId": column_id
        }
        if description:
            payload["description"] = description
        
        r = requests.post(
            f"{YOUGILE_API}/tasks",
            headers=HEADERS,
            json=payload,
            timeout=10
        )
        
        if r.status_code in [200, 201]:
            task_id = r.json().get("id", "")
            return f"✅ Задача создана: {title} (ID: {task_id[:8]}...)"
        else:
            return f"❌ Ошибка создания: {r.text}"
    
    except Exception as e:
        return f"❌ Error: {e}"


def move_task(task_id: str, column_id: str) -> str:
    """Переместить задачу в другую колонку"""
    try:
        r = requests.put(
            f"{YOUGILE_API}/tasks/{task_id}",
            headers=HEADERS,
            json={"columnId": column_id},
            timeout=10
        )
        
        if r.status_code == 200:
            return f"✅ Задача перемещена"
        else:
            return f"❌ Ошибка: {r.text}"
    
    except Exception as e:
        return f"❌ Error: {e}"


def set_deadline(task_id: str, deadline: str) -> str:
    """Установить дедлайн"""
    try:
        # Преобразуем в timestamp (миллисекунды)
        dt = datetime.strptime(deadline, "%Y-%m-%d")
        timestamp = int(dt.timestamp() * 1000)
        
        r = requests.put(
            f"{YOUGILE_API}/tasks/{task_id}",
            headers=HEADERS,
            json={"deadline": timestamp},
            timeout=10
        )
        
        if r.status_code == 200:
            return f"✅ Дедлайн установлен: {deadline}"
        else:
            return f"❌ Ошибка: {r.text}"
    
    except ValueError:
        return "❌ Неверный формат даты. Используйте YYYY-MM-DD"
    except Exception as e:
        return f"❌ Error: {e}"


def complete_task(task_id: str) -> str:
    """Отметить задачу выполненной"""
    try:
        # Ищем колонку "Готово" или "Done"
        columns = get_columns()
        done_column_id = None
        
        r = requests.get(f"{YOUGILE_API}/boards", headers=HEADERS, timeout=10)
        for board in r.json().get("content", []):
            r2 = requests.get(
                f"{YOUGILE_API}/columns?boardId={board['id']}",
                headers=HEADERS,
                timeout=10
            )
            for col in r2.json().get("content", []):
                title_lower = col.get("title", "").lower()
                if "готово" in title_lower or "done" in title_lower or "выполнен" in title_lower:
                    done_column_id = col["id"]
                    break
        
        if not done_column_id:
            return "❌ Не найдена колонка 'Готово'"
        
        return move_task(task_id, done_column_id)
    
    except Exception as e:
        return f"❌ Error: {e}"


def append_to_description(task_id: str, text: str) -> str:
    """Добавить текст в описание задачи"""
    try:
        # Получаем текущее описание
        r = requests.get(f"{YOUGILE_API}/tasks/{task_id}", headers=HEADERS, timeout=10)
        
        if r.status_code != 200:
            return f"❌ Задача не найдена: {r.status_code}"
        
        current = r.json().get("description") or ""
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        new_description = f"{current}\n\n---\n🤖 Animara ({timestamp}):\n{text}"
        
        r2 = requests.put(
            f"{YOUGILE_API}/tasks/{task_id}",
            headers=HEADERS,
            json={"description": new_description},
            timeout=10
        )
        
        if r2.status_code == 200:
            return "✅ Текст добавлен в описание"
        else:
            return f"❌ Ошибка: {r2.text}"
    
    except Exception as e:
        return f"❌ Error: {e}"


def get_today_tasks() -> str:
    """Получить задачи с дедлайном сегодня"""
    try:
        r = requests.get(f"{YOUGILE_API}/tasks", headers=HEADERS, timeout=10)
        
        if r.status_code != 200:
            return f"❌ API Error: {r.status_code}"
        
        today = datetime.now().date()
        today_tasks = []
        overdue_tasks = []
        
        for t in r.json().get("content", []):
            if t.get("deleted"):
                continue
            
            deadline = t.get("deadline")
            if deadline:
                dl_date = datetime.fromtimestamp(deadline / 1000).date()
                if dl_date == today:
                    today_tasks.append(t.get("title"))
                elif dl_date < today:
                    overdue_tasks.append(t.get("title"))
        
        output = ""
        if overdue_tasks:
            output += "🔴 Просрочено:\n"
            for task in overdue_tasks:
                output += f"  • {task}\n"
        
        if today_tasks:
            output += "🟡 Сегодня:\n"
            for task in today_tasks:
                output += f"  • {task}\n"
        
        if not output:
            output = "✅ Нет задач на сегодня и просроченных"
        
        return output
    
    except Exception as e:
        return f"❌ Error: {e}"


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
