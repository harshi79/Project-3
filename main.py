import os
import html as html_lib
import asyncio
import random
from datetime import datetime, timedelta
from typing import Optional, List, Tuple, Dict, Any

from dotenv import load_dotenv
import asyncpg
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    InputMediaPhoto
)
from telegram.error import Forbidden, ChatMigrated, BadRequest
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ConversationHandler,
    ContextTypes, ChatMemberHandler
)
from telegram.constants import ChatMemberStatus as CMS
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
import uvicorn

load_dotenv()

# ---------- Configuration ----------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN missing")

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise ValueError("DATABASE_URL missing")

OWNER_ID = int(os.getenv("OWNER_ID", "7728424218"))
OWNER_USERNAME = os.getenv("OWNER_USERNAME", "YorichiiPrime")
OWNER_LINK = f"https://t.me/{OWNER_USERNAME}"
SUPPORT_LINK = os.getenv("SUPPORT_LINK", "https://t.me/kingchaos7")
WEB_STORE_URL = os.getenv("WEB_STORE_URL", "https://your-vercel-app.vercel.app")
# Set WEBHOOK_URL in your environment for production (e.g. https://myapp.railway.app)
# Leave empty to use polling (local/dev)
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "")

# Conversation states
NAME, ANIME, IMG_URL, RARITY, PRICE = range(5)
# Dev broadcast states
BROADCAST_CONTENT = 10
SETSTARTMSG_CONTENT = 11

# Global scheduler and application reference (used by webhook endpoint)
scheduler = AsyncIOScheduler()
bot_application = None

# ---------- Rarity System ----------
RARITY_WEIGHTS = {
    'Common': 40,
    'Uncommon': 25,
    'Elite': 15,
    'Epic': 8,
    'Waifu': 4,
    'Special Edition': 3,
    'Legendary': 2,
    'Limited': 1.5,
    'Event': 1,
    'Mythic': 0.5,
}

RARITY_COINS = {
    'Common': 50,
    'Uncommon': 100,
    'Elite': 200,
    'Epic': 400,
    'Waifu': 500,
    'Special Edition': 700,
    'Legendary': 1000,
    'Limited': 1200,
    'Event': 1500,
    'Mythic': 2500,
}

def get_rarity_bonus(rarity: str) -> int:
    return RARITY_COINS.get(rarity, 50)

def format_time_delta(seconds: float) -> str:
    """Convert seconds into human-readable countdown like 1h 23m 45s"""
    seconds = int(seconds)
    if seconds <= 0:
        return "0s"
    h = seconds // 3600
    m = (seconds % 3600) // 60
    s = seconds % 60
    parts = []
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s or not parts:
        parts.append(f"{s}s")
    return " ".join(parts)

# ---------- Language Strings ----------
STRINGS: Dict[str, Dict[str, Any]] = {
    'en': {
        'start_first': "❌ Please start the bot first with /start",
        'welcome': "Welcome to Anime Character Collector Bot!\nUse /help to see commands.",
        'daily_claimed': "💸 You claimed *{reward} coins*!\n💰 Total balance: `{coins}` coins{streak_text}",
        'daily_streak': "\n🔥 Daily Streak: {streak} days",
        'daily_streak_bonus': "\n🎉 *7-Day Streak Bonus!* +3000 coins!",
        'daily_wait': "⏳ Already claimed here. Next daily in *{time}*.",
        'claim_wait': "⏳ Already claimed here. Next claim in *{time}*.",
        'claim_no_chars': "❌ No characters available. Contact the owner.",
        'claim_all_owned': (
            "🏆 *You own every character in this group's collection!*\n\n╭───────────────╮\n"
            "💰 *Reward:* +10,000 Coins\n👜 *Balance:* {coins} Coins\n╰───────────────╯\n\n"
            "⏳ Come back in 11 hours for your next claim!"
        ),
        'claim_rarity_bonus': "✨ *{rarity} Rarity Bonus!* +{bonus} coins!",
        'claim_caption': (
            "{emoji} *{name}*\n╭───────────────╮\n🎬 Anime: {anime}\n💎 Tier: {emoji} {rarity}\n"
            "🆔 Card ID: `{char_id}`\n💰 Value: {price} Coins\n╰───────────────╯\n\n"
            "✨ A rare presence has been claimed…\n🌸 Grace\\. Power\\. Mystery — all in one\\.\n\n🔐 Status: Newly Claimed"
        ),
        'wallet_text': (
            "👤 *{name}'s Wallet*\n━━━━━━━━━━━━━━━━\n💰 *Coins:* `{coins}` _(global)_\n"
            "🎴 *Characters here:* `{char_count}`\n━━━━━━━━━━━━━━━━\n_/daily to earn coins • /vault to see collection_"
        ),
        'vault_empty': "📭 Your vault is empty here. Use /claim or /buy to get characters!",
        'vault_caption': (
            "{emoji} *{name}*\n╭───────────────╮\n🎬 Anime: {anime}\n💎 Tier: {emoji} {rarity}\n"
            "🆔 Card ID: `{char_id}`\n💰 Value: {price} Coins\n╰───────────────╯\n\n_Card {page} of {total}_"
        ),
        'vault_not_yours': "⛔ This is not your vault!",
        'market_text': "🛒 *Character Market*\nBrowse all characters in the web store 👇",
        'buy_usage': "Usage: /buy <character_id> [id2 ...]",
        'buy_no_coins': "❌ Insufficient coins. Need {total_cost}, you have {coins}.",
        'buy_first_bonus': "🎉 *First Buy Bonus!* +1500 coins!",
        'buy_success': "✅ Bought {count} character(s).\n",
        'buy_failed': "⚠️ Failed: {items}",
        'buy_not_found': "{id} (not found)",
        'buy_already_owned': "{id} (already owned)",
        'sell_usage': "Usage: /sell <character_id>",
        'sell_not_found': "❌ Character not found.",
        'sell_not_owned': "❌ You don't own this character.",
        'sell_success': "💰 Sold <b>{name}</b> for <b>{price} coins</b> (70% of base).",
        'search_usage': "Usage: /search <character name>",
        'search_no_results': "No matching characters.",
        'guess_groups_only': "🎭 This command only works in groups!",
        'guess_usage': "Usage: /guess <character name>",
        'guess_cooldown': "⏳ Please wait 10 seconds before guessing again.",
        'guess_no_drop': "❌ No active drop right now. Wait for the next one!",
        'guess_already_won': "🏆 Someone already guessed this character!",
        'guess_error': "❌ Error loading character data.",
        'guess_correct': "✨ <b>CORRECT!</b> {mention} guessed <b>{name}</b>!{streak_text}\n\n💰 Reward: +{reward} coins\n{reward_text}",
        'guess_already_own': "💰 Already owned! You get *{coins}* coins instead! ({rarity} × 2)",
        'guess_added': "🎴 {name} added to your vault! +{coins} bonus coins!",
        'guess_wrong': "❌ Wrong guess! Try again!",
        'guess_streak': "\n🔥 x{streak} Streak!",
        'guess_first_bonus': "🎉 <b>First Guess Win Bonus!</b> +1000 coins!",
        'streak_msg': "🔥 <b>@{name} x{streak} streak!</b> 🔥",
        'drops_groups_only': "This command only works in groups!",
        'drops_enable_admin': "⛔ Only group admins or the bot owner can enable drops.",
        'drops_enabled': "🎭 *Drops Enabled!*\n\nCharacters will now drop every hour.\nUse /guess <n> to guess the character!",
        'drops_disable_admin': "⛔ Only group admins or the bot owner can disable drops.",
        'drops_disabled': "🚫 *Drops Disabled!*\n\nNo more automatic drops in this group.",
        'drop_guess_caption': "🎭 Guess the character!",
        'drop_hint_caption': "🎭 Guess the character!\n\n💡 <b>Hint:</b> From <i>{anime}</i>",
        'collector_bonus': "🎉 <b>Collector Bonus!</b> You own 10 characters in this group! +2500 coins!",
        'tasks_dm_only': "📋 Please use /tasks in DM (private chat) with me!",
        'tasks_header': "📋 <b>Your Tasks</b>\n━━━━━━━━━━━━━━━━\n\n",
        'tasks_referral': (
            "📨 <b>Referral Task</b>\n   ✅ Refer friends and earn!\n"
            "   📊 Referred: {ref_count} users | Earned: {ref_earned} coins\n"
            "   💰 Reward: 1000 coins per referral\n\n"
        ),
        'tasks_channel_header': "📢 <b>Channel Join Tasks</b>\n",
        'tasks_no_channel': "   No channel tasks available\n",
        'tasks_group_add': "\n➕ <b>Add Bot to Group</b>\n   ⏳ Add me to a group as admin (+5000 coins)\n\n",
        'tasks_bonus_header': "🎁 <b>Bonus Tasks</b>\n",
        'tasks_streak': "   {status} 7-Day Streak ({streak}/7) (+3000 coins)\n",
        'tasks_first_buy': "   {status} First Buy (+1500 coins)\n",
        'tasks_collector': "   {status} Collector ({count}/10 chars) (+2500 coins)\n",
        'tasks_first_guess': "   {status} First Guess Win (+1000 coins)\n",
        'tasks_done_btn': "✅ Done: {label}",
        'tasks_complete': "🎉 <b>Task Complete!</b>\n\n✅ Joined {desc}\n💰 Reward: +{reward} coins!",
        'tasks_not_joined': "❌ You haven't joined the channel yet!",
        'tasks_verify_error': "❌ Error verifying membership. Make sure the bot is admin in the channel!",
        'tasks_already_done': "✅ You already completed this task!",
        'refer_dm_only': "📨 Please use /refer in DM with me!",
        'refer_text': (
            "📨 <b>Your Referral Link</b>\n━━━━━━━━━━━━━━━━\n\n🔗 <code>{link}</code>\n\n"
            "📊 <b>Stats:</b>\n   👥 Referred: {ref_count} users\n   💰 Total earned: {ref_earned} coins\n\n"
            "💡 Share this link with friends!\n   • You get 1000 coins per referral\n   • They get 500 coins for joining"
        ),
        'lb_groups_only': "🏆 This command only works in groups!",
        'lb_empty': "No collectors yet! Start collecting with /claim or /buy!",
        'lb_header': "╔══════════════════════════╗\n   🏆 <b>GLOBAL LEADERBOARD</b> 🏆\n╚══════════════════════════╝\n\n",
        'lb_footer': "\n━━━━━━━━━━━━━━━━\n📅 <i>{date}</i>\n🎁 <i>Top 3 earn weekly prizes every Sunday!</i>\n💡 <i>Use /claim and /buy to collect more!</i>",
        'weekly_lb_header': "╔══════════════════════════╗\n   🏆 <b>WEEKLY LEADERBOARD</b> 🏆\n╚══════════════════════════╝\n\n",
        'weekly_lb_prizes': "\n━━━━━━━━━━━━━━━━\n🎊 <b>Weekly Prizes Distributed!</b>\n",
        'weekly_lb_footer': "\n📅 <i>{date}</i> | 💡 <i>Collect more to climb the ranks!</i>",
        'weekly_dm': (
            "🎉 <b>Weekly Leaderboard Prize!</b>\n\nYou ranked <b>#{rank}</b> on the global collector leaderboard!\n"
            "💰 <b>+{reward} coins</b> have been added to your wallet!\n\nKeep collecting to stay on top! 🏆"
        ),
        'welcome_member': (
            "👋 Welcome to <b>{group}</b>, {mention}!\n━━━━━━━━━━━━━━━━\n"
            "🎮 Use /start to begin your adventure\n💰 Claim daily coins with /daily\n"
            "🎴 Get your first character with /claim\n🛒 Browse the /market for more!"
        ),
        'admins_groups_only': "This command only works in groups.",
        'admins_none': "No human admins found.",
        'admins_header': "👥 <b>Human Admins</b>\n",
        'calladmins_groups_only': "Only in groups.",
        'calladmins_cooldown': "⏳ Rate limit: once per 10 minutes per group.",
        'calladmins_none': "No human admins to call.",
        'calladmins_text': "Hey admins come fast 🙃\n",
        'error': "⚠️ An error occurred. Please try again.",
        'lang_choose': "🌐 Choose your language / Выберите язык:",
        'lang_set_en': "✅ Language set to English!",
        'lang_set_ru': "✅ Язык установлен: Русский!",
        'bot_added_thanks': "🎉 <b>Thanks for adding me to {group}!</b>\n\n💰 You earned <b>5000 coins!</b>\nUse /tasks to see more ways to earn!",
        'ref_notify': "🎉 <b>New Referral!</b>\n@{name} joined using your link!\n💰 You earned <b>1000 coins!</b>",
        'salty': [
            "No one guessed... what a fool group 🙄",
            "50 minutes and nothing? Embarrassing 💀",
            "The character was {name}... y'all really didn't know? 😂",
            "Zero correct guesses. Zero. 💀",
            "Even my grandma would have guessed that. Unbelievable.",
            "Dropped the ball on this one, didn't you? 🏀❌",
            "Mystery remains... because none of you tried hard enough 🤷",
            "Y'all need to watch more anime. That was easy."
        ],
    },
    'ru': {
        'start_first': "❌ Пожалуйста, сначала запустите бота командой /start",
        'welcome': "Добро пожаловать в Anime Character Collector Bot!\nИспользуйте /help для просмотра команд.",
        'daily_claimed': "💸 Вы получили *{reward} монет*!\n💰 Баланс: `{coins}` монет{streak_text}",
        'daily_streak': "\n🔥 Серия: {streak} дней",
        'daily_streak_bonus': "\n🎉 *Бонус за 7 дней подряд!* +3000 монет!",
        'daily_wait': "⏳ Уже получено. Следующий ежедневный через *{time}*.",
        'claim_wait': "⏳ Уже получено. Следующий персонаж через *{time}*.",
        'claim_no_chars': "❌ Персонажи недоступны. Обратитесь к владельцу.",
        'claim_all_owned': (
            "🏆 *Вы владеете всеми персонажами коллекции этой группы!*\n\n╭───────────────╮\n"
            "💰 *Награда:* +10,000 Монет\n👜 *Баланс:* {coins} Монет\n╰───────────────╯\n\n"
            "⏳ Возвращайтесь через 11 часов за следующим персонажем!"
        ),
        'claim_rarity_bonus': "✨ *Бонус редкости {rarity}!* +{bonus} монет!",
        'claim_caption': (
            "{emoji} *{name}*\n╭───────────────╮\n🎬 Аниме: {anime}\n💎 Уровень: {emoji} {rarity}\n"
            "🆔 ID Карты: `{char_id}`\n💰 Стоимость: {price} Монет\n╰───────────────╯\n\n"
            "✨ Редкое появление было заявлено…\n🌸 Грация\\. Сила\\. Загадка — всё в одном\\.\n\n🔐 Статус: Только что получен"
        ),
        'wallet_text': (
            "👤 *Кошелёк {name}*\n━━━━━━━━━━━━━━━━\n💰 *Монеты:* `{coins}` _(глобально)_\n"
            "🎴 *Персонажей здесь:* `{char_count}`\n━━━━━━━━━━━━━━━━\n_/daily для монет • /vault для коллекции_"
        ),
        'vault_empty': "📭 Ваше хранилище пусто. Используйте /claim или /buy!",
        'vault_caption': (
            "{emoji} *{name}*\n╭───────────────╮\n🎬 Аниме: {anime}\n💎 Уровень: {emoji} {rarity}\n"
            "🆔 ID Карты: `{char_id}`\n💰 Стоимость: {price} Монет\n╰───────────────╯\n\n_Карта {page} из {total}_"
        ),
        'vault_not_yours': "⛔ Это не ваше хранилище!",
        'market_text': "🛒 *Рынок персонажей*\nПросматривайте всех персонажей в веб-магазине 👇",
        'buy_usage': "Использование: /buy <id> [id2 ...]",
        'buy_no_coins': "❌ Недостаточно монет. Нужно {total_cost}, у вас {coins}.",
        'buy_first_bonus': "🎉 *Бонус за первую покупку!* +1500 монет!",
        'buy_success': "✅ Куплено {count} персонаж(ей).\n",
        'buy_failed': "⚠️ Не удалось: {items}",
        'buy_not_found': "{id} (не найден)",
        'buy_already_owned': "{id} (уже в коллекции)",
        'sell_usage': "Использование: /sell <id>",
        'sell_not_found': "❌ Персонаж не найден.",
        'sell_not_owned': "❌ Вы не владеете этим персонажем.",
        'sell_success': "💰 Продан <b>{name}</b> за <b>{price} монет</b> (70% от базовой цены).",
        'search_usage': "Использование: /search <имя персонажа>",
        'search_no_results': "Совпадений не найдено.",
        'guess_groups_only': "🎭 Эта команда работает только в группах!",
        'guess_usage': "Использование: /guess <имя персонажа>",
        'guess_cooldown': "⏳ Подождите 10 секунд перед следующей попыткой.",
        'guess_no_drop': "❌ Сейчас нет активного дропа. Подождите следующего!",
        'guess_already_won': "🏆 Кто-то уже угадал этого персонажа!",
        'guess_error': "❌ Ошибка загрузки данных персонажа.",
        'guess_correct': "✨ <b>ПРАВИЛЬНО!</b> {mention} угадал <b>{name}</b>!{streak_text}\n\n💰 Награда: +{reward} монет\n{reward_text}",
        'guess_already_own': "💰 Уже в коллекции! Вы получаете *{coins}* монет! ({rarity} × 2)",
        'guess_added': "🎴 {name} добавлен в хранилище! +{coins} бонусных монет!",
        'guess_wrong': "❌ Неверно! Попробуйте ещё раз!",
        'guess_streak': "\n🔥 x{streak} Серия!",
        'guess_first_bonus': "🎉 <b>Бонус за первое угадывание!</b> +1000 монет!",
        'streak_msg': "🔥 <b>@{name} x{streak} серия!</b> 🔥",
        'drops_groups_only': "Эта команда работает только в группах!",
        'drops_enable_admin': "⛔ Только администраторы группы или владелец бота могут включить дропы.",
        'drops_enabled': "🎭 *Дропы включены!*\n\nПерсонажи появляются каждый час.\nИспользуйте /guess <имя> для угадывания!",
        'drops_disable_admin': "⛔ Только администраторы группы или владелец бота могут отключить дропы.",
        'drops_disabled': "🚫 *Дропы отключены!*\n\nАвтоматические дропы в этой группе остановлены.",
        'drop_guess_caption': "🎭 Угадайте персонажа!",
        'drop_hint_caption': "🎭 Угадайте персонажа!\n\n💡 <b>Подсказка:</b> Из аниме <i>{anime}</i>",
        'collector_bonus': "🎉 <b>Бонус коллекционера!</b> У вас 10 персонажей в этой группе! +2500 монет!",
        'tasks_dm_only': "📋 Пожалуйста, используйте /tasks в личных сообщениях!",
        'tasks_header': "📋 <b>Ваши задания</b>\n━━━━━━━━━━━━━━━━\n\n",
        'tasks_referral': (
            "📨 <b>Реферальное задание</b>\n   ✅ Приглашайте друзей и зарабатывайте!\n"
            "   📊 Приглашено: {ref_count} пользователей | Заработано: {ref_earned} монет\n"
            "   💰 Награда: 1000 монет за реферала\n\n"
        ),
        'tasks_channel_header': "📢 <b>Задания по подписке на канал</b>\n",
        'tasks_no_channel': "   Заданий по каналу нет\n",
        'tasks_group_add': "\n➕ <b>Добавить бота в группу</b>\n   ⏳ Добавьте меня в группу как администратора (+5000 монет)\n\n",
        'tasks_bonus_header': "🎁 <b>Бонусные задания</b>\n",
        'tasks_streak': "   {status} 7-дневная серия ({streak}/7) (+3000 монет)\n",
        'tasks_first_buy': "   {status} Первая покупка (+1500 монет)\n",
        'tasks_collector': "   {status} Коллекционер ({count}/10 персонажей) (+2500 монет)\n",
        'tasks_first_guess': "   {status} Первое угадывание (+1000 монет)\n",
        'tasks_done_btn': "✅ Готово: {label}",
        'tasks_complete': "🎉 <b>Задание выполнено!</b>\n\n✅ Подписались на {desc}\n💰 Награда: +{reward} монет!",
        'tasks_not_joined': "❌ Вы ещё не подписались на канал!",
        'tasks_verify_error': "❌ Ошибка проверки. Убедитесь, что бот является администратором канала!",
        'tasks_already_done': "✅ Вы уже выполнили это задание!",
        'refer_dm_only': "📨 Пожалуйста, используйте /refer в личных сообщениях!",
        'refer_text': (
            "📨 <b>Ваша реферальная ссылка</b>\n━━━━━━━━━━━━━━━━\n\n🔗 <code>{link}</code>\n\n"
            "📊 <b>Статистика:</b>\n   👥 Приглашено: {ref_count} пользователей\n   💰 Заработано: {ref_earned} монет\n\n"
            "💡 Поделитесь ссылкой с друзьями!\n   • Вы получаете 1000 монет за реферала\n   • Друг получает 500 монет"
        ),
        'lb_groups_only': "🏆 Эта команда работает только в группах!",
        'lb_empty': "Коллекционеров пока нет! Начните с /claim или /buy!",
        'lb_header': "╔══════════════════════════╗\n   🏆 <b>ГЛОБАЛЬНЫЙ РЕЙТИНГ</b> 🏆\n╚══════════════════════════╝\n\n",
        'lb_footer': "\n━━━━━━━━━━━━━━━━\n📅 <i>{date}</i>\n🎁 <i>Топ-3 получают призы каждое воскресенье!</i>\n💡 <i>Используйте /claim и /buy для пополнения!</i>",
        'weekly_lb_header': "╔══════════════════════════╗\n   🏆 <b>ЕЖЕНЕДЕЛЬНЫЙ РЕЙТИНГ</b> 🏆\n╚══════════════════════════╝\n\n",
        'weekly_lb_prizes': "\n━━━━━━━━━━━━━━━━\n🎊 <b>Еженедельные призы распределены!</b>\n",
        'weekly_lb_footer': "\n📅 <i>{date}</i> | 💡 <i>Собирайте больше для продвижения!</i>",
        'weekly_dm': (
            "🎉 <b>Приз еженедельного рейтинга!</b>\n\nВы заняли <b>#{rank}</b> место в глобальном рейтинге!\n"
            "💰 <b>+{reward} монет</b> добавлены в ваш кошелёк!\n\nПродолжайте собирать! 🏆"
        ),
        'welcome_member': (
            "👋 Добро пожаловать в <b>{group}</b>, {mention}!\n━━━━━━━━━━━━━━━━\n"
            "🎮 Используйте /start для начала\n💰 Ежедневные монеты: /daily\n"
            "🎴 Первый персонаж: /claim\n🛒 Магазин: /market"
        ),
        'admins_groups_only': "Эта команда работает только в группах.",
        'admins_none': "Администраторы-люди не найдены.",
        'admins_header': "👥 <b>Администраторы</b>\n",
        'calladmins_groups_only': "Только в группах.",
        'calladmins_cooldown': "⏳ Ограничение: раз в 10 минут для группы.",
        'calladmins_none': "Нет администраторов для вызова.",
        'calladmins_text': "Эй, администраторы, скорее сюда 🙃\n",
        'error': "⚠️ Произошла ошибка. Пожалуйста, попробуйте снова.",
        'lang_choose': "🌐 Choose your language / Выберите язык:",
        'lang_set_en': "✅ Language set to English!",
        'lang_set_ru': "✅ Язык установлен: Русский!",
        'bot_added_thanks': "🎉 <b>Спасибо, что добавили меня в {group}!</b>\n\n💰 Вы заработали <b>5000 монет!</b>\nИспользуйте /tasks для других способов заработка!",
        'ref_notify': "🎉 <b>Новый реферал!</b>\n@{name} присоединился по вашей ссылке!\n💰 Вы заработали <b>1000 монет!</b>",
        'salty': [
            "Никто не угадал... какая беспомощная группа 🙄",
            "50 минут — и ничего? Позор 💀",
            "Персонаж был {name}... вы правда не знали? 😂",
            "Ноль правильных ответов. Ноль. 💀",
            "Даже моя бабушка угадала бы. Невероятно.",
            "Упустили мяч, не так ли? 🏀❌",
            "Загадка остаётся... потому что никто не старался 🤷",
            "Вам нужно смотреть больше аниме. Это было легко."
        ],
    }
}

def t(lang: str, key: str, **kwargs) -> str:
    """Return translated string for given language and key."""
    s = STRINGS.get(lang, STRINGS['en']).get(key)
    if s is None:
        s = STRINGS['en'].get(key, key)
    if kwargs and isinstance(s, str):
        try:
            s = s.format(**kwargs)
        except (KeyError, IndexError):
            pass
    return s

# ---------- Database Layer ----------
class Database:
    def __init__(self):
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(DATABASE_URL)

    async def init_tables(self):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS groups (
                    group_id BIGINT PRIMARY KEY,
                    welcome_img_id TEXT,
                    last_calladmins TIMESTAMP,
                    title TEXT
                )
            ''')
            # Migration: add title column if table already existed without it
            await conn.execute('''
                ALTER TABLE groups ADD COLUMN IF NOT EXISTS title TEXT
            ''')
            # Migration: add streak columns if group_user_data existed without them
            await conn.execute('''
                ALTER TABLE group_user_data ADD COLUMN IF NOT EXISTS daily_streak INT DEFAULT 0
            ''')
            await conn.execute('''
                ALTER TABLE group_user_data ADD COLUMN IF NOT EXISTS last_daily_date DATE
            ''')
            # Migration: add language column to user_info
            await conn.execute('''
                ALTER TABLE user_info ADD COLUMN IF NOT EXISTS language TEXT DEFAULT 'en'
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS users (
                    user_id BIGINT, group_id BIGINT, PRIMARY KEY (user_id, group_id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS global_users (
                    user_id BIGINT PRIMARY KEY, coins INT DEFAULT 0
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS group_user_data (
                    user_id BIGINT, group_id BIGINT,
                    last_daily TIMESTAMP, last_claim TIMESTAMP,
                    daily_streak INT DEFAULT 0, last_daily_date DATE,
                    PRIMARY KEY (user_id, group_id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS characters (
                    char_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL, anime TEXT NOT NULL, img_url TEXT NOT NULL,
                    rarity TEXT NOT NULL, rarity_tier INT NOT NULL,
                    price INT NOT NULL, is_available BOOLEAN DEFAULT TRUE
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS inventory (
                    user_id BIGINT, group_id BIGINT, char_id TEXT REFERENCES characters(char_id),
                    PRIMARY KEY (user_id, group_id, char_id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS started_users (
                    user_id BIGINT PRIMARY KEY, started_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bot_config (
                    key TEXT PRIMARY KEY, value TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS rarity_ranking (
                    rarity TEXT PRIMARY KEY, tier INT UNIQUE, emoji TEXT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS drops_active (
                    group_id BIGINT PRIMARY KEY, enabled BOOLEAN DEFAULT FALSE
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS current_drops (
                    group_id BIGINT PRIMARY KEY,
                    char_id TEXT, start_time TIMESTAMP, message_id BIGINT,
                    hint_shown BOOLEAN DEFAULT FALSE, winner_id BIGINT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS drop_winners (
                    group_id BIGINT, user_id BIGINT,
                    win_streak INT DEFAULT 0, last_win_time TIMESTAMP,
                    PRIMARY KEY (group_id, user_id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS tasks (
                    task_id SERIAL PRIMARY KEY,
                    type TEXT, target TEXT, reward INT,
                    description TEXT, created_by BIGINT
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS task_completions (
                    user_id BIGINT, task_id INT,
                    completed_at TIMESTAMP, next_reset TIMESTAMP,
                    PRIMARY KEY (user_id, task_id)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS referrals (
                    referrer_id BIGINT, referred_id BIGINT PRIMARY KEY, joined_at TIMESTAMP
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS group_adds (
                    user_id BIGINT, group_id BIGINT PRIMARY KEY,
                    added_at TIMESTAMP, rewarded BOOLEAN DEFAULT FALSE
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS bonus_tasks (
                    user_id BIGINT,
                    task_name TEXT,
                    completed BOOLEAN DEFAULT FALSE,
                    PRIMARY KEY (user_id, task_name)
                )
            ''')
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS guess_cooldown (
                    user_id BIGINT, group_id BIGINT,
                    last_guess TIMESTAMP,
                    PRIMARY KEY (user_id, group_id)
                )
            ''')
            # User info cache for stats & leaderboard display
            await conn.execute('''
                CREATE TABLE IF NOT EXISTS user_info (
                    user_id BIGINT PRIMARY KEY,
                    first_name TEXT,
                    username TEXT,
                    updated_at TIMESTAMP DEFAULT NOW()
                )
            ''')
            # Default rarities
            await conn.executemany('''
                INSERT INTO rarity_ranking (rarity, tier, emoji)
                VALUES ($1, $2, $3) ON CONFLICT (rarity) DO NOTHING
            ''', [
                ('Common', 1, '⚪'), ('Uncommon', 2, '🟢'), ('Elite', 3, '🔵'),
                ('Epic', 4, '🟣'), ('Mythic', 5, '🔴'), ('Waifu', 6, '💖'),
                ('Special Edition', 7, '✨'), ('Limited', 8, '⏳'),
                ('Event', 9, '🎉'), ('Legendary', 10, '🌟')
            ])

    # ---------- User Info ----------
    async def update_user_info(self, user_id: int, first_name: str, username: str = None):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO user_info (user_id, first_name, username, updated_at)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (user_id) DO UPDATE
                SET first_name = $2, username = $3, updated_at = NOW()
            ''', user_id, first_name, username)

    async def get_user_lang(self, user_id: int) -> str:
        async with self.pool.acquire() as conn:
            lang = await conn.fetchval('SELECT language FROM user_info WHERE user_id = $1', user_id)
            return lang if lang in ('en', 'ru') else 'en'

    async def set_user_lang(self, user_id: int, lang: str):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO user_info (user_id, language) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET language = $2
            ''', user_id, lang)

    # ---------- User tracking ----------
    async def user_has_started(self, user_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT 1 FROM started_users WHERE user_id = $1', user_id) is not None

    async def register_start(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('INSERT INTO started_users (user_id) VALUES ($1) ON CONFLICT DO NOTHING', user_id)

    # ---------- Groups ----------
    async def get_group_welcome_img(self, group_id: int) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT welcome_img_id FROM groups WHERE group_id = $1', group_id)

    async def set_group_welcome_img(self, group_id: int, file_id: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO groups (group_id, welcome_img_id) VALUES ($1, $2) '
                'ON CONFLICT (group_id) DO UPDATE SET welcome_img_id = $2',
                group_id, file_id
            )

    async def update_group_title(self, group_id: int, title: str):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO groups (group_id, title) VALUES ($1, $2)
                ON CONFLICT (group_id) DO UPDATE SET title = $2
            ''', group_id, title)

    async def get_last_calladmins(self, group_id: int) -> Optional[datetime]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT last_calladmins FROM groups WHERE group_id = $1', group_id)

    async def update_calladmins_time(self, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO groups (group_id, last_calladmins) VALUES ($1, NOW()) '
                'ON CONFLICT (group_id) DO UPDATE SET last_calladmins = NOW()',
                group_id
            )

    async def get_all_group_ids(self) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT group_id FROM groups')
            return [r['group_id'] for r in rows]

    async def get_all_groups_info(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT group_id, title FROM groups ORDER BY group_id')
            return [dict(r) for r in rows]

    async def get_group_members_info(self, group_id: int) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT DISTINCT gu.user_id, u.first_name, u.username
                FROM group_user_data gu
                LEFT JOIN user_info u ON gu.user_id = u.user_id
                WHERE gu.group_id = $1
                ORDER BY u.first_name NULLS LAST
            ''', group_id)
            return [dict(r) for r in rows]

    # ---------- Coins ----------
    async def get_user_coins(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            val = await conn.fetchval('SELECT coins FROM global_users WHERE user_id = $1', user_id)
            return val if val is not None else 0

    async def add_coins(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO global_users (user_id, coins) VALUES ($1, $2)
                ON CONFLICT (user_id) DO UPDATE SET coins = global_users.coins + $2
            ''', user_id, amount)

    async def remove_coins(self, user_id: int, amount: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO global_users (user_id, coins) VALUES ($1, 0)
                ON CONFLICT (user_id) DO UPDATE SET coins = GREATEST(0, global_users.coins - $2)
            ''', user_id, amount)

    # ---------- Daily & Claim ----------
    async def can_claim_daily(self, user_id: int, group_id: int) -> bool:
        async with self.pool.acquire() as conn:
            last = await conn.fetchval(
                'SELECT last_daily FROM group_user_data WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )
            if not last:
                return True
            return (datetime.utcnow() - last).total_seconds() >= 7200

    async def get_daily_cooldown_remaining(self, user_id: int, group_id: int) -> float:
        """Returns seconds remaining until next daily claim. 0 if ready."""
        async with self.pool.acquire() as conn:
            last = await conn.fetchval(
                'SELECT last_daily FROM group_user_data WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )
            if not last:
                return 0
            elapsed = (datetime.utcnow() - last).total_seconds()
            return max(0, 7200 - elapsed)

    async def get_claim_cooldown_remaining(self, user_id: int, group_id: int) -> float:
        """Returns seconds remaining until next character claim. 0 if ready."""
        async with self.pool.acquire() as conn:
            last = await conn.fetchval(
                'SELECT last_claim FROM group_user_data WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )
            if not last:
                return 0
            elapsed = (datetime.utcnow() - last).total_seconds()
            return max(0, 39600 - elapsed)

    async def record_daily(self, user_id: int, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO group_user_data (user_id, group_id, last_daily)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id, group_id) DO UPDATE SET last_daily = NOW()
            ''', user_id, group_id)

    async def update_daily_streak(self, user_id: int, group_id: int) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT daily_streak, last_daily_date FROM group_user_data WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )
            today = datetime.utcnow().date()
            if row and row['last_daily_date']:
                last_date = row['last_daily_date']
                streak = row['daily_streak'] or 0
                if (today - last_date).days == 1:
                    streak += 1
                elif (today - last_date).days > 1:
                    streak = 1
            else:
                streak = 1
            await conn.execute('''
                INSERT INTO group_user_data (user_id, group_id, daily_streak, last_daily_date)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, group_id) DO UPDATE
                SET daily_streak = $3, last_daily_date = $4
            ''', user_id, group_id, streak, today)
            return streak

    async def get_daily_streak(self, user_id: int, group_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT daily_streak FROM group_user_data WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            ) or 0

    async def get_daily_streak_global(self, user_id: int) -> int:
        """Returns the highest daily streak this user has across all groups."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT COALESCE(MAX(daily_streak), 0) FROM group_user_data WHERE user_id = $1',
                user_id
            ) or 0

    async def get_user_char_count_global(self, user_id: int) -> int:
        """Returns total distinct characters this user owns across all groups."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT COUNT(DISTINCT char_id) FROM inventory WHERE user_id = $1',
                user_id
            ) or 0

    async def can_claim_character(self, user_id: int, group_id: int) -> bool:
        async with self.pool.acquire() as conn:
            last = await conn.fetchval(
                'SELECT last_claim FROM group_user_data WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )
            if not last:
                return True
            return (datetime.utcnow() - last).total_seconds() >= 39600

    async def record_claim(self, user_id: int, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO group_user_data (user_id, group_id, last_claim)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id, group_id) DO UPDATE SET last_claim = NOW()
            ''', user_id, group_id)

    async def get_user_char_count(self, user_id: int, group_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT COUNT(*) FROM inventory WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            ) or 0

    # ---------- Characters ----------
    async def add_character(self, char_id: str, name: str, anime: str, img_url: str, rarity: str, price: int):
        async with self.pool.acquire() as conn:
            tier = await conn.fetchval('SELECT tier FROM rarity_ranking WHERE rarity = $1', rarity)
            if tier is None:
                tier = 1
            await conn.execute('''
                INSERT INTO characters (char_id, name, anime, img_url, rarity, rarity_tier, price)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
            ''', char_id, name, anime, img_url, rarity, tier, price)

    async def remove_character(self, char_id: str):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE characters SET is_available = FALSE WHERE char_id = $1', char_id)

    async def char_id_exists(self, char_id: str) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT 1 FROM characters WHERE char_id = $1', char_id) is not None

    async def get_character_by_id(self, char_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM characters WHERE char_id = $1 AND is_available = true', char_id)
            return dict(row) if row else None

    async def get_character_by_id_any(self, char_id: str) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM characters WHERE char_id = $1', char_id)
            return dict(row) if row else None

    async def search_characters(self, query: str) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT char_id, name, anime, img_url, rarity, price, rarity_tier
                FROM characters WHERE is_available = true AND (name ILIKE $1 OR anime ILIKE $1)
                ORDER BY rarity_tier DESC LIMIT 20
            ''', f'%{query}%')
            return [dict(r) for r in rows]

    async def get_random_character(self) -> Optional[dict]:
        """Weighted-random character using SQL — no full table load."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM characters
                WHERE is_available = true
                ORDER BY -LOG(RANDOM()) / (
                    CASE rarity
                        WHEN 'Common'          THEN 40.0
                        WHEN 'Uncommon'        THEN 25.0
                        WHEN 'Elite'           THEN 15.0
                        WHEN 'Epic'            THEN 8.0
                        WHEN 'Waifu'           THEN 4.0
                        WHEN 'Special Edition' THEN 3.0
                        WHEN 'Legendary'       THEN 2.0
                        WHEN 'Limited'         THEN 1.5
                        WHEN 'Event'           THEN 1.0
                        WHEN 'Mythic'          THEN 0.5
                        ELSE 1.0
                    END
                )
                LIMIT 1
            ''')
            return dict(row) if row else None

    async def get_random_unowned_character(self, user_id: int, group_id: int) -> Optional[dict]:
        """Weighted-random character the user doesn't own — no full table load."""
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('''
                SELECT * FROM characters
                WHERE is_available = true
                AND char_id NOT IN (
                    SELECT char_id FROM inventory
                    WHERE user_id = $1 AND group_id = $2
                )
                ORDER BY -LOG(RANDOM()) / (
                    CASE rarity
                        WHEN 'Common'          THEN 40.0
                        WHEN 'Uncommon'        THEN 25.0
                        WHEN 'Elite'           THEN 15.0
                        WHEN 'Epic'            THEN 8.0
                        WHEN 'Waifu'           THEN 4.0
                        WHEN 'Special Edition' THEN 3.0
                        WHEN 'Legendary'       THEN 2.0
                        WHEN 'Limited'         THEN 1.5
                        WHEN 'Event'           THEN 1.0
                        WHEN 'Mythic'          THEN 0.5
                        ELSE 1.0
                    END
                )
                LIMIT 1
            ''', user_id, group_id)
            return dict(row) if row else None

    # ---------- Inventory ----------
    async def add_to_inventory(self, user_id: int, group_id: int, char_id: str) -> bool:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    'INSERT INTO inventory (user_id, group_id, char_id) VALUES ($1, $2, $3)',
                    user_id, group_id, char_id
                )
                return True
            except asyncpg.UniqueViolationError:
                return False

    async def remove_from_inventory(self, user_id: int, group_id: int, char_id: str) -> bool:
        async with self.pool.acquire() as conn:
            result = await conn.execute(
                'DELETE FROM inventory WHERE user_id = $1 AND group_id = $2 AND char_id = $3',
                user_id, group_id, char_id
            )
            return result != "DELETE 0"

    async def user_owns_character(self, user_id: int, group_id: int, char_id: str) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT 1 FROM inventory WHERE user_id = $1 AND group_id = $2 AND char_id = $3',
                user_id, group_id, char_id
            ) is not None

    async def get_user_inventory(self, user_id: int, group_id: int, limit: int = 1, offset: int = 0) -> Tuple[List[dict], int]:
        async with self.pool.acquire() as conn:
            total = await conn.fetchval('SELECT COUNT(*) FROM inventory WHERE user_id = $1 AND group_id = $2', user_id, group_id)
            rows = await conn.fetch('''
                SELECT c.char_id, c.name, c.anime, c.img_url, c.rarity, c.price, c.rarity_tier
                FROM inventory i JOIN characters c ON i.char_id = c.char_id
                WHERE i.user_id = $1 AND i.group_id = $2
                ORDER BY c.rarity_tier DESC, c.name
                LIMIT $3 OFFSET $4
            ''', user_id, group_id, limit, offset)
            return [dict(r) for r in rows], total

    async def get_market_characters(self, limit: int = 5, offset: int = 0) -> Tuple[List[dict], int]:
        async with self.pool.acquire() as conn:
            total = await conn.fetchval('SELECT COUNT(*) FROM characters WHERE is_available = true')
            rows = await conn.fetch('''
                SELECT char_id, name, anime, img_url, rarity, price, rarity_tier
                FROM characters WHERE is_available = true
                ORDER BY rarity_tier DESC, name
                LIMIT $1 OFFSET $2
            ''', limit, offset)
            return [dict(r) for r in rows], total

    async def get_start_video(self) -> Optional[str]:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT value FROM bot_config WHERE key = $1', 'start_video')

    async def set_start_video(self, file_id: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO bot_config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2',
                'start_video', file_id
            )

    async def get_start_msg(self) -> Optional[str]:
        """Returns the custom start message caption if set, else None."""
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT value FROM bot_config WHERE key = $1', 'start_msg')

    async def set_start_msg(self, msg: str):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO bot_config (key, value) VALUES ($1, $2) ON CONFLICT (key) DO UPDATE SET value = $2',
                'start_msg', msg
            )

    async def get_rarity_emoji(self, rarity: str) -> str:
        async with self.pool.acquire() as conn:
            emoji = await conn.fetchval('SELECT emoji FROM rarity_ranking WHERE rarity = $1', rarity)
            return emoji or '⭐'

    # ---------- Drop System ----------
    async def is_drops_enabled(self, group_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT enabled FROM drops_active WHERE group_id = $1', group_id) or False

    async def enable_drops(self, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO drops_active (group_id, enabled) VALUES ($1, TRUE) ON CONFLICT (group_id) DO UPDATE SET enabled = TRUE',
                group_id
            )

    async def disable_drops(self, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'INSERT INTO drops_active (group_id, enabled) VALUES ($1, FALSE) ON CONFLICT (group_id) DO UPDATE SET enabled = FALSE',
                group_id
            )

    async def create_drop(self, group_id: int, char_id: str, message_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO current_drops (group_id, char_id, start_time, message_id, hint_shown, winner_id)
                VALUES ($1, $2, NOW(), $3, FALSE, NULL)
                ON CONFLICT (group_id) DO UPDATE SET
                    char_id = $2, start_time = NOW(), message_id = $3, hint_shown = FALSE, winner_id = NULL
            ''', group_id, char_id, message_id)

    async def get_current_drop(self, group_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM current_drops WHERE group_id = $1', group_id)
            return dict(row) if row else None

    async def show_hint(self, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE current_drops SET hint_shown = TRUE WHERE group_id = $1', group_id)

    async def end_drop(self, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('DELETE FROM current_drops WHERE group_id = $1', group_id)

    async def set_drop_winner(self, group_id: int, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE current_drops SET winner_id = $2 WHERE group_id = $1', group_id, user_id)

    async def get_win_streak(self, group_id: int, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT win_streak FROM drop_winners WHERE group_id = $1 AND user_id = $2',
                group_id, user_id
            ) or 0

    async def update_win_streak(self, group_id: int, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT win_streak, last_win_time FROM drop_winners WHERE group_id = $1 AND user_id = $2',
                group_id, user_id
            )
            if row and row['last_win_time'] and (datetime.utcnow() - row['last_win_time']).total_seconds() < 7200:
                new_streak = (row['win_streak'] or 0) + 1
            else:
                new_streak = 1
            await conn.execute('''
                INSERT INTO drop_winners (group_id, user_id, win_streak, last_win_time)
                VALUES ($1, $2, $3, NOW())
                ON CONFLICT (group_id, user_id) DO UPDATE
                SET win_streak = $3, last_win_time = NOW()
            ''', group_id, user_id, new_streak)
            return new_streak

    async def reset_win_streak(self, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('UPDATE drop_winners SET win_streak = 0 WHERE group_id = $1', group_id)

    async def get_groups_with_drops(self) -> List[int]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT group_id FROM drops_active WHERE enabled = TRUE')
            return [r['group_id'] for r in rows]

    # ---------- Guess Cooldown ----------
    async def can_guess(self, user_id: int, group_id: int, cooldown_sec: int = 10) -> bool:
        async with self.pool.acquire() as conn:
            last = await conn.fetchval(
                'SELECT last_guess FROM guess_cooldown WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )
            if not last:
                return True
            return (datetime.utcnow() - last).total_seconds() >= cooldown_sec

    async def record_guess(self, user_id: int, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO guess_cooldown (user_id, group_id, last_guess)
                VALUES ($1, $2, NOW())
                ON CONFLICT (user_id, group_id) DO UPDATE SET last_guess = NOW()
            ''', user_id, group_id)

    # ---------- Tasks System ----------
    async def add_task(self, task_type: str, target: str, reward: int, description: str, created_by: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('''
                INSERT INTO tasks (type, target, reward, description, created_by)
                VALUES ($1, $2, $3, $4, $5) RETURNING task_id
            ''', task_type, target, reward, description, created_by)

    async def remove_task(self, task_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('DELETE FROM tasks WHERE task_id = $1', task_id)

    async def get_tasks(self, task_type: str = None) -> List[dict]:
        async with self.pool.acquire() as conn:
            if task_type:
                rows = await conn.fetch('SELECT * FROM tasks WHERE type = $1', task_type)
            else:
                rows = await conn.fetch('SELECT * FROM tasks')
            return [dict(r) for r in rows]

    async def get_task(self, task_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow('SELECT * FROM tasks WHERE task_id = $1', task_id)
            return dict(row) if row else None

    async def is_task_completed(self, user_id: int, task_id: int) -> bool:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow(
                'SELECT next_reset FROM task_completions WHERE user_id = $1 AND task_id = $2',
                user_id, task_id
            )
            if not row:
                return False
            next_reset = row['next_reset']
            if next_reset and datetime.utcnow() > next_reset:
                await conn.execute('DELETE FROM task_completions WHERE user_id = $1 AND task_id = $2', user_id, task_id)
                return False
            return True

    async def complete_task(self, user_id: int, task_id: int, weekly: bool = False):
        async with self.pool.acquire() as conn:
            next_reset = datetime.utcnow() + timedelta(days=7) if weekly else None
            await conn.execute('''
                INSERT INTO task_completions (user_id, task_id, completed_at, next_reset)
                VALUES ($1, $2, NOW(), $3)
                ON CONFLICT (user_id, task_id) DO UPDATE SET completed_at = NOW(), next_reset = $3
            ''', user_id, task_id, next_reset)

    # ---------- Referrals ----------
    async def add_referral(self, referrer_id: int, referred_id: int) -> bool:
        async with self.pool.acquire() as conn:
            if referrer_id == referred_id:
                return False
            existing = await conn.fetchval('SELECT 1 FROM referrals WHERE referred_id = $1', referred_id)
            if existing:
                return False
            await conn.execute(
                'INSERT INTO referrals (referrer_id, referred_id, joined_at) VALUES ($1, $2, NOW())',
                referrer_id, referred_id
            )
            return True

    async def get_referral_count(self, user_id: int) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM referrals WHERE referrer_id = $1', user_id) or 0

    async def get_referral_stats(self, user_id: int) -> Tuple[int, int]:
        cnt = await self.get_referral_count(user_id)
        return cnt, cnt * 1000

    # ---------- Group Adds ----------
    async def record_group_add(self, user_id: int, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO group_adds (user_id, group_id, added_at, rewarded)
                VALUES ($1, $2, NOW(), FALSE) ON CONFLICT (group_id) DO NOTHING
            ''', user_id, group_id)

    async def is_group_add_rewarded(self, group_id: int) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT rewarded FROM group_adds WHERE group_id = $1', group_id) or False

    async def reward_group_add(self, user_id: int, group_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                'UPDATE group_adds SET rewarded = TRUE WHERE user_id = $1 AND group_id = $2',
                user_id, group_id
            )

    # ---------- Bonus Tasks ----------
    async def is_bonus_completed(self, user_id: int, task_name: str) -> bool:
        async with self.pool.acquire() as conn:
            return await conn.fetchval(
                'SELECT completed FROM bonus_tasks WHERE user_id = $1 AND task_name = $2',
                user_id, task_name
            ) or False

    async def complete_bonus(self, user_id: int, task_name: str):
        async with self.pool.acquire() as conn:
            await conn.execute('''
                INSERT INTO bonus_tasks (user_id, task_name, completed)
                VALUES ($1, $2, TRUE) ON CONFLICT (user_id, task_name) DO UPDATE SET completed = TRUE
            ''', user_id, task_name)

    # ---------- Leaderboard ----------
    async def get_leaderboard_data(self, limit: int = 10) -> List[dict]:
        """Top users by total distinct characters owned across all groups."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT i.user_id,
                       COUNT(DISTINCT i.char_id) AS total,
                       u.first_name,
                       u.username
                FROM inventory i
                LEFT JOIN user_info u ON i.user_id = u.user_id
                GROUP BY i.user_id, u.first_name, u.username
                ORDER BY total DESC
                LIMIT $1
            ''', limit)
            return [dict(r) for r in rows]

    # ---------- Stats ----------
    async def get_total_users(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM started_users') or 0

    async def get_active_today(self) -> int:
        async with self.pool.acquire() as conn:
            today = datetime.utcnow().date()
            return await conn.fetchval(
                'SELECT COUNT(DISTINCT user_id) FROM group_user_data WHERE last_daily::date = $1',
                today
            ) or 0

    async def get_all_users_info(self) -> List[dict]:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('''
                SELECT s.user_id, u.first_name, u.username
                FROM started_users s
                LEFT JOIN user_info u ON s.user_id = u.user_id
                ORDER BY s.started_at DESC
            ''')
            return [dict(r) for r in rows]

    async def get_all_started_user_ids(self) -> List[int]:
        """Returns all user IDs that have started the bot — used for broadcast."""
        async with self.pool.acquire() as conn:
            rows = await conn.fetch('SELECT user_id FROM started_users')
            return [r['user_id'] for r in rows]

    async def get_total_characters(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM characters WHERE is_available = true') or 0

    async def get_total_referrals(self) -> int:
        async with self.pool.acquire() as conn:
            return await conn.fetchval('SELECT COUNT(*) FROM referrals') or 0

db = Database()

# ---------- Helper Functions ----------
def is_owner(user_id: int) -> bool:
    return user_id == OWNER_ID

async def ensure_started(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    user = update.effective_user
    if not user:
        return False
    if not await db.user_has_started(user.id):
        lang = await db.get_user_lang(user.id)
        await update.message.reply_text(t(lang, 'start_first'))
        return False
    await db.update_user_info(user.id, user.first_name, user.username)
    return True

def get_effective_group_id(update: Update) -> int:
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        return chat.id
    return 0

async def format_character_card(char: dict, emoji: str) -> str:
    """Returns an HTML-formatted character card."""
    name = html_lib.escape(char['name'])
    anime = html_lib.escape(char['anime'])
    rarity = html_lib.escape(char['rarity'])
    return (
        f"{emoji} <b>{name}</b>\n"
        f"🎬 <b>Anime:</b> {anime}\n"
        f"💎 <b>Rarity:</b> {emoji} {rarity}\n"
        f"🆔 <b>ID:</b> <code>{char['char_id']}</code>\n"
        f"💰 <b>Price:</b> {char['price']} coins"
    )

async def check_collector_bonus(user_id: int, group_id: int, update: Update):
    """If user reaches 10 unique chars in this group, give 2500 coins (once)."""
    if await db.is_bonus_completed(user_id, 'collector'):
        return
    count = await db.get_user_char_count(user_id, group_id)
    if count >= 10:
        lang = await db.get_user_lang(user_id)
        await db.complete_bonus(user_id, 'collector')
        await db.add_coins(user_id, 2500)
        await update.message.reply_text(t(lang, 'collector_bonus'), parse_mode="HTML")

# ---------- Drop System Jobs ----------
async def perform_drop(bot, group_id: int):
    if not await db.is_drops_enabled(group_id):
        return
    if await db.get_current_drop(group_id):
        return
    char = await db.get_random_character()
    if not char:
        return
    try:
        msg = await bot.send_photo(
            chat_id=group_id,
            photo=char['img_url'],
            caption=t('en', 'drop_guess_caption')
        )
        try:
            await bot.pin_chat_message(group_id, msg.message_id)
        except Exception:
            pass
        await db.create_drop(group_id, char['char_id'], msg.message_id)
        scheduler.add_job(
            show_drop_hint, 'date',
            run_date=datetime.utcnow() + timedelta(minutes=30),
            args=[bot, group_id],
            id=f"hint_{group_id}",
            replace_existing=True
        )
        scheduler.add_job(
            expire_drop, 'date',
            run_date=datetime.utcnow() + timedelta(minutes=50),
            args=[bot, group_id],
            id=f"expire_{group_id}",
            replace_existing=True
        )
    except (Forbidden, ChatMigrated) as e:
        # Bot was kicked or chat migrated — auto-disable drops to stop retrying
        print(f"Drop auto-disabled in {group_id} (bot removed): {e}")
        await db.disable_drops(group_id)
    except Exception as e:
        # Transient error (network, rate limit, etc.) — log but DO NOT disable drops
        print(f"Drop error in {group_id}: {e}")

async def show_drop_hint(bot, group_id: int):
    drop = await db.get_current_drop(group_id)
    if not drop or drop['winner_id'] or drop['hint_shown']:
        return
    char = await db.get_character_by_id_any(drop['char_id'])
    if not char:
        return
    try:
        anime = html_lib.escape(char['anime'])
        await bot.edit_message_caption(
            chat_id=group_id,
            message_id=drop['message_id'],
            caption=t('en', 'drop_hint_caption', anime=anime),
            parse_mode="HTML"
        )
        await db.show_hint(group_id)
    except Exception:
        pass

async def expire_drop(bot, group_id: int):
    drop = await db.get_current_drop(group_id)
    if not drop or drop['winner_id']:
        return
    char = await db.get_character_by_id_any(drop['char_id'])
    if not char:
        await db.end_drop(group_id)
        return
    try:
        await bot.unpin_chat_message(group_id, drop['message_id'])
    except Exception:
        pass
    msg = random.choice(t('en', 'salty')).replace("{name}", char['name'])
    await bot.send_message(group_id, msg)
    await db.end_drop(group_id)

async def send_weekly_leaderboard(bot):
    """Every Sunday: send leaderboard to all groups, reward top 3, notify winners in DM."""
    top_users = await db.get_leaderboard_data(limit=10)
    if not top_users:
        return

    medals = ["🥇", "🥈", "🥉"]
    prizes = [3000, 2000, 1000]
    now = datetime.utcnow().strftime("%B %d, %Y")

    prize_lines = []
    for i, reward in enumerate(prizes):
        if i >= len(top_users):
            break
        user = top_users[i]
        user_lang = await db.get_user_lang(user['user_id'])
        await db.add_coins(user['user_id'], reward)
        name = html_lib.escape(user.get('first_name') or f"User {user['user_id']}")
        mention = f'<a href="tg://user?id={user["user_id"]}">{name}</a>'
        prize_lines.append((medals[i], mention, name, user['user_id'], reward))
        try:
            await bot.send_message(
                user['user_id'],
                t(user_lang, 'weekly_dm', rank=i + 1, reward=reward),
                parse_mode="HTML"
            )
        except Exception:
            pass

    lb_text = t('en', 'weekly_lb_header')
    for i, user in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i + 1}."
        name = html_lib.escape(user.get('first_name') or f"User {user['user_id']}")
        username_line = f" (@{html_lib.escape(user['username'])})" if user.get('username') else ""
        mention = f'<a href="tg://user?id={user["user_id"]}">{name}</a>{username_line}'
        lb_text += f"{medal} {mention} — <b>{user['total']}</b> chars\n"

    lb_text += t('en', 'weekly_lb_prizes')
    for medal, mention, name, uid, reward in prize_lines:
        lb_text += f"{medal} {mention} — <b>+{reward} coins</b>\n"
    lb_text += t('en', 'weekly_lb_footer', date=now)

    all_groups = await db.get_all_group_ids()
    for group_id in all_groups:
        try:
            msg = await bot.send_message(group_id, lb_text, parse_mode="HTML")
            try:
                await bot.pin_chat_message(group_id, msg.message_id)
            except Exception:
                pass
        except Exception:
            pass

async def start_drop_scheduler(bot):
    async def hourly_drops():
        groups = await db.get_groups_with_drops()
        for gid in groups:
            await perform_drop(bot, gid)

    scheduler.add_job(hourly_drops, IntervalTrigger(hours=1), id='hourly_drops', replace_existing=True)
    # Weekly leaderboard every Sunday at 12:00 UTC
    scheduler.add_job(
        send_weekly_leaderboard,
        CronTrigger(day_of_week='sun', hour=12, minute=0),
        args=[bot],
        id='weekly_leaderboard',
        replace_existing=True
    )
    scheduler.start()

# ---------- Bot Command Handlers ----------
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    chat = update.effective_chat
    if chat.type in ["group", "supergroup"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("▶ Start in DM", url=f"https://t.me/{context.bot.username}?start=true")]
        ])
        await update.message.reply_text(
            f"👋 Hey {user.first_name}!\nPlease start me in DM to register and use all features! 👇",
            reply_markup=keyboard
        )
        return
    await db.update_user_info(user.id, user.first_name, user.username)
    lang = await db.get_user_lang(user.id)
    if context.args and context.args[0].startswith('ref_'):
        try:
            referrer_id = int(context.args[0].split('_')[1])
            if referrer_id != user.id:
                success = await db.add_referral(referrer_id, user.id)
                if success:
                    await db.add_coins(referrer_id, 1000)
                    await db.add_coins(user.id, 500)
                    try:
                        ref_name = html_lib.escape(user.username or user.first_name)
                        ref_lang = await db.get_user_lang(referrer_id)
                        await context.bot.send_message(
                            referrer_id,
                            t(ref_lang, 'ref_notify', name=ref_name),
                            parse_mode="HTML"
                        )
                    except Exception:
                        pass
        except Exception:
            pass
    await db.register_start(user.id)
    video_id = await db.get_start_video()
    custom_msg = await db.get_start_msg()
    name_display = html_lib.escape(user.first_name or "Collector")
    uname_display = f" · @{html_lib.escape(user.username)}" if user.username else ""

    # Default aesthetic start message — overridden by /setstartmsg
    default_caption = (
        f"🎐 <b>ꜱᴏᴜʟ ᴄᴏʟʟᴇᴄᴛᴏʀ</b>\n\n"
        f"✦ Welcome, <b>{name_display}</b>{uname_display}\n\n"
        f"<i>Anime souls drift through the void…\n"
        f"Only the worthy may claim them.</i>\n\n"
        f"╭───────────────────╮\n"
        f"🎴  /claim  · Summon a soul\n"
        f"💰  /daily  · Daily offering\n"
        f"🛒  /market · Soul bazaar\n"
        f"╰───────────────────╯"
    )
    welcome_text = custom_msg if custom_msg else default_caption

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Add To Group", url=f"https://t.me/{context.bot.username}?startgroup=true")],
        [InlineKeyboardButton("Owner 🤪", url=OWNER_LINK), InlineKeyboardButton("Support chat 💝", url=SUPPORT_LINK)],
        [InlineKeyboardButton("Lang 🗽", callback_data="lang:choose")]
    ])
    if video_id:
        await update.message.reply_video(video_id, caption=welcome_text, reply_markup=keyboard, parse_mode="HTML")
    else:
        await update.message.reply_text(welcome_text, reply_markup=keyboard, parse_mode="HTML")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = """🎮 *Available Commands*

*💰 Economy*
/daily - Claim coins (every 2h, per group)
/claim - Claim random character (every 11h, per group)
/wallet - Show your coins

*📦 Collection*
/vault - Your collected characters (per group)
/market - View buyable characters
/buy <id> [id2 ...] - Buy character(s)
/sell <id> - Sell character (70% refund)
/search <n> - Search characters

*🎭 Drop System (Groups)*
/guess <n> - Guess the dropped character
/enabledrops - Enable drops (admin/owner)
/disabledrops - Disable drops (admin/owner)

*🏆 Leaderboard (Groups)*
/leaderboard - View top global collectors
_(Auto-posts & pins every Sunday with prizes!)_

*📋 Tasks (DM Only)*
/tasks - View and complete tasks
/refer - Get your referral link

*👥 Group Admin*
/listadmins - List human admins
/calladmins - Mention all admins (10min cooldown)

*👑 Owner/Dev*
/addcharacter - Add new character (interactive)
/remove <id> - Remove character
/listchar - List all characters (IDs)
/addcoins (reply) - Add coins
/removecoins (reply) - Remove coins
/setstartvid (reply to video)
/setwelcomepic (reply to photo, in group)
/setstartmsg - Update start message caption
/broadcast - Broadcast to all users & groups
/resetgrpdata - Reset group data (danger)
/stats - Bot statistics
/groupmembers <id> - Members of a group

*Other*
/start - Start the bot
/help - This menu"""
    await update.message.reply_text(text, parse_mode="Markdown")

async def daily(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = get_effective_group_id(update)
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    if await db.can_claim_daily(user.id, group_id):
        reward = random.randint(50, 200)
        await db.add_coins(user.id, reward)
        await db.record_daily(user.id, group_id)
        streak = await db.update_daily_streak(user.id, group_id)
        coins = await db.get_user_coins(user.id)
        streak_text = t(lang, 'daily_streak', streak=streak) if streak > 1 else ""
        if streak >= 7 and streak % 7 == 0:
            await db.add_coins(user.id, 3000)
            streak_text += t(lang, 'daily_streak_bonus')
        await update.message.reply_text(
            t(lang, 'daily_claimed', reward=reward, coins=coins, streak_text=streak_text),
            parse_mode="Markdown"
        )
    else:
        remaining = await db.get_daily_cooldown_remaining(user.id, group_id)
        await update.message.reply_text(
            t(lang, 'daily_wait', time=format_time_delta(remaining)),
            parse_mode="Markdown"
        )

async def claim(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = get_effective_group_id(update)
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    if not await db.can_claim_character(user.id, group_id):
        remaining = await db.get_claim_cooldown_remaining(user.id, group_id)
        await update.message.reply_text(
            t(lang, 'claim_wait', time=format_time_delta(remaining)),
            parse_mode="Markdown"
        )
        return
    char = await db.get_random_unowned_character(user.id, group_id)
    if char is None:
        any_char = await db.get_random_character()
        if not any_char:
            await update.message.reply_text(t(lang, 'claim_no_chars'))
            return
        await db.add_coins(user.id, 10000)
        await db.record_claim(user.id, group_id)
        coins = await db.get_user_coins(user.id)
        await update.message.reply_text(
            t(lang, 'claim_all_owned', coins=f"{coins:,}"),
            parse_mode="Markdown"
        )
        return
    await db.add_to_inventory(user.id, group_id, char['char_id'])
    await db.record_claim(user.id, group_id)
    # Rarity bonus coins
    bonus = get_rarity_bonus(char['rarity'])
    await db.add_coins(user.id, bonus)
    emoji = await db.get_rarity_emoji(char['rarity'])
    caption = t(lang, 'claim_caption',
        emoji=emoji, name=char['name'], anime=char['anime'],
        rarity=char['rarity'], char_id=char['char_id'], price=f"{char['price']:,}"
    )
    try:
        await update.message.reply_photo(photo=char['img_url'], caption=caption, parse_mode="MarkdownV2")
    except Exception:
        await update.message.reply_text(caption, parse_mode="MarkdownV2")
    await update.message.reply_text(
        t(lang, 'claim_rarity_bonus', rarity=char['rarity'], bonus=bonus),
        parse_mode="Markdown"
    )
    await check_collector_bonus(user.id, group_id, update)

async def wallet(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = get_effective_group_id(update)
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    coins = await db.get_user_coins(user.id)
    char_count = await db.get_user_char_count(user.id, group_id)
    await update.message.reply_text(
        t(lang, 'wallet_text', name=user.first_name, coins=f"{coins:,}", char_count=char_count),
        parse_mode="Markdown"
    )

async def send_vault_page(target, user_id: int, group_id: int, page: int, send_new: bool = True, lang: str = 'en'):
    items, total = await db.get_user_inventory(user_id, group_id, 1, page - 1)
    total_pages = max(1, total)
    if not items:
        text = t(lang, 'vault_empty')
        if send_new:
            await target.reply_text(text)
        else:
            await target.edit_text(text)
        return
    char = items[0]
    emoji = await db.get_rarity_emoji(char['rarity'])
    caption = t(lang, 'vault_caption',
        emoji=emoji, name=char['name'], anime=char['anime'],
        rarity=char['rarity'], char_id=char['char_id'],
        price=f"{char['price']:,}", page=page, total=total_pages
    )
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("◀", callback_data=f"vlt:{user_id}:{group_id}:{page - 1}"))
    row.append(InlineKeyboardButton(f"🗂 {page}/{total_pages}", callback_data="vlt:noop"))
    if page < total_pages:
        row.append(InlineKeyboardButton("▶", callback_data=f"vlt:{user_id}:{group_id}:{page + 1}"))
    keyboard = InlineKeyboardMarkup([row])
    if send_new:
        try:
            await target.reply_photo(char['img_url'], caption=caption, parse_mode="Markdown", reply_markup=keyboard)
        except Exception:
            await target.reply_text(caption, parse_mode="Markdown", reply_markup=keyboard)
    else:
        try:
            await target.edit_media(media=InputMediaPhoto(media=char['img_url'], caption=caption, parse_mode="Markdown"), reply_markup=keyboard)
        except Exception:
            try:
                await target.edit_caption(caption=caption, parse_mode="Markdown", reply_markup=keyboard)
            except Exception:
                await target.edit_text(caption, parse_mode="Markdown", reply_markup=keyboard)

async def vault(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = get_effective_group_id(update)
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    page = int(context.args[0]) if context.args and context.args[0].isdigit() else 1
    await send_vault_page(update.message, user.id, group_id, page, send_new=True, lang=lang)

async def vault_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    if query.data == "vlt:noop":
        await query.answer()
        return
    parts = query.data.split(":")
    user_id, group_id, page = int(parts[1]), int(parts[2]), int(parts[3])
    if update.effective_user.id != user_id:
        lang = await db.get_user_lang(update.effective_user.id)
        await query.answer(t(lang, 'vault_not_yours'), show_alert=True)
        return
    await query.answer()
    lang = await db.get_user_lang(user_id)
    await send_vault_page(query.message, user_id, group_id, page, send_new=False, lang=lang)

async def send_market_page(target, page: int, send_new: bool = True):
    PER_PAGE = 5
    offset = (page - 1) * PER_PAGE
    items, total = await db.get_market_characters(PER_PAGE, offset)
    total_pages = max(1, (total + PER_PAGE - 1) // PER_PAGE)
    page = max(1, min(page, total_pages))
    if not items:
        text = "🛒 The market is currently empty. Check back later!"
        if send_new:
            await target.reply_text(text)
        else:
            await target.edit_text(text)
        return
    text = f"🛒 *Character Market — Page {page}/{total_pages}*\n━━━━━━━━━━━━━━━━\n\n"
    for c in items:
        emoji = await db.get_rarity_emoji(c['rarity'])
        text += f"{emoji} *{c['name']}* — _{c['anime']}_\n   💰 `{c['price']}` coins  •  🆔 `{c['char_id']}`\n\n"
    text += "_Use /buy <id> to purchase a character_"
    row = []
    if page > 1:
        row.append(InlineKeyboardButton("◀ Prev", callback_data=f"mkt:{page - 1}"))
    row.append(InlineKeyboardButton(f"📄 {page}/{total_pages}", callback_data="mkt:noop"))
    if page < total_pages:
        row.append(InlineKeyboardButton("Next ▶", callback_data=f"mkt:{page + 1}"))
    keyboard = InlineKeyboardMarkup([row])
    if send_new:
        await target.reply_text(text, parse_mode="Markdown", reply_markup=keyboard)
    else:
        await target.edit_text(text, parse_mode="Markdown", reply_markup=keyboard)

async def market(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await db.get_user_lang(update.effective_user.id)
    keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("🌐 Open Web Store", url=WEB_STORE_URL)]])
    await update.message.reply_text(t(lang, 'market_text'), parse_mode="Markdown", reply_markup=keyboard)

async def market_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.data == "mkt:noop":
        return
    page = int(query.data.split(":")[1])
    await send_market_page(query.message, page, send_new=False)

async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = get_effective_group_id(update)
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    if not context.args:
        await update.message.reply_text(t(lang, 'buy_usage'))
        return
    char_ids = context.args
    bought = []
    failed = []
    total_cost = 0
    for cid in char_ids:
        char = await db.get_character_by_id(cid)
        if not char:
            failed.append(t(lang, 'buy_not_found', id=cid))
            continue
        if await db.user_owns_character(user.id, group_id, cid):
            failed.append(t(lang, 'buy_already_owned', id=cid))
            continue
        total_cost += char['price']
        bought.append(char)
    coins = await db.get_user_coins(user.id)
    if total_cost > coins:
        await update.message.reply_text(t(lang, 'buy_no_coins', total_cost=total_cost, coins=coins))
        return
    for char in bought:
        await db.remove_coins(user.id, char['price'])
        await db.add_to_inventory(user.id, group_id, char['char_id'])
    if not await db.is_bonus_completed(user.id, 'first_buy'):
        await db.complete_bonus(user.id, 'first_buy')
        await db.add_coins(user.id, 1500)
        await update.message.reply_text(t(lang, 'buy_first_bonus'), parse_mode="Markdown")
    msg = t(lang, 'buy_success', count=len(bought))
    if failed:
        msg += t(lang, 'buy_failed', items=', '.join(failed))
    await update.message.reply_text(msg)
    await check_collector_bonus(user.id, group_id, update)

async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    group_id = get_effective_group_id(update)
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    if not context.args:
        await update.message.reply_text(t(lang, 'sell_usage'))
        return
    char_id = context.args[0]
    char = await db.get_character_by_id(char_id)
    if not char:
        await update.message.reply_text(t(lang, 'sell_not_found'))
        return
    if not await db.user_owns_character(user.id, group_id, char_id):
        await update.message.reply_text(t(lang, 'sell_not_owned'))
        return
    sell_price = int(char['price'] * 0.7)
    await db.add_coins(user.id, sell_price)
    await db.remove_from_inventory(user.id, group_id, char_id)
    await update.message.reply_text(
        t(lang, 'sell_success', name=html_lib.escape(char['name']), price=sell_price),
        parse_mode="HTML"
    )

async def search(update: Update, context: ContextTypes.DEFAULT_TYPE):
    lang = await db.get_user_lang(update.effective_user.id)
    if not context.args:
        await update.message.reply_text(t(lang, 'search_usage'))
        return
    query = " ".join(context.args)
    results = await db.search_characters(query)
    if not results:
        await update.message.reply_text(t(lang, 'search_no_results'))
        return
    for char in results[:5]:
        emoji = await db.get_rarity_emoji(char['rarity'])
        caption = await format_character_card(char, emoji)
        if char.get('img_url'):
            await update.message.reply_photo(char['img_url'], caption=caption, parse_mode="HTML")
        else:
            await update.message.reply_text(caption, parse_mode="HTML")

async def guess(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(t(lang, 'guess_groups_only'))
        return
    if not context.args:
        await update.message.reply_text(t(lang, 'guess_usage'))
        return
    group_id = chat.id
    if not await db.can_guess(user.id, group_id, 10):
        await update.message.reply_text(t(lang, 'guess_cooldown'))
        return
    await db.record_guess(user.id, group_id)
    guess_name = " ".join(context.args).lower()
    drop = await db.get_current_drop(group_id)
    if not drop:
        await update.message.reply_text(t(lang, 'guess_no_drop'))
        return
    if drop['winner_id']:
        await update.message.reply_text(t(lang, 'guess_already_won'))
        return
    char = await db.get_character_by_id_any(drop['char_id'])
    if not char:
        await update.message.reply_text(t(lang, 'guess_error'))
        return
    char_name = char['name'].lower()
    char_first = char_name.split()[0]
    if guess_name == char_name or guess_name == char_first:
        await db.set_drop_winner(group_id, user.id)
        streak = await db.update_win_streak(group_id, user.id)
        already_owned = await db.user_owns_character(user.id, group_id, char['char_id'])
        rarity_bonus = get_rarity_bonus(char['rarity'])
        if already_owned:
            reward = rarity_bonus * 2
            reward_text = t(lang, 'guess_already_own', coins=reward, rarity=char['rarity'])
        else:
            reward = rarity_bonus
            await db.add_to_inventory(user.id, group_id, char['char_id'])
            reward_text = t(lang, 'guess_added', name=html_lib.escape(char['name']), coins=reward)
        await db.add_coins(user.id, reward)
        try:
            await context.bot.unpin_chat_message(group_id, drop['message_id'])
        except Exception:
            pass
        mention = f'<a href="tg://user?id={user.id}">{html_lib.escape(user.first_name)}</a>'
        streak_text = t(lang, 'guess_streak', streak=streak) if streak >= 3 else ""
        await update.message.reply_text(
            t(lang, 'guess_correct', mention=mention, name=html_lib.escape(char['name']),
              streak_text=streak_text, reward=reward, reward_text=reward_text),
            parse_mode="HTML"
        )
        if streak >= 3:
            try:
                streak_name = user.username or user.first_name
                streak_msg = await context.bot.send_message(
                    group_id,
                    t(lang, 'streak_msg', name=html_lib.escape(streak_name), streak=streak),
                    parse_mode="HTML"
                )
                await context.bot.pin_chat_message(group_id, streak_msg.message_id)
            except Exception:
                pass
        await db.end_drop(group_id)
        if not await db.is_bonus_completed(user.id, 'first_guess'):
            await db.complete_bonus(user.id, 'first_guess')
            await db.add_coins(user.id, 1000)
            await update.message.reply_text(t(lang, 'guess_first_bonus'), parse_mode="HTML")
        await check_collector_bonus(user.id, group_id, update)
    else:
        await update.message.reply_text(t(lang, 'guess_wrong'))

async def enabledrops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(t(lang, 'drops_groups_only'))
        return
    is_admin = is_owner(user.id)
    if not is_admin:
        try:
            member = await chat.get_member(user.id)
            is_admin = member.status in [CMS.ADMINISTRATOR, CMS.OWNER]
        except Exception:
            pass
    if not is_admin:
        await update.message.reply_text(t(lang, 'drops_enable_admin'))
        return
    await db.enable_drops(chat.id)
    await update.message.reply_text(t(lang, 'drops_enabled'), parse_mode="Markdown")

async def disabledrops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(t(lang, 'drops_groups_only'))
        return
    is_admin = is_owner(user.id)
    if not is_admin:
        try:
            member = await chat.get_member(user.id)
            is_admin = member.status in [CMS.ADMINISTRATOR, CMS.OWNER]
        except Exception:
            pass
    if not is_admin:
        await update.message.reply_text(t(lang, 'drops_disable_admin'))
        return
    await db.disable_drops(chat.id)
    await update.message.reply_text(t(lang, 'drops_disabled'), parse_mode="Markdown")

async def tasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    if chat.type != "private":
        lang = await db.get_user_lang(user.id)
        await update.message.reply_text(t(lang, 'tasks_dm_only'))
        return
    if not await ensure_started(update, context):
        return
    lang = await db.get_user_lang(user.id)
    ref_count, ref_earned = await db.get_referral_stats(user.id)
    streak = await db.get_daily_streak_global(user.id)
    char_count = await db.get_user_char_count_global(user.id)
    # Auto-complete collector bonus if eligible
    if not await db.is_bonus_completed(user.id, 'collector') and char_count >= 10:
        await db.complete_bonus(user.id, 'collector')
        await db.add_coins(user.id, 2500)
    text = t(lang, 'tasks_header')
    text += t(lang, 'tasks_referral', ref_count=ref_count, ref_earned=ref_earned)
    channel_tasks = await db.get_tasks("channel")
    text += t(lang, 'tasks_channel_header')
    if channel_tasks:
        for task in channel_tasks:
            completed = await db.is_task_completed(user.id, task['task_id'])
            status = "✅" if completed else "⏳"
            safe_desc = html_lib.escape(task['description'])
            text += f"   {status} {safe_desc} (+{task['reward']} coins)\n"
    else:
        text += t(lang, 'tasks_no_channel')
    text += t(lang, 'tasks_group_add')
    text += t(lang, 'tasks_bonus_header')
    streak_status = "✅" if streak >= 7 else "⏳"
    text += t(lang, 'tasks_streak', status=streak_status, streak=streak)
    first_buy = await db.is_bonus_completed(user.id, 'first_buy')
    text += t(lang, 'tasks_first_buy', status="✅" if first_buy else "⏳")
    collector_done = await db.is_bonus_completed(user.id, 'collector')
    text += t(lang, 'tasks_collector', status="✅" if collector_done else "⏳", count=char_count)
    first_guess = await db.is_bonus_completed(user.id, 'first_guess')
    text += t(lang, 'tasks_first_guess', status="✅" if first_guess else "⏳")
    buttons = []
    for task in channel_tasks:
        if not await db.is_task_completed(user.id, task['task_id']):
            label = task['description'][:30]
            if len(task['description']) > 30:
                label += "..."
            buttons.append([InlineKeyboardButton(t(lang, 'tasks_done_btn', label=label), callback_data=f"task:{task['task_id']}")])
    keyboard = InlineKeyboardMarkup(buttons) if buttons else None
    await update.message.reply_text(text, parse_mode="HTML", reply_markup=keyboard)

async def tasks_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    await query.answer()
    if not query.data.startswith("task:"):
        return
    task_id = int(query.data.split(":")[1])
    task = await db.get_task(task_id)
    if not task:
        await query.edit_message_text("❌ Task not found.")
        return
    if await db.is_task_completed(user.id, task_id):
        await query.answer(t(lang, 'tasks_already_done'), show_alert=True)
        return
    try:
        channel = task['target']
        if 't.me/' in channel:
            username = channel.split('t.me/')[-1].split('/')[0]
            if username.startswith('@'):
                username = username[1:]
            channel = f"@{username}"
        member = await context.bot.get_chat_member(channel, user.id)
        if member.status in [CMS.MEMBER, CMS.ADMINISTRATOR, CMS.OWNER]:
            await db.complete_task(user.id, task_id, weekly=True)
            await db.add_coins(user.id, task['reward'])
            safe_desc = html_lib.escape(task['description'])
            await query.edit_message_text(
                t(lang, 'tasks_complete', desc=safe_desc, reward=task['reward']),
                parse_mode="HTML"
            )
        else:
            await query.answer(t(lang, 'tasks_not_joined'), show_alert=True)
    except Exception:
        await query.answer(t(lang, 'tasks_verify_error'), show_alert=True)

async def refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    if chat.type != "private":
        await update.message.reply_text(t(lang, 'refer_dm_only'))
        return
    if not await ensure_started(update, context):
        return
    ref_link = f"https://t.me/{context.bot.username}?start=ref_{user.id}"
    ref_count, ref_earned = await db.get_referral_stats(user.id)
    await update.message.reply_text(
        t(lang, 'refer_text', link=html_lib.escape(ref_link), ref_count=ref_count, ref_earned=ref_earned),
        parse_mode="HTML"
    )

async def leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(t(lang, 'lb_groups_only'))
        return
    top_users = await db.get_leaderboard_data(limit=10)
    if not top_users:
        await update.message.reply_text(t(lang, 'lb_empty'))
        return
    medals = ["🥇", "🥈", "🥉"]
    now = datetime.utcnow().strftime("%B %d, %Y")
    text = t(lang, 'lb_header')
    for i, u in enumerate(top_users):
        medal = medals[i] if i < 3 else f"{i + 1}."
        name = html_lib.escape(u.get('first_name') or f"User {u['user_id']}")
        username_line = f" (@{html_lib.escape(u['username'])})" if u.get('username') else ""
        mention = f'<a href="tg://user?id={u["user_id"]}">{name}</a>{username_line}'
        text += f"{medal} {mention} — <b>{u['total']}</b> chars\n"
    text += t(lang, 'lb_footer', date=now)
    await update.message.reply_text(text, parse_mode="HTML")

# ---------- Owner/Dev Commands ----------
async def addcharacter_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner can add characters.")
        return ConversationHandler.END
    await update.message.reply_text("Send the character name (or /cancel to stop):")
    return NAME

async def addcharacter_name(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_name'] = update.message.text
    await update.message.reply_text("Send the anime name:")
    return ANIME

async def addcharacter_anime(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_anime'] = update.message.text
    await update.message.reply_text("Send the image URL (catbox.moe):")
    return IMG_URL

async def addcharacter_img(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data['char_img'] = update.message.text
    rarities = "Common, Uncommon, Elite, Epic, Mythic, Waifu, Special Edition, Limited, Event, Legendary"
    await update.message.reply_text(f"Send rarity (choose one):\n{rarities}")
    return RARITY

async def addcharacter_rarity(update: Update, context: ContextTypes.DEFAULT_TYPE):
    rarity = update.message.text
    valid = ['Common', 'Uncommon', 'Elite', 'Epic', 'Mythic', 'Waifu', 'Special Edition', 'Limited', 'Event', 'Legendary']
    if rarity not in valid:
        await update.message.reply_text(f"Invalid rarity. Choose from: {', '.join(valid)}")
        return RARITY
    context.user_data['char_rarity'] = rarity
    await update.message.reply_text("Send the price in coins:")
    return PRICE

async def addcharacter_price(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        price = int(update.message.text)
    except ValueError:
        await update.message.reply_text("Price must be a number.")
        return PRICE
    # Fixed: added safety counter to prevent infinite loop if IDs are exhausted
    rand_id = None
    for _ in range(200):
        candidate = f"#{random.randint(0, 9999):04d}"
        if not await db.char_id_exists(candidate):
            rand_id = candidate
            break
    if rand_id is None:
        await update.message.reply_text("❌ Could not generate a unique ID. Consider expanding the ID range.")
        return ConversationHandler.END
    await db.add_character(
        rand_id, context.user_data['char_name'], context.user_data['char_anime'],
        context.user_data['char_img'], context.user_data['char_rarity'], price
    )
    await update.message.reply_text(f"✅ Character added with ID {rand_id}")
    return ConversationHandler.END

async def cancel_add(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Cancelled.")
    return ConversationHandler.END

async def remove_character(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /remove <character_id>")
        return
    char_id = context.args[0]
    await db.remove_character(char_id)
    await update.message.reply_text(f"Removed {char_id} from the market (existing inventories unaffected).")

async def listchar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    chars, _ = await db.get_market_characters(1000, 0)
    if not chars:
        await update.message.reply_text("No characters.")
        return
    text = "📋 *All Characters*\n"
    for c in chars[:30]:
        text += f"`{c['char_id']}` {c['name']} ({c['anime']})\n"
    await update.message.reply_text(text, parse_mode="Markdown")

async def addcoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user's message.")
        return
    target = update.message.reply_to_message.from_user
    try:
        amount = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /addcoins <amount> (reply to user)")
        return
    await db.add_coins(target.id, amount)
    await update.message.reply_text(f"Added {amount} coins to {target.first_name}.")

async def removecoins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    if not update.message.reply_to_message:
        await update.message.reply_text("Reply to a user.")
        return
    target = update.message.reply_to_message.from_user
    try:
        amount = int(context.args[0])
    except (IndexError, ValueError):
        await update.message.reply_text("Usage: /removecoins <amount> (reply)")
        return
    await db.remove_coins(target.id, amount)
    await update.message.reply_text(f"Removed {amount} coins from {target.first_name}.")

async def setstartvid(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.video:
        await update.message.reply_text("Reply to a video with /setstartvid")
        return
    file_id = update.message.reply_to_message.video.file_id
    await db.set_start_video(file_id)
    await update.message.reply_text("Start video updated.")

async def setwelcomepic(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Use this command in a group.")
        return
    if not update.message.reply_to_message or not update.message.reply_to_message.photo:
        await update.message.reply_text("Reply to a photo with /setwelcomepic")
        return
    file_id = update.message.reply_to_message.photo[-1].file_id
    await db.set_group_welcome_img(chat.id, file_id)
    await update.message.reply_text("Welcome image set for this group.")

async def resetgrpdata(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("Only owner.")
        return
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text("Use in group.")
        return
    async with db.pool.acquire() as conn:
        await conn.execute('DELETE FROM users WHERE group_id = $1', chat.id)
        await conn.execute('DELETE FROM inventory WHERE group_id = $1', chat.id)
        await conn.execute('DELETE FROM group_user_data WHERE group_id = $1', chat.id)
    await update.message.reply_text("All user data reset for this group.")

async def stats(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only command.")
        return
    total_users = await db.get_total_users()
    active_today = await db.get_active_today()
    total_chars = await db.get_total_characters()
    total_referrals = await db.get_total_referrals()

    # -- Overview --
    overview = (
        f"📊 <b>Bot Statistics</b>\n"
        f"━━━━━━━━━━━━━━━━\n"
        f"👥 Total Users: <b>{total_users:,}</b>\n"
        f"🟢 Active Today: <b>{active_today:,}</b>\n"
        f"🎴 Total Characters: <b>{total_chars:,}</b>\n"
        f"📨 Total Referrals: <b>{total_referrals:,}</b>\n"
    )
    await update.message.reply_text(overview, parse_mode="HTML")

    # -- Groups List --
    groups_info = await db.get_all_groups_info()
    if groups_info:
        grp_text = f"🏘 <b>Groups ({len(groups_info)})</b>\n━━━━━━━━━━━━━━━━\n\n"
        for g in groups_info:
            title = html_lib.escape(g.get('title') or '〔Unknown Group〕')
            grp_text += f"📌 <b>{title}</b>\n🆔 <code>{g['group_id']}</code>\n\n"
        # Split into chunks of 4096 chars
        if len(grp_text) <= 4096:
            await update.message.reply_text(grp_text, parse_mode="HTML")
        else:
            lines = grp_text.split("\n\n")
            chunk = f"🏘 <b>Groups ({len(groups_info)})</b>\n━━━━━━━━━━━━━━━━\n\n"
            for line in lines[1:]:
                if len(chunk) + len(line) + 2 > 4096:
                    await update.message.reply_text(chunk, parse_mode="HTML")
                    chunk = ""
                chunk += line + "\n\n"
            if chunk.strip():
                await update.message.reply_text(chunk, parse_mode="HTML")

    # -- Users List (chunked) --
    users = await db.get_all_users_info()
    if users:
        CHUNK = 30
        for i in range(0, len(users), CHUNK):
            chunk = users[i:i + CHUNK]
            user_text = f"👤 <b>Users {i + 1}–{i + len(chunk)}</b>\n━━━━━━━━━━━━━━━━\n\n"
            for u in chunk:
                name = html_lib.escape(u.get('first_name') or '〔Unknown〕')
                uname = f"@{html_lib.escape(u['username'])}" if u.get('username') else "no username"
                user_text += f"• <b>{name}</b> ({uname})\n  🆔 <code>{u['user_id']}</code>\n"
            await update.message.reply_text(user_text, parse_mode="HTML")

async def groupmembers(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /groupmembers <group_id>")
        return
    try:
        group_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Group ID must be a number.")
        return
    members = await db.get_group_members_info(group_id)
    if not members:
        await update.message.reply_text("No members found for this group.")
        return
    try:
        chat = await context.bot.get_chat(group_id)
        title = html_lib.escape(chat.title or str(group_id))
    except Exception:
        title = str(group_id)
    CHUNK = 30
    for i in range(0, len(members), CHUNK):
        chunk = members[i:i + CHUNK]
        text = f"👥 <b>{title} — Members {i + 1}–{i + len(chunk)}</b>\n━━━━━━━━━━━━━━━━\n\n"
        for m in chunk:
            name = html_lib.escape(m.get('first_name') or '〔Unknown〕')
            uname = f"@{html_lib.escape(m['username'])}" if m.get('username') else "no username"
            text += f"• <b>{name}</b> ({uname})\n  🆔 <code>{m['user_id']}</code>\n"
        await update.message.reply_text(text, parse_mode="HTML")

async def addtask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only.")
        return
    if len(context.args) < 4:
        await update.message.reply_text("Usage: /addtask channel @username reward_coins description")
        return
    task_type = context.args[0]
    target = context.args[1]
    try:
        reward = int(context.args[2])
    except ValueError:
        await update.message.reply_text("Reward must be a number.")
        return
    description = " ".join(context.args[3:])
    task_id = await db.add_task(task_type, target, reward, description, update.effective_user.id)
    await update.message.reply_text(f"✅ Task added! ID: {task_id}")

async def removetask(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /removetask <task_id>")
        return
    try:
        task_id = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Task ID must be a number.")
        return
    await db.remove_task(task_id)
    await update.message.reply_text(f"✅ Task {task_id} removed.")

async def listtasks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        await update.message.reply_text("⛔ Owner only.")
        return
    all_tasks = await db.get_tasks()
    if not all_tasks:
        await update.message.reply_text("No tasks found.")
        return
    text = "📋 <b>All Tasks</b>\n━━━━━━━━━━━━━━━━\n\n"
    for t in all_tasks:
        safe_desc = html_lib.escape(t['description'])
        safe_target = html_lib.escape(t['target'])
        text += (
            f"🆔 <code>{t['task_id']}</code> | Type: {t['type']}\n"
            f"🎯 Target: {safe_target}\n"
            f"💰 Reward: {t['reward']} coins\n"
            f"📝 {safe_desc}\n\n"
        )
    await update.message.reply_text(text, parse_mode="HTML")

# ---------- /setstartmsg — Dev only ----------
async def setstartmsg_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    await update.message.reply_text(
        "✏️ <b>Set Start Message</b>\n\n"
        "Send the new caption for the /start command.\n"
        "This replaces the default text (video stays the same, buttons stay the same).\n\n"
        "Send /cancel to abort.",
        parse_mode="HTML"
    )
    return SETSTARTMSG_CONTENT

async def setstartmsg_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    new_msg = update.message.text
    await db.set_start_msg(new_msg)
    await update.message.reply_text(
        f"✅ Start message updated!\n\nPreview:\n\n{new_msg}"
    )
    return ConversationHandler.END

# ---------- /broadcast — Dev only ----------
async def broadcast_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop('broadcast_msg', None)
    await update.message.reply_text(
        "📣 <b>Broadcast Mode</b>\n\n"
        "Send me the content to broadcast:\n"
        "• Text message\n"
        "• Photo\n"
        "• Photo + caption\n"
        "• Video\n"
        "• Video + caption\n\n"
        "✅ When ready → send <code>/go</code> to broadcast to all users &amp; groups.\n"
        "❌ To cancel → send <code>/cancelbc</code>",
        parse_mode="HTML"
    )
    return BROADCAST_CONTENT

async def broadcast_receive(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Store the message the dev wants to broadcast."""
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    msg = update.message
    data: Dict[str, Any] = {
        'text': msg.text or None,
        'caption': msg.caption or None,
        'photo': msg.photo[-1].file_id if msg.photo else None,
        'video': msg.video.file_id if msg.video else None,
    }
    context.user_data['broadcast_msg'] = data
    if data['photo']:
        kind = "🖼 Photo"
    elif data['video']:
        kind = "🎬 Video"
    else:
        kind = "📝 Text"
    await msg.reply_text(
        f"✅ Content saved ({kind}).\n"
        "Send another message to replace it, or send /go to start broadcasting."
    )
    return BROADCAST_CONTENT

async def _send_broadcast_msg(bot, chat_id: int, data: Dict[str, Any]):
    """Send one broadcast message to a chat. Returns the sent Message object."""
    caption = data.get('caption')
    if data.get('photo'):
        return await bot.send_photo(chat_id, data['photo'], caption=caption)
    elif data.get('video'):
        return await bot.send_video(chat_id, data['video'], caption=caption)
    elif data.get('text'):
        return await bot.send_message(chat_id, data['text'])
    return None

async def broadcast_go(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send the stored broadcast content to all users and all groups."""
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    data = context.user_data.get('broadcast_msg')
    if not data:
        await update.message.reply_text("❌ No content stored. Use /broadcast first.")
        return ConversationHandler.END

    status_msg = await update.message.reply_text("📣 Starting broadcast to users…")

    # --- Broadcast to all started users ---
    user_ids = await db.get_all_started_user_ids()
    u_sent, u_failed = 0, 0
    for uid in user_ids:
        try:
            await _send_broadcast_msg(context.bot, uid, data)
            u_sent += 1
        except (Forbidden, BadRequest):
            # User blocked the bot or chat doesn't exist — silent skip
            u_failed += 1
        except Exception:
            u_failed += 1
        # Respect Telegram rate limit: ~20 msg/sec
        await asyncio.sleep(0.05)

    try:
        await status_msg.edit_text(
            f"✅ Users done: {u_sent} sent · {u_failed} skipped\n📣 Broadcasting to groups…"
        )
    except Exception:
        pass

    # --- Broadcast to all registered groups ---
    group_ids = await db.get_all_group_ids()
    g_sent, g_failed, g_pinned = 0, 0, 0
    for gid in group_ids:
        try:
            sent_msg = await _send_broadcast_msg(context.bot, gid, data)
            g_sent += 1
            if sent_msg:
                # Try to pin — succeeds if bot is admin, silently fails otherwise
                try:
                    await context.bot.pin_chat_message(gid, sent_msg.message_id)
                    g_pinned += 1
                except Exception:
                    pass
        except (Forbidden, BadRequest):
            # Bot kicked or group deleted — silent skip
            g_failed += 1
        except Exception:
            g_failed += 1
        await asyncio.sleep(0.05)

    context.user_data.pop('broadcast_msg', None)
    try:
        await status_msg.edit_text(
            f"📣 <b>Broadcast Complete!</b>\n\n"
            f"👤 Users: ✅ {u_sent} sent · ❌ {u_failed} skipped\n"
            f"🏘 Groups: ✅ {g_sent} sent · ❌ {g_failed} skipped\n"
            f"📌 Pinned in {g_pinned} groups",
            parse_mode="HTML"
        )
    except Exception:
        await update.message.reply_text(
            f"📣 Broadcast done!\nUsers: {u_sent}/{len(user_ids)} · Groups: {g_sent}/{len(group_ids)} · Pinned: {g_pinned}"
        )
    return ConversationHandler.END

async def broadcast_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_owner(update.effective_user.id):
        return ConversationHandler.END
    context.user_data.pop('broadcast_msg', None)
    await update.message.reply_text("❌ Broadcast cancelled.")
    return ConversationHandler.END

# ---------- Group Admin Commands ----------
async def listadmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    lang = await db.get_user_lang(update.effective_user.id)
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(t(lang, 'admins_groups_only'))
        return
    admins = await chat.get_administrators()
    human_admins = [a.user for a in admins if not a.user.is_bot]
    if not human_admins:
        await update.message.reply_text(t(lang, 'admins_none'))
        return
    text = t(lang, 'admins_header') + "\n".join(
        f"• <a href='tg://user?id={a.id}'>{html_lib.escape(a.full_name)}</a>" for a in human_admins
    )
    await update.message.reply_text(text, parse_mode="HTML")

async def calladmins(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    lang = await db.get_user_lang(update.effective_user.id)
    if chat.type not in ["group", "supergroup"]:
        await update.message.reply_text(t(lang, 'calladmins_groups_only'))
        return
    last = await db.get_last_calladmins(chat.id)
    if last and (datetime.utcnow() - last).total_seconds() < 600:
        await update.message.reply_text(t(lang, 'calladmins_cooldown'))
        return
    admins = await chat.get_administrators()
    human_admins = [a.user for a in admins if not a.user.is_bot]
    if not human_admins:
        await update.message.reply_text(t(lang, 'calladmins_none'))
        return
    mentions = [f'<a href="tg://user?id={a.id}">.</a>' for a in human_admins]
    text = t(lang, 'calladmins_text') + "".join(mentions)
    await update.message.reply_text(text, parse_mode="HTML")
    await db.update_calladmins_time(chat.id)

async def welcome_new_members(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    if chat.type not in ["group", "supergroup"]:
        return
    for member in update.message.new_chat_members:
        if member.is_bot:
            continue
        await db.update_user_info(member.id, member.first_name, member.username)
        lang = await db.get_user_lang(member.id)
        mention = f'<a href="tg://user?id={member.id}">{html_lib.escape(member.first_name)}</a>'
        welcome_text = t(lang, 'welcome_member', group=html_lib.escape(chat.title), mention=mention)
        welcome_img = await db.get_group_welcome_img(chat.id)
        if welcome_img:
            await update.message.reply_photo(welcome_img, caption=welcome_text, parse_mode="HTML")
        else:
            await update.message.reply_text(welcome_text, parse_mode="HTML")

async def bot_added_to_group(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_member = update.chat_member
    if not chat_member:
        return
    new_status = chat_member.new_chat_member.status
    # Register group whenever bot is added (admin OR regular member)
    if chat_member.new_chat_member.user.id == context.bot.id and new_status in [CMS.ADMINISTRATOR, CMS.MEMBER]:
        adder_id = chat_member.from_user.id
        group_id = chat_member.chat.id
        group_title = chat_member.chat.title or str(group_id)
        # Always register the group so it shows up in stats/broadcasts
        await db.update_group_title(group_id, group_title)
        # Only reward coins when bot is added as ADMINISTRATOR
        if new_status == CMS.ADMINISTRATOR:
            await db.record_group_add(adder_id, group_id)
            if not await db.is_group_add_rewarded(group_id):
                await db.reward_group_add(adder_id, group_id)
                await db.add_coins(adder_id, 5000)
                try:
                    adder_lang = await db.get_user_lang(adder_id)
                    await context.bot.send_message(
                        adder_id,
                        t(adder_lang, 'bot_added_thanks', group=html_lib.escape(group_title)),
                        parse_mode="HTML"
                    )
                except Exception:
                    pass

# ---------- Global Error Handler ----------
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE):
    import traceback
    tb = "".join(traceback.format_exception(None, context.error, context.error.__traceback__))
    print(f"[ERROR] Exception while handling update:\n{tb}")
    if isinstance(update, Update) and update.message:
        try:
            lang = 'en'
            if update.effective_user:
                lang = await db.get_user_lang(update.effective_user.id)
            await update.message.reply_text(t(lang, 'error'))
        except Exception:
            pass

# ---------- Language Command ----------
async def lang_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    lang = await db.get_user_lang(user.id)
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("🇬🇧 English", callback_data="setlang:en"),
            InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang:ru"),
        ]
    ])
    await update.message.reply_text(t(lang, 'lang_choose'), reply_markup=keyboard)

async def lang_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    user = update.effective_user
    await query.answer()
    if query.data == "lang:choose":
        lang = await db.get_user_lang(user.id)
        keyboard = InlineKeyboardMarkup([
            [
                InlineKeyboardButton("🇬🇧 English", callback_data="setlang:en"),
                InlineKeyboardButton("🇷🇺 Русский", callback_data="setlang:ru"),
            ]
        ])
        # Fixed: edit the existing message instead of sending a new one
        try:
            await query.edit_message_text(t(lang, 'lang_choose'), reply_markup=keyboard)
        except Exception:
            await query.message.reply_text(t(lang, 'lang_choose'), reply_markup=keyboard)
        return
    chosen = query.data.split(":")[1]
    if chosen not in ('en', 'ru'):
        return
    await db.set_user_lang(user.id, chosen)
    confirm_key = f'lang_set_{chosen}'
    await query.edit_message_text(t(chosen, confirm_key))

# ---------- Web Preview (FastAPI) ----------
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, user-scalable=yes">
    <title>Anime Character Store</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            background: linear-gradient(145deg, #0b0b1a 0%, #1a1a2e 100%);
            font-family: 'Segoe UI', Roboto, 'Helvetica Neue', sans-serif;
            min-height: 100vh;
            color: #fff;
        }

        /* ── Header ── */
        .header {
            text-align: center;
            padding: 28px 16px 10px;
        }
        .header h1 {
            font-size: 1.65rem;
            font-weight: 800;
            background: linear-gradient(90deg, #a78bfa, #f472b6);
            -webkit-background-clip: text; background-clip: text;
            color: transparent;
            letter-spacing: -0.5px;
        }
        .header p { color: #666; font-size: 0.82rem; margin-top: 5px; }

        /* ── Search Bar ── */
        .search-wrap {
            padding: 14px 16px 10px;
            max-width: 500px;
            margin: 0 auto;
        }
        .search-bar {
            width: 100%;
            padding: 13px 18px;
            background: rgba(255,255,255,0.06);
            border: 1.5px solid rgba(255,255,255,0.1);
            border-radius: 50px;
            color: #fff;
            font-size: 0.93rem;
            outline: none;
            transition: border-color 0.25s;
        }
        .search-bar::placeholder { color: #555; }
        .search-bar:focus { border-color: #a78bfa; background: rgba(167,139,250,0.07); }

        /* ── Anime Filter Strip ── */
        .filter-strip {
            padding: 4px 12px 14px;
            overflow-x: auto;
            white-space: nowrap;
            scrollbar-width: none;
        }
        .filter-strip::-webkit-scrollbar { display: none; }
        .anime-btn {
            display: inline-flex;
            align-items: center;
            gap: 5px;
            padding: 7px 14px;
            margin-right: 7px;
            background: rgba(255,255,255,0.06);
            border: 1.5px solid rgba(255,255,255,0.09);
            border-radius: 50px;
            color: #aaa;
            font-size: 0.8rem;
            cursor: pointer;
            transition: all 0.2s;
            white-space: nowrap;
            user-select: none;
            -webkit-tap-highlight-color: transparent;
        }
        .anime-btn.active {
            background: linear-gradient(90deg, #7c3aed, #db2777);
            border-color: transparent;
            color: #fff;
            font-weight: 700;
            box-shadow: 0 4px 14px rgba(124,58,237,0.4);
        }
        .btn-count {
            background: rgba(255,255,255,0.14);
            border-radius: 20px;
            padding: 1px 7px;
            font-size: 0.72rem;
            font-weight: 600;
        }
        .anime-btn.active .btn-count { background: rgba(255,255,255,0.22); }

        /* ── Card Area ── */
        .main {
            max-width: 500px;
            margin: 0 auto;
            padding: 0 16px 50px;
        }
        .card {
            background: rgba(18,18,38,0.82);
            backdrop-filter: blur(14px);
            border-radius: 28px;
            padding: 18px;
            border: 1px solid rgba(255,255,255,0.07);
            box-shadow: 0 22px 44px rgba(0,0,0,0.55);
            transition: transform 0.22s;
        }
        .card:hover { transform: translateY(-4px); }
        .character-img {
            width: 100%; border-radius: 20px;
            object-fit: cover; aspect-ratio: 1/1;
            background: #0d0d1a;
            box-shadow: 0 8px 24px rgba(0,0,0,0.45);
            display: block;
        }
        .info { margin-top: 14px; }
        .char-name {
            font-size: 1.55rem; font-weight: 800;
            background: linear-gradient(90deg, #a78bfa, #f472b6);
            -webkit-background-clip: text; background-clip: text;
            color: transparent;
            line-height: 1.25;
            margin-bottom: 5px;
        }
        .char-anime { font-size: 0.92rem; color: #bbb; margin-bottom: 10px; }
        .badges { display: flex; flex-wrap: wrap; gap: 7px; margin-bottom: 10px; }
        .badge {
            padding: 4px 13px; border-radius: 40px;
            font-size: 0.78rem; font-weight: 700;
        }
        .badge-rarity { background: rgba(255,215,0,0.12); color: #ffd700; border: 1px solid rgba(255,215,0,0.2); }
        .badge-price  { background: rgba(124,252,0,0.10); color: #7CFC00;  border: 1px solid rgba(124,252,0,0.18); }
        .char-id { font-family: monospace; font-size: 0.76rem; color: #555; margin-top: 4px; }

        /* ── Navigation ── */
        .nav {
            display: flex; align-items: center;
            justify-content: center; gap: 18px;
            margin-top: 18px;
        }
        .nav-btn {
            background: rgba(124,58,237,0.25);
            border: 1.5px solid rgba(124,58,237,0.35);
            color: #fff; font-size: 1.25rem;
            padding: 11px 24px; border-radius: 50px;
            cursor: pointer; transition: all 0.2s;
            -webkit-tap-highlight-color: transparent;
        }
        .nav-btn:active { transform: scale(0.93); }
        .nav-btn:hover:not(:disabled) { background: rgba(124,58,237,0.45); }
        .nav-btn:disabled { opacity: 0.28; cursor: default; }
        .page-info { color: #777; font-size: 0.84rem; min-width: 70px; text-align: center; }

        /* ── Empty / Loading ── */
        .empty {
            text-align: center; padding: 64px 20px;
            color: #555; font-size: 0.95rem;
        }
        .empty-icon { font-size: 2.8rem; margin-bottom: 12px; }
        .loading { text-align: center; padding: 80px 20px; }
        .dot {
            display: inline-block; width: 9px; height: 9px;
            background: #a78bfa; border-radius: 50%;
            margin: 0 3px;
            animation: blink 1.2s infinite ease-in-out;
        }
        .dot:nth-child(2){ animation-delay:.2s }
        .dot:nth-child(3){ animation-delay:.4s }
        @keyframes blink {
            0%,80%,100%{ transform:scale(1); opacity:.6 }
            40%{ transform:scale(1.5); opacity:1 }
        }

        @media(max-width:420px){
            .char-name{ font-size:1.3rem }
            .card{ padding:14px }
            .header h1{ font-size:1.4rem }
        }
    </style>
</head>
<body>

<div class="header">
    <h1>✨ Anime Character Store</h1>
    <p>Collect · Trade · Dominate</p>
</div>

<div class="search-wrap">
    <input type="text" id="searchBar" class="search-bar" placeholder="🔍  Search by name, anime or ID…" autocomplete="off">
</div>

<div class="filter-strip" id="filterStrip"></div>

<div class="main">
    <div id="cardArea">
        <div class="loading">
            <span class="dot"></span><span class="dot"></span><span class="dot"></span>
            <p style="margin-top:18px;color:#555;font-size:0.88rem">Loading characters…</p>
        </div>
    </div>
    <div class="nav" id="navRow" style="display:none">
        <button class="nav-btn" id="prevBtn">◀</button>
        <span class="page-info" id="pageInfo"></span>
        <button class="nav-btn" id="nextBtn">▶</button>
    </div>
</div>

<script>
(function(){
    const RARITY_EMOJI = {
        'Common':'⚪','Uncommon':'🟢','Elite':'🔵','Epic':'🟣','Mythic':'🔴',
        'Waifu':'💖','Special Edition':'✨','Limited':'⏳','Event':'🎉','Legendary':'🌟'
    };

    let all = [], shown = [], idx = 0, activeAnime = 'All';

    const cardArea   = document.getElementById('cardArea');
    const navRow     = document.getElementById('navRow');
    const prevBtn    = document.getElementById('prevBtn');
    const nextBtn    = document.getElementById('nextBtn');
    const pageInfo   = document.getElementById('pageInfo');
    const filterStrip= document.getElementById('filterStrip');
    const searchBar  = document.getElementById('searchBar');

    function esc(s){ return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;'); }

    function buildFilters(){
        const counts = {};
        all.forEach(c => counts[c.anime] = (counts[c.anime]||0)+1);
        const names = Object.keys(counts).sort();
        let html = `<span class="anime-btn active" data-a="All">🌸 All<span class="btn-count">${all.length}</span></span>`;
        names.forEach(a => {
            html += `<span class="anime-btn" data-a="${esc(a)}">${esc(a)}<span class="btn-count">${counts[a]}</span></span>`;
        });
        filterStrip.innerHTML = html;
        filterStrip.querySelectorAll('.anime-btn').forEach(btn => {
            btn.addEventListener('click', ()=>{
                activeAnime = btn.dataset.a;
                filterStrip.querySelectorAll('.anime-btn').forEach(b=>b.classList.remove('active'));
                btn.classList.add('active');
                idx = 0;
                applyFilter();
            });
        });
    }

    function applyFilter(){
        const q = searchBar.value.trim().toLowerCase();
        shown = all.filter(c => {
            const okAnime  = activeAnime === 'All' || c.anime === activeAnime;
            const okSearch = !q || c.name.toLowerCase().includes(q)
                              || c.anime.toLowerCase().includes(q)
                              || c.char_id.toLowerCase().includes(q);
            return okAnime && okSearch;
        });
        idx = 0;
        render();
    }

    function render(){
        if(!shown.length){
            cardArea.innerHTML = `<div class="empty"><div class="empty-icon">🌙</div><p>No characters found.<br><span style="font-size:.82rem;color:#444">Try a different filter or search.</span></p></div>`;
            navRow.style.display='none';
            return;
        }
        const c = shown[idx];
        const em = RARITY_EMOJI[c.rarity]||'⭐';
        cardArea.innerHTML = `
        <div class="card">
            <img class="character-img" src="${esc(c.img_url)}" alt="${esc(c.name)}" loading="lazy">
            <div class="info">
                <div class="char-name">${em} ${esc(c.name)}</div>
                <div class="char-anime">🎬 ${esc(c.anime)}</div>
                <div class="badges">
                    <span class="badge badge-rarity">${em} ${esc(c.rarity)}</span>
                    <span class="badge badge-price">💰 ${Number(c.price).toLocaleString()} coins</span>
                </div>
                <div class="char-id">🆔 ${esc(c.char_id)}</div>
            </div>
        </div>`;
        navRow.style.display = 'flex';
        pageInfo.textContent = `${idx+1} / ${shown.length}`;
        prevBtn.disabled = idx === 0;
        nextBtn.disabled = idx === shown.length-1;
    }

    prevBtn.addEventListener('click', ()=>{ if(idx>0){ idx--; render(); } });
    nextBtn.addEventListener('click', ()=>{ if(idx<shown.length-1){ idx++; render(); } });

    let debounce;
    searchBar.addEventListener('input', ()=>{ clearTimeout(debounce); debounce=setTimeout(applyFilter,220); });

    fetch('/api/characters')
        .then(r=>r.json())
        .then(data=>{
            all = data; shown = data;
            if(!all.length){
                cardArea.innerHTML=`<div class="empty"><div class="empty-icon">📭</div><p>No characters yet.<br><span style="font-size:.82rem;color:#444">Check back soon!</span></p></div>`;
                return;
            }
            buildFilters();
            render();
        })
        .catch(()=>{
            cardArea.innerHTML=`<div class="empty"><div class="empty-icon">⚠️</div><p>Failed to load.<br><span style="font-size:.82rem;color:#444">Please refresh the page.</span></p></div>`;
        });
})();
</script>
</body>
</html>
"""

# ---------- FastAPI App ----------
app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/", response_class=HTMLResponse)
async def store_page():
    return HTML_TEMPLATE

@app.get("/api/characters")
async def api_characters():
    chars, _ = await db.get_market_characters(limit=500, offset=0)
    return [
        {"char_id": c["char_id"], "name": c["name"], "anime": c["anime"],
         "img_url": c["img_url"], "rarity": c["rarity"], "price": c["price"]}
        for c in chars
    ]

@app.get("/health")
async def health_check():
    """
    Health endpoint for Uptime Robot / Render keep-alive.
    Uptime Robot: set monitor URL to https://your-render-url.onrender.com/health
    Check interval: every 5 minutes (keeps Render free tier from sleeping).
    """
    return JSONResponse({"status": "ok", "timestamp": datetime.utcnow().isoformat()})

@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Receives Telegram updates when WEBHOOK_URL is set."""
    if bot_application is None:
        return {"ok": False, "error": "Bot not ready"}
    data = await request.json()
    update = Update.de_json(data, bot_application.bot)
    await bot_application.process_update(update)
    return {"ok": True}

# ---------- Main Entry Point ----------
async def run_bot():
    global bot_application
    await db.connect()
    await db.init_tables()

    if WEBHOOK_URL:
        # Webhook mode: disable PTB's built-in updater, FastAPI handles updates
        bot_application = Application.builder().token(BOT_TOKEN).updater(None).build()
    else:
        # Polling mode: PTB manages its own updater
        bot_application = Application.builder().token(BOT_TOKEN).build()

    bot_application.add_error_handler(error_handler)

    # User commands
    bot_application.add_handler(CommandHandler("start", start))
    bot_application.add_handler(CommandHandler("help", help_command))
    bot_application.add_handler(CommandHandler("lang", lang_command))
    bot_application.add_handler(CallbackQueryHandler(lang_callback, pattern=r'^(lang:|setlang:)'))
    bot_application.add_handler(CommandHandler("daily", daily))
    bot_application.add_handler(CommandHandler("claim", claim))
    bot_application.add_handler(CommandHandler("wallet", wallet))
    bot_application.add_handler(CommandHandler("vault", vault))
    bot_application.add_handler(CommandHandler("mycollection", vault))
    bot_application.add_handler(CommandHandler("market", market))
    bot_application.add_handler(CommandHandler("buy", buy))
    bot_application.add_handler(CommandHandler("sell", sell))
    bot_application.add_handler(CommandHandler("search", search))

    # Drop system
    bot_application.add_handler(CommandHandler("guess", guess))
    bot_application.add_handler(CommandHandler("enabledrops", enabledrops))
    bot_application.add_handler(CommandHandler("disabledrops", disabledrops))

    # Leaderboard
    bot_application.add_handler(CommandHandler("leaderboard", leaderboard))

    # Tasks
    bot_application.add_handler(CommandHandler("tasks", tasks))
    bot_application.add_handler(CommandHandler("refer", refer))
    bot_application.add_handler(CallbackQueryHandler(tasks_callback, pattern=r'^task:'))

    # Group admin
    bot_application.add_handler(CommandHandler("listadmins", listadmins))
    bot_application.add_handler(CommandHandler("calladmins", calladmins))

    # Owner commands — addcharacter conversation
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("addcharacter", addcharacter_start)],
        states={
            NAME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcharacter_name)],
            ANIME: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcharacter_anime)],
            IMG_URL: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcharacter_img)],
            RARITY: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcharacter_rarity)],
            PRICE: [MessageHandler(filters.TEXT & ~filters.COMMAND, addcharacter_price)],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )
    bot_application.add_handler(conv_handler)

    # Owner — /setstartmsg conversation
    setstartmsg_conv = ConversationHandler(
        entry_points=[CommandHandler("setstartmsg", setstartmsg_start)],
        states={
            SETSTARTMSG_CONTENT: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, setstartmsg_receive),
            ],
        },
        fallbacks=[CommandHandler("cancel", cancel_add)],
    )
    bot_application.add_handler(setstartmsg_conv)

    # Owner — /broadcast conversation
    # per_chat=False so owner can run broadcast from any chat (DM, group, etc.)
    broadcast_conv = ConversationHandler(
        entry_points=[CommandHandler("broadcast", broadcast_start)],
        states={
            BROADCAST_CONTENT: [
                CommandHandler("go", broadcast_go),
                CommandHandler("cancelbc", broadcast_cancel),
                MessageHandler(
                    (filters.TEXT | filters.PHOTO | filters.VIDEO) & ~filters.COMMAND,
                    broadcast_receive
                ),
            ],
        },
        fallbacks=[CommandHandler("cancelbc", broadcast_cancel)],
        per_user=True,
        per_chat=False,
    )
    bot_application.add_handler(broadcast_conv)

    bot_application.add_handler(CommandHandler("remove", remove_character))
    bot_application.add_handler(CommandHandler("listchar", listchar))
    bot_application.add_handler(CommandHandler("addcoins", addcoins))
    bot_application.add_handler(CommandHandler("removecoins", removecoins))
    bot_application.add_handler(CommandHandler("setstartvid", setstartvid))
    bot_application.add_handler(CommandHandler("setwelcomepic", setwelcomepic))
    bot_application.add_handler(CommandHandler("resetgrpdata", resetgrpdata))
    bot_application.add_handler(CommandHandler("stats", stats))
    bot_application.add_handler(CommandHandler("groupmembers", groupmembers))
    bot_application.add_handler(CommandHandler("addtask", addtask))
    bot_application.add_handler(CommandHandler("removetask", removetask))
    bot_application.add_handler(CommandHandler("listtasks", listtasks))

    # Welcome & group tracking
    bot_application.add_handler(MessageHandler(filters.StatusUpdate.NEW_CHAT_MEMBERS, welcome_new_members))
    bot_application.add_handler(ChatMemberHandler(bot_added_to_group, ChatMemberHandler.CHAT_MEMBER))

    # Pagination callbacks
    bot_application.add_handler(CallbackQueryHandler(market_callback, pattern=r'^mkt:'))
    bot_application.add_handler(CallbackQueryHandler(vault_callback, pattern=r'^vlt:'))

    await start_drop_scheduler(bot_application.bot)
    await bot_application.initialize()
    await bot_application.start()

    if WEBHOOK_URL:
        await bot_application.bot.set_webhook(f"{WEBHOOK_URL}/webhook")
        print(f"✅ Bot started with WEBHOOK: {WEBHOOK_URL}/webhook")
        # FastAPI serves the webhook — no polling needed
    else:
        await bot_application.updater.start_polling()
        print("✅ Bot started with POLLING (set WEBHOOK_URL env var for production)")

    return bot_application

async def run_web():
    port = int(os.getenv("PORT", 8000))
    config = uvicorn.Config(app, host="0.0.0.0", port=port, log_level="info")
    server = uvicorn.Server(config)
    await server.serve()

async def main():
    bot_task = asyncio.create_task(run_bot())
    web_task = asyncio.create_task(run_web())
    await asyncio.gather(bot_task, web_task)

if __name__ == "__main__":
    asyncio.run(main())
