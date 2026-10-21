FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn -c requirements.lock
COPY . .
RUN useradd -r -u 10001 trafficker && mkdir -p /data && chown trafficker /data
USER trafficker
ENV TRAFFICKER_DB=/data/trafficker.db TRAFFICKER_WSGI=1 TRAFFICKER_SECURE_COOKIE=1
EXPOSE 8000
# État partagé en SQLite (volume /data) : plusieurs processus possibles sur une même
# machine. TRAFFICKER_WORKERS règle leur nombre (défaut 2). Plusieurs machines : non
# (SQLite n'est pas partageable en réseau ; passer à PostgreSQL d'abord).
ENV TRAFFICKER_WORKERS=2
CMD ["sh", "-c", "exec gunicorn -w ${TRAFFICKER_WORKERS} --threads 8 -b 0.0.0.0:8000 cm360_trafficker_ui:app"]
