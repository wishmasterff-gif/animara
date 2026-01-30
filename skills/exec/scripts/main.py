#!/usr/bin/env python3
"""
⚡ Exec Skill
Выполнение shell команд с проверками безопасности
"""

import subprocess
import shlex
import re
from typing import Dict, Optional

# Опасные паттерны команд (блокируются)
DANGEROUS_PATTERNS = [
    r"rm\s+-rf\s+/",           # rm -rf /
    r"rm\s+-rf\s+~",           # rm -rf ~
    r"rm\s+-rf\s+\*",          # rm -rf *
    r"mkfs\.",                  # форматирование
    r"dd\s+if=.*of=/dev/",     # перезапись дисков
    r":(){ :|:& };:",          # fork bomb
    r">\s*/dev/sd",            # запись в диски
    r"chmod\s+-R\s+777\s+/",   # chmod 777 /
    r"curl.*\|\s*bash",        # curl | bash
    r"wget.*\|\s*bash",        # wget | bash
    r"nc\s+-e",                # reverse shell
    r"python.*-c.*import\s+socket", # socket в one-liner
]

# Команды требующие подтверждения
REQUIRES_CONFIRMATION = [
    r"^sudo\s+",               # любая sudo команда
    r"apt\s+(install|remove)", # установка/удаление пакетов
    r"pip\s+install",          # pip install
    r"docker\s+rm",            # удаление контейнеров
    r"docker\s+rmi",           # удаление образов
    r"systemctl\s+(stop|disable|restart)", # управление сервисами
]


def is_dangerous(command: str) -> bool:
    """Проверить команду на опасность"""
    command_lower = command.lower()
    for pattern in DANGEROUS_PATTERNS:
        if re.search(pattern, command_lower):
            return True
    return False


def requires_confirmation(command: str) -> bool:
    """Проверить нужно ли подтверждение"""
    for pattern in REQUIRES_CONFIRMATION:
        if re.search(pattern, command, re.IGNORECASE):
            return True
    return False


def run(command: str, timeout: int = 30, cwd: Optional[str] = None) -> Dict:
    """
    Выполнить shell команду.
    
    Args:
        command: Команда для выполнения
        timeout: Таймаут в секундах
        cwd: Рабочая директория
        
    Returns:
        Dict с результатами выполнения
    """
    # Проверка на опасность
    if is_dangerous(command):
        return {
            "success": False,
            "stdout": "",
            "stderr": "❌ ЗАБЛОКИРОВАНО: Эта команда потенциально опасна",
            "return_code": -1,
            "blocked": True
        }
    
    # Предупреждение о командах требующих подтверждения
    needs_confirm = requires_confirmation(command)
    
    try:
        result = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd
        )
        
        return {
            "success": result.returncode == 0,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "return_code": result.returncode,
            "needs_confirmation": needs_confirm
        }
        
    except subprocess.TimeoutExpired:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"❌ Таймаут: команда выполнялась дольше {timeout} сек",
            "return_code": -1,
            "timeout": True
        }
    except Exception as e:
        return {
            "success": False,
            "stdout": "",
            "stderr": f"❌ Ошибка: {e}",
            "return_code": -1
        }


def run_safe(command: str, timeout: int = 30) -> str:
    """
    Безопасное выполнение команды с форматированным выводом.
    
    Args:
        command: Команда для выполнения
        timeout: Таймаут в секундах
        
    Returns:
        Форматированная строка с результатом
    """
    result = run(command, timeout)
    
    if result.get("blocked"):
        return result["stderr"]
    
    if result.get("timeout"):
        return result["stderr"]
    
    if result["success"]:
        output = result["stdout"].strip()
        if not output:
            return "✅ Команда выполнена (без вывода)"
        return f"✅ Результат:\n```\n{output}\n```"
    else:
        stderr = result["stderr"].strip()
        stdout = result["stdout"].strip()
        error_msg = stderr or stdout or "Неизвестная ошибка"
        return f"❌ Ошибка (код {result['return_code']}):\n```\n{error_msg}\n```"


def check_docker() -> str:
    """Проверить статус Docker контейнеров"""
    return run_safe("docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Ports}}'")


def check_disk() -> str:
    """Проверить дисковое пространство"""
    return run_safe("df -h | grep -E '^/dev|Filesystem'")


def check_memory() -> str:
    """Проверить память"""
    return run_safe("free -h")


def check_gpu() -> str:
    """Проверить GPU (для Jetson)"""
    # Jetson не имеет nvidia-smi, используем tegrastats или jtop
    result = run("which tegrastats", timeout=5)
    if result["success"]:
        return run_safe("timeout 1 tegrastats | head -1")
    return run_safe("cat /sys/devices/gpu.0/load 2>/dev/null || echo 'GPU info not available'")


# CLI интерфейс для тестирования
if __name__ == "__main__":
    import sys
    
    if len(sys.argv) < 2:
        print("Использование: python main.py <команда>")
        print("Пример: python main.py 'ls -la'")
        print("\nБыстрые проверки:")
        print("  python main.py --docker")
        print("  python main.py --disk")
        print("  python main.py --memory")
        sys.exit(1)
    
    arg = sys.argv[1]
    
    if arg == "--docker":
        print(check_docker())
    elif arg == "--disk":
        print(check_disk())
    elif arg == "--memory":
        print(check_memory())
    elif arg == "--gpu":
        print(check_gpu())
    else:
        command = " ".join(sys.argv[1:])
        print(f"⚡ Выполняю: {command}\n")
        print(run_safe(command))
