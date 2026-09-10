FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends     ffmpeg     git     curl     && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV PORT=8800
EXPOSE 8800

CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8800"]
