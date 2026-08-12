FROM python:3.14-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
RUN addgroup --system amatopay && adduser --system --ingroup amatopay amatopay \
    && mkdir -p /app/staticfiles /app/media \
    && chown -R amatopay:amatopay /app
USER amatopay
CMD ["gunicorn","config.wsgi:application","--bind","0.0.0.0:8000","--workers","3","--timeout","60","--access-logfile","-","--error-logfile","-"]
