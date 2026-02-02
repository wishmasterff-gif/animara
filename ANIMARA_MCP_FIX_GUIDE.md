# 🔧 ANIMARA — Решение проблемы MCP серверов

**Дата:** 2026-02-02  
**Статус:** Готово к деплою

---

## 🔍 СУТЬ ПРОБЛЕМЫ

```
┌─────────────────────────────────────────────────────────────┐
│                     ТЕКУЩАЯ СИТУАЦИЯ                        │
│                                                             │
│   RAG Proxy v12 (ХОСТ, Python)                              │
│       ↓ читает mcp_config.json                              │
│       ↓ видит: command: "node", args: ["/app/servers/..."]  │
│       ↓ пытается запустить /app/servers/... НА ХОСТЕ        │
│       ↓ ФАЙЛОВ НЕТ → ❌ ОШИБКА                              │
│                                                             │
│   Docker MCP Hub (КОНТЕЙНЕР)                                │
│       └── /app/servers/yougile/    ← ФАЙЛЫ ЗДЕСЬ           │
│       └── /app/servers/brave-search/                        │
│       └── ...                                               │
│                                                             │
│   Qwen-Agent запускает MCP серверы как subprocess.           │
│   Он не может запустить процесс ВНУТРИ Docker извне.        │
└─────────────────────────────────────────────────────────────┘
```

**Почему работали только 3 сервера (yougile, time, exec)?**  
Потому что в СТАРОМ `~/animara/mcp_config.json` у них были хостовые пути:
- `python3 /home/agx-thor/animara/mcp_servers/yougile_mcp.py` — файл на хосте ✅
- `uvx mcp-server-time` — uvx на хосте ✅
- `python3 /home/agx-thor/animara/mcp_servers/exec_mcp.py` — файл на хосте ✅

Когда путь переключили на `~/animara/mcp-hub/mcp_config.json`, все пути стали Docker-овские (`/app/servers/...`) и сломались.

---

## ✅ РЕШЕНИЕ: Вариант B — Нативная установка на хосте

### Что и как устанавливается:

| # | Сервер | Команда запуска | Установка на хосте | Статус |
|---|--------|-----------------|-------------------|--------|
| 1 | **yougile** | `python3 ~/animara/mcp_servers/yougile_mcp.py` | Кастомный, уже есть | ✅ работает |
| 2 | **time** | `uvx mcp-server-time` | uvx (без установки) | ✅ работает |
| 3 | **exec** | `python3 ~/animara/mcp_servers/exec_mcp.py` | Кастомный, уже есть | ✅ работает |
| 4 | **brightdata** | `npx -y @brightdata/mcp` | `npm install -g @brightdata/mcp` | 🆕 добавить |
| 5 | **filesystem** | `npx -y @modelcontextprotocol/server-filesystem` | уже установлен | ✅ работает |
| 6 | **memory** | `npx -y @modelcontextprotocol/server-memory` | уже установлен | ✅ работает |
| 7 | **milvus** | `uvx mcp-server-milvus` | уже pip installed | ✅ работает |
| 8 | **gmail** | `npx -y @gongrzhe/server-gmail-autoauth-mcp` | 🆕 добавить | ⚠️ OAuth |

### Что НЕ включено (и почему):

| Сервер | Причина | Альтернатива |
|--------|---------|-------------|
| **twilio** | `@twilio/mcp-server` не ставится на ARM64 | Custom Python MCP или другой пакет |
| **home_assistant** | `hass-mcp` требует Python 3.13, на Thor 3.12 | Ждать обновления или custom |
| **jetsonmcp** | Не критичен, GPU мониторинг через exec | `exec_mcp.py` + `nvidia-smi` |

---

## 📋 ОШИБКИ ИЗ ПРОШЛЫХ ЧАТОВ (исправлены)

| Ошибка | Было | Стало |
|--------|------|-------|
| **BrightData** | `@anthropic/brightdata-mcp` (404!) | `@brightdata/mcp` ✅ |
| **Gmail** | `@anthropic/gmail-mcp` (404!) | `@gongrzhe/server-gmail-autoauth-mcp` ✅ |
| **brave_search** | Отдельный UVX + свой Python сервер | BrightData MCP включает поиск! |
| **mcp_config_path** | Указывал на Docker конфиг | Указывает на `~/animara/mcp_config.json` |

### ⚡ Важное про BrightData vs Brave Search

BrightData MCP (`@brightdata/mcp`) **уже включает** поиск (`search_engine`, `search_engine_batch`, `scrape_as_markdown`). Он МОЩНЕЕ чем Brave Search:
- Обходит блокировки и CAPTCHA
- Может скрапить динамические сайты
- 5000 бесплатных запросов/месяц

Поэтому в конфиге BrightData заменяет и brave_search и brightdata из Docker одним сервером.

---

## 🗂️ ФАЙЛОВАЯ СТРУКТУРА ПОСЛЕ ФИКСА

```
~/animara/
├── mcp_config.json              ← ГЛАВНЫЙ КОНФИГ (8 серверов, хостовые пути)
├── mcp_config.json.bak.*        ← бэкапы
├── mcp_servers/
│   ├── yougile_mcp.py           ← кастомный YouGile MCP
│   └── exec_mcp.py              ← кастомный Exec MCP
├── mcp-hub/                     ← Docker (backup, можно остановить)
│   ├── Dockerfile
│   ├── docker-compose.yml
│   └── mcp_config.json          ← Docker конфиг (НЕ ИСПОЛЬЗУЕТСЯ RAG Proxy!)
├── data/
│   └── memory_kg.json           ← Memory KG storage
├── workspace/
│   ├── SOUL.md
│   ├── IDENTITY.md
│   └── USER.md
├── output/                      ← для filesystem MCP
└── logs/
    └── rag_v12.log

~/animara_rag_proxy_v12.py       ← CONFIG["mcp_config_path"] → ~/animara/mcp_config.json
```

---

## 📜 КОМАНДЫ (КОПИРУЙ В ТЕРМИНАЛ)

### Блок 1: Установка (1 раз)

```bash
# Фикс nvm
export NVM_DIR="$HOME/.nvm"
[ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh"
nvm use --delete-prefix v20.20.0 --silent 2>/dev/null

# BrightData MCP (правильное имя!)
npm install -g @brightdata/mcp

# Gmail MCP (правильное имя!)
npm install -g @gongrzhe/server-gmail-autoauth-mcp

# Проверка
npm list -g --depth=0 2>/dev/null | grep -E "brightdata|gmail|filesystem|memory"
```

### Блок 2: Конфиг

```bash
# Бэкап
cp ~/animara/mcp_config.json ~/animara/mcp_config.json.bak 2>/dev/null

# Новый конфиг (8 серверов, все пути хостовые)
cat > ~/animara/mcp_config.json << 'MCPEOF'
{
  "mcpServers": {
    "yougile": {
      "command": "python3",
      "args": ["/home/agx-thor/animara/mcp_servers/yougile_mcp.py"],
      "env": {
        "YOUGILE_TOKEN": "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg"
      }
    },
    "time": {
      "command": "uvx",
      "args": ["mcp-server-time", "--local-timezone", "Asia/Makassar"],
      "env": {}
    },
    "exec": {
      "command": "python3",
      "args": ["/home/agx-thor/animara/mcp_servers/exec_mcp.py"],
      "env": {}
    },
    "brightdata": {
      "command": "npx",
      "args": ["-y", "@brightdata/mcp"],
      "env": {
        "API_TOKEN": "59562d71-3910-4f98-aae3-985429dbf71b"
      }
    },
    "filesystem": {
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "/home/agx-thor/animara/workspace",
        "/home/agx-thor/animara/output",
        "/home/agx-thor/animara/logs"
      ],
      "env": {}
    },
    "memory": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-memory"],
      "env": {
        "MEMORY_FILE": "/home/agx-thor/animara/data/memory_kg.json"
      }
    },
    "milvus": {
      "command": "uvx",
      "args": ["mcp-server-milvus", "--uri", "http://localhost:19530"],
      "env": {
        "MILVUS_URI": "http://localhost:19530"
      }
    },
    "gmail": {
      "command": "npx",
      "args": ["-y", "@gongrzhe/server-gmail-autoauth-mcp"],
      "env": {}
    }
  }
}
MCPEOF

echo "✅ Конфиг создан: $(grep -c '"command"' ~/animara/mcp_config.json) серверов"

# Создать директории
mkdir -p ~/animara/data ~/animara/output
```

### Блок 3: Путь в RAG Proxy

```bash
# Убедиться что путь правильный
sed -i 's|"mcp_config_path": ".*"|"mcp_config_path": "/home/agx-thor/animara/mcp_config.json"|' ~/animara_rag_proxy_v12.py
grep "mcp_config_path" ~/animara_rag_proxy_v12.py
# Должно быть: "mcp_config_path": "/home/agx-thor/animara/mcp_config.json",
```

### Блок 4: Перезапуск

```bash
# Убить старый процесс
pkill -f "animara_rag_proxy_v12" 2>/dev/null
sleep 3

# Запустить новый
nohup python3 ~/animara_rag_proxy_v12.py > ~/animara/logs/rag_v12.log 2>&1 &
sleep 15

# Проверить health
curl -s http://localhost:8015/health | python3 -m json.tool

# Проверить логи (ищем MCP)
grep -i "mcp\|tool\|agent" ~/animara/logs/rag_v12.log | tail -20
```

### Блок 5: Gmail OAuth (отдельно, один раз)

```bash
# Gmail требует OAuth авторизацию через браузер
# Нужно выполнить на машине с браузером или с X-forwarding
mkdir -p ~/.gmail-mcp

# Если есть gcp-oauth.keys.json:
# cp /path/to/gcp-oauth.keys.json ~/.gmail-mcp/
# npx @gongrzhe/server-gmail-autoauth-mcp auth

# Или скопировать credentials.json из Docker:
# cp ~/animara/mcp-hub/data/gmail/credentials.json ~/.gmail-mcp/gcp-oauth.keys.json
# npx @gongrzhe/server-gmail-autoauth-mcp auth
```

---

## 🧪 ТЕСТЫ (через Telegram бот)

После деплоя проверь каждый сервер:

| Тест | Сообщение в Telegram | Ожидаемый MCP |
|------|---------------------|---------------|
| Time | "Который час?" | `time` |
| YouGile | "Покажи мои задачи" | `yougile` |
| BrightData | "Поищи в интернете последние новости о Бали" | `brightdata` |
| Filesystem | "Прочитай файл SOUL.md из workspace" | `filesystem` |
| Memory | "Запомни что я люблю кофе" | `memory` |
| Milvus | "Покажи коллекции в Milvus" | `milvus` |
| Exec | "Покажи температуру GPU" | `exec` |
| Gmail | "Проверь мою почту" | `gmail` (нужен OAuth!) |

---

## 🔮 ДАЛЬНЕЙШИЕ ШАГИ

1. **Twilio** — написать кастомный Python MCP (как yougile_mcp.py) с Twilio REST API
2. **Home Assistant** — ждать hass-mcp для Python 3.12, или написать кастомный
3. **JetsonMCP** — можно добавить позже, пока exec_mcp.py покрывает GPU мониторинг
4. **Docker MCP Hub** — можно остановить для экономии RAM:
   ```bash
   cd ~/animara/mcp-hub && docker compose down
   ```
5. **Git commit** — после успешного теста:
   ```bash
   cd ~/animara && git add -A && git commit -m "MCP fix: native host install, 8 servers"
   ```
