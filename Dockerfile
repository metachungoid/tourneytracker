FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt gunicorn

COPY app.py .
COPY models.py .
COPY bracket/ bracket/
COPY routes/ routes/
COPY templates/ templates/
COPY static/ static/

RUN mkdir -p instance

ENV SECRET_KEY=change-me-in-production
ENV FLASK_DEBUG=0

EXPOSE 5050

CMD ["gunicorn", "--bind", "0.0.0.0:5050", "--workers", "2", "app:app"]
