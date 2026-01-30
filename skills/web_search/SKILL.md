---
name: web_search
description: Поиск в интернете через Brave Search API
version: 1.0.0
metadata:
  animara:
    requires:
      env: ["BRAVE_API_KEY"]
    security:
      level: standard
    limits:
      max_per_session: 3
---

# 🔍 Web Search

Поиск в интернете через Brave Search API.

## Использование
```
web_search(query="запрос")
```

## Лимиты

- 3 поиска за сессию
