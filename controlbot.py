from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import (
    Message, CallbackQuery,
    InlineKeyboardMarkup, InlineKeyboardButton
)
import state

BOT_TOKEN = '8772402014:AAHWFC1n5P4-OPK5D5YlJVFm1IZO9B4dPCg'

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Ссылка на userbot клиент — устанавливается из main.py
userbot_client = None


def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text='📋 Мои чаты', callback_data='my_chats')],
        [InlineKeyboardButton(text='➕ Добавить / убрать чат', callback_data='add_chat')],
        [InlineKeyboardButton(text='📊 Сводка сейчас', callback_data='summary_now')],
    ])


def chats_keyboard(dialogs):
    buttons = []
    for i, d in enumerate(dialogs):
        mark = '✅ ' if d['id'] in state.monitored_chats else ''
        buttons.append([InlineKeyboardButton(
            text=f'{mark}{d["name"]}',
            callback_data=f'toggle_{i}'
        )])
    buttons.append([InlineKeyboardButton(text='◀️ Назад', callback_data='back')])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# Временный список диалогов для выбора
dialog_cache = []


@dp.message(Command('start'))
async def cmd_start(message: Message):
    state.owner_id = message.from_user.id
    await message.answer(
        '👋 Привет! Я *SummaryAI Bot*\n\n'
        'Слежу за твоими чатами и делаю краткие AI-сводки.\n\n'
        'Выбери действие:',
        parse_mode='Markdown',
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == 'back')
async def cb_back(call: CallbackQuery):
    await call.message.edit_text(
        '👋 Главное меню:',
        reply_markup=main_menu()
    )


@dp.callback_query(F.data == 'my_chats')
async def cb_my_chats(call: CallbackQuery):
    if not state.monitored_chats:
        await call.message.edit_text(
            '📭 Ты ещё не добавил ни одного чата.\n\nНажми *Добавить / убрать чат*.',
            parse_mode='Markdown',
            reply_markup=InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text='➕ Добавить чат', callback_data='add_chat')],
                [InlineKeyboardButton(text='◀️ Назад', callback_data='back')],
            ])
        )
        return

    names = '\n'.join(f'• {state.monitored_names.get(c, c)}' for c in state.monitored_chats)
    await call.message.edit_text(
        f'📋 *Отслеживаемые чаты:*\n\n{names}',
        parse_mode='Markdown',
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text='➕ Добавить / убрать', callback_data='add_chat')],
            [InlineKeyboardButton(text='◀️ Назад', callback_data='back')],
        ])
    )


@dp.callback_query(F.data == 'add_chat')
async def cb_add_chat(call: CallbackQuery):
    global dialog_cache
    await call.message.edit_text('⏳ Загружаю список чатов...')

    from telethon.tl.types import Channel, Chat as TgChat
    dialogs = []
    async for dialog in userbot_client.iter_dialogs(limit=60):
        if isinstance(dialog.entity, (Channel, TgChat)):
            dialogs.append({'id': dialog.entity.id, 'name': dialog.name})

    if not dialogs:
        await call.message.edit_text('❌ Нет доступных чатов.', reply_markup=main_menu())
        return

    dialog_cache = dialogs
    await call.message.edit_text(
        '📋 Выбери чаты для мониторинга.\n✅ — уже отслеживается:',
        reply_markup=chats_keyboard(dialogs)
    )


@dp.callback_query(F.data.startswith('toggle_'))
async def cb_toggle(call: CallbackQuery):
    global dialog_cache
    idx = int(call.data.split('_')[1])
    if idx >= len(dialog_cache):
        await call.answer('Ошибка, попробуй снова.')
        return

    chosen = dialog_cache[idx]
    chat_id = chosen['id']
    name = chosen['name']

    if chat_id in state.monitored_chats:
        state.monitored_chats.remove(chat_id)
        state.monitored_names.pop(chat_id, None)
        state.messages_buffer.pop(name, None)
        await call.answer(f'🗑 Убран: {name}')
    else:
        state.monitored_chats.append(chat_id)
        state.monitored_names[chat_id] = name
        await call.answer(f'✅ Добавлен: {name}')

    # Обновляем клавиатуру
    await call.message.edit_reply_markup(reply_markup=chats_keyboard(dialog_cache))


@dp.callback_query(F.data == 'summary_now')
async def cb_summary(call: CallbackQuery):
    await call.message.edit_text('⏳ Генерирую сводку...')

    if not state.messages_buffer:
        await call.message.edit_text(
            '📭 Новых сообщений нет.',
            reply_markup=main_menu()
        )
        return

    from groq import Groq
    import os
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
        summary = resp.choices[0].message.content
        text += f'*{name}* ({len(msgs)} сообщ.)\n{summary}\n\n'

    state.messages_buffer.clear()
    await call.message.edit_text(text, parse_mode='Markdown', reply_markup=main_menu())


async def start_bot():
    await dp.start_polling(bot)
