import asyncio
import os
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
from groq import Groq

# === НАСТРОЙКИ ===
API_ID = int(os.getenv('API_ID', '34806337'))
API_HASH = os.getenv('API_HASH', 'acf1d2c83573f5649c578bcf6a1d2da4')
GROQ_KEY = os.getenv('GROQ_KEY', '')
SESSION_STRING = os.getenv('SESSION_STRING', '')

SUMMARY_HOUR = 21  # час ежедневной сводки (по времени сервера)
# =================

session = StringSession(SESSION_STRING) if SESSION_STRING else 'session'
client = TelegramClient(session, API_ID, API_HASH)
groq_client = Groq(api_key=GROQ_KEY)

messages_buffer = {}   # {название чата: [сообщения]}
monitored_chats = []   # список ID отслеживаемых чатов
monitored_names = {}   # {chat_id: название}

# Временное хранилище для выбора чата из списка
pending_selection = {}  # {user_id: [{'id': ..., 'name': ...}]}


def update_handlers():
    for cb in list(client._event_builders):
        if cb[0].__class__.__name__ == 'NewMessage' and getattr(cb[1], 'chats', None) is not None:
            client.remove_event_handler(cb[1], cb[0])
    if monitored_chats:
        @client.on(events.NewMessage(chats=monitored_chats))
        async def _on_message(event):
            await on_message(event)


async def on_message(event):
    if not event.text:
        return
    chat = await event.get_chat()
    name = monitored_names.get(chat.id) or getattr(chat, 'title', str(chat.id))
    sender = await event.get_sender()
    who = getattr(sender, 'first_name', '?')
    messages_buffer.setdefault(name, []).append(f'{who}: {event.text}')


async def make_summary(chat_name, messages):
    text = '\n'.join(messages[-150:])
    resp = groq_client.chat.completions.create(
        model='llama3-8b-8192',
        messages=[{
            'role': 'user',
            'content': (
                f'Сделай краткое резюме переписки в чате "{chat_name}". '
                f'О чём говорят люди, что важного обсуждается? '
                f'Отвечай на русском, кратко и по делу.\n\nПереписка:\n{text}'
            )
        }]
    )
    return resp.choices[0].message.content


async def send_summary():
    if not messages_buffer:
        await client.send_message('me', '📭 Новых сообщений в отслеживаемых чатах нет.')
        return

    text = '📊 *Сводка по чатам*\n\n'
    for name, msgs in messages_buffer.items():
        summary = await make_summary(name, msgs)
        text += f'*{name}* ({len(msgs)} сообщ.)\n{summary}\n\n'

    await client.send_message('me', text, parse_mode='md')
    messages_buffer.clear()


# ── Команды ──────────────────────────────────────────────

@client.on(events.NewMessage(pattern='/add', outgoing=True))
async def cmd_add(event):
    """Показать список чатов для выбора."""
    await event.respond('⏳ Загружаю список чатов...')

    dialogs = []
    async for dialog in client.iter_dialogs(limit=50):
        if isinstance(dialog.entity, (Channel, Chat)):
            dialogs.append({
                'id': dialog.entity.id,
                'name': dialog.name,
                'access_hash': getattr(dialog.entity, 'access_hash', None)
            })

    if not dialogs:
        await event.respond('❌ Не найдено групп или каналов.')
        return

    me = await client.get_me()
    pending_selection[me.id] = dialogs

    lines = []
    for i, d in enumerate(dialogs, 1):
        mark = '✅ ' if d['id'] in monitored_chats else ''
        lines.append(f'{i}. {mark}{d["name"]}')

    text = '📋 *Твои чаты и каналы:*\n\n' + '\n'.join(lines)
    text += '\n\nОтветь цифрой чтобы добавить/убрать чат.\nПример: `3`'
    await event.respond(text, parse_mode='md')


@client.on(events.NewMessage(outgoing=True))
async def cmd_select(event):
    """Обработка выбора цифры из списка."""
    if not event.text or not event.text.strip().isdigit():
        return

    me = await client.get_me()
    dialogs = pending_selection.get(me.id)
    if not dialogs:
        return

    num = int(event.text.strip())
    if num < 1 or num > len(dialogs):
        await event.respond(f'❌ Введи число от 1 до {len(dialogs)}')
        return

    chosen = dialogs[num - 1]
    chat_id = chosen['id']
    name = chosen['name']

    if chat_id in monitored_chats:
        monitored_chats.remove(chat_id)
        monitored_names.pop(chat_id, None)
        messages_buffer.pop(name, None)
        update_handlers()
        await event.respond(f'🗑 Убран: *{name}*\n\nОтслеживается: {len(monitored_chats)} чат(ов).', parse_mode='md')
    else:
        monitored_chats.append(chat_id)
        monitored_names[chat_id] = name
        update_handlers()
        await event.respond(f'✅ Добавлен: *{name}*\n\nОтслеживается: {len(monitored_chats)} чат(ов).', parse_mode='md')

    del pending_selection[me.id]


@client.on(events.NewMessage(pattern='/chats', outgoing=True))
async def cmd_chats(event):
    if monitored_chats:
        chats_text = '\n'.join(f'• {monitored_names.get(c, c)}' for c in monitored_chats)
        await event.respond(f'📋 *Отслеживаемые чаты:*\n{chats_text}', parse_mode='md')
    else:
        await event.respond('⚠️ Список пуст. Напиши `/add` чтобы выбрать чаты.', parse_mode='md')


@client.on(events.NewMessage(pattern='/summary', outgoing=True))
async def cmd_summary(event):
    await event.respond('⏳ Генерирую сводку...')
    await send_summary()


@client.on(events.NewMessage(pattern='/help', outgoing=True))
async def cmd_help(event):
    await event.respond(
        '🤖 *Команды юзербота:*\n\n'
        '/add — выбрать чаты из списка\n'
        '/chats — отслеживаемые чаты\n'
        '/summary — сводка прямо сейчас\n'
        '/help — помощь\n\n'
        f'⏰ Автосводка каждый день в {SUMMARY_HOUR}:00',
        parse_mode='md'
    )


# ── Фоновый цикл ─────────────────────────────────────────

async def daily_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=SUMMARY_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        wait = (target - now).total_seconds()
        await asyncio.sleep(wait)
        await send_summary()


async def main():
    await client.start()
    me = await client.get_me()
    print(f'✅ Запущен как: {me.first_name} (@{me.username})')

    if not SESSION_STRING:
        print('\n' + '=' * 50)
        print('SESSION_STRING (сохрани для сервера):')
        print(client.session.save())
        print('=' * 50 + '\n')

    await client.send_message('me', (
        '✅ Юзербот запущен!\n\n'
        '/add — выбрать чаты из списка\n'
        '/chats — список чатов\n'
        '/summary — сводка сейчас\n'
        '/help — помощь'
    ))

    asyncio.create_task(daily_loop())
    await client.run_until_disconnected()


asyncio.run(main())
