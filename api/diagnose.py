"""Diagnostic endpoint to find which import is failing."""
from http.server import BaseHTTPRequestHandler
import json
import sys
import traceback

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        results = {
            "python_version": sys.version,
            "imports": {}
        }
        
        # Test each import step by step
        imports_to_test = [
            ("flask", "from flask import Flask"),
            ("flask_limiter", "from flask_limiter import Limiter"),
            ("loguru", "from loguru import logger"),
            ("requests", "import requests"),
            ("dotenv", "from dotenv import load_dotenv"),
            ("friday.config", "from friday.config import PORT"),
            ("friday.db", "from friday import db"),
            ("friday.system_prompt", "from friday.system_prompt import get_system_prompt"),
            ("friday.modules.llm", "from friday.modules import llm"),
            ("friday.modules.auth", "from friday.modules import auth"),
            ("friday.modules.music", "from friday.modules import music"),
            ("friday.modules.memory", "from friday.modules import memory"),
            ("friday.modules.tool_calling", "from friday.modules.tool_calling import IntentRouter"),
        ]
        
        for name, import_stmt in imports_to_test:
            try:
                exec(import_stmt)
                results["imports"][name] = "OK"
            except Exception as e:
                results["imports"][name] = f"FAILED: {type(e).__name__}: {str(e)[:200]}"
                # Get full traceback
                results["imports"][name + "_traceback"] = traceback.format_exc()[-500:]
        
        self.wfile.write(json.dumps(results, indent=2).encode())
        return
