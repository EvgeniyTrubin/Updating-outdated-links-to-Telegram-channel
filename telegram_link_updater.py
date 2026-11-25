#!/usr/bin/env python3
"""
Скрипт для массового обновления ссылок в Telegram-канале.
Версия: 4.0 (Личный аккаунт + поддержка скрытых гиперссылок/entities)
"""
import asyncio
import csv
import json
import os
import re
import sys
from datetime import datetime, timezone
from pyrogram import Client
from pyrogram.errors import (
    FloodWait,
    MessageNotModified,
    ChannelPrivate,
    UsernameNotOccupied,
)
from pyrogram.enums import MessageEntityType
from pyrogram.types import Message, MessageEntity, InlineKeyboardMarkup, InlineKeyboardButton

# =============================================================================
# КОНФИГУРАЦИЯ — ЗАПОЛНИТЕ ЭТИ СТРОКИ ПЕРЕД ЗАПУСКОМ
# =============================================================================
API_ID = 12345678
API_HASH = "ваш_api_hash"
PHONE = "+79001234567"

CHANNEL_USERNAME = "new_channel_name"   # текущий username канала (без @)
OLD_USERNAME = "old_channel_name"       # старый username для поиска в ссылках
DRY_RUN = True                          # оставьте True для первого запуска

CURRENT_USERNAME = ""                              # заполняется автоматически
PAUSE_BETWEEN_EDITS = 3                            # пауза между редактированиями (сек)
CHECKPOINT_FILE = "checkpoint.json"
LOG_FILE = "replacement_log.csv"
BATCH_SIZE = 100

# =============================================================================
# РЕГУЛЯРНЫЕ ВЫРАЖЕНИЯ
# =============================================================================
LINK_PATTERN = re.compile(
    r"(https?://)?t\.me/" + re.escape(OLD_USERNAME) + r"/(\d+)",
    re.IGNORECASE,
)

# =============================================================================
# CHECKPOINT & ЛОГИРОВАНИЕ
# =============================================================================
def load_checkpoint() -> dict:
    if not os.path.exists(CHECKPOINT_FILE):
        return {}
    try:
        with open(CHECKPOINT_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        print(f"[✓] Checkpoint загружен: последнее сообщение ID {data.get('last_processed_message_id', 0)}")
        return data
    except (json.JSONDecodeError, IOError) as e:
        print(f"[!] Ошибка чтения checkpoint: {e}. Начинаем с начала.")
        return {}

def save_checkpoint(message_id: int, total_processed: int) -> None:
    data = {
        "last_processed_message_id": message_id,
        "total_processed": total_processed,
        "last_update": datetime.now(timezone.utc).isoformat(),
    }
    try:
        with open(CHECKPOINT_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
    except IOError as e:
        print(f"[!] Ошибка записи checkpoint: {e}")

def delete_checkpoint() -> None:
    if os.path.exists(CHECKPOINT_FILE):
        os.remove(CHECKPOINT_FILE)
        print("[✓] Checkpoint удалён. Начинаем с начала.")

def init_csv_log() -> None:
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["message_id", "old_link", "new_link", "status", "error_message", "timestamp"])
        print(f"[✓] CSV-лог инициализирован: {LOG_FILE}")

def write_log_entry(message_id: int, old_link: str, new_link: str, status: str, error_message: str = "") -> None:
    timestamp = datetime.now(timezone.utc).isoformat()
    with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow([message_id, old_link, new_link, status, error_message, timestamp])

# =============================================================================
# ПОИСК И ЗАМЕНА ССЫЛОК (ТЕКСТ + ENTITIES)
# =============================================================================
def find_links_in_text(text: str) -> list:
    if not text:
        return []
    results = []
    for match in LINK_PATTERN.finditer(text):
        old_link = match.group(0)
        message_id = match.group(2)
        new_link = f"t.me/{CURRENT_USERNAME}/{message_id}"
        results.append((old_link, new_link))
    return results

def replace_links_in_text(text: str) -> str:
    if not text:
        return text
    def replacer(match):
        message_id = match.group(2)
        return f"t.me/{CURRENT_USERNAME}/{message_id}"
    return LINK_PATTERN.sub(replacer, text)

def find_links_in_entities(entities) -> list:
    """Ищет старые ссылки внутри скрытых гиперссылок (URL-entities)."""
    if not entities:
        return []
    results = []
    for entity in entities:
        if entity.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK) and entity.url:
            results.extend(find_links_in_text(entity.url))
    return results

def replace_links_in_entities(entities):
    """Заменяет URL в скрытых гиперссылках, сохраняя все прочие entities."""
    if not entities:
        return None, []
    new_entities = []
    replacements = []
    for entity in entities:
        if entity.type in (MessageEntityType.URL, MessageEntityType.TEXT_LINK) and entity.url:
            links = find_links_in_text(entity.url)
            if links:
                new_url = entity.url
                for old_link, new_link in links:
                    new_url = new_url.replace(old_link, new_link)
                    replacements.append((old_link, new_link))
                new_entities.append(MessageEntity(
                    type=entity.type, offset=entity.offset,
                    length=entity.length, url=new_url
                ))
            else:
                new_entities.append(entity)
        else:
            new_entities.append(entity)
    return new_entities, replacements

# =============================================================================
# ОБРАБОТКА СООБЩЕНИЙ
# =============================================================================
def has_old_links(message: Message) -> bool:
    if message.text and find_links_in_text(message.text):
        return True
    if message.caption and find_links_in_text(message.caption):
        return True
    if message.entities and find_links_in_entities(message.entities):
        return True
    if message.caption_entities and find_links_in_entities(message.caption_entities):
        return True
    if message.reply_markup and isinstance(message.reply_markup, InlineKeyboardMarkup):
        for row in message.reply_markup.inline_keyboard:
            for button in row:
                if button.url and find_links_in_text(button.url):
                    return True
    return False

def process_inline_keyboard(keyboard: InlineKeyboardMarkup):
    replacements = []
    new_rows = []
    for row in keyboard.inline_keyboard:
        new_row = []
        for button in row:
            if button.url and find_links_in_text(button.url):
                links = find_links_in_text(button.url)
                new_url = button.url
                for old_link, new_link in links:
                    new_url = new_url.replace(old_link, new_link)
                replacements.extend(links)
                new_button = InlineKeyboardButton(text=button.text, url=new_url)
                new_row.append(new_button)
            else:
                new_row.append(button)
        new_rows.append(new_row)
    new_keyboard = InlineKeyboardMarkup(new_rows)
    return new_keyboard, replacements

async def edit_message(app: Client, chat_id: int, message: Message):
    all_replacements = []
    new_text = message.text
    new_caption = message.caption
    new_keyboard = None
    new_entities = None
    new_caption_entities = None

    if message.text:
        links = find_links_in_text(message.text)
        if links:
            all_replacements.extend(links)
            new_text = replace_links_in_text(message.text)

    if message.caption:
        links = find_links_in_text(message.caption)
        if links:
            all_replacements.extend(links)
            new_caption = replace_links_in_text(message.caption)

    if message.entities:
        new_entities, ent_reps = replace_links_in_entities(message.entities)
        all_replacements.extend(ent_reps)

    if message.caption_entities:
        new_caption_entities, cap_ent_reps = replace_links_in_entities(message.caption_entities)
        all_replacements.extend(cap_ent_reps)

    if message.reply_markup and isinstance(message.reply_markup, InlineKeyboardMarkup):
        new_keyboard, kb_replacements = process_inline_keyboard(message.reply_markup)
        all_replacements.extend(kb_replacements)

    if not all_replacements:
        return [], "skipped"

    is_media = bool(message.photo or message.video or message.document or message.audio or message.voice or message.animation)

    try:
        if is_media:
            caption_to_set = new_caption if (new_caption and new_caption != message.caption) else message.caption
            keyboard_to_set = new_keyboard if new_keyboard else message.reply_markup
            await app.edit_message_caption(
                chat_id=chat_id, message_id=message.id,
                caption=caption_to_set, caption_entities=new_caption_entities,
                reply_markup=keyboard_to_set
            )
        else:
            text_to_set = new_text if (new_text and new_text != message.text) else message.text
            keyboard_to_set = new_keyboard if new_keyboard else message.reply_markup
            if not text_to_set and not keyboard_to_set:
                return all_replacements, "skipped"
            await app.edit_message_text(
                text=text_to_set or " ", chat_id=chat_id, message_id=message.id,
                entities=new_entities, reply_markup=keyboard_to_set
            )
        return all_replacements, "success"
    except MessageNotModified:
        return all_replacements, "skipped"
    except FloodWait as e:
        raise e
    except Exception as e:
        return all_replacements, f"error: {str(e)}"

# =============================================================================
# СБОР ИСТОРИИ (Pyrogram 2.x: async for)
# =============================================================================
async def collect_all_messages(app: Client, chat_id: int) -> list:
    all_messages = []
    offset_id = 0
    print("[*] Собираю сообщения из канала...")
    while True:
        try:
            batch = []
            async for message in app.get_chat_history(chat_id, limit=BATCH_SIZE, offset_id=offset_id):
                batch.append(message)
            if not batch:
                break
            all_messages.extend(batch)
            print(f"  Загружено {len(all_messages)} сообщений (батч: {len(batch)})")
            if len(batch) < BATCH_SIZE:
                break
            offset_id = batch[-1].id
        except FloodWait as e:
            print(f"[!] FloodWait: ждём {e.value} секунд...")
            await asyncio.sleep(e.value + 1)
        except Exception as e:
            print(f"[!] Ошибка при загрузке истории: {e}")
            break

    all_messages.sort(key=lambda m: m.id)
    print(f"[✓] Всего собрано сообщений: {len(all_messages)}")
    return all_messages

# =============================================================================
# ОСНОВНАЯ ФУНКЦИЯ
# =============================================================================
async def main():
    global CURRENT_USERNAME
    print("=" * 60)
    print("  СКРИПТ ОБНОВЛЕНИЯ ССЫЛОК В TELEGRAM-КАНАЛЕ (v4.0)")
    print("  (режим работы: личный аккаунт + поддержка entities)")
    print("=" * 60)
    print()

    if API_ID == 0 or not API_HASH or PHONE == "" or PHONE == "+7...":
        print("[!] ОШИБКА: Заполните PHONE в начале скрипта!")
        sys.exit(1)

    if DRY_RUN:
        print("[i] Режим: DRY RUN (тестовый прогон, изменения НЕ будут применены)")
    else:
        print("[i] Режим: РАБОЧИЙ (изменения будут применены)")
    print()

    app = Client(
        "user_session_v4",
        api_id=API_ID,
        api_hash=API_HASH,
        phone_number=PHONE,
    )
    await app.start()
    me = await app.get_me()
    print(f"[✓] Подключено как пользователь: {me.first_name} (@{me.username or 'нет username'})")

    try:
        print(f"[*] Получаю информацию о канале @{CHANNEL_USERNAME}...")
        try:
            chat = await app.get_chat(CHANNEL_USERNAME)
        except UsernameNotOccupied:
            print(f"[!] ОШИБКА: Канал @{CHANNEL_USERNAME} не найден!")
            sys.exit(1)
        except ChannelPrivate:
            print(f"[!] ОШИБКА: Канал @{CHANNEL_USERNAME} является приватным!")
            sys.exit(1)

        current_username = chat.username
        if current_username is None:
            print("[!] ОШИБКА: Канал стал приватным (нет username).")
            sys.exit(1)

        CURRENT_USERNAME = current_username
        print(f"[i] Старый username для поиска: {OLD_USERNAME}")
        print(f"[i] Текущий username для замены: {CURRENT_USERNAME}")
        print(f"[i] ID канала: {chat.id}")
        print()

        checkpoint = load_checkpoint()
        start_from_id = 0
        total_processed = 0
        if checkpoint and checkpoint.get("last_processed_message_id", 0) > 0:
            start_from_id = checkpoint["last_processed_message_id"]
            total_processed = checkpoint.get("total_processed", 0)
            print(f"[i] Обнаружен checkpoint. Возобновление с сообщения ID {start_from_id}")
            if not DRY_RUN:
                confirm = input("    Продолжить с checkpoint? (y/n): ").strip().lower()
                if confirm != "y":
                    delete_checkpoint()
                    start_from_id = 0
                    total_processed = 0
            else:
                print(f"    (В режиме DRY_RUN checkpoint игнорируется для полной проверки)")
        print()

        messages = await collect_all_messages(app, chat.id)
        if not messages:
            print("[i] Нет сообщений для обработки.")
            return

        # ВАЖНО: пропускаем по checkpoint ТОЛЬКО в рабочем режиме
        if start_from_id > 0 and not DRY_RUN:
            messages = [m for m in messages if m.id > start_from_id]
            print(f"[i] Сообщений после checkpoint: {len(messages)}")

        if not DRY_RUN:
            init_csv_log()

        stats = {
            "total_messages": len(messages),
            "messages_with_links": 0,
            "total_links_found": 0,
            "success": 0,
            "errors": 0,
            "skipped": 0,
        }
        dry_run_examples = []

        print()
        print("[*] Начинаю обработку сообщений...")
        print("-" * 60)

        for idx, message in enumerate(messages, 1):
            if message.service:
                if not DRY_RUN:
                    write_log_entry(message.id, "", "", "skipped", "Сервисное сообщение")
                stats["skipped"] += 1
                total_processed += 1
                continue

            if message.forward_from or message.forward_from_chat or message.forward_sender_name:
                if not DRY_RUN:
                    write_log_entry(message.id, "", "", "skipped", "Пересланное сообщение")
                stats["skipped"] += 1
                total_processed += 1
                continue

            if not has_old_links(message):
                stats["skipped"] += 1
                total_processed += 1
                continue

            all_links = []
            if message.text:
                all_links.extend(find_links_in_text(message.text))
            if message.caption:
                all_links.extend(find_links_in_text(message.caption))
            if message.entities:
                all_links.extend(find_links_in_entities(message.entities))
            if message.caption_entities:
                all_links.extend(find_links_in_entities(message.caption_entities))
            if message.reply_markup and isinstance(message.reply_markup, InlineKeyboardMarkup):
                for row in message.reply_markup.inline_keyboard:
                    for button in row:
                        if button.url:
                            all_links.extend(find_links_in_text(button.url))

            if not all_links:
                stats["skipped"] += 1
                total_processed += 1
                continue

            stats["messages_with_links"] += 1
            stats["total_links_found"] += len(all_links)

            if DRY_RUN:
                for old_link, new_link in all_links:
                    dry_run_examples.append((message.id, old_link, new_link))
                print(f"  [{idx}/{len(messages)}] ID {message.id}: найдено {len(all_links)} ссылок")
            else:
                print(f"  [{idx}/{len(messages)}] ID {message.id}: редактирую ({len(all_links)} ссылок)...")
                try:
                    replacements, status = await edit_message(app, chat.id, message)
                    if status == "success":
                        stats["success"] += 1
                        for old_link, new_link in replacements:
                            write_log_entry(message.id, old_link, new_link, "success")
                        print(f"    ✓ Успешно заменено {len(replacements)} ссылок")
                    elif status == "skipped":
                        stats["skipped"] += 1
                        write_log_entry(message.id, "", "", "skipped", "Нет изменений")
                        print(f"    - Пропущено (нет изменений)")
                    else:
                        stats["errors"] += 1
                        error_msg = status.replace("error: ", "")
                        for old_link, new_link in replacements:
                            write_log_entry(message.id, old_link, new_link, "error", error_msg)
                        print(f"    ✗ Ошибка: {error_msg}")
                except FloodWait as e:
                    wait_time = e.value + 1
                    print(f"    [!] FloodWait: ждём {wait_time} секунд...")
                    await asyncio.sleep(wait_time)
                    try:
                        replacements, status = await edit_message(app, chat.id, message)
                        if status == "success":
                            stats["success"] += 1
                            for old_link, new_link in replacements:
                                write_log_entry(message.id, old_link, new_link, "success")
                        elif status == "skipped":
                            stats["skipped"] += 1
                            write_log_entry(message.id, "", "", "skipped", "Нет изменений")
                        else:
                            stats["errors"] += 1
                            error_msg = status.replace("error: ", "")
                            for old_link, new_link in replacements:
                                write_log_entry(message.id, old_link, new_link, "error", error_msg)
                    except Exception as retry_error:
                        stats["errors"] += 1
                        write_log_entry(message.id, "", "", "error", str(retry_error))
                        print(f"    ✗ Ошибка после повторной попытки: {retry_error}")
                except Exception as e:
                    stats["errors"] += 1
                    write_log_entry(message.id, "", "", "error", str(e))
                    print(f"    ✗ Ошибка: {e}")

            save_checkpoint(message.id, total_processed + 1)
            await asyncio.sleep(PAUSE_BETWEEN_EDITS)
            total_processed += 1

            if idx % 50 == 0:
                print(f"  --- Прогресс: {idx}/{len(messages)} ---")

        print()
        print("=" * 60)
        print("  ИТОГОВАЯ СТАТИСТИКА")
        print("=" * 60)
        print(f"  Всего сообщений обработано: {stats['total_messages']}")
        print(f"  Сообщений со ссылками:      {stats['messages_with_links']}")
        print(f"  Всего ссылок найдено:       {stats['total_links_found']}")
        print()

        if DRY_RUN:
            print("  [DRY RUN] Изменения НЕ применены.")
            print()
            if dry_run_examples:
                print(f"  Примеры замен (первые 10 из {len(dry_run_examples)}):")
                print("  " + "-" * 56)
                for msg_id, old_link, new_link in dry_run_examples[:10]:
                    print(f"    ID {msg_id}: {old_link} → {new_link}")
                print()
                print("  Для применения изменений:")
                print("    1. Установите DRY_RUN = False")
                print("    2. Удалите файл checkpoint.json (чтобы начать с начала)")
                print("    3. Запустите скрипт заново")
        else:
            print(f"  Успешно изменено: {stats['success']}")
            print(f"  С ошибками:       {stats['errors']}")
            print(f"  Пропущено:        {stats['skipped']}")
            print()
            print(f"  Лог сохранён в: {LOG_FILE}")
            print(f"  Checkpoint: {CHECKPOINT_FILE}")
        print("=" * 60)

    finally:
        await app.stop()
        print("[✓] Сессия завершена.")

# =============================================================================
# ТОЧКА ВХОДА
# =============================================================================
if __name__ == "__main__":
    print()
    print("Запуск скрипта обновления ссылок...")
    print()
    asyncio.run(main())