# 🤖 Animara

**Персональный AI-ассистент на Jetson AGX Thor**

Вдохновлён архитектурой [Moltbot](https://github.com/moltbot/moltbot)

## 📁 Структура
```
animara/
├── core/                      # Основные сервисы
│   ├── rag_proxy.py          # RAG Proxy v9.4
│   ├── telegram_bot.py       # Telegram бот
│   ├── voice_bridge.py       # Голосовой интерфейс
│   └── identity_service.py   # Face Recognition
│
├── workspace/                 # Moltbot-style workspace
│   ├── IDENTITY.md           # Кто АГЕНТ
│   ├── SOUL.md               # Характер агента
│   ├── USER.md               # О ЧЕЛОВЕКЕ (автозаполнение)
│   ├── AGENTS.md             # Инструкции для сессий
│   ├── TOOLS.md              # Доступные инструменты
│   └── memory/               # Память
│
├── skills/                    # Skills (Anthropic-style)
│   ├── web_search/SKILL.md
│   ├── exec/SKILL.md
│   ├── yougile/SKILL.md
│   └── browser/SKILL.md
│
└── config/
    └── animara.yaml
```

## 🚀 Запуск
```bash
# RAG Proxy
python3 core/rag_proxy.py

# Telegram Bot
python3 core/telegram_bot.py
```

## 🔧 Hardware

- Jetson AGX Thor (Blackwell)
- 122 GB unified memory
- Qwen3-30B-A3B-NVFP4

## 📊 Компоненты

| Сервис | Порт |
|--------|------|
| LLM (Qwen3) | 8010 |
| RAG Proxy | 8015 |
| Milvus | 19530 |
