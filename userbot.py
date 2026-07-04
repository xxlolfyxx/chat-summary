import asyncio
import os
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
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
monitored_chats = []   # список чатов (изменяется командами /add и /del)


def update_handlers():
    """Перерегистрировать обработчик сообщений с актуальным списком чатов."""
    # Снимаем все обработчики NewMessage (кроме команд)
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
    name = getattr(chat, 'title', None) or getattr(chat, 'username', str(chat.id))
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

@client.on(events.NewMessage(pattern=r'/add(?:\s+(.+))?', outgoing=True))
async def cmd_add(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await event.respond('❌ Укажи username или ID чата.\nПример: `/add durov` или `/add -1001234567890`')
        return

    arg = arg.strip()
    # Попробуем преобразовать в int если это ID
    try:
        chat_id = int(arg)
        entry = chat_id
    except ValueError:
        entry = arg

    if entry in monitored_chats:
        await event.respond(f'⚠️ `{arg}` уже в списке.')
        return

    monitored_chats.append(entry)
    update_handlers()
    await event.respond(f'✅ Добавлен: `{arg}`\n\nТеперь отслеживается {len(monitored_chats)} чат(ов).', parse_mode='md')


@client.on(events.NewMessage(pattern=r'/del(?:\s+(.+))?', outgoing=True))
async def cmd_del(event):
    arg = event.pattern_match.group(1)
    if not arg:
        await event.respond('❌ Укажи username или ID чата.\nПример: `/del durov`')
        return

    arg = arg.strip()
    try:
        entry = int(arg)
    except ValueError:
        entry = arg

    if entry not in monitored_chats:
        await event.respond(f'⚠️ `{arg}` не найден в списке.')
        return

    monitored_chats.remove(entry)
    # Очищаем буфер этого чата
    messages_buffer.pop(arg, None)
    update_handlers()
    await event.respond(f'🗑 Удалён: `{arg}`\n\nОсталось {len(monitored_chats)} чат(ов).', parse_mode='md')


@client.on(events.NewMessage(pattern='/summary', outgoing=True))
async def cmd_summary(event):
    await event.respond('⏳ Генерирую сводку...')
    await send_summary()


@client.on(events.NewMessage(pattern='/chats', outgoing=True))
async def cmd_chats(event):
    if monitored_chats:
        chats_text = '\n'.join(f'• {c}' for c in monitored_chats)
        await event.respond(f'📋 Отслеживаемые чаты:\n{chats_text}')
    else:
        await event.respond('⚠️ Список чатов пуст.\nДобавь: `/add username_или_id`', parse_mode='md')


@client.on(events.NewMessage(pattern='/help', outgoing=True))
async def cmd_help(event):
    await event.respond(
        '🤖 *Команды юзербота:*\n\n'
        '/add `username или ID` — добавить чат\n'
        '/del `username или ID` — удалить чат\n'
        '/chats — список отслеживаемых чатов\n'
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
        '/add username — добавить чат\n'
        '/del username — удалить чат\n'
        '/chats — список чатов\n'
        '/summary — сводка сейчас\n'
        '/help — помощь'
    ))

    asyncio.create_task(daily_loop())
    await client.run_until_disconnected()


asyncio.run(main())
