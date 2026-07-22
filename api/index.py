"""Vercel serverless function entry point."""
from app import app

# Vercel expects this handler
handler = app
