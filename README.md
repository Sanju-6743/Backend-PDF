# PDF Toolkit Backend

Flask + Socket.IO backend for PDF operations (merge, split, compress).

## Local development
1. Python 3.11+
2. Install deps:
   ```bash
   pip install -r requirements.txt
   ```
3. Run:
   ```bash
   python app.py
   ```
   Server: http://localhost:5000

## Deploy on Render
- Uses render.yaml (Blueprint). Create new Blueprint service in Render and connect this repo.
- Health check: /health
- Start command: `gunicorn -k eventlet -w 1 app:app`

## API
- POST /merge  (multipart, files[])
- POST /split  (multipart, file, split_page)
- POST /compress  (multipart, file)
- GET /download/<filename>
- GET /health