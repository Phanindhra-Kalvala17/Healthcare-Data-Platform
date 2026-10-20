FROM python:3.13-slim

RUN useradd --create-home app
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
USER app

ENV HDP_DATA_DIR=/app/data
CMD ["python", "-m", "orchestration.pipeline", "--generate", "1000"]
