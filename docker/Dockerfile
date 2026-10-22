FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src/ ./src/
RUN useradd --uid 10001 --create-home telelogin && mkdir -p /app/data && chown telelogin:telelogin /app/data
ENV PYTHONUNBUFFERED=1 DB_URL=sqlite:///data/db.sqlite3 API_PORT=8000 FORWARDED_ALLOW_IPS=127.0.0.1
COPY docker/entrypoint.sh /usr/local/bin/telelogin-entrypoint
RUN chmod +x /usr/local/bin/telelogin-entrypoint
ENTRYPOINT ["/usr/local/bin/telelogin-entrypoint"]
EXPOSE 8000
CMD ["sh", "-c", "exec uvicorn src.app:app --host 0.0.0.0 --port \"${API_PORT}\" --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS}\""]
