# Guild Market — WoW Hardcore Guild Marketplace Bot

A Discord bot that runs a gold-based marketplace for a World of Warcraft
hardcore guild. Members use a **button panel and pop-up forms**, so there are no
commands to type. Gold and items change hands in-game; the bot keeps track of
listings, notifies people, and records completed trades.

Built in Python with discord.py. It runs on your own PC, with no paid hosting.

---

## How it works

### Channel layout

| Channel | Type | What goes there |
|---|---|---|
| **Marketplace** (panel) | Text | Only the button panel. Nothing else is posted here. |
| **Marketplace forum** (listings) | Forum | One forum post per open listing. Finished listings are removed. |
| **Market listings** (activity) | Text | Only the "New for sale / New wanted / New crafting order" announcements, which update to SOLD, FILLED, CRAFTED, or REMOVED when finished. |
| **Completed** | Text | A permanent record of every finished trade. |

### The button panel

| Button | What it does |
|---|---|
| 💰 **Sell an Item** | Pick a category from a drop-down (Weapon, Cloth/Leather/Mail/Plate Armor, Material, Recipe, Consumable), then a form asks for item, price, quantity, notes. Creates a "For Sale" listing showing the category. |
| 🔎 **Want to Buy** | Form: item, max price, quantity, notes. Creates a "Wanted" listing. |
| 🔨 **Crafting Request** | Pick a profession from a drop-down (only you see it, and it disappears once you post), then a form asks for item, materials, tip, notes. Creates a "Crafting Order" forum post that pings everyone with that profession's role. The ping goes away with the post. |
| 📜 **Browse** | Private list of all open listings with jump links. |
| 🔍 **Search** | Private search by item name, notes, profession, or category (e.g. "plate"). |
| 📋 **My Listings** | Private list of your own listings and claims. |

### Buttons on each listing

| Button | Who can use it | What happens |
|---|---|---|
| **Buy / I Have This / I Can Craft This** | Anyone except the poster | Claims the listing. The poster gets a DM saying who's interested. |
| **Release** | Poster, claimer, or officer | Un-claims it and reopens the listing. |
| **Mark Sold / Filled / Crafted** | Poster or officer (for crafts, also the crafter who claimed it) | Posts a record to the completed channel, deletes the forum post, and updates the announcement to ✅ SOLD/FILLED/CRAFTED. |
| **Remove** | Poster or officer | Deletes the forum post and updates the announcement to 🗑️ REMOVED. |

If an officer deletes a listing's forum post by hand, the bot treats it as removed and updates the announcement.

"Officer" means anyone with the **Manage Messages** permission.

### Listings expire automatically

A listing that nobody has claimed closes by itself after **2 days** (change this with
`LISTING_EXPIRY_DAYS` in `.env`). Each open listing shows when it will expire. When it
expires, the bot deletes the forum post, updates the announcement to ⌛ EXPIRED, and
DMs the poster so they can repost it. Claimed listings never expire, since a trade is
in progress. The bot checks every 15 minutes while it's running.

### Private notifications (DMs)

- **After posting a listing:** the poster gets a DM with a link to their post.
- **When a listing expires:** the poster gets a DM saying it expired and can be reposted.
- **When someone claims a listing:** the poster gets a DM saying who's interested. The claimer sees a private "Claimed!" confirmation.
- **If someone has DMs from server members turned off:** they get a private "only you can see this" message instead (or, for claims, a ping inside their forum post).

---

## Files

| File | What it is |
|---|---|
| `bot.py` | The bot. |
| `requirements.txt` | Python libraries to install. |
| `.env` | Your settings and secret token. **Never share or upload this.** |
| `marketplace.db` | Created automatically. Stores all listings and history. **Back this up.** |

---

## Settings (`.env`)

Create a file named exactly `.env` (not `.env.txt`) in the bot folder. To make one
from the terminal, run `notepad .env`.

```
DISCORD_TOKEN=your-bot-token
PANEL_CHANNEL_ID=marketplace-text-channel-id
LISTINGS_CHANNEL_ID=marketplace-forum-id
ACTIVITY_CHANNEL_ID=market-listings-text-channel-id
COMPLETED_CHANNEL_ID=completed-text-channel-id
LISTING_EXPIRY_DAYS=2
```

| Setting | Required? | What it does |
|---|---|---|
| `DISCORD_TOKEN` | Yes | The bot's password. Find it in the Developer Portal → your app → **Bot** → **Reset Token** → **Copy**. |
| `PANEL_CHANNEL_ID` | Yes | Where the button panel lives. If this is a forum, the panel becomes a pinned, locked post. |
| `LISTINGS_CHANNEL_ID` | No | Where listings go. A forum makes one post per listing. If left blank, listings go in the panel channel, and the panel reposts itself at the bottom. |
| `ACTIVITY_CHANNEL_ID` | No | Where new-listing announcements go. |
| `COMPLETED_CHANNEL_ID` | No | Where finished trades are recorded. If left blank, finished forum posts are locked and archived instead of deleted. |
| `LISTING_EXPIRY_DAYS` | No | Days before an unclaimed listing expires. Defaults to `2`. Set to `0` to turn expiry off. |

To get a channel ID: in Discord, go to **User Settings → Advanced → Developer Mode**
and turn it on. Then right-click a channel and choose **Copy Channel ID**.

No spaces or quotes go around the values.

---

## First-time setup

### 1. Create the bot in Discord
1. Go to <https://discord.com/developers/applications> → **New Application**.
2. **Bot** tab → **Reset Token** → **Copy**. Put this in `.env`.
   Leave **Requires OAuth2 Code Grant** off.
3. **General Information** → make sure **Interactions Endpoint URL** is **empty**.
4. **Installation** tab:
   - Installation Contexts: **Guild Install** ticked
   - Install Link: **Discord Provided Link**
   - Default Install Settings → Guild Install → Scopes: **bot**
   - Permissions: **View Channels, Send Messages, Embed Links, Read Message
     History, Mention Everyone, Manage Threads, Create Public Threads,
     Send Messages in Threads**
   - **Save Changes**, open the install link, pick your server, and click **Authorize**.

### 2. Set up the server
1. Create the channels from the table above.
2. **Forum settings:**
   - **Tags (optional):** add `For Sale`, `Wanted`, `Crafting`, `Sold`, profession
     names like `Tailoring`, and categories like `Weapon`, `Plate Armor` or `Recipe`.
     The bot applies matching tags automatically (up to 5 per post), so members can
     filter the forum by category.
   - Leave **"Require people to select tags"** off.
3. **Profession roles:** create roles named `Alchemy`, `Blacksmithing`,
   `Enchanting`, `Engineering`, `Leatherworking`, `Tailoring`, `Cooking`, and
   `First Aid`, and give them to your crafters. When someone picks a profession in the
   Crafting Request drop-down, the bot pings that role, which notifies everyone who has it.
   Role names like `Blacksmith`, `BS` or `⚒️ Blacksmithing` also match.
   For the ping to go through, the bot needs **Mention All Roles** in the listings forum
   (or turn on **Allow anyone to @mention this role** in each role's settings).
4. **Permissions:** in **each** of the channels, go to **Edit Channel →
   Permissions**, add the **Guild Market** role, and allow:

   | Channel | Bot needs |
   |---|---|
   | Panel | View Channel, Send Messages, Embed Links, Read Message History |
   | Forum | View Channel, Create Posts, Send Messages in Posts, Embed Links, Read Message History, **Manage Threads**, **Mention All Roles** |
   | Activity | View Channel, Send Messages, Read Message History |
   | Completed | View Channel, Send Messages, Embed Links, Read Message History |

5. **Keeping channels clean (recommended):** for @everyone, turn off **Send Messages**
   in the panel, activity, and completed channels, and **Create Posts** in the forum.
   Buttons still work for everyone.

### 3. Install and run on your PC
1. Install **Python 3.10+** from <https://www.python.org/downloads/>
   (tick **Add Python to PATH**).
2. Open the bot folder, click the address bar, type `cmd`, and press Enter.
3. Install the libraries:
   ```
   pip install -r requirements.txt
   ```
4. Create `.env` (see **Settings** above).
5. Start the bot:
   ```
   python bot.py
   ```
   You should see `Logged in as Guild Market#...` and `Marketplace panel is ready.`

---

## Day-to-day use

- **Start:** open a terminal in the bot folder and run `python bot.py`.
- **Stop:** click the terminal window and press **Ctrl+C**, or close the window.
- **Restart after changing `bot.py` or `.env`:** press **Ctrl+C**, then press the **Up arrow** and **Enter**.
- The bot is only online while that window is open. Listings are saved in
  `marketplace.db`, so nothing is lost on restart and all buttons keep working.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `Missing DISCORD_TOKEN` | `.env` is missing or saved as `.env.txt`. Run `ren .env.txt .env`. |
| `Could not open requirements file` | The terminal isn't in the bot folder. Open it from the folder's address bar. |
| `python` not recognized | Use `py bot.py` instead. |
| "This interaction failed" | The bot isn't running. Start it. |
| "Didn't respond in time" | Clear **Interactions Endpoint URL** in the Developer Portal, then restart the bot. |
| `403 Forbidden (50001): Missing Access` | The bot can't see a channel. Add the Guild Market role to that channel's permissions (see the permissions table). Check the category too if it's private. |
| `403 Forbidden (50013): Missing Permissions` | The bot can see the channel but is missing a permission from the table above. |
| `'ForumChannel' object has no attribute ...` | You're running an old `bot.py`. Replace it with the latest. |
| Forum posts aren't deleted when sold | The bot needs **Manage Threads** in the forum, and access to the completed channel. |
| Profession role isn't pinged | Check the terminal for a `[!]` line. Either no role matches the profession name, or the bot needs **Mention All Roles** in the listings forum. Members also need to be able to see the forum to get notified. |
| Old listings disappeared right after updating | Expected: unclaimed listings older than 2 days expire on the first check. Set `LISTING_EXPIRY_DAYS=0` to turn expiry off. |
| The bot posts a `[!]` line in the terminal | It's a warning that says what's wrong, usually a channel ID or permission. |

---

## Moving to an always-on host later

Copy the whole folder, including `.env` and `marketplace.db`, to the new machine
(an old laptop, a Raspberry Pi, or a small cloud server). Install Python, run
`pip install -r requirements.txt`, then run `python bot.py`. No code changes are needed.

---

## Ideas for later

- [x] Drop-down menu to pick the profession when submitting a crafting order
- [x] Listings that expire automatically after X days
- [ ] Auctions with timed bidding
- [ ] Trade reputation, so members can rate completed trades
- [ ] Ping actual crafters from the guild roster tool instead of Discord roles
- [ ] Always-on hosting
- [ ] Optionally drop "New wanted" announcements from the activity channel
