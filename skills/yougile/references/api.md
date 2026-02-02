# YouGile API v2 Reference

Полная документация по YouGile REST API.

## Base URL

```
https://ru.yougile.com/api-v2
```

Для международной версии: `https://yougile.com/api-v2`

## Authentication

Все запросы требуют Bearer token в заголовке:

```
Authorization: Bearer YOUR_API_KEY
Content-Type: application/json
```

### Получение API Key

```bash
curl -X POST "https://yougile.com/api-v2/auth/keys" \
  -H "Content-Type: application/json" \
  -d '{
    "login": "your_email@example.com",
    "password": "your_password",
    "companyName": "Your Company Name"
  }'
```

## Endpoints

### Tasks

#### GET /tasks
Список задач.

**Query params:**
- `limit` (int): Количество (default: 25, max: 100)
- `offset` (int): Смещение для пагинации
- `columnId` (uuid): Фильтр по колонке

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "title": "Task title",
      "description": "Description",
      "columnId": "uuid",
      "completed": false,
      "archived": false,
      "deleted": false,
      "deadline": {
        "deadline": 1707955200000,
        "startDate": null,
        "withTime": false
      },
      "assigned": ["user-uuid"],
      "subtasks": 3,
      "subtasksDone": 1,
      "stickers": ["sticker-uuid"],
      "stopwatch": null,
      "timer": null,
      "createdBy": "user-uuid",
      "timestamp": 1707955200000
    }
  ],
  "paging": {
    "limit": 25,
    "offset": 0,
    "count": 100
  }
}
```

#### GET /tasks/{id}
Получить задачу по ID.

#### POST /tasks
Создать задачу.

**Body:**
```json
{
  "title": "Task title",
  "columnId": "uuid",
  "description": "Description",
  "deadline": {
    "deadline": 1707955200000,
    "startDate": null,
    "withTime": false
  },
  "assigned": ["user-uuid"],
  "stickers": ["sticker-uuid"]
}
```

**Required fields:** `title`, `columnId`

#### PUT /tasks/{id}
Обновить задачу.

**Body:** Любые поля из POST (все опциональны)

#### DELETE /tasks/{id}
Удалить задачу (soft delete).

---

### Task Chat / Comments

#### GET /tasks/{taskId}/chat-messages
Получить комментарии к задаче.

**Query params:**
- `limit` (int): Количество сообщений

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "text": "Message text",
      "userId": "uuid",
      "timestamp": 1707955200000,
      "edited": false,
      "reactions": []
    }
  ]
}
```

#### POST /tasks/{taskId}/chat-messages
Отправить комментарий.

**Body:**
```json
{
  "text": "Comment text"
}
```

---

### Columns

#### GET /columns
Список колонок.

**Query params:**
- `boardId` (uuid): Фильтр по доске (обязательно)

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "title": "To Do",
      "boardId": "uuid",
      "color": "#FF5733",
      "position": 0
    }
  ]
}
```

#### GET /columns/{id}
Колонка по ID.

#### POST /columns
Создать колонку.

**Body:**
```json
{
  "title": "Column name",
  "boardId": "uuid",
  "color": "#FF5733"
}
```

#### PUT /columns/{id}
Обновить колонку.

---

### Boards

#### GET /boards
Список досок.

**Query params:**
- `projectId` (uuid): Фильтр по проекту

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "title": "Main Board",
      "projectId": "uuid",
      "deleted": false
    }
  ]
}
```

#### GET /boards/{id}
Доска по ID.

#### POST /boards
Создать доску.

**Body:**
```json
{
  "title": "Board name",
  "projectId": "uuid"
}
```

---

### Projects

#### GET /projects
Список проектов.

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "title": "Project Name",
      "users": ["user-uuid"]
    }
  ]
}
```

#### GET /projects/{id}
Проект по ID.

#### POST /projects
Создать проект.

**Body:**
```json
{
  "title": "Project name",
  "users": ["user-uuid"]
}
```

---

### Users

#### GET /users
Список пользователей компании.

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "email": "user@example.com",
      "firstName": "John",
      "lastName": "Doe",
      "isAdmin": false,
      "lastActivity": 1707955200000
    }
  ]
}
```

#### GET /users/{id}
Пользователь по ID.

---

### Stickers (Метки)

#### GET /stickers
Список стикеров.

**Response:**
```json
{
  "content": [
    {
      "id": "uuid",
      "name": "Bug",
      "color": "#FF0000",
      "textSticker": false
    }
  ]
}
```

---

### Webhooks

#### POST /event-subscriptions
Подписаться на события.

**Body:**
```json
{
  "url": "https://your-server.com/webhook",
  "event": "task-created"
}
```

**Доступные события:**
- `task-created`
- `task-updated`
- `task-deleted`
- `task-moved`
- `message-created`

---

## Error Codes

| Code | Description |
|------|-------------|
| 400 | Bad Request - неверные параметры |
| 401 | Unauthorized - неверный API key |
| 403 | Forbidden - нет доступа |
| 404 | Not Found - ресурс не найден |
| 429 | Too Many Requests - превышен лимит |
| 500 | Internal Server Error |

## Rate Limits

- 100 запросов в минуту на API key
- 1000 запросов в час

## Deadline Format

```json
{
  "deadline": 1707955200000,  // timestamp в миллисекундах
  "startDate": 1707868800000, // опционально, начало периода
  "withTime": false           // true = точное время, false = весь день
}
```

Преобразование даты в timestamp:
```python
import datetime
dt = datetime.datetime(2026, 2, 15, 12, 0, 0)
timestamp_ms = int(dt.timestamp() * 1000)
```
