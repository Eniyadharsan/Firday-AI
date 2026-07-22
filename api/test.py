"""Minimal test endpoint to verify Vercel Python works."""
from http.server import BaseHTTPRequestHandler
import json
import sys

class handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'application/json')
        self.end_headers()
        
        response = {
            "status": "ok",
            "python_version": sys.version,
            "message": "Vercel Python is working!"
        }
        
        self.wfile.write(json.dumps(response).encode())
        return
