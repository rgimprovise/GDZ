FROM python:3.11-slim

WORKDIR /app

# No gcc/libpq-dev: psycopg2-binary installs as prebuilt wheel

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN chmod +x entrypoint.sh

EXPOSE 8000

CMD ["./entrypoint.sh"]
