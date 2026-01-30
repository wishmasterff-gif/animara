#!/bin/bash
# 🤖 ANIMARA SKILLS INSTALLER
# Копирует skills в правильное место и настраивает конфиг

set -e

SKILLS_DIR="$HOME/animara/skills"
CONFIG_DIR="$HOME/animara/config"

echo "🤖 ANIMARA SKILLS INSTALLER"
echo "=========================="

# Удаляем старую неправильную структуру
if [ -d "$HOME/animara/workspace/skills/builtin" ]; then
    echo "🗑️  Удаляю старую структуру skills..."
    rm -rf "$HOME/animara/workspace/skills"
fi

# Создаём директории
echo "📁 Создаю директории..."
mkdir -p "$SKILLS_DIR"
mkdir -p "$CONFIG_DIR"
mkdir -p "$HOME/animara/screenshots"

# Копируем skills (если запущен из директории со skills)
if [ -d "./web_search" ]; then
    echo "📦 Копирую skills..."
    cp -r ./web_search "$SKILLS_DIR/"
    cp -r ./exec "$SKILLS_DIR/"
    cp -r ./yougile "$SKILLS_DIR/"
    cp -r ./browser "$SKILLS_DIR/"
    cp ./__init__.py "$SKILLS_DIR/"
    cp ./README.md "$SKILLS_DIR/"
fi

# Создаём конфиг если его нет
if [ ! -f "$CONFIG_DIR/secrets.json" ]; then
    echo "⚙️  Создаю конфиг..."
    cat > "$CONFIG_DIR/secrets.json" << 'EOF'
{
  "brave_api_key": "BSA1PthqtF-a8kZj7f_xNcLGBbMDfN3",
  "yougile_token": "eAbKs-KzViRbIzz+k0dscDYbfrUxJdlvC9OmeUN4YKZIxEt0gax9WUQpjbCB3wJg",
  "telegram_bot_token": "628287747:AAETorXaNvstqJZSENiYHdlhZnvLrShyHmc"
}
EOF
    echo "✅ Конфиг создан: $CONFIG_DIR/secrets.json"
else
    echo "ℹ️  Конфиг уже существует"
fi

# Проверяем структуру
echo ""
echo "📊 Проверка структуры:"
echo "====================="
ls -la "$SKILLS_DIR/" 2>/dev/null || echo "Skills директория пуста"

echo ""
echo "✅ Установка завершена!"
echo ""
echo "Следующие шаги:"
echo "1. Проверь skills: python3 $SKILLS_DIR/__init__.py"
echo "2. Тест web_search: python3 $SKILLS_DIR/web_search/scripts/main.py 'тест'"
echo "3. Тест yougile: python3 $SKILLS_DIR/yougile/scripts/main.py tasks"
