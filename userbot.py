import asyncio
import os
from datetime import datetime, timedelta
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from telethon.tl.types import Channel, Chat
import state

API_ID = int(os.getenv('API_ID', '34806337'))
API_HASH = os.getenv('API_HASH', 'acf1d2c83573f5649c578bcf6a1d2da4')
SESSION_STRING = os.getenv('SESSION_STRING', '')
SUMMARY_HOUR = 21

session = StringSession(SESSION_STRING) if SESSION_STRING else 'session'
client = TelegramClient(session, API_ID, API_HASH)


def update_handlers():
    for cb in list(client._event_builders):
        if cb[0].__class__.__name__ == 'NewMessage' and getattr(cb[1], 'chats', None) is not None:
            client.remove_event_handler(cb[1], cb[0])
    if state.monitored_chats:
        @client.on(events.NewMessage(chats=state.monitored_chats))
        async def _on_message(event):
            if not event.text:
                return
            chat = await event.get_chat()
            name = state.monitored_names.get(chat.id) or getattr(chat, 'title', str(chat.id))
            sender = await event.get_sender()
            who = getattr(sender, 'first_name', '?')
            state.messages_buffer.setdefault(name, []).append(f'{who}: {event.text}')


async def daily_loop():
    while True:
        now = datetime.now()
        target = now.replace(hour=SUMMARY_HOUR, minute=0, second=0, microsecond=0)
        if now >= target:
            target += timedelta(days=1)
        await asyncio.sleep((target - now).total_seconds())

        if not state.messages_buffer:
            await client.send_message('me', '📭 Новых сообщений нет.')
            return

        from groq import Groq
        groq = Groq(api_key=os.getenv('GROQ_KEY', ''))
        text = '📊 *Сводка по чатам*\n\n'
        for name, msgs in state.messages_buffer.items():
            chunk = '\n'.join(msgs[-150:])
            resp = groq.chat.completions.create(
                model='llama3-8b-8192',
                messages=[{'role': 'user', 'content': (
                    f'Сделай краткое резюме переписки в чате "{name}". '
                    f'О чём говорят, что важного? Отвечай на русском.\n\n{chunk}'
                )}]
            )
            text += f'*{name}* ({len(msgs)} сообщ.)\n{resp.choices[0].message.content}\n\n'

        await client.send_message('me', text, parse_mode='md')
        state.messages_buffer.clear()


async def start_userbot():
    await client.start()
    me = await client.get_me()
    print(f'✅ Юзербот запущен как: {me.first_name} (@{me.username})')
    asyncio.create_task(daily_loop())
    await client.run_until_disconnected()
