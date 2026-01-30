---
name: exec
description: Выполнение shell команд на хосте
version: 1.0.0
author: Animara
metadata:
  animara:
    requires:
      bins: ["bash"]
    security:
      level: elevated
      requires_confirmation: true
      owner_only_patterns:
        - "sudo *"
        - "docker rm *"
        - "systemctl *"
      denied_patterns:
        - "rm -rf /"
        - "rm -rf ~"
        - "dd if="
        - "mkfs"
        - "> /dev/sd"
        - "chmod 777 /"
---

# ⚡ Exec

Выполнение shell команд на хост-системе.

## Использование

```
exec(command="команда для выполнения")
```

## Параметры

| Параметр | Тип | Обязательный | Описание |
|----------|-----|--------------|----------|
| command | string | ✅ | Shell команда |
| timeout | int | ❌ | Таймаут в секундах (default: 30) |
| cwd | string | ❌ | Рабочая директория |

## Примеры

```
# Список файлов
exec(command="ls -la ~/animara")

# Docker статус
exec(command="docker ps --format '{{.Names}}: {{.Status}}'")

# Проверка диска
exec(command="df -h /")

# С рабочей директорией
exec(command="ls", cwd="~/animara/workspace")
```

## Уровни безопасности

### ✅ Разрешено (без подтверждения)
- `ls`, `cat`, `head`, `tail`
- `pwd`, `whoami`, `date`
- `docker ps`, `docker logs`
- `curl` (только GET)
- `python3` (только для скриптов в workspace)

### ⚠️ Требует подтверждения
- `sudo *`
- `docker rm`, `docker stop`
- `pip install/uninstall`
- `systemctl *`
- Любая запись вне ~/animara/

### ❌ Запрещено (НИКОГДА)
```
rm -rf /
rm -rf ~
dd if=/dev/zero
mkfs.*
> /dev/sda
chmod 777 /
curl ... | bash  # без проверки
```

## Формат подтверждения

```
⚠️ Эта команда требует подтверждения:

$ sudo systemctl restart docker

Это elevated команда. Выполнить? (да/нет)
```

## Обработка ошибок

```json
{
  "success": false,
  "returncode": 1,
  "stdout": "",
  "stderr": "bash: команда: not found",
  "error": "Command failed with exit code 1"
}
```

## Безопасность

1. **Sandbox paths:** Запись только в разрешённые пути
2. **Timeout:** Автоматическое прерывание долгих команд
3. **Logging:** Все команды логируются в memory/

## Логирование

Каждое выполнение записывается:

```markdown
## 14:35 — exec
- Command: `docker ps`
- User: owner_sergey
- Result: success
- Duration: 0.2s
```

---

*Skill version: 1.0.0 | Last updated: 2026-01-31*
