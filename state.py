monitored_chats = []       # [chat_id, ...]
monitored_names = {}       # {chat_id: name}
messages_buffer = {}       # {chat_name: [messages]}
owner_id = None            # Telegram ID владельца (кто написал /start первым)
