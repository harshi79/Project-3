"""Owner-only, inline management panel for the Soul Collector bot.

The panel uses Telegram's native rich-message API when available and falls back
through the injected helpers to ordinary editable text messages.
"""

import re
from typing import Any, Callable, Optional, Tuple

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes


_MARKDOWN_SPECIALS = set("\\_*[]()~`>#+-=|{}.!")


def _escape_markdown(value: Any) -> str:
    text = str(value if value is not None else "")
    return "".join("\\" + char if char in _MARKDOWN_SPECIALS else char for char in text)


def _plain_text(markdown: str) -> str:
    text = re.sub(r"(?m)^#{1,6}\s*", "", markdown)
    text = re.sub(r"(?<!\\)[*_`]", "", text)
    return text.replace("\\", "")


def register_admin_management(
    application: Application,
    db,
    owner_id: int,
    send_rich_or_text_message: Callable,
    edit_rich_or_text_message: Callable,
) -> None:
    """Register /manage and its owner-checked callback router."""

    def home_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Overview", callback_data="manage:stats"),
             InlineKeyboardButton("🎴 Characters", callback_data="manage:characters:1")],
            [InlineKeyboardButton("📋 Tasks", callback_data="manage:tasks"),
             InlineKeyboardButton("📣 Broadcast", callback_data="manage:broadcast")],
            [InlineKeyboardButton("➕ Add character", callback_data="manage:add"),
             InlineKeyboardButton("✏️ Start message", callback_data="manage:startmsg")],
            [InlineKeyboardButton("✕ Close", callback_data="manage:close")],
        ])

    def back_keyboard() -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[InlineKeyboardButton("← Management home", callback_data="manage:home")]])

    async def render(view: str, page: int = 1, item_id: Optional[str] = None) -> Tuple[str, str, Optional[InlineKeyboardMarkup]]:
        if view == "home":
            total_users = await db.get_total_users()
            active_today = await db.get_active_today()
            total_chars = await db.get_total_characters()
            group_count = len(await db.get_all_groups_info())
            markdown = (
                "# ✦ Soul Collector · Management\n\n"
                "> Private owner workspace. Pick a section below; navigation edits this message in place.\n\n"
                "| Live overview | Count |\n|:--|--:|\n"
                f"| Collectors | **{total_users:,}** |\n"
                f"| Active today | **{active_today:,}** |\n"
                f"| Characters in market | **{total_chars:,}** |\n"
                f"| Registered groups | **{group_count:,}** |\n\n"
                "**Free Telegram features enabled:** rich formatting and inline controls. "
                "No Premium-only emoji or paid-broadcast features are used.\n\n"
                "Use `/manage` any time to reopen this control panel."
            )
            return markdown, _plain_text(markdown), home_keyboard()

        if view == "stats":
            total_users = await db.get_total_users()
            active_today = await db.get_active_today()
            total_chars = await db.get_total_characters()
            total_referrals = await db.get_total_referrals()
            groups = await db.get_all_groups_info()
            markdown = (
                "## 📊 Bot overview\n\n"
                "| Metric | Value |\n|:--|--:|\n"
                f"| Started users | **{total_users:,}** |\n"
                f"| Active today | **{active_today:,}** |\n"
                f"| Characters available | **{total_chars:,}** |\n"
                f"| Registered groups | **{len(groups):,}** |\n"
                f"| Successful referrals | **{total_referrals:,}** |\n\n"
                "For the detailed group and user export, run `/stats`."
            )
            return markdown, _plain_text(markdown), back_keyboard()

        if view == "characters":
            per_page = 5
            requested_page = max(1, page)
            items, total = await db.get_market_characters(per_page, (requested_page - 1) * per_page)
            total_pages = max(1, (total + per_page - 1) // per_page)
            page = max(1, min(requested_page, total_pages))
            if page != requested_page:
                items, total = await db.get_market_characters(per_page, (page - 1) * per_page)
            lines = [f"## 🎴 Market characters · {page}/{total_pages}", ""]
            buttons = []
            if items:
                for char in items:
                    name = _escape_markdown(char.get("name", "Unnamed"))
                    anime = _escape_markdown(char.get("anime", "Unknown anime"))
                    char_id = str(char.get("char_id", ""))
                    safe_id = char_id.replace("`", "")
                    lines.append(
                        f"**{name}** · `{safe_id}`\n"
                        f"{anime} · {_escape_markdown(char.get('rarity', ''))} · "
                        f"{int(char.get('price') or 0):,} coins"
                    )
                    if char_id and len(char_id.encode("utf-8")) <= 38:
                        buttons.append([InlineKeyboardButton(
                            f"🗑 Remove {char_id}", callback_data=f"manage:remove-char:{page}:{char_id}"
                        )])
                lines.extend(["", "Remove always asks for a second confirmation; owned copies are preserved."])
            else:
                lines.append("The market is empty. Use `/addcharacter` to add the first character.")
            nav = []
            if page > 1:
                nav.append(InlineKeyboardButton("◀ Previous", callback_data=f"manage:characters:{page - 1}"))
            nav.append(InlineKeyboardButton(f"{page} / {total_pages}", callback_data="manage:characters:noop"))
            if page < total_pages:
                nav.append(InlineKeyboardButton("Next ▶", callback_data=f"manage:characters:{page + 1}"))
            buttons.append(nav)
            buttons.append([InlineKeyboardButton("➕ Add character", callback_data="manage:add"),
                            InlineKeyboardButton("← Home", callback_data="manage:home")])
            markdown = "\n".join(lines)
            return markdown, _plain_text(markdown), InlineKeyboardMarkup(buttons)

        if view == "tasks":
            tasks = await db.get_tasks()
            lines = ["## 📋 Channel tasks", ""]
            buttons = []
            if tasks:
                for task in tasks[:8]:
                    task_id = int(task["task_id"])
                    lines.append(
                        f"**#{task_id} · {_escape_markdown(task.get('type', 'task'))}** — "
                        f"{int(task.get('reward') or 0):,} coins\n"
                        f"{_escape_markdown(task.get('description', ''))} · "
                        f"`{_escape_markdown(task.get('target', ''))}`"
                    )
                    buttons.append([InlineKeyboardButton(
                        f"🗑 Remove task #{task_id}", callback_data=f"manage:remove-task:{task_id}"
                    )])
                if len(tasks) > 8:
                    lines.extend(["", f"Showing 8 of {len(tasks)} tasks. Use `/listtasks` for the full list."])
            else:
                lines.append("No channel tasks configured yet. Add one with `/addtask`.")
            buttons.append([InlineKeyboardButton("← Management home", callback_data="manage:home")])
            markdown = "\n\n".join(lines)
            return markdown, _plain_text(markdown), InlineKeyboardMarkup(buttons)

        if view == "broadcast":
            markdown = (
                "## 📣 Broadcast tools\n\n"
                "Send `/broadcast` to stage a text, photo, or video broadcast. Review the preview, "
                "then confirm with `/go`; use `/cancelbc` to stop.\n\n"
                "Progress is updated in one status message instead of flooding chats. Blocked users "
                "and unreachable groups are skipped automatically.\n\n"
                "**Safety note:** broadcasts reach every started user and registered group."
            )
            return markdown, _plain_text(markdown), back_keyboard()

        if view == "add":
            markdown = (
                "## ➕ Add a character\n\n"
                "Run `/addcharacter` to start the guided flow. It collects the name, anime, image URL, "
                "rarity, and coin price, then creates a unique card ID.\n\n"
                "Send `/cancel` at any step to leave the flow."
            )
            return markdown, _plain_text(markdown), back_keyboard()

        if view == "startmsg":
            markdown = (
                "## ✏️ Start message\n\n"
                "Run `/setstartmsg` to replace the `/start` welcome caption. The current version "
                "keeps the configured intro video and inline buttons. Use `/cancel` to abort."
            )
            return markdown, _plain_text(markdown), back_keyboard()

        if view == "confirm-char":
            char = await db.get_character_by_id_any(str(item_id or ""))
            if not char:
                markdown = "## Character unavailable\n\nIt may already have been removed from the market."
                return markdown, _plain_text(markdown), back_keyboard()
            char_id = str(char["char_id"])
            markdown = (
                "## ⚠️ Remove this character?\n\n"
                f"**{_escape_markdown(char['name'])}** · `{char_id.replace('`', '')}`\n\n"
                "This removes it from the market. Existing collection copies are not deleted."
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 Confirm removal", callback_data=f"manage:confirm-char:{page}:{char_id}"),
                InlineKeyboardButton("Keep it", callback_data=f"manage:characters:{page}"),
            ]])
            return markdown, _plain_text(markdown), keyboard

        if view == "confirm-task":
            task = await db.get_task(int(item_id or 0))
            if not task:
                markdown = "## Task unavailable\n\nIt may already have been removed."
                return markdown, _plain_text(markdown), back_keyboard()
            task_id = int(task["task_id"])
            markdown = (
                "## ⚠️ Remove this task?\n\n"
                f"**Task #{task_id}** · {_escape_markdown(task.get('description', ''))}\n\n"
                "The task and its available reward entry will be removed."
            )
            keyboard = InlineKeyboardMarkup([[
                InlineKeyboardButton("🗑 Confirm removal", callback_data=f"manage:confirm-task:{task_id}"),
                InlineKeyboardButton("Keep it", callback_data="manage:tasks"),
            ]])
            return markdown, _plain_text(markdown), keyboard

        markdown = "## Management panel\n\nChoose an option from the home screen."
        return markdown, _plain_text(markdown), back_keyboard()

    async def manage_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not update.effective_user or update.effective_user.id != owner_id:
            await update.effective_message.reply_text("⛔ This control panel is owner-only.")
            return
        if not update.effective_chat or update.effective_chat.type != "private":
            await update.effective_message.reply_text("Open the bot in a private chat to use /manage.")
            return
        markdown, fallback, keyboard = await render("home")
        await send_rich_or_text_message(
            context.bot, update.effective_chat.id, markdown, fallback, keyboard
        )

    async def manage_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        if not query or not update.effective_user or update.effective_user.id != owner_id:
            if query:
                await query.answer("Owner-only control.", show_alert=True)
            return
        await query.answer()
        parts = query.data.split(":")
        action = parts[1] if len(parts) > 1 else "home"

        if action == "close":
            await edit_rich_or_text_message(query, "## Panel closed\n\nUse `/manage` to open it again.",
                                            "Panel closed. Use /manage to open it again.", None)
            return
        if action == "home":
            view, page, item_id = "home", 1, None
        elif action == "stats":
            view, page, item_id = "stats", 1, None
        elif action == "characters":
            if len(parts) > 2 and parts[2] == "noop":
                return
            view, page, item_id = "characters", int(parts[2]) if len(parts) > 2 else 1, None
        elif action == "tasks":
            view, page, item_id = "tasks", 1, None
        elif action == "broadcast":
            view, page, item_id = "broadcast", 1, None
        elif action == "add":
            view, page, item_id = "add", 1, None
        elif action == "startmsg":
            view, page, item_id = "startmsg", 1, None
        elif action == "remove-char":
            page = int(parts[2]) if len(parts) > 3 else 1
            item_id = ":".join(parts[3:]) if len(parts) > 3 else ":".join(parts[2:])
            view = "confirm-char"
        elif action == "confirm-char":
            page = int(parts[2]) if len(parts) > 3 else 1
            char_id = ":".join(parts[3:]) if len(parts) > 3 else ":".join(parts[2:])
            char = await db.get_character_by_id_any(char_id)
            if char:
                await db.remove_character(char_id)
            view, item_id = "characters", None
        elif action == "remove-task":
            view, page, item_id = "confirm-task", 1, parts[2] if len(parts) > 2 else "0"
        elif action == "confirm-task":
            task_id = int(parts[2]) if len(parts) > 2 else 0
            if await db.get_task(task_id):
                await db.remove_task(task_id)
            view, page, item_id = "tasks", 1, None
        else:
            view, page, item_id = "home", 1, None

        markdown, fallback, keyboard = await render(view, page, item_id)
        await edit_rich_or_text_message(query, markdown, fallback, keyboard)

    application.add_handler(CommandHandler("manage", manage_command))
    application.add_handler(CallbackQueryHandler(manage_callback, pattern=r"^manage:"))
