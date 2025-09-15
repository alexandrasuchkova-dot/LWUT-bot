# Telegram Q&A Bot (No Repeats)

Бот связывает двух участников (A ↔ B) и работает со списком из 127 вопросов.
Добавлено: запрет повторов — вопросы не повторяются, пока не будут использованы все 127. Есть кнопка для сброса истории.

## Запуск локально
```bash
python -m venv .venv
source .venv/bin/activate    # Windows: .venv\Scripts\activate
pip install -r requirements.txt
export TELEGRAM_TOKEN="ВАШ_ТОКЕН_ОТ_BOTFATHER"   # Windows: set TELEGRAM_TOKEN=...
python bot.py
```

## Файлы
- `bot.py` — код бота
- `questions.txt` — 127 вопросов (по одному на строку)
- `state.json` — состояние (создаётся автоматически)
- `requirements.txt` — зависимости
- `Dockerfile` — контейнеризация (для деплоя на Render/Fly/VPS)
- `README.md` — этот файл

## Деплой через Docker (пример)
```bash
docker build -t tg-bot-norepeats .
docker run -e TELEGRAM_TOKEN="ВАШ_ТОКЕН" -p 8080:8080 tg-bot-norepeats
```

Для вебхуков замените `app.run_polling` на `app.run_webhook` и задайте `WEBHOOK_URL`.
```bash
docker run -e TELEGRAM_TOKEN="..." -e WEBHOOK_URL="https://YOUR-APP/webhook" -p 8080:8080 tg-bot-norepeats
```

## Сброс истории
В боте есть кнопка: **«Сбросить историю вопросов»** — очищает историю использованных вопросов.
Также доступна команда `/reset`.
```