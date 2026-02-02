"""
YouGile Skill Scripts

Provides YouGileClient and standalone functions for task management.

Usage:
    # Client usage
    from yougile.scripts import YouGileClient
    client = YouGileClient()
    tasks = client.get_tasks()
    
    # Standalone functions
    from yougile.scripts import get_tasks, create_task
    tasks = get_tasks(limit=10)
    
    # OpenAI tools for RAG Proxy
    from yougile.scripts import OPENAI_TOOLS, execute_tool
"""

from .yougile_client import (
    YouGileClient,
    # Tasks
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
    # Chat
    get_task_chat,
    send_message,
    # Structure
    get_columns,
    get_column,
    get_boards,
    get_board,
    get_projects,
    get_project,
    # Users
    get_users,
    get_user,
)

from .tools import (
    OPENAI_TOOLS,
    FUNCTION_MAP,
    execute_tool,
    get_tool_names,
    get_tools_for_local_llm,
)

__all__ = [
    # Client
    "YouGileClient",
    # Tasks
    "get_tasks",
    "get_task", 
    "find_task",
    "create_task",
    "update_task",
    "move_task",
    "complete_task",
    "set_deadline",
    "assign_task",
    "append_to_description",
    "get_today_tasks",
    # Chat
    "get_task_chat",
    "send_message",
    # Structure
    "get_columns",
    "get_column",
    "get_boards",
    "get_board",
    "get_projects",
    "get_project",
    # Users
    "get_users",
    "get_user",
    # OpenAI Tools
    "OPENAI_TOOLS",
    "FUNCTION_MAP",
    "execute_tool",
    "get_tool_names",
    "get_tools_for_local_llm",
]
