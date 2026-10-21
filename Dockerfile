FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn
COPY . .
RUN useradd -r -u 10001 trafficker && mkdir -p /data && chown trafficker /data
USER trafficker
ENV TRAFFICKER_DB=/data/trafficker.db TRAFFICKER_WSGI=1 TRAFFICKER_SECURE_COOKIE=1
EXPOSE 8000
# Un seul processus : jobs en cours en mémoire (threads pour la concurrence)
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:8000", "cm360_trafficker_ui:app"]
