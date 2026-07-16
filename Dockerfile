FROM python:3.11-slim

WORKDIR /app

# Install deps first (cached layer — only rebuilds when requirements.txt changes)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy code (this layer rebuilds on every code change — fast since deps are cached)
COPY app.py .
COPY jarvis/ ./jarvis/
COPY public/ ./public/

ENV PORT=7860
ENV HOST=0.0.0.0
EXPOSE 7860

CMD ["python", "app.py"]
