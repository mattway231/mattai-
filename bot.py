import asyncio
import logging
import os
import uuid

import google.generativeai as genai
from aiogram import Bot, Dispatcher
from aiogram.types import InlineQuery, InlineQueryResultArticle, InputTextMessageContent

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("tg-ai-bot")

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.0-flash")  # быстрый и бесплатный

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


async def main():
    log.info("Бот запущен, режим polling")
    await bot.delete_webhook(drop_pending_updates=True)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
