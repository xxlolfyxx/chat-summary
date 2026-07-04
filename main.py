import asyncio
import userbot
import controlbot


async def main():
    # Передаём клиент юзербота в контрол-бот
    controlbot.userbot_client = userbot.client

    await asyncio.gather(
        userbot.start_userbot(),
        controlbot.start_bot(),
    )


asyncio.run(main())
