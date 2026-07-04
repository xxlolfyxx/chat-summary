from telethon.sync import TelegramClient
from telethon.sessions import StringSession

API_ID = 34806337
API_HASH = 'acf1d2c83573f5649c578bcf6a1d2da4'

with TelegramClient(StringSession(), API_ID, API_HASH) as client:
    print('\n' + '=' * 50)
    print('SESSION_STRING (скопируй для Koyeb):')
    print(client.session.save())
    print('=' * 50 + '\n')
