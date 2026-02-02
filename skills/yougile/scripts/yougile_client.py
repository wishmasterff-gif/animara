#!/usr/bin/env python3
"""
YouGile API Client

Full-featured client for YouGile REST API v2.
Provides task management, comments, projects, boards, and user operations.

Usage:
    from yougile_client import YouGileClient
    
    client = YouGileClient()
    tasks = client.get_tasks()
    client.create_task("New task", column_id="xxx")
"""

import json
import requests
from datetime import datetime, date
from typing import Optional, List, Dict, Any, Union

try:
    from .config import YOUGILE_API_KEY, YOUGILE_BASE_URL, REQUEST_TIMEOUT, DEFAULT_LIMIT
except ImportError:
    from config import YOUGILE_API_KEY, YOUGILE_BASE_URL, REQUEST_TIMEOUT, DEFAULT_LIMIT


class YouGileClient:
    """YouGile API Client with full functionality."""
    
    def __init__(self, api_key: str = None, base_url: str = None):
        self.api_key = api_key or YOUGILE_API_KEY
        self.base_url = (base_url or YOUGILE_BASE_URL).rstrip('/')
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }
    
    def _request(self, method: str, endpoint: str, data: dict = None, params: dict = None) -> Dict[str, Any]:
        """Make API request with error handling."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        
        try:
            response = requests.request(
                method=method,
                url=url,
                headers=self.headers,
                json=data,
                params=params,
                timeout=REQUEST_TIMEOUT
            )
            
            if response.status_code == 401:
                return {"error": "Unauthorized - check API key"}
            if response.status_code == 404:
                return {"error": "Not found"}
            if response.status_code >= 400:
                return {"error": f"API error {response.status_code}: {response.text[:200]}"}
            
            return response.json() if response.text else {"success": True}
            
        except requests.Timeout:
            return {"error": f"Request timeout after {REQUEST_TIMEOUT}s"}
        except requests.RequestException as e:
            return {"error": f"Request failed: {str(e)}"}
        except json.JSONDecodeError:
            return {"error": "Invalid JSON response"}
    
    def _format_result(self, data: Any, success_msg: str = None) -> str:
        """Format result for display."""
        if isinstance(data, dict) and "error" in data:
            return f"❌ Ошибка: {data['error']}"
        
        if success_msg:
            return f"✅ {success_msg}"
        
        return json.dumps(data, ensure_ascii=False, indent=2)
    
    def _parse_deadline(self, deadline: Union[str, int, date, datetime]) -> Dict[str, Any]:
        """Convert deadline to YouGile format."""
        if isinstance(deadline, str):
            # Parse ISO date string
            dt = datetime.fromisoformat(deadline.replace('Z', '+00:00'))
            ts = int(dt.timestamp() * 1000)
        elif isinstance(deadline, (date, datetime)):
            ts = int(datetime.combine(deadline, datetime.min.time()).timestamp() * 1000)
        elif isinstance(deadline, int):
            ts = deadline if deadline > 1e10 else deadline * 1000
        else:
            return None
        
        return {
            "deadline": ts,
            "startDate": None,
            "withTime": isinstance(deadline, datetime) and deadline.hour > 0
        }

    # ═══════════════════════════════════════════════════════════════
    # TASKS
    # ═══════════════════════════════════════════════════════════════
    
    def get_tasks(self, limit: int = DEFAULT_LIMIT, column_id: str = None) -> str:
        """
        Get list of tasks.
        
        Args:
            limit: Maximum number of tasks (default: 25, max: 100)
            column_id: Filter by column ID (optional)
        
        Returns:
            JSON string with tasks list
        """
        params = {"limit": min(limit, 100)}
        if column_id:
            params["columnId"] = column_id
        
        result = self._request("GET", "/tasks", params=params)
        
        if "error" in result:
            return self._format_result(result)
        
        tasks = result.get("content", [])
        active_tasks = [t for t in tasks if not t.get("deleted") and not t.get("archived")]
        
        output = []
        for t in active_tasks[:limit]:
            status = "✓" if t.get("completed") else "○"
            deadline = ""
            if t.get("deadline"):
                dl = t["deadline"].get("deadline")
                if dl:
                    deadline = f" 📅 {datetime.fromtimestamp(dl/1000).strftime('%Y-%m-%d')}"
            
            output.append({
                "id": t.get("id"),
                "title": t.get("title"),
                "completed": t.get("completed", False),
                "deadline": deadline.strip() if deadline else None,
                "subtasks": f"{t.get('subtasksDone', 0)}/{t.get('subtasks', 0)}" if t.get('subtasks') else None
            })
        
        return json.dumps(output, ensure_ascii=False, indent=2)
    
    def get_task(self, task_id: str) -> str:
        """
        Get task by ID with full details.
        
        Args:
            task_id: Task UUID
        
        Returns:
            JSON string with task details
        """
        result = self._request("GET", f"/tasks/{task_id}")
        return self._format_result(result)
    
    def find_task(self, search_term: str) -> str:
        """
        Find task by name (case-insensitive partial match).
        
        Args:
            search_term: Text to search in task titles
        
        Returns:
            JSON with found task or error
        """
        result = self._request("GET", "/tasks", params={"limit": 100})
        
        if "error" in result:
            return self._format_result(result)
        
        tasks = result.get("content", [])
        search_lower = search_term.lower()
        
        for t in tasks:
            if t.get("deleted") or t.get("archived"):
                continue
            if search_lower in t.get("title", "").lower():
                return json.dumps({
                    "id": t.get("id"),
                    "title": t.get("title"),
                    "description": t.get("description") or "нет описания",
                    "completed": t.get("completed", False),
                    "columnId": t.get("columnId")
                }, ensure_ascii=False, indent=2)
        
        return "❌ Задача не найдена"
    
    def create_task(
        self, 
        title: str, 
        column_id: str,
        description: str = None,
        deadline: Union[str, int, date, datetime] = None,
        assigned: List[str] = None
    ) -> str:
        """
        Create a new task.
        
        Args:
            title: Task title (required)
            column_id: Column UUID (required)
            description: Task description
            deadline: Deadline as YYYY-MM-DD string, timestamp, or date object
            assigned: List of user UUIDs to assign
        
        Returns:
            Success message with task ID or error
        """
        payload = {
            "title": title,
            "columnId": column_id
        }
        
        if description:
            payload["description"] = description
        
        if deadline:
            dl = self._parse_deadline(deadline)
            if dl:
                payload["deadline"] = dl
        
        if assigned:
            payload["assigned"] = assigned
        
        result = self._request("POST", "/tasks", data=payload)
        
        if "error" in result:
            return self._format_result(result)
        
        task_id = result.get("id", "unknown")
        return f"✅ Задача создана! ID: {task_id}"
    
    def update_task(
        self,
        task_id: str,
        title: str = None,
        description: str = None,
        completed: bool = None,
        deadline: Union[str, int, date, datetime] = None,
        column_id: str = None,
        assigned: List[str] = None
    ) -> str:
        """
        Update existing task.
        
        Args:
            task_id: Task UUID (required)
            title: New title
            description: New description
            completed: Mark as completed/incomplete
            deadline: New deadline
            column_id: Move to column
            assigned: New list of assignees
        
        Returns:
            Success message or error
        """
        payload = {}
        
        if title is not None:
            payload["title"] = title
        if description is not None:
            payload["description"] = description
        if completed is not None:
            payload["completed"] = completed
        if column_id is not None:
            payload["columnId"] = column_id
        if assigned is not None:
            payload["assigned"] = assigned
        if deadline is not None:
            dl = self._parse_deadline(deadline)
            if dl:
                payload["deadline"] = dl
        
        if not payload:
            return "❌ Нечего обновлять"
        
        result = self._request("PUT", f"/tasks/{task_id}", data=payload)
        
        if "error" in result:
            return self._format_result(result)
        
        return "✅ Задача обновлена"
    
    def move_task(self, task_id: str, column_id: str) -> str:
        """
        Move task to another column.
        
        Args:
            task_id: Task UUID
            column_id: Target column UUID
        
        Returns:
            Success message or error
        """
        return self.update_task(task_id, column_id=column_id)
    
    def complete_task(self, task_id: str) -> str:
        """
        Mark task as completed.
        
        Args:
            task_id: Task UUID
        
        Returns:
            Success message or error
        """
        return self.update_task(task_id, completed=True)
    
    def set_deadline(self, task_id: str, deadline: Union[str, int, date, datetime]) -> str:
        """
        Set or update task deadline.
        
        Args:
            task_id: Task UUID
            deadline: Deadline as YYYY-MM-DD, timestamp, or date object
        
        Returns:
            Success message or error
        """
        return self.update_task(task_id, deadline=deadline)
    
    def assign_task(self, task_id: str, user_ids: Union[str, List[str]]) -> str:
        """
        Assign users to task.
        
        Args:
            task_id: Task UUID
            user_ids: Single user ID or list of user IDs
        
        Returns:
            Success message or error
        """
        if isinstance(user_ids, str):
            user_ids = [user_ids]
        return self.update_task(task_id, assigned=user_ids)
    
    def append_to_description(self, task_id: str, text: str) -> str:
        """
        Append text to task description.
        
        Args:
            task_id: Task UUID
            text: Text to append
        
        Returns:
            Success message or error
        """
        # Get current description
        result = self._request("GET", f"/tasks/{task_id}")
        if "error" in result:
            return self._format_result(result)
        
        current = result.get("description", "") or ""
        timestamp = datetime.now().strftime("%d.%m.%Y %H:%M")
        new_description = f"{current}\n\n---\n🤖 Animara ({timestamp}):\n{text}"
        
        return self.update_task(task_id, description=new_description.strip())
    
    def get_today_tasks(self) -> str:
        """
        Get tasks with deadline today.
        
        Returns:
            JSON string with today's tasks
        """
        result = self._request("GET", "/tasks", params={"limit": 100})
        
        if "error" in result:
            return self._format_result(result)
        
        tasks = result.get("content", [])
        today = date.today()
        today_tasks = []
        
        for t in tasks:
            if t.get("deleted") or t.get("archived") or t.get("completed"):
                continue
            
            dl = t.get("deadline", {}).get("deadline")
            if dl:
                task_date = datetime.fromtimestamp(dl / 1000).date()
                if task_date == today:
                    today_tasks.append({
                        "id": t.get("id"),
                        "title": t.get("title"),
                        "deadline": datetime.fromtimestamp(dl/1000).strftime("%H:%M") if t.get("deadline", {}).get("withTime") else "весь день"
                    })
        
        if not today_tasks:
            return "📋 На сегодня задач нет"
        
        return json.dumps(today_tasks, ensure_ascii=False, indent=2)

    # ═══════════════════════════════════════════════════════════════
    # TASK CHAT / COMMENTS
    # ═══════════════════════════════════════════════════════════════
    
    def get_task_chat(self, task_id: str, limit: int = 20) -> str:
        """
        Get chat messages/comments for a task.
        
        Args:
            task_id: Task UUID
            limit: Maximum messages to return
        
        Returns:
            JSON string with messages
        """
        result = self._request("GET", f"/tasks/{task_id}/chat-messages", params={"limit": limit})
        
        if "error" in result:
            return self._format_result(result)
        
        messages = result.get("content", [])
        output = []
        
        for m in messages[:limit]:
            output.append({
                "id": m.get("id"),
                "text": m.get("text"),
                "userId": m.get("userId"),
                "timestamp": datetime.fromtimestamp(m.get("timestamp", 0) / 1000).strftime("%Y-%m-%d %H:%M") if m.get("timestamp") else None
            })
        
        if not output:
            return "💬 Нет комментариев"
        
        return json.dumps(output, ensure_ascii=False, indent=2)
    
    def send_message(self, task_id: str, text: str) -> str:
        """
        Send a message/comment to task chat.
        
        Args:
            task_id: Task UUID
            text: Message text
        
        Returns:
            Success message or error
        """
        result = self._request("POST", f"/tasks/{task_id}/chat-messages", data={"text": text})
        
        if "error" in result:
            return self._format_result(result)
        
        return "✅ Комментарий добавлен"

    # ═══════════════════════════════════════════════════════════════
    # COLUMNS
    # ═══════════════════════════════════════════════════════════════
    
    def get_columns(self, board_id: str = None) -> str:
        """
        Get all columns, optionally filtered by board.
        
        Args:
            board_id: Filter by board UUID (optional)
        
        Returns:
            JSON string with columns
        """
        # First get all boards if no board_id specified
        if not board_id:
            boards_result = self._request("GET", "/boards")
            if "error" in boards_result:
                return self._format_result(boards_result)
            
            all_columns = []
            for board in boards_result.get("content", []):
                cols_result = self._request("GET", "/columns", params={"boardId": board.get("id")})
                if "content" in cols_result:
                    for col in cols_result["content"]:
                        col["boardTitle"] = board.get("title")
                    all_columns.extend(cols_result["content"])
            
            return json.dumps([{
                "id": c.get("id"),
                "title": c.get("title"),
                "board": c.get("boardTitle")
            } for c in all_columns], ensure_ascii=False, indent=2)
        
        result = self._request("GET", "/columns", params={"boardId": board_id})
        
        if "error" in result:
            return self._format_result(result)
        
        columns = result.get("content", [])
        return json.dumps([{
            "id": c.get("id"),
            "title": c.get("title")
        } for c in columns], ensure_ascii=False, indent=2)
    
    def get_column(self, column_id: str) -> str:
        """
        Get column details by ID.
        
        Args:
            column_id: Column UUID
        
        Returns:
            JSON string with column details
        """
        result = self._request("GET", f"/columns/{column_id}")
        return self._format_result(result)

    # ═══════════════════════════════════════════════════════════════
    # BOARDS
    # ═══════════════════════════════════════════════════════════════
    
    def get_boards(self, project_id: str = None) -> str:
        """
        Get all boards, optionally filtered by project.
        
        Args:
            project_id: Filter by project UUID (optional)
        
        Returns:
            JSON string with boards
        """
        params = {}
        if project_id:
            params["projectId"] = project_id
        
        result = self._request("GET", "/boards", params=params if params else None)
        
        if "error" in result:
            return self._format_result(result)
        
        boards = result.get("content", [])
        return json.dumps([{
            "id": b.get("id"),
            "title": b.get("title"),
            "projectId": b.get("projectId")
        } for b in boards], ensure_ascii=False, indent=2)
    
    def get_board(self, board_id: str) -> str:
        """
        Get board details by ID.
        
        Args:
            board_id: Board UUID
        
        Returns:
            JSON string with board details
        """
        result = self._request("GET", f"/boards/{board_id}")
        return self._format_result(result)

    # ═══════════════════════════════════════════════════════════════
    # PROJECTS
    # ═══════════════════════════════════════════════════════════════
    
    def get_projects(self) -> str:
        """
        Get all projects.
        
        Returns:
            JSON string with projects list
        """
        result = self._request("GET", "/projects")
        
        if "error" in result:
            return self._format_result(result)
        
        projects = result.get("content", [])
        return json.dumps([{
            "id": p.get("id"),
            "title": p.get("title")
        } for p in projects], ensure_ascii=False, indent=2)
    
    def get_project(self, project_id: str) -> str:
        """
        Get project details by ID.
        
        Args:
            project_id: Project UUID
        
        Returns:
            JSON string with project details
        """
        result = self._request("GET", f"/projects/{project_id}")
        return self._format_result(result)

    # ═══════════════════════════════════════════════════════════════
    # USERS
    # ═══════════════════════════════════════════════════════════════
    
    def get_users(self) -> str:
        """
        Get all users in the company.
        
        Returns:
            JSON string with users list
        """
        result = self._request("GET", "/users")
        
        if "error" in result:
            return self._format_result(result)
        
        users = result.get("content", [])
        return json.dumps([{
            "id": u.get("id"),
            "email": u.get("email"),
            "name": f"{u.get('firstName', '')} {u.get('lastName', '')}".strip() or u.get("email")
        } for u in users], ensure_ascii=False, indent=2)
    
    def get_user(self, user_id: str) -> str:
        """
        Get user details by ID.
        
        Args:
            user_id: User UUID
        
        Returns:
            JSON string with user details
        """
        result = self._request("GET", f"/users/{user_id}")
        return self._format_result(result)


# ═══════════════════════════════════════════════════════════════
# STANDALONE FUNCTIONS (for tool calling)
# ═══════════════════════════════════════════════════════════════

_client = None

def _get_client() -> YouGileClient:
    """Get or create singleton client."""
    global _client
    if _client is None:
        _client = YouGileClient()
    return _client

# Tasks
def get_tasks(limit: int = 25) -> str:
    """Get list of tasks."""
    return _get_client().get_tasks(limit)

def get_task(task_id: str) -> str:
    """Get task by ID."""
    return _get_client().get_task(task_id)

def find_task(search_term: str) -> str:
    """Find task by name."""
    return _get_client().find_task(search_term)

def create_task(title: str, column_id: str, description: str = None, deadline: str = None) -> str:
    """Create a new task."""
    return _get_client().create_task(title, column_id, description, deadline)

def update_task(task_id: str, title: str = None, description: str = None, completed: bool = None, deadline: str = None) -> str:
    """Update existing task."""
    return _get_client().update_task(task_id, title, description, completed, deadline)

def move_task(task_id: str, column_id: str) -> str:
    """Move task to column."""
    return _get_client().move_task(task_id, column_id)

def complete_task(task_id: str) -> str:
    """Mark task as completed."""
    return _get_client().complete_task(task_id)

def set_deadline(task_id: str, deadline: str) -> str:
    """Set task deadline (YYYY-MM-DD)."""
    return _get_client().set_deadline(task_id, deadline)

def assign_task(task_id: str, user_id: str) -> str:
    """Assign user to task."""
    return _get_client().assign_task(task_id, user_id)

def append_to_description(task_id: str, text: str) -> str:
    """Append text to task description."""
    return _get_client().append_to_description(task_id, text)

def get_today_tasks() -> str:
    """Get tasks with deadline today."""
    return _get_client().get_today_tasks()

# Chat
def get_task_chat(task_id: str, limit: int = 20) -> str:
    """Get task comments."""
    return _get_client().get_task_chat(task_id, limit)

def send_message(task_id: str, text: str) -> str:
    """Send comment to task."""
    return _get_client().send_message(task_id, text)

# Structure
def get_columns() -> str:
    """Get all columns."""
    return _get_client().get_columns()

def get_column(column_id: str) -> str:
    """Get column by ID."""
    return _get_client().get_column(column_id)

def get_boards() -> str:
    """Get all boards."""
    return _get_client().get_boards()

def get_board(board_id: str) -> str:
    """Get board by ID."""
    return _get_client().get_board(board_id)

def get_projects() -> str:
    """Get all projects."""
    return _get_client().get_projects()

def get_project(project_id: str) -> str:
    """Get project by ID."""
    return _get_client().get_project(project_id)

# Users
def get_users() -> str:
    """Get all users."""
    return _get_client().get_users()

def get_user(user_id: str) -> str:
    """Get user by ID."""
    return _get_client().get_user(user_id)


if __name__ == "__main__":
    # Quick test
    client = YouGileClient()
    print("=== Tasks ===")
    print(client.get_tasks(limit=5))
    print("\n=== Columns ===")
    print(client.get_columns())
