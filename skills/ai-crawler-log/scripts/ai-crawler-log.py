#!/usr/bin/env python3
"""Launcher: python3 ai-crawler-log.py analyze /var/log/nginx/access.log*"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ai_crawler_log.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main())
