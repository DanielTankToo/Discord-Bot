"""
Guild Marketplace Bot
---------------------
A Discord bot that runs a gold-based marketplace for a WoW guild using a
button panel and pop-up forms (no slash commands needed by members).

Members click buttons on a pinned panel to:
  * Sell an Item        -> posts a "WTS" listing
  * Want to Buy         -> posts a "WTB" request
  * Crafting Request    -> posts a craft order and pings the profession role
  * Browse / Search     -> private list of open listings with jump links
  * My Listings         -> private list of your own open listings

Each listing has buttons to claim it, release it, mark it done, or remove it.
Gold and items change hands in-game; the bot only tracks listings.
"""

import asyncio
import os
import re
import sqlite3
from datetime import datetime, timezone

import discord
from discord.ext import commands
from dotenv import load_dotenv

# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------

load_dotenv()

TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
PANEL_CHANNEL_ID = int(os.getenv("PANEL_CHANNEL_ID", "0") or 0)
# Optional: post listings to a different channel. Defaults to the panel channel.
LISTINGS_CHANNEL_ID = int(os.getenv("LISTINGS_CHANNEL_ID", "0") or 0) or PANEL_CHANNEL_ID
# Optional: a channel for announcements, pings and trade updates, so the panel channel
# and the listings stay clean. Leave blank to post pings inside the listing itself.
ACTIVITY_CHANNEL_ID = int(os.getenv("ACTIVITY_CHANNEL_ID", "0") or 0)
# Optional: a channel where finished trades are moved to (a sales history).
COMPLETED_CHANNEL_ID = int(os.getenv("COMPLETED_CHANNEL_ID", "0") or 0)
DB_PATH = os.getenv("DB_PATH", "marketplace.db")

# Listing types
WTS, WTB, CRAFT = "WTS", "WTB", "CRAFT"

TYPE_INFO = {
    WTS: {"title": "For Sale", "color": discord.Color.green(), "owner": "Seller",
          "claim": "Buy", "claimer": "Buyer", "done": "Sold", "emoji": "💰"},
    WTB: {"title": "Wanted", "color": discord.Color.blue(), "owner": "Buyer",
          "claim": "I Have This", "claimer": "Seller", "done": "Filled", "emoji": "🔎"},
    CRAFT: {"title": "Crafting Order", "color": discord.Color.orange(), "owner": "Requested by",
            "claim": "I Can Craft This", "claimer": "Crafter", "done": "Crafted", "emoji": "🔨"},
}

# Profession names (Classic/Hardcore) and common shorthand members might type.
PROFESSIONS = {
    "alchemy": ["alch", "alchemist"],
    "blacksmithing": ["bs", "blacksmith", "smithing"],
    "enchanting": ["ench", "enchant", "enchanter"],
    "engineering": ["engi", "eng", "engineer"],
    "leatherworking": ["lw", "leather", "leatherworker"],
    "tailoring": ["tailor", "tail"],
    "cooking": ["cook"],
    "first aid": ["fa", "firstaid", "bandages"],
    "fishing": ["fish"],
    "mining": ["mine", "miner", "smelting"],
    "herbalism": ["herb", "herbs"],
    "skinning": ["skin", "skinner"],
}


def normalize_profession(text: str) -> str | None:
    """Turn what a member typed into a canonical profession name, if we can."""
    t = text.strip().lower()
    for name, aliases in PROFESSIONS.items():
        if t == name or t in aliases or t.replace(" ", "") == name.replace(" ", ""):
            return name
    return None


# --------------------------------------------------------------------------
# Database (SQLite file next to the bot -- survives restarts)
# --------------------------------------------------------------------------

db = sqlite3.connect(DB_PATH)
db.row_factory = sqlite3.Row
db.executescript(
    """
    CREATE TABLE IF NOT EXISTS listings (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        type        TEXT NOT NULL,
        guild_id    INTEGER NOT NULL,
        user_id     INTEGER NOT NULL,
        item        TEXT NOT NULL,
        price       TEXT,
        quantity    TEXT,
        notes       TEXT,
        profession  TEXT,
        status      TEXT NOT NULL DEFAULT 'open',   -- open | claimed | done | removed
        claimed_by  INTEGER,
        channel_id  INTEGER,
        message_id  INTEGER,
        created_at  TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """
)
# Upgrade older databases: remember the announcement message for each listing.
if "activity_message_id" not in [c[1] for c in db.execute("PRAGMA table_info(listings)")]:
    db.execute("ALTER TABLE listings ADD COLUMN activity_message_id INTEGER")
db.commit()


def get_listing(listing_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM listings WHERE id = ?", (listing_id,)).fetchone()


def update_listing(listing_id: int, **fields) -> None:
    cols = ", ".join(f"{k} = ?" for k in fields)
    db.execute(f"UPDATE listings SET {cols} WHERE id = ?", (*fields.values(), listing_id))
    db.commit()


def get_meta(key: str) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_meta(key: str, value: str) -> None:
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value))
    db.commit()


# --------------------------------------------------------------------------
# Display helpers
# --------------------------------------------------------------------------

def jump_url(row: sqlite3.Row) -> str:
    return f"https://discord.com/channels/{row['guild_id']}/{row['channel_id']}/{row['message_id']}"


def listing_embed(row: sqlite3.Row) -> discord.Embed:
    info = TYPE_INFO[row["type"]]
    status = row["status"]

    title = f"{info['emoji']} {info['title']}: {row['item']}"
    color = info["color"]
    if status == "done":
        title = f"✅ {info['done'].upper()}: {row['item']}"
        color = discord.Color.dark_grey()

    embed = discord.Embed(title=title, color=color, description=row["notes"] or None)

    if row["type"] == CRAFT and row["profession"]:
        embed.add_field(name="Profession", value=row["profession"].title())
    if row["price"]:
        label = {WTS: "Price", WTB: "Paying up to", CRAFT: "Tip offered"}[row["type"]]
        embed.add_field(name=label, value=row["price"])
    if row["quantity"]:
        embed.add_field(name="Quantity", value=row["quantity"])

    embed.add_field(name=info["owner"], value=f"<@{row['user_id']}>")

    if status == "claimed":
        embed.add_field(name="Status", value=f"🤝 Claimed by <@{row['claimed_by']}> — meet in-game", inline=False)
    elif status == "done":
        who = f" (with <@{row['claimed_by']}>)" if row["claimed_by"] else ""
        embed.add_field(name="Status", value=f"Closed{who}", inline=False)
    else:
        embed.add_field(name="Status", value="🟢 Open", inline=False)

    embed.set_footer(text=f"Listing #{row['id']}")
    embed.timestamp = datetime.fromisoformat(row["created_at"])
    return embed


def listing_view(row: sqlite3.Row) -> discord.ui.View | None:
    """Buttons shown under a listing, based on its current state."""
    if row["status"] in ("done", "removed"):
        return None
    info = TYPE_INFO[row["type"]]
    view = discord.ui.View(timeout=None)
    lid = row["id"]
    if row["status"] == "open":
        view.add_item(ListingButton("claim", lid, label=info["claim"], style=discord.ButtonStyle.success))
    else:
        view.add_item(ListingButton("unclaim", lid, label="Release", style=discord.ButtonStyle.secondary))
    view.add_item(ListingButton("done", lid, label=f"Mark {info['done']}", style=discord.ButtonStyle.primary))
    view.add_item(ListingButton("remove", lid, label="Remove", style=discord.ButtonStyle.danger))
    return view


def is_officer(member: discord.abc.User) -> bool:
    perms = getattr(member, "guild_permissions", None)
    return bool(perms and perms.manage_messages)


def format_lines(rows: list[sqlite3.Row], limit_chars: int = 1000) -> str:
    lines, total = [], 0
    for r in rows:
        extra = f" — {r['price']}" if r["price"] else ""
        prof = f" ({r['profession'].title()})" if r["type"] == CRAFT and r["profession"] else ""
        claimed = " 🤝" if r["status"] == "claimed" else ""
        line = f"• [{r['item']}]({jump_url(r)}){prof}{extra} — <@{r['user_id']}>{claimed}"
        if total + len(line) > limit_chars:
            lines.append("…and more")
            break
        lines.append(line)
        total += len(line) + 1
    return "\n".join(lines) or "_Nothing right now._"


def listings_overview(rows: list[sqlite3.Row], heading: str) -> discord.Embed:
    embed = discord.Embed(title=heading, color=discord.Color.gold())
    for t in (WTS, WTB, CRAFT):
        group = [r for r in rows if r["type"] == t]
        info = TYPE_INFO[t]
        embed.add_field(name=f"{info['emoji']} {info['title']} ({len(group)})",
                        value=format_lines(group), inline=False)
    embed.set_footer(text="🤝 = already claimed. Click an item to jump to it.")
    return embed


# --------------------------------------------------------------------------
# Posting listings and keeping the panel at the bottom
# --------------------------------------------------------------------------

panel_lock = asyncio.Lock()


def panel_embed() -> discord.Embed:
    embed = discord.Embed(
        title="🏪 Guild Marketplace",
        description=(
            "Trade with your guildmates — gold and items change hands in-game.\n\n"
            "💰 **Sell an Item** — list something for sale\n"
            "🔎 **Want to Buy** — post an item you're looking for\n"
            "🔨 **Crafting Request** — ask a crafter to make something\n"
            "📜 **Browse** / **Search** — see what's available\n"
            "📋 **My Listings** — find your own posts"
        ),
        color=discord.Color.gold(),
    )
    embed.set_footer(text="Stay safe out there. Deaths are forever.")
    return embed


async def ensure_forum_panel(bot: commands.Bot, forum: discord.ForumChannel) -> None:
    """In a forum, keep the panel as a pinned, locked post at the top."""
    thread = None
    tid = get_meta("panel_thread_id")
    if tid:
        try:
            thread = await bot.fetch_channel(int(tid))
        except (discord.NotFound, discord.Forbidden, discord.HTTPException):
            thread = None

    if isinstance(thread, discord.Thread):
        if thread.archived:  # forum posts go idle after a while; wake the panel back up
            try:
                await thread.edit(archived=False, locked=True)
            except discord.HTTPException:
                try:
                    await thread.edit(archived=False)
                except discord.HTTPException as e:
                    print(f"[!] Couldn't reopen the panel post: {e}")
        return

    try:
        created = await forum.create_thread(
            name="🏪 Marketplace — click here to buy, sell & craft",
            embed=panel_embed(), view=PanelView(), auto_archive_duration=10080)
    except discord.HTTPException as e:
        print(f"[!] Couldn't create the panel post in the forum: {e}\n"
              "    If the forum requires tags, turn that off, and check the bot can Create Posts.")
        return
    set_meta("panel_thread_id", str(created.thread.id))
    try:
        await created.thread.edit(pinned=True, locked=True)  # needs Manage Threads
    except discord.HTTPException:
        print("[!] Panel post created but couldn't pin/lock it. Give the bot 'Manage Threads' in the forum.")


async def refresh_panel(bot: commands.Bot, bump: bool = False) -> None:
    """Make sure the panel exists. If bump=True, move it to the bottom of the channel."""
    async with panel_lock:
        channel = bot.get_channel(PANEL_CHANNEL_ID)
        if channel is None:
            print(f"[!] Can't find panel channel {PANEL_CHANNEL_ID}. Check PANEL_CHANNEL_ID.")
            return

        if isinstance(channel, discord.ForumChannel):
            await ensure_forum_panel(bot, channel)
            return

        old_id = get_meta("panel_message_id")
        old_msg = None
        if old_id:
            try:
                old_msg = await channel.fetch_message(int(old_id))
            except (discord.NotFound, discord.Forbidden, discord.HTTPException):
                old_msg = None

        if old_msg and not bump:
            return  # panel already there; buttons keep working across restarts

        if old_msg:
            try:
                await old_msg.delete()
            except discord.HTTPException:
                pass

        msg = await channel.send(embed=panel_embed(), view=PanelView())
        set_meta("panel_message_id", str(msg.id))


# Forum tags the bot applies automatically if your forum has tags with these names.
TYPE_TAG_NAMES = {
    WTS: ["for sale", "wts", "selling", "sell"],
    WTB: ["wanted", "wtb", "buying", "buy"],
    CRAFT: ["crafting", "crafting order", "craft"],
}
DONE_TAG_NAMES = ["sold", "closed", "done", "completed", "filled", "crafted"]


def forum_tags(forum: discord.ForumChannel, names: list[str]) -> list[discord.ForumTag]:
    """Pick the forum's tags whose names match any of `names` (case-insensitive). Max 5."""
    wanted = {n.lower() for n in names}
    return [t for t in forum.available_tags if t.name.lower() in wanted][:5]


async def close_forum_post(thread: discord.Thread, delete: bool = False) -> None:
    """Tag a finished listing's forum post, then lock/archive it (or delete it)."""
    if delete:
        try:
            await thread.delete()
            return
        except discord.HTTPException:
            pass  # no Manage Threads permission -> just archive it below
    kwargs = {"archived": True}
    if isinstance(thread.parent, discord.ForumChannel) and not delete:
        done = forum_tags(thread.parent, DONE_TAG_NAMES)
        if done:
            kwargs["applied_tags"] = (done + [t for t in thread.applied_tags if t not in done])[:5]
    try:
        await thread.edit(locked=True, **kwargs)
    except discord.HTTPException:
        try:
            await thread.edit(**kwargs)  # locking needs Manage Threads; archive anyway
        except discord.HTTPException:
            pass


def in_forum_post(interaction: discord.Interaction) -> discord.Thread | None:
    ch = interaction.channel
    if isinstance(ch, discord.Thread) and isinstance(ch.parent, discord.ForumChannel):
        return ch
    return None


async def log_activity(bot: commands.Bot, text: str,
                       allowed: discord.AllowedMentions | None = None) -> discord.Message | None:
    """Post to the activity channel, if one is set. Returns the message if it was posted."""
    if not ACTIVITY_CHANNEL_ID:
        return None
    channel = bot.get_channel(ACTIVITY_CHANNEL_ID)
    if channel is None:
        print(f"[!] Can't find activity channel {ACTIVITY_CHANNEL_ID}. Check ACTIVITY_CHANNEL_ID.")
        return None
    try:
        return await channel.send(text, allowed_mentions=allowed or discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"[!] Couldn't post in the activity channel: {e}")
        return None


async def update_announcement(bot: commands.Bot, row: sqlite3.Row) -> None:
    """Rewrite a listing's 'New for sale' announcement to show it's sold/crafted/removed."""
    if not (ACTIVITY_CHANNEL_ID and row["activity_message_id"]):
        return
    channel = bot.get_channel(ACTIVITY_CHANNEL_ID)
    if channel is None:
        return
    info = TYPE_INFO[row["type"]]
    price_txt = f" — {row['price']}" if row["price"] else ""
    if row["status"] == "removed":
        text = f"🗑️ ~~{row['item']}{price_txt}~~ — **REMOVED** (by <@{row['user_id']}>)"
    else:
        partner = f" with <@{row['claimed_by']}>" if row["claimed_by"] else ""
        text = (f"✅ **{info['done'].upper()}:** {item_link(row)}{price_txt} — "
                f"<@{row['user_id']}>{partner}")
    try:
        msg = await channel.fetch_message(row["activity_message_id"])
        await msg.edit(content=text, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"[!] Couldn't update the announcement for listing #{row['id']}: {e}")


def item_link(row: sqlite3.Row) -> str:
    return f"[{row['item']}]({jump_url(row)})"


async def move_to_completed(bot: commands.Bot, row: sqlite3.Row) -> bool:
    """Copy a finished listing into the completed channel. Returns True if it was posted."""
    if not COMPLETED_CHANNEL_ID:
        return False
    channel = bot.get_channel(COMPLETED_CHANNEL_ID)
    if channel is None:
        print(f"[!] Can't find completed channel {COMPLETED_CHANNEL_ID}. Check COMPLETED_CHANNEL_ID.")
        return False
    embed = listing_embed(row)
    embed.add_field(name="Completed", value=f"<t:{int(datetime.now(timezone.utc).timestamp())}:f>",
                    inline=False)
    try:
        msg = await channel.send(embed=embed, allowed_mentions=discord.AllowedMentions.none())
    except discord.HTTPException as e:
        print(f"[!] Couldn't post in the completed channel: {e}")
        return False
    update_listing(row["id"], channel_id=channel.id, message_id=msg.id)
    return True


async def post_listing(interaction: discord.Interaction, ltype: str, item: str, price: str | None,
                       quantity: str | None, notes: str | None, profession: str | None = None) -> None:
    bot = interaction.client
    # Acknowledge right away (silently) so Discord doesn't time out while we post.
    await interaction.response.defer()

    channel = bot.get_channel(LISTINGS_CHANNEL_ID)
    if channel is None:
        await interaction.followup.send(
            "The listings channel isn't set up correctly. Ask an officer to check the bot config.",
            ephemeral=True)
        return

    cur = db.execute(
        "INSERT INTO listings (type, guild_id, user_id, item, price, quantity, notes, profession, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (ltype, interaction.guild_id, interaction.user.id, item, price or None, quantity or None,
         notes or None, profession, datetime.now(timezone.utc).isoformat()),
    )
    db.commit()
    row = get_listing(cur.lastrowid)

    # Ping the profession role for crafting orders, if a role with that name exists.
    content = None
    allowed = discord.AllowedMentions.none()
    role = None
    if ltype == CRAFT and profession and interaction.guild:
        role = discord.utils.find(lambda r: r.name.lower() == profession.lower(), interaction.guild.roles)
        if role and not ACTIVITY_CHANNEL_ID:
            content = f"{role.mention} — new crafting order!"
            allowed = discord.AllowedMentions(roles=[role])

    if isinstance(channel, discord.ForumChannel):
        # Each listing becomes its own forum post; trade talk happens inside it.
        info = TYPE_INFO[ltype]
        name = f"[{info['title']}] {item}" + (f" — {price}" if price else "")
        tags = forum_tags(channel, TYPE_TAG_NAMES[ltype] + ([profession] if profession else []))
        created = await channel.create_thread(
            name=name[:100], content=content, embed=listing_embed(row), view=listing_view(row),
            allowed_mentions=allowed, applied_tags=tags)
        msg = created.message
        update_listing(row["id"], channel_id=created.thread.id, message_id=msg.id)
    else:
        msg = await channel.send(content=content, embed=listing_embed(row), view=listing_view(row),
                                 allowed_mentions=allowed)
        update_listing(row["id"], channel_id=channel.id, message_id=msg.id)

    row = get_listing(row["id"])
    info = TYPE_INFO[ltype]
    price_txt = f" — {row['price']}" if row["price"] else ""
    ping = f"{role.mention} " if role else ""
    announcement = await log_activity(
        bot,
        f"{ping}{info['emoji']} **New {info['title'].lower()}:** {item_link(row)}{price_txt} "
        f"by <@{row['user_id']}>",
        discord.AllowedMentions(roles=[role]) if role else None,
    )
    if announcement:
        update_listing(row["id"], activity_message_id=announcement.id)

    # Confirm to the poster by DM, so nothing shows up in the marketplace channel.
    info = TYPE_INFO[ltype]
    try:
        await interaction.user.send(f"{info['emoji']} Your listing **{item}** is posted: {msg.jump_url}")
    except discord.HTTPException:
        # DMs closed: fall back to a private "only you can see this" message.
        await interaction.followup.send(f"Posted! {msg.jump_url}", ephemeral=True)

    # Keep the panel as the last message so it's always easy to find.
    # (In a forum, this instead makes sure the pinned panel post is still open.)
    if LISTINGS_CHANNEL_ID == PANEL_CHANNEL_ID or isinstance(bot.get_channel(PANEL_CHANNEL_ID), discord.ForumChannel):
        await refresh_panel(bot, bump=not isinstance(channel, discord.ForumChannel))


# --------------------------------------------------------------------------
# Error reporting -- shows problems to the clicker and in the terminal
# --------------------------------------------------------------------------

import traceback


async def report_error(interaction: discord.Interaction, error: Exception) -> None:
    print(f"[!] Error handling a click from {interaction.user}:")
    traceback.print_exception(type(error), error, error.__traceback__)
    text = f"Something went wrong: `{type(error).__name__}: {error}`"[:1900]
    try:
        if interaction.response.is_done():
            await interaction.followup.send(text, ephemeral=True)
        else:
            await interaction.response.send_message(text, ephemeral=True)
    except discord.HTTPException:
        pass


class MarketModal(discord.ui.Modal):
    async def on_error(self, interaction: discord.Interaction, error: Exception) -> None:
        await report_error(interaction, error)


# --------------------------------------------------------------------------
# Pop-up forms (modals)
# --------------------------------------------------------------------------

class SellModal(MarketModal, title="Sell an Item"):
    item = discord.ui.TextInput(label="Item", placeholder="e.g. Lifestone, Black Lotus", max_length=100)
    price = discord.ui.TextInput(label="Price (gold)", placeholder="e.g. 25g or 1g 50s", max_length=30)
    quantity = discord.ui.TextInput(label="Quantity", required=False, default="1", max_length=20)
    notes = discord.ui.TextInput(label="Notes", style=discord.TextStyle.paragraph, required=False,
                                 placeholder="Stats, when you're online, open to offers, etc.",
                                 max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        await post_listing(interaction, WTS, self.item.value.strip(), self.price.value.strip(),
                           self.quantity.value.strip(), self.notes.value.strip())


class BuyModal(MarketModal, title="Want to Buy"):
    item = discord.ui.TextInput(label="Item you want", max_length=100)
    price = discord.ui.TextInput(label="Paying up to (gold)", required=False,
                                 placeholder="Leave blank if open to offers", max_length=30)
    quantity = discord.ui.TextInput(label="Quantity", required=False, default="1", max_length=20)
    notes = discord.ui.TextInput(label="Notes", style=discord.TextStyle.paragraph, required=False,
                                 max_length=500)

    async def on_submit(self, interaction: discord.Interaction):
        await post_listing(interaction, WTB, self.item.value.strip(), self.price.value.strip(),
                           self.quantity.value.strip(), self.notes.value.strip())


class CraftModal(MarketModal, title="Crafting Request"):
    profession = discord.ui.TextInput(label="Profession", placeholder="e.g. Blacksmithing, Tailoring, LW",
                                      max_length=30)
    item = discord.ui.TextInput(label="What do you want crafted?", max_length=100)
    materials = discord.ui.TextInput(label="Materials", required=False, max_length=200,
                                     placeholder="e.g. I have all mats / need the crafter to supply")
    price = discord.ui.TextInput(label="Tip offered (gold)", required=False, max_length=30)
    notes = discord.ui.TextInput(label="Notes", style=discord.TextStyle.paragraph, required=False,
                                 max_length=400)

    async def on_submit(self, interaction: discord.Interaction):
        prof = normalize_profession(self.profession.value) or self.profession.value.strip().lower()
        notes = "\n".join(filter(None, [
            f"**Materials:** {self.materials.value.strip()}" if self.materials.value.strip() else "",
            self.notes.value.strip(),
        ]))
        await post_listing(interaction, CRAFT, self.item.value.strip(), self.price.value.strip(),
                           None, notes, profession=prof)


class SearchModal(MarketModal, title="Search the Marketplace"):
    query = discord.ui.TextInput(label="Item or keyword", max_length=50)

    async def on_submit(self, interaction: discord.Interaction):
        q = f"%{self.query.value.strip()}%"
        rows = db.execute(
            "SELECT * FROM listings WHERE status IN ('open', 'claimed') AND guild_id = ?"
            " AND (item LIKE ? OR notes LIKE ? OR profession LIKE ?) ORDER BY id DESC LIMIT 60",
            (interaction.guild_id, q, q, q),
        ).fetchall()
        await interaction.response.send_message(
            embed=listings_overview(rows, f"Results for “{self.query.value.strip()}”"), ephemeral=True)


# --------------------------------------------------------------------------
# The marketplace panel (persistent buttons)
# --------------------------------------------------------------------------

class PanelView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    async def on_error(self, interaction: discord.Interaction, error: Exception, item) -> None:
        await report_error(interaction, error)

    @discord.ui.button(label="Sell an Item", emoji="💰", style=discord.ButtonStyle.success,
                       custom_id="panel:sell", row=0)
    async def sell(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SellModal())

    @discord.ui.button(label="Want to Buy", emoji="🔎", style=discord.ButtonStyle.primary,
                       custom_id="panel:wtb", row=0)
    async def wtb(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(BuyModal())

    @discord.ui.button(label="Crafting Request", emoji="🔨", style=discord.ButtonStyle.primary,
                       custom_id="panel:craft", row=0)
    async def craft(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(CraftModal())

    @discord.ui.button(label="Browse", emoji="📜", style=discord.ButtonStyle.secondary,
                       custom_id="panel:browse", row=1)
    async def browse(self, interaction: discord.Interaction, _):
        rows = db.execute(
            "SELECT * FROM listings WHERE status IN ('open', 'claimed') AND guild_id = ?"
            " ORDER BY id DESC LIMIT 90",
            (interaction.guild_id,),
        ).fetchall()
        await interaction.response.send_message(embed=listings_overview(rows, "Marketplace Listings"),
                                                ephemeral=True)

    @discord.ui.button(label="Search", emoji="🔍", style=discord.ButtonStyle.secondary,
                       custom_id="panel:search", row=1)
    async def search(self, interaction: discord.Interaction, _):
        await interaction.response.send_modal(SearchModal())

    @discord.ui.button(label="My Listings", emoji="📋", style=discord.ButtonStyle.secondary,
                       custom_id="panel:mine", row=1)
    async def mine(self, interaction: discord.Interaction, _):
        rows = db.execute(
            "SELECT * FROM listings WHERE status IN ('open', 'claimed') AND guild_id = ?"
            " AND (user_id = ? OR claimed_by = ?) ORDER BY id DESC LIMIT 60",
            (interaction.guild_id, interaction.user.id, interaction.user.id),
        ).fetchall()
        embed = listings_overview(rows, "Your Listings & Claims")
        embed.description = "Use the buttons on each listing to release, close, or remove it."
        await interaction.response.send_message(embed=embed, ephemeral=True)


# --------------------------------------------------------------------------
# Buttons on each listing (work even after the bot restarts)
# --------------------------------------------------------------------------

class ListingButton(discord.ui.DynamicItem[discord.ui.Button],
                    template=r"listing:(?P<action>[a-z]+):(?P<id>[0-9]+)"):
    def __init__(self, action: str, listing_id: int, *, label: str = "…",
                 style: discord.ButtonStyle = discord.ButtonStyle.secondary):
        super().__init__(discord.ui.Button(label=label, style=style,
                                           custom_id=f"listing:{action}:{listing_id}"))
        self.action = action
        self.listing_id = listing_id

    @classmethod
    async def from_custom_id(cls, interaction, item, match):
        return cls(match["action"], int(match["id"]))

    async def callback(self, interaction: discord.Interaction):
        try:
            await self.handle(interaction)
        except Exception as error:
            await report_error(interaction, error)

    async def handle(self, interaction: discord.Interaction):
        row = get_listing(self.listing_id)
        if row is None or row["status"] in ("done", "removed"):
            await interaction.response.send_message("This listing is already closed.", ephemeral=True)
            return

        user = interaction.user
        is_owner = user.id == row["user_id"]
        info = TYPE_INFO[row["type"]]

        if self.action == "claim":
            if is_owner:
                await interaction.response.send_message("You can't claim your own listing.", ephemeral=True)
                return
            if row["status"] != "open":
                await interaction.response.send_message("Someone already claimed this one.", ephemeral=True)
                return
            update_listing(row["id"], status="claimed", claimed_by=user.id)
            row = get_listing(row["id"])
            await interaction.response.edit_message(embed=listing_embed(row), view=listing_view(row))
            # Tell the poster privately by DM, so no channel gets cluttered.
            dm_sent = False
            try:
                owner = interaction.client.get_user(row["user_id"]) or \
                    await interaction.client.fetch_user(row["user_id"])
                await owner.send(
                    f"🤝 **{user.display_name}** ({info['claimer'].lower()}) is interested in your listing "
                    f"{item_link(row)}. Whisper them in-game to trade!")
                dm_sent = True
            except discord.HTTPException:
                pass  # the poster has DMs from server members turned off

            if dm_sent:
                await interaction.followup.send(
                    f"Claimed! <@{row['user_id']}> got a DM. Whisper them in-game to trade.", ephemeral=True)
            else:
                # Fallback: ping the poster inside the listing itself (never in the activity channel).
                await interaction.followup.send(
                    f"<@{row['user_id']}> — {user.mention} is interested in **{row['item']}**. "
                    f"Whisper each other in-game to trade!",
                    allowed_mentions=discord.AllowedMentions(users=True))

        elif self.action == "unclaim":
            if not (is_owner or user.id == row["claimed_by"] or is_officer(user)):
                await interaction.response.send_message(
                    "Only the poster or the person who claimed it can release it.", ephemeral=True)
                return
            update_listing(row["id"], status="open", claimed_by=None)
            row = get_listing(row["id"])
            await interaction.response.edit_message(embed=listing_embed(row), view=listing_view(row))

        elif self.action == "done":
            # For crafting orders, the crafter who claimed it can also mark it crafted.
            is_crafter = row["type"] == CRAFT and user.id == row["claimed_by"]
            if not (is_owner or is_crafter or is_officer(user)):
                who = "the requester or the crafter" if row["type"] == CRAFT else "the poster"
                await interaction.response.send_message(
                    f"Only {who} can mark this {info['done'].lower()}.", ephemeral=True)
                return
            update_listing(row["id"], status="done")
            row = get_listing(row["id"])
            await interaction.response.edit_message(content=None, embed=listing_embed(row), view=None)

            moved = await move_to_completed(interaction.client, row)
            if moved:
                row = get_listing(row["id"])  # now points at the completed-channel copy
            await update_announcement(interaction.client, row)

            thread = in_forum_post(interaction)
            if thread:
                await close_forum_post(thread, delete=moved)
            elif moved:
                try:
                    await interaction.message.delete()
                except discord.HTTPException:
                    pass

        elif self.action == "remove":
            if not (is_owner or is_officer(user)):
                await interaction.response.send_message("Only the poster can remove this.", ephemeral=True)
                return
            update_listing(row["id"], status="removed")
            await interaction.response.send_message("Listing removed.", ephemeral=True)
            await update_announcement(interaction.client, get_listing(row["id"]))
            thread = in_forum_post(interaction)
            if thread:
                await close_forum_post(thread, delete=True)
                return
            try:
                await interaction.message.delete()
            except discord.HTTPException:
                pass


# --------------------------------------------------------------------------
# Bot startup
# --------------------------------------------------------------------------

class MarketplaceBot(commands.Bot):
    def __init__(self):
        intents = discord.Intents.default()  # no privileged intents needed
        super().__init__(command_prefix=commands.when_mentioned, intents=intents)
        self._panel_ready = False

    async def setup_hook(self):
        # Register buttons so they keep working after a restart.
        self.add_view(PanelView())
        self.add_dynamic_items(ListingButton)

    async def on_ready(self):
        print(f"Logged in as {self.user} (id {self.user.id})")
        if not self._panel_ready:
            self._panel_ready = True
            await refresh_panel(self)
            print("Marketplace panel is ready.")


def main():
    if not TOKEN:
        raise SystemExit("Missing DISCORD_TOKEN. Copy .env.example to .env and fill it in.")
    if not PANEL_CHANNEL_ID:
        raise SystemExit("Missing PANEL_CHANNEL_ID. Put your #marketplace channel ID in .env.")
    MarketplaceBot().run(TOKEN)


if __name__ == "__main__":
    main()
