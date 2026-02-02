"""
YouGile OpenAI-Compatible Tool Definitions

This module provides tool definitions in OpenAI format for use with
RAG Proxy or any OpenAI-compatible API.

Usage in RAG Proxy:
    from yougile.scripts.tools import OPENAI_TOOLS, execute_tool
    
    # Add tools to LLM request
    response = llm.chat.completions.create(
        model="qwen3",
        messages=messages,
        tools=OPENAI_TOOLS
    )
    
    # Execute tool call
    result = execute_tool(tool_name, arguments)
"""

from typing import Dict, Any, List
import json

# Import all functions
from .yougile_client import (
    get_tasks,
    get_task,
    find_task,
    create_task,
    update_task,
    move_task,
    complete_task,
    set_deadline,
    assign_task,
    append_to_description,
    get_today_tasks,
    get_task_chat,
    send_message,
    get_columns,
    get_column,
    get_boards,
    get_board,
    get_projects,
    get_project,
    get_users,
    get_user,
)


# ═══════════════════════════════════════════════════════════════
# OPENAI TOOL DEFINITIONS
# ═══════════════════════════════════════════════════════════════

OPENAI_TOOLS: List[Dict[str, Any]] = [
    # ─── Tasks ───
    {
        "type": "function",
        "function": {
            "name": "yougile_get_tasks",
            "description": "Получить список задач из YouGile. Используй когда пользователь просит показать задачи, список дел или спрашивает 'что делать'.",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Количество задач (по умолчанию 25, макс 100)",
                        "default": 25
                    }
                },
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_find_task",
            "description": "Найти задачу по названию (частичное совпадение). Используй когда нужно найти конкретную задачу по ключевым словам.",
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Текст для поиска в названиях задач"
                    }
                },
                "required": ["search_term"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_create_task",
            "description": "Создать новую задачу в YouGile. ВАЖНО: Если пользователь НЕ указал колонку, СПРОСИ его: \"В какую колонку? Бэклог, В работе, Готово?\" или предложи Бэклог по умолчанию. Для получения ID колонки вызови yougile_get_columns.",
            "parameters": {
                "type": "object",
                "properties": {
                    "title": {
                        "type": "string",
                        "description": "Название задачи"
                    },
                    "column_id": {
                        "type": "string",
                        "description": "UUID колонки (получи через yougile_get_columns)"
                    },
                    "description": {
                        "type": "string",
                        "description": "Описание задачи (опционально)"
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Дедлайн в формате YYYY-MM-DD (опционально)"
                    }
                },
                "required": ["title", "column_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_move_task",
            "description": "Переместить задачу в другую колонку. Используй когда пользователь просит переместить задачу или изменить её статус.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    },
                    "column_id": {
                        "type": "string",
                        "description": "UUID целевой колонки"
                    }
                },
                "required": ["task_id", "column_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_complete_task",
            "description": "Отметить задачу как выполненную.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_set_deadline",
            "description": "Установить или изменить дедлайн задачи.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    },
                    "deadline": {
                        "type": "string",
                        "description": "Дедлайн в формате YYYY-MM-DD"
                    }
                },
                "required": ["task_id", "deadline"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_assign_task",
            "description": "Назначить исполнителя на задачу. Сначала получи список пользователей через yougile_get_users.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    },
                    "user_id": {
                        "type": "string",
                        "description": "UUID пользователя"
                    }
                },
                "required": ["task_id", "user_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_append_to_description",
            "description": "Добавить текст в конец описания задачи. Полезно для добавления результатов исследования или заметок.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст для добавления"
                    }
                },
                "required": ["task_id", "text"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_get_today_tasks",
            "description": "Получить задачи с дедлайном на сегодня. Используй когда пользователь спрашивает 'что на сегодня' или 'какие задачи на сегодня'.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    # ─── Chat / Comments ───
    {
        "type": "function",
        "function": {
            "name": "yougile_get_task_chat",
            "description": "Получить комментарии к задаче.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Количество комментариев (по умолчанию 20)",
                        "default": 20
                    }
                },
                "required": ["task_id"]
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_send_message",
            "description": "Отправить комментарий к задаче.",
            "parameters": {
                "type": "object",
                "properties": {
                    "task_id": {
                        "type": "string",
                        "description": "UUID задачи"
                    },
                    "text": {
                        "type": "string",
                        "description": "Текст комментария"
                    }
                },
                "required": ["task_id", "text"]
            }
        }
    },
    # ─── Structure ───
    {
        "type": "function",
        "function": {
            "name": "yougile_get_columns",
            "description": "Получить список всех колонок (статусов). Используй чтобы узнать column_id перед созданием или перемещением задачи.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_get_boards",
            "description": "Получить список всех досок.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "yougile_get_projects",
            "description": "Получить список всех проектов.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
    # ─── Users ───
    {
        "type": "function",
        "function": {
            "name": "yougile_get_users",
            "description": "Получить список пользователей компании. Используй перед назначением исполнителя.",
            "parameters": {
                "type": "object",
                "properties": {},
                "required": []
            }
        }
    },
]


# ═══════════════════════════════════════════════════════════════
# TOOL EXECUTION
# ═══════════════════════════════════════════════════════════════

FUNCTION_MAP = {
    "yougile_get_tasks": get_tasks,
    "yougile_get_task": get_task,
    "yougile_find_task": find_task,
    "yougile_create_task": create_task,
    "yougile_update_task": update_task,
    "yougile_move_task": move_task,
    "yougile_complete_task": complete_task,
    "yougile_set_deadline": set_deadline,
    "yougile_assign_task": assign_task,
    "yougile_append_to_description": append_to_description,
    "yougile_get_today_tasks": get_today_tasks,
    "yougile_get_task_chat": get_task_chat,
    "yougile_send_message": send_message,
    "yougile_get_columns": get_columns,
    "yougile_get_column": get_column,
    "yougile_get_boards": get_boards,
    "yougile_get_board": get_board,
    "yougile_get_projects": get_projects,
    "yougile_get_project": get_project,
    "yougile_get_users": get_users,
    "yougile_get_user": get_user,
}


def execute_tool(tool_name: str, arguments: Dict[str, Any]) -> str:
    """
    Execute a YouGile tool by name.
    
    Args:
        tool_name: Name of the tool (e.g., "yougile_get_tasks")
        arguments: Dictionary of arguments
    
    Returns:
        Result string from the tool
    """
    if tool_name not in FUNCTION_MAP:
        return f"❌ Unknown tool: {tool_name}"
    
    func = FUNCTION_MAP[tool_name]
    
    try:
        # Filter out None values and call function
        filtered_args = {k: v for k, v in arguments.items() if v is not None}
        return func(**filtered_args)
    except TypeError as e:
        return f"❌ Invalid arguments: {e}"
    except Exception as e:
        return f"❌ Tool error: {e}"


def get_tool_names() -> List[str]:
    """Get list of all available tool names."""
    return list(FUNCTION_MAP.keys())


def get_tools_for_local_llm() -> str:
    """
    Get tool descriptions formatted for local LLM (Qwen3).
    Returns a compact prompt describing available tools.
    """
    tools_desc = []
    for tool in OPENAI_TOOLS:
        func = tool["function"]
        name = func["name"]
        desc = func["description"]
        params = func["parameters"].get("properties", {})
        required = func["parameters"].get("required", [])
        
        param_strs = []
        for pname, pinfo in params.items():
            req = "*" if pname in required else ""
            param_strs.append(f"{pname}{req}")
        
        params_str = f"({', '.join(param_strs)})" if param_strs else "()"
        tools_desc.append(f"• {name}{params_str} — {desc}")
    
    tools_list = "\n".join(tools_desc)
    
    instructions = """
### ⚠️ ВАЖНЫЕ ПРАВИЛА для YouGile:

1. **ЗАПОМНИ task_id** — когда находишь задачу через find_task, СОХРАНИ её ID для следующих операций!

2. **Сложные запросы** — выполняй ВСЕ шаги по порядку:
   - "Найди задачу и добавь информацию" → find_task → append_to_description
   - "Поставь дедлайн и добавь описание" → find_task → set_deadline → append_to_description
   
3. **НЕ ВЫДУМЫВАЙ task_id** — используй ТОЛЬКО ID полученный от find_task или get_tasks!

4. **Проверяй результат** — после append_to_description можешь вызвать get_task чтобы убедиться.

Пример правильной последовательности:
1. <tool>{"name": "yougile_find_task", "params": {"search_term": "молоко"}}</tool>
   → Получаем ID: "abc-123"
2. <tool>{"name": "yougile_append_to_description", "params": {"task_id": "abc-123", "text": "Информация..."}}</tool>
"""
    
    return tools_list + instructions


if __name__ == "__main__":
    # Print tool definitions
    print("=== Available YouGile Tools ===\n")
    print(get_tools_for_local_llm())
    
    print("\n\n=== OpenAI Tool Count ===")
    print(f"Total tools: {len(OPENAI_TOOLS)}")
