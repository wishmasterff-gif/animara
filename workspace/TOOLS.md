# 🔧 TOOLS — Твои инструменты

*Что ты умеешь делать.*

---

## Core Tools (встроенные)

### exec — Выполнение команд
```
exec(command="ls -la ~/animara")
```
- Выполняет shell команды на хосте
- **Sandbox:** Только разрешённые пути
- **Elevated:** sudo требует подтверждения

### read — Чтение файлов
```
read(path="~/animara/workspace/USER.md")
```
- Читает содержимое файла
- Поддерживает: .md, .txt, .py, .json, .yaml

### write — Запись файлов
```
write(path="~/animara/workspace/memory/2026-01-31.md", content="...")
```
- Создаёт или перезаписывает файл
- **Sandbox:** Только ~/animara/ и /tmp/

### edit — Редактирование файлов
```
edit(path="...", old="текст", new="новый текст")
```
- Заменяет часть файла
- Для точечных изменений

### memory_search — Поиск в памяти
```
memory_search(query="что обсуждали про Milvus")
```
- Hybrid search: vector + BM25
- Ищет в conversations + memories

### memory_save — Сохранение факта
```
memory_save(content="Сергей предпочитает TypeScript", type="preference")
```
- Сохраняет в Milvus memories
- Типы: fact, preference, project, hobby, skill, plan

---

## Skills (расширения)

### web_search — Поиск в интернете
```
web_search(query="jetson agx thor specs")
```
- Через Brave Search API
- Лимит: 3 поиска за сессию (защита от зацикливания)

### browser — Автоматизация браузера
```
browser(action="screenshot", url="https://example.com")
browser(action="click", selector="#button")
```
- Playwright headless
- Для скриншотов и автоматизации

### yougile_tasks — Управление задачами
```
yougile_tasks(action="list")
yougile_tasks(action="create", title="Новая задача", column_id="...")
yougile_tasks(action="find", search="квадроцикл")
```
- CRUD для YouGile
- API ключ в config

### camera — Камера
```
camera(action="snapshot")
camera(action="identify")  # Face recognition
```
- Снимок с камеры
- Распознавание лиц через InsightFace

### speak — Синтез речи
```
speak(text="Привет, Сергей!")
```
- Через Piper TTS
- Голос: ru_RU-ruslan-medium

### listen — Распознавание речи
```
listen(duration=5)  # секунд
```
- Через Riva ASR
- Возвращает текст

---

## Tool Policies

### По ролям

| Tool | owner | admin | friend | guest |
|------|-------|-------|--------|-------|
| exec | ✅ | ⚠️ limited | ❌ | ❌ |
| read | ✅ | ✅ | ⚠️ limited | ❌ |
| write | ✅ | ✅ | ❌ | ❌ |
| memory_search | ✅ | ✅ | ✅ own | ❌ |
| web_search | ✅ | ✅ | ✅ | ✅ |
| browser | ✅ | ✅ | ❌ | ❌ |
| yougile | ✅ | ✅ | ❌ | ❌ |
| camera | ✅ | ❌ | ❌ | ❌ |
| speak/listen | ✅ | ✅ | ✅ | ❌ |

### Запрещённые паттерны
```python
DENIED = [
    "rm -rf /",
    "rm -rf ~",
    "sudo rm -rf",
    "dd if=",
    "mkfs",
    "> /dev/sd",
    "chmod 777 /",
    "curl | bash",  # без проверки
]
```

### Elevated (требуют подтверждения)
```python
ELEVATED = [
    "sudo *",
    "docker rm",
    "docker stop",
    "systemctl stop",
    "pip uninstall",
    "rm -rf ~/animara",
]
```

---

## Добавление новых tools

Создай файл `skills/<name>/SKILL.md`:

```markdown
---
name: my_tool
description: Что делает этот инструмент
metadata:
  animara:
    requires:
      bins: ["python3", "curl"]
    security:
      level: standard  # standard | elevated | owner_only
      requires_confirmation: false
---

# My Tool

## Использование
...

## Примеры
...
```

---

*Обновляй этот файл когда добавляешь новые инструменты.*
