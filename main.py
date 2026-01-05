"""
Точка входа для запуска Telegram бота.
"""
import sys
from pathlib import Path

# Добавляем корневую директорию проекта в sys.path
project_root = Path(__file__).parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

import asyncio
from src.bot import main

if __name__ == "__main__":
    asyncio.run(main())
