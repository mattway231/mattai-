import asyncio
import logging
import os
import uuid

import google.generativeai as genai
from aiogram import Bot, Dispatcher
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web, ClientSession, ClientTimeout

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tg-ai-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-3.6-flash")  # актуальная бесплатная модель

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Простой кэш, чтобы не дёргать API повторно на одинаковый запрос подряд
_cache: dict[str, str] = {}


def ask_gemini(prompt: str) -> str:
    """Синхронный вызов Gemini. Для больших нагрузок можно заменить на async-клиент."""
    if prompt in _cache:
        return _cache[prompt]
    try:
        response = model.generate_content(
            prompt,
            generation_config={"max_output_tokens": 512, "temperature": 0.7},
        )
        text = (response.text or "").strip()
    except Exception as e:
        log.exception("Gemini error")
        text = f"Ошибка запроса к ИИ: {e}"
    _cache[prompt] = text
    # ограничиваем размер кэша
    if len(_cache) > 200:
        _cache.pop(next(iter(_cache)))
    return text


@dp.inline_query()
async def handle_inline(query: InlineQuery):
    text = query.query.strip()

    if not text:
        # Подсказка, когда пользователь только набрал @имя_бота
        results = [
            InlineQueryResultArticle(
                id=str(uuid.uuid4()),
                title="Введите запрос к ИИ",
                description="Например: перефразируй вежливо / ответь на вопрос / переведи",
                input_message_content=InputTextMessageContent(
                    message_text="_(пустой запрос)_", parse_mode="Markdown"
                ),
            )
        ]
        await query.answer(results, cache_time=1, is_personal=True)
        return

    # Режим команд через префикс, чтобы гибко управлять поведением:
    # "написать: ..." -> просто ответ
    # "правь: ..." -> исправить/улучшить твой текст
    # "переведи: ..." -> перевод
    # без префикса -> обычный ответ на вопрос
    answer_text = ask_gemini(text)

    # Обрезаем, т.к. Telegram ограничивает превью
    preview = answer_text[:200] + ("…" if len(answer_text) > 200 else "")

    results = [
        InlineQueryResultArticle(
            id=str(uuid.uuid4()),
            title="Вставить ответ ИИ",
            description=preview,
            input_message_content=InputTextMessageContent(message_text=answer_text),
        )
    ]
    await query.answer(results, cache_time=1, is_personal=True)


# Render сам даёт публичный домен вида https://ваш-сервис.onrender.com
# Он придёт как переменная окружения RENDER_EXTERNAL_URL автоматически
WEBHOOK_PATH = "/webhook"
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").rstrip("/")
WEBHOOK_URL = f"{BASE_URL}{WEBHOOK_PATH}"
PORT = int(os.environ.get("PORT", 10000))


async def self_ping():
    """Раз в 10 минут дёргаем свой же публичный URL, чтобы Render
    не усыплял бесплатный инстанс после 15 минут простоя."""
    if not BASE_URL:
        log.warning("BASE_URL не задан — самопинг отключён")
        return
    await asyncio.sleep(30)  # даём серверу время подняться
    async with ClientSession(timeout=ClientTimeout(total=15)) as session:
        while True:
            try:
                async with session.get(BASE_URL) as resp:
                    log.info(f"Самопинг: {resp.status}")
            except Exception as e:
                log.warning(f"Самопинг не удался: {e}")
            await asyncio.sleep(600)  # 10 минут


async def on_startup(app: web.Application):
    if WEBHOOK_URL and BASE_URL:
        await bot.set_webhook(WEBHOOK_URL, drop_pending_updates=True)
        log.info(f"Webhook установлен: {WEBHOOK_URL}")
    else:
        log.warning("RENDER_EXTERNAL_URL не найден, webhook не установлен")
    asyncio.create_task(self_ping())


async def health(request):
    # чтобы Render видел, что сервис жив, и не считал деплой неудачным
    return web.Response(text="ok")


def main():
    app = web.Application()
    app.router.add_get("/", health)
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
