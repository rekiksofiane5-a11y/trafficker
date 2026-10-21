FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install --no-cache-dir -r requirements.txt gunicorn -c requirements.lock
COPY . .
RUN useradd -r -u 10001 trafficker && mkdir -p /data && chown trafficker /data
USER trafficker
ENV TRAFFICKER_DB=/data/trafficker.db TRAFFICKER_WSGI=1 TRAFFICKER_SECURE_COOKIE=1
EXPOSE 8000
# UN SEUL processus (-w 1) obligatoire : JOBS, PLANS et LOGIN_ATTEMPTS sont en mémoire.
# Plusieurs workers casseraient le suivi des jobs, les jetons d'analyse et l'anti-force brute.
CMD ["gunicorn", "-w", "1", "--threads", "8", "-b", "0.0.0.0:8000", "cm360_trafficker_ui:app"]
