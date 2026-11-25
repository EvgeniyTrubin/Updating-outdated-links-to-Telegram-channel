# Updating-outdated-links-to-Telegram-channel
An asynchronous Python script for bulk-updating outdated links to Telegram channel posts following a channel rename.  The script identifies all occurrences of the old address—within post text, media captions, inline buttons, and hidden hyperlinks (TEXT_LINK ent.)—and replaces them with the new address, while preserving the original post formatting.
# Telegram Channel Link Updater

Асинхронный Python-скрипт для массового обновления устаревших ссылок на сообщения в Telegram-канале после его переименования (смены username).

Скрипт находит все упоминания старого адреса в тексте, подписях к медиа, inline-кнопках и скрытых гиперссылках (TEXT_LINK entities) и заменяет их на новый адрес, сохраняя форматирование поста.

## Особенности

- **Pyrogram 2.x**: асинхронный перебор истории через `async for`
- **Глубокий парсинг entities**: обрабатывает `URL` и `TEXT_LINK` — скрытые гиперссылки, которые не видны в открытом тексте
- **DRY_RUN режим**: по умолчанию только показывает планируемые изменения без их применения
- **Checkpointing**: сохраняет прогресс в `checkpoint.json`, позволяет возобновить работу после обрыва
- **Автоматическая обработка FloodWait**: скрипт сам ставит себя на паузу при лимитах API
- **CSV-логирование**: все операции записываются в `replacement_log.csv`

## Требования

- Python 3.9+
- Учётная запись Telegram с правами администратора в канале
- `api_id` и `api_hash` с [my.telegram.org](https://my.telegram.org)

**Важно**: использование Bot Token невозможно — Telegram API запрещает ботам чтение истории каналов (`BOT_METHOD_INVALID`). Требуется авторизация через личный аккаунт (`phone_number`).

## Установка

```bash
git clone https://github.com/ВАШ_НИК/telegram-link-updater.git
cd telegram-link-updater
pip install -r requirements.txt
