FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py ./
COPY questions.txt ./

ENV PYTHONUNBUFFERED=1
# По умолчанию запускаем polling
CMD ["python", "bot.py"]