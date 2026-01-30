#!/usr/bin/env python3
"""
📋 YouGile Skill
Управление задачами в YouGile API
"""

import os
import json
import requests
from datetime import datetime
from typing import Dict, List, Optional

# Конфигурация
CONFIG_PATH = os.path.expanduser("~/animara/config/secrets.json")
DEFAULT_TOKEN = "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
API_BASE = "https://ru.yougile.com/api-v2"


def get_token() -> str:
    """Получить API токен"""
    try:
        if os.path.exists(CONFIG_PATH):
            with open(CONFIG_PATH, 'r') as f:
                config = json.load(f)
                return config.get("yougile_token", DEFAULT_TOKEN)
    except Exception:
        pass
    return DEFAULT_TOKEN


def get_headers() -> Dict[str, str]:
    """Получить заголовки для API"""
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json"
    }


# ═══════════════════════════════════════════════════════════════
# ПОЛУЧЕНИЕ ДАННЫХ
# ═══════════════════════════════════════════════════════════════

def get_tasks(limit: int = 25) -> str:
    """
    Получить список всех задач.
    
    Args:
        limit: Максимальное количество задач
        
    Returns:
        JSON строка со списком задач
    """
    try:
        response = requests.get(
            f"{API_BASE}/tasks",
            headers=get_headers(),
            timeout=15
        )
        
        if response.status_code != 200:
            return f"❌ Ошибка API: {response.status_code}"
        
        tasks = response.json().get("content", [])
        
        # Фильтруем удалённые и ограничиваем количество
        active_tasks = [
            {
                "id": t.get("id"),
                "title": t.get("title"),
                "deadline": t.get("deadline"),
                "completed": t.get("completed", False)
            }
            for t in tasks[:limit]
            if not t.get("deleted")
        ]
        
        return json.dumps(active_tasks, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"❌ Ошибка: {e}"


def get_columns() -> str:
    """
    Получить список всех колонок.
    
    Returns:
        JSON строка со списком колонок
    """
    try:
        # Сначала получаем доски
        boards_resp = requests.get(
            f"{API_BASE}/boards",
            headers=get_headers(),
            timeout=15
        )
        
        if boards_resp.status_code != 200:
            return f"❌ Ошибка получения досок: {boards_resp.status_code}"
        
        boards = boards_resp.json().get("content", [])
        
        # Для каждой доски получаем колонки
        all_columns = []
        for board in boards:
            board_id = board.get("id")
            board_title = board.get("title", "Unknown")
            
            cols_resp = requests.get(
                f"{API_BASE}/columns",
                params={"boardId": board_id},
                headers=get_headers(),
                timeout=10
            )
            
            if cols_resp.status_code == 200:
                columns = cols_resp.json().get("content", [])
                for col in columns:
                    all_columns.append({
                        "id": col.get("id"),
                        "title": col.get("title"),
                        "board": board_title
                    })
        
        return json.dumps(all_columns, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"❌ Ошибка: {e}"


def find_task(search_term: str) -> Dict:
    """
    Найти задачу по части названия.
    
    Args:
        search_term: Поисковый запрос
        
    Returns:
        Dict с данными задачи или сообщение об ошибке
    """
    try:
        response = requests.get(
            f"{API_BASE}/tasks",
            headers=get_headers(),
            timeout=15
        )
        
        if response.status_code != 200:
            return {"error": f"Ошибка API: {response.status_code}"}
        
        tasks = response.json().get("content", [])
        search_lower = search_term.lower()
        
        for task in tasks:
            if task.get("deleted"):
                continue
            title = task.get("title", "").lower()
            if search_lower in title:
                return {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "description": task.get("description") or "нет описания",
                    "deadline": task.get("deadline"),
                    "completed": task.get("completed", False)
                }
        
        return {"error": f"Задача '{search_term}' не найдена"}
        
    except Exception as e:
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# СОЗДАНИЕ И ИЗМЕНЕНИЕ
# ═══════════════════════════════════════════════════════════════

def create_task(title: str, column_id: str, description: str = "") -> str:
    """
    Создать новую задачу.
    
    Args:
        title: Название задачи
        column_id: ID колонки
        description: Описание (опционально)
        
    Returns:
        Сообщение о результате
    """
    try:
        payload = {
            "title": title,
            "columnId": column_id
        }
        if description:
            payload["description"] = description
        
        response = requests.post(
            f"{API_BASE}/tasks",
            headers=get_headers(),
            json=payload,
            timeout=15
        )
        
        if response.status_code in [200, 201]:
            task_id = response.json().get("id")
            return f"✅ Задача создана! ID: {task_id}"
        else:
            return f"❌ Ошибка создания: {response.text}"
            
    except Exception as e:
        return f"❌ Ошибка: {e}"


def move_task(task_id: str, column_id: str) -> str:
    """
    Переместить задачу в другую колонку.
    
    Args:
        task_id: ID задачи
        column_id: ID новой колонки
        
    Returns:
        Сообщение о результате
    """
    try:
        response = requests.put(
            f"{API_BASE}/tasks/{task_id}",
            headers=get_headers(),
            json={"columnId": column_id},
            timeout=15
        )
        
        if response.status_code == 200:
            return "✅ Задача перемещена"
        else:
            return f"❌ Ошибка перемещения: {response.text}"
            
    except Exception as e:
        return f"❌ Ошибка: {e}"


def append_to_description(task_id: str, text: str) -> str:
    """
    Добавить текст в конец описания задачи.
    
    Args:
        task_id: ID задачи
        text: Текст для добавления
        
    Returns:
        Сообщение о результате
    """
    try:
        # Получаем текущее описание
        response = requests.get(
            f"{API_BASE}/tasks/{task_id}",
            headers=get_headers(),
            timeout=15
        )
        
        if response.status_code != 200:
            return f"❌ Задача не найдена: {task_id}"
        
        current_description = response.json().get("description", "") or ""
        
        # Формируем новое описание
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        new_description = f"{current_description}\n\n---\n🤖 Animara ({timestamp}):\n{text}"
        
        # Обновляем задачу
        update_response = requests.put(
            f"{API_BASE}/tasks/{task_id}",
            headers=get_headers(),
            json={"description": new_description},
            timeout=15
        )
        
        if update_response.status_code == 200:
            return "✅ Информация добавлена в описание задачи"
        else:
            return f"❌ Ошибка обновления: {update_response.text}"
            
    except Exception as e:
        return f"❌ Ошибка: {e}"


def set_deadline(task_id: str, deadline: str) -> str:
    """
    Установить дедлайн задачи.
    
    Args:
        task_id: ID задачи
        deadline: Дата в формате YYYY-MM-DD
        
    Returns:
        Сообщение о результате
    """
    try:
        # Парсим дату и конвертируем в timestamp
        dt = datetime.strptime(deadline, "%Y-%m-%d")
        timestamp = int(dt.timestamp() * 1000)  # YouGile использует ms
        
        response = requests.put(
            f"{API_BASE}/tasks/{task_id}",
            headers=get_headers(),
            json={"deadline": timestamp},
            timeout=15
        )
        
        if response.status_code == 200:
            return f"✅ Дедлайн установлен: {deadline}"
        else:
            return f"❌ Ошибка: {response.text}"
            
    except ValueError:
        return "❌ Неверный формат даты. Используй: YYYY-MM-DD"
    except Exception as e:
        return f"❌ Ошибка: {e}"


def complete_task(task_id: str) -> str:
    """
    Отметить задачу как выполненную.
    
    Args:
        task_id: ID задачи
        
    Returns:
        Сообщение о результате
    """
    try:
        response = requests.put(
            f"{API_BASE}/tasks/{task_id}",
            headers=get_headers(),
            json={"completed": True},
            timeout=15
        )
        
        if response.status_code == 200:
            return "✅ Задача отмечена как выполненная"
        else:
            return f"❌ Ошибка: {response.text}"
            
    except Exception as e:
        return f"❌ Ошибка: {e}"


# ═══════════════════════════════════════════════════════════════
# УТИЛИТЫ
# ═══════════════════════════════════════════════════════════════

def get_today_tasks() -> str:
    """Получить задачи с дедлайном сегодня"""
    try:
        response = requests.get(
            f"{API_BASE}/tasks",
            headers=get_headers(),
            timeout=15
        )
        
        if response.status_code != 200:
            return f"❌ Ошибка API: {response.status_code}"
        
        tasks = response.json().get("content", [])
        today = datetime.now().date()
        
        today_tasks = []
        for task in tasks:
            if task.get("deleted") or task.get("completed"):
                continue
            
            deadline = task.get("deadline")
            if deadline:
                # YouGile хранит deadline в ms
                deadline_date = datetime.fromtimestamp(deadline / 1000).date()
                if deadline_date == today:
                    today_tasks.append({
                        "id": task.get("id"),
                        "title": task.get("title")
                    })
        
        if not today_tasks:
            return "📋 На сегодня нет задач с дедлайном"
        
        return json.dumps(today_tasks, ensure_ascii=False, indent=2)
        
    except Exception as e:
        return f"❌ Ошибка: {e}"


# CLI интерфейс для тестирования
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование:")
        print("  python main.py tasks          - список задач")
        print("  python main.py columns        - список колонок")
        print("  python main.py find <query>   - найти задачу")
        print("  python main.py today          - задачи на сегодня")
        sys.exit(1)
    
    cmd = sys.argv[1]
    
    if cmd == "tasks":
        print(get_tasks())
    elif cmd == "columns":
        print(get_columns())
    elif cmd == "find" and len(sys.argv) > 2:
        query = " ".join(sys.argv[2:])
        result = find_task(query)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    elif cmd == "today":
        print(get_today_tasks())
    else:
        print(f"Неизвестная команда: {cmd}")
