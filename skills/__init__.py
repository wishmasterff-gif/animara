"""
🤖 ANIMARA SKILLS
Модульная система навыков для AI-ассистента

Skills:
- web_search: Поиск в интернете через Brave API
- exec: Выполнение shell команд
- yougile: Управление задачами YouGile
- browser: Браузерная автоматизация (Playwright)
"""

__version__ = "1.0.0"
__author__ = "Sergey Ardasenov"

# Реестр доступных skills
AVAILABLE_SKILLS = {
    "web_search": {
        "description": "Поиск в интернете через Brave API",
        "module": "skills.web_search.scripts.main",
        "functions": ["search", "search_news"]
    },
    "exec": {
        "description": "Выполнение shell команд",
        "module": "skills.exec.scripts.main",
        "functions": ["run", "run_safe", "check_docker", "check_disk", "check_memory"]
    },
    "yougile": {
        "description": "Управление задачами YouGile",
        "module": "skills.yougile.scripts.main",
        "functions": [
            "get_tasks", "get_columns", "find_task",
            "create_task", "move_task", "append_to_description",
            "set_deadline", "complete_task", "get_today_tasks"
        ]
    },
    "browser": {
        "description": "Браузерная автоматизация",
        "module": "skills.browser.scripts.main",
        "functions": ["open_page_sync", "screenshot_sync", "get_text_sync"]
    }
}


def list_skills():
    """Вывести список доступных skills"""
    print("🤖 ANIMARA SKILLS v" + __version__)
    print("=" * 50)
    for name, info in AVAILABLE_SKILLS.items():
        print(f"\n📦 {name}")
        print(f"   {info['description']}")
        print(f"   Functions: {', '.join(info['functions'])}")


if __name__ == "__main__":
    list_skills()
