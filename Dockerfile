FROM python:3.11-slim

WORKDIR /app

COPY README.md ./
COPY sandbox ./sandbox

RUN pip install --no-cache-dir ./sandbox

CMD ["sandbox-demo", "demo"]
