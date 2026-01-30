# 🤖 ANIMARA SKILLS

Модульная система навыков для AI-ассистента Animara.

## 📦 Доступные Skills

| Skill | Описание | Статус |
|-------|----------|--------|
| `web_search` | Поиск в интернете через Brave API | ✅ |
| `exec` | Выполнение shell команд | ✅ |
| `yougile` | Управление задачами YouGile | ✅ |
| `browser` | Браузерная автоматизация (Playwright) | ✅ |

## 📁 Структура

```
skills/
├── __init__.py           # Реестр skills
├── README.md             # Документация
├── config/
│   └── secrets.json.example
│
├── web_search/
│   ├── SKILL.md          # Инструкции
│   └── scripts/
│       └── main.py       # Код
│
├── exec/
│   ├── SKILL.md
│   └── scripts/
│       └── main.py
│
├── yougile/
│   ├── SKILL.md
│   └── scripts/
│       └── main.py
│
└── browser/
    ├── SKILL.md
    └── scripts/
        └── main.py
```

## 🚀 Использование

### Как модуль Python

```python
# Web Search
from skills.web_search.scripts.main import search
results = search("погода Бали")
print(results)

# YouGile
from skills.yougile.scripts.main import get_tasks, find_task
tasks = get_tasks()
task = find_task("покупки")

# Exec
from skills.exec.scripts.main import run_safe
output = run_safe("docker ps")

# Browser
from skills.browser.scripts.main import screenshot_sync
screenshot_sync("https://example.com", "example")
```

### Из командной строки

```bash
# Web Search
python skills/web_search/scripts/main.py "погода Бали"

# YouGile
python skills/yougile/scripts/main.py tasks
python skills/yougile/scripts/main.py find "покупки"

# Exec
python skills/exec/scripts/main.py "ls -la"
python skills/exec/scripts/main.py --docker

# Browser
python skills/browser/scripts/main.py open https://example.com
```

## ⚙️ Конфигурация

Создай `~/animara/config/secrets.json`:

```json
{
  "brave_api_key": "BSA1PthqtF-...",
  "yougile_token": "eAbKs-KzViRbIzz+...",
  "telegram_bot_token": "628287747:AAE..."
}
```

## 🔒 Безопасность

- `exec` skill блокирует опасные команды (rm -rf /, dd, mkfs)
- Команды с `sudo` требуют подтверждения
- API ключи хранятся отдельно от кода

## 📋 TODO

- [ ] `calendar` skill — Google Calendar интеграция
- [ ] `email` skill — Gmail интеграция
- [ ] `voice` skill — Text-to-Speech
- [ ] `vision` skill — Анализ изображений

## 📝 Добавление нового skill

1. Создай директорию: `skills/my_skill/`
2. Создай `SKILL.md` с описанием
3. Создай `scripts/main.py` с кодом
4. Добавь в `__init__.py` AVAILABLE_SKILLS

---

**Версия:** 1.0.0  
**Автор:** Sergey Ardasenov (Animara Project)
