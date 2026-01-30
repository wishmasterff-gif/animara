---
name: exec
description: Выполнение shell команд
version: 1.0.0
metadata:
  animara:
    security:
      level: elevated
      requires_confirmation: true
    denied_patterns:
      - "rm -rf /"
      - "sudo rm -rf"
---

# ⚡ Exec

Выполнение shell команд на хосте.

## Использование
```
exec(command="ls -la")
```

## Безопасность

- Требует подтверждения для sudo
- Запрещены деструктивные команды
