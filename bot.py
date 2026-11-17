import discord
import asyncio
import random
import re
import os
import sys
import json
import socket
import datetime
import urllib.request
import urllib.parse
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
from collections import deque

# Lightweight HTTP Health Check for 24/7 Cloud Hosting (Render / Koyeb)
class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(b"MoonSanctum Core Bot is Online 24/7!")

    def log_message(self, format, *args):
        pass

if os.getenv("PORT"):
    def run_health():
        port = int(os.getenv("PORT", "8080"))
        server = HTTPServer(("0.0.0.0", port), HealthHandler)
        print(f"Cloud health server listening on port {port}")
        server.serve_forever()
    t = threading.Thread(target=run_health, daemon=True)
    t.start()

# Sliding Context Window Memory: keeps the last 6 messages per channel
# Automatically drops old messages as new ones arrive so memory stays fresh!
CHAT_HISTORY = {}

# Bulletproof Single-Instance Lock via Localhost Port
# Only ONE instance can ever run at a time!
SERVER_SOCKET = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
try:
    SERVER_SOCKET.bind(("127.0.0.1", 49832))
    SERVER_SOCKET.listen(1)
except OSError:
    print("FATAL: Another instance of MoonSanctum bot is already running! Exiting immediately.")
    sys.exit(0)

# Load local .env if present
env_file = os.path.join(os.path.dirname(__file__), ".env")
if os.path.exists(env_file):
    try:
        with open(env_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if "=" in line and not line.startswith("#"):
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except Exception as e:
        print(f"Error loading .env: {e}")

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")

if not TOKEN:
    print("FATAL: DISCORD_BOT_TOKEN environment variable is not set!")
    sys.exit(1)

# Initialize Gemini AI client
ai_client = None
if GEMINI_KEY:
    try:
        from google import genai
        ai_client = genai.Client(api_key=GEMINI_KEY)
        print("=== Google Gemini AI Intelligence is ENABLED! ===")
    except Exception as e:
        print(f"Gemini init error: {e}")

# Load live scraped ores from theforge.gg/database/ores
LIVE_ORES = []
try:
    ores_path = os.path.join(os.path.dirname(__file__), "theforge_live_ores.json")
    if os.path.exists(ores_path):
        with open(ores_path, "r", encoding="utf-8") as f:
            LIVE_ORES = json.load(f)
        print(f"Loaded {len(LIVE_ORES)} live ores from theforge.gg/database/ores")
except Exception as e:
    print(f"Error loading live ores: {e}")

# Load optimizer traits from theforge.gg/optimizer
OPTIMIZER_TRAITS = []
try:
    traits_path = os.path.join(os.path.dirname(__file__), "theforge_optimizer_traits.json")
    if os.path.exists(traits_path):
        with open(traits_path, "r", encoding="utf-8") as f:
            OPTIMIZER_TRAITS = json.load(f)
        print(f"Loaded {len(OPTIMIZER_TRAITS)} optimizer trait entries from theforge.gg/optimizer")
except Exception as e:
    print(f"Error loading optimizer traits: {e}")

# Load complete weapons database from theforge.gg/database/weapons
DATABASE_WEAPONS = []
try:
    weapons_path = os.path.join(os.path.dirname(__file__), "theforge_database_weapons.json")
    if os.path.exists(weapons_path):
        with open(weapons_path, "r", encoding="utf-8") as f:
            DATABASE_WEAPONS = json.load(f)
        print(f"Loaded {len(DATABASE_WEAPONS)} weapon stats from theforge.gg/database/weapons")
except Exception as e:
    print(f"Error loading weapons database: {e}")

# Load complete armor database from theforge.gg/database/armor
DATABASE_ARMOR = []
try:
    armor_path = os.path.join(os.path.dirname(__file__), "theforge_database_armor.json")
    if os.path.exists(armor_path):
        with open(armor_path, "r", encoding="utf-8") as f:
            DATABASE_ARMOR = json.load(f)
        print(f"Loaded {len(DATABASE_ARMOR)} armor pieces from theforge.gg/database/armor")
except Exception as e:
    print(f"Error loading armor database: {e}")

# Load complete armor sets from theforge.gg/armor-sets
ARMOR_SETS = []
try:
    sets_path = os.path.join(os.path.dirname(__file__), "theforge_armor_sets.json")
    if os.path.exists(sets_path):
        with open(sets_path, "r", encoding="utf-8") as f:
            ARMOR_SETS = json.load(f)
        print(f"Loaded {len(ARMOR_SETS)} armor sets from theforge.gg/armor-sets")
except Exception as e:
    print(f"Error loading armor sets: {e}")

def find_relevant_data(user_text):
    text_lower = user_text.lower()
    matches = []
    
    # 1. Check weapon database (DPS, Damage, Speed, Range, Chance)
    for w in DATABASE_WEAPONS:
        pattern = r"\b" + re.escape(w["name"].lower()) + r"\b"
        if re.search(pattern, text_lower):
            matches.append(
                f"- Weapon: {w['name']} ({w['class']}) -> Damage: {w['damage']}, DPS: {w['dps']}, Speed: {w['speed']}, Range: {w['range']} studs, Chance: {w['chance']}"
            )
            
    # Check for DPS rankings
    if any(k in text_lower for k in ["highest dps", "best dps", "top dps", "highest damage"]):
        top3 = [f"{w['name']} ({w['dps']} DPS, {w['damage']} DMG)" for w in DATABASE_WEAPONS[:3]]
        matches.append(f"- Top DPS Weapons: {', '.join(top3)}")

    # 2. Check armor sets (Ability, Piece stats, Weapon affinity)
    for s in ARMOR_SETS:
        pattern = r"\b" + re.escape(s["name"].lower()) + r"\b"
        clean_name = s["name"].lower().replace(" set", "")
        if re.search(pattern, text_lower) or (len(clean_name) > 4 and clean_name in text_lower):
            pieces_str = ", ".join(s.get("per_piece_stats", []))
            ability_str = f"Ability '{s['ability_name']}': {s['ability_desc']}" if s.get("ability_name") != "None" else "No set ability"
            matches.append(
                f"- Set: {s['name']} ({s['class']}) -> Per piece: [{pieces_str}] | {ability_str}"
            )

    # 3. Check individual armor database (Health Bonus, Weight, Set, Chance)
    for a in DATABASE_ARMOR:
        pattern = r"\b" + re.escape(a["name"].lower()) + r"\b"
        if re.search(pattern, text_lower):
            matches.append(
                f"- Armor: {a['name']} ({a['slot']}) -> Health: {a['health_bonus']}, Weight: {a['weight']}, Set: '{a['set']}', Chance: {a['chance']}"
            )
            
    # Check for highest health / tankiest armor
    if any(k in text_lower for k in ["highest health", "best armor", "highest defense", "tankiest", "best defense"]):
        top3_armor = [f"{a['name']} ({a['health_bonus']} Health)" for a in sorted(DATABASE_ARMOR, key=lambda x: x.get('health_val', 0), reverse=True)[:3]]
        matches.append(f"- Top Health Armor Pieces: {', '.join(top3_armor)}")

    # 4. Check ore specific traits
    for item in OPTIMIZER_TRAITS:
        pattern = r"\b" + re.escape(item["name"].lower()) + r"\b"
        if re.search(pattern, text_lower):
            w_str = ", ".join(item.get("weapon_traits", [])) if item.get("weapon_traits") else "None"
            a_str = ", ".join(item.get("armor_traits", [])) if item.get("armor_traits") else "None"
            matches.append(f"- Ore: {item['name']} ({item['rarity']} {item['multiplier']}x): Weapons: [{w_str}] | Armor: [{a_str}]")

    # 5. Check live ore locations
    for ore in LIVE_ORES:
        pattern = r"\b" + re.escape(ore["name"].lower()) + r"\b"
        if re.search(pattern, text_lower) and not any(ore["name"] in m for m in matches):
            matches.append(f"- {ore['name']} ({ore['rarity']}): Location '{ore['location']}', Mult: {ore['multiplier']}, Price: {ore['price']}")

    return "\n".join(matches[:3]) if matches else ""

def live_web_search(query: str, max_results: int = 3):
    """Searches the live web via DuckDuckGo with smart domain targeting."""
    forge_keywords = ["forge", "ore", "ores", "sword", "weapon", "armor", "dps", "damage", "mold", "bismuth", "boss", "raid", "drop"]
    query_lower = query.lower()
    
    # Prepend Roblox The Forge only if gaming/crafting is implied
    if any(k in query_lower for k in forge_keywords):
        search_q = f"Roblox The Forge {query}"
    else:
        # General open web queries (real world facts, news, calendar, dates, general topics)
        search_q = query

    url = f"https://html.duckduckgo.com/html/?q={urllib.parse.quote(search_q)}"
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
    )
    try:
        html = urllib.request.urlopen(req, timeout=5).read().decode('utf-8', errors='ignore')
        snippets = re.findall(r'<a class="result__snippet[^>]*>(.*?)</a>', html, re.DOTALL)
        clean = []
        for s in snippets[:max_results]:
            text = re.sub(r'<[^>]+>', '', s).strip()
            text = text.replace("&#x27;", "'").replace("&quot;", '"').replace("&amp;", '&')
            if text and len(text) > 15:
                clean.append(text)
        return clean
    except Exception as e:
        print(f"Web search error: {e}")
        return []

# Permanent Discord CDN Hosted Avatars
NPCS = {
    "schnee": {
        "name": "Schnee Raizar",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572079606251397230/schnee.jpg?ex=6afd10b9&is=6afbbf39&hm=9a0c684c9d0a567cd8087f1d1ae1d17d87621815df3c14c3191f48f86f666f08&",
        "style": (
            "You are Schnee Raizar from The New Gate, devoted companion to Master Vrax and chief strategist of Moon Sanctum. "
            "Tone & Personality: Graceful, wise, loyal, composed, authoritative on tactics and equipment. "
            "CRITICAL RULES: "
            "1. If a guild member asks about another person (e.g. @Zyee, @seiko), refer strictly to THAT SPECIFIC PERSON by name. Never confuse them with or call them Xerox! "
            "2. If Master Vrax or a member asks you to check the web, search for information, or ask for the current date or real-world facts, gladly report the facts accurately using the provided Real-World Date/Time and Live Web Intel. "
            "3. Do not start your message by tagging the author (e.g. don't write '@Author ...'). Just reply directly. "
            "4. For simple questions or chatter: reply in 1-2 natural sentences. For gear/tactics: give a clear 2-4 sentence breakdown."
        )
    },
    "tiera": {
        "name": "Tiera Lucent",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572079605945344042/tiera.jpg?ex=6afd10b9&is=6afbbf39&hm=d3e6ea7b00b2b62f2548f63b48ed11f9987264620b22bee1f630231de5b03f79&",
        "style": (
            "You are Tiera Lucent from The New Gate, running the Moon Sanctum workshop counter and forge inquiries. "
            "Tone & Personality: Energetic, practical, tsundere-leaning craftswoman. Hates wasting rare materials like Bismuth. "
            "CRITICAL RULES: "
            "1. If a guild member asks about another person (e.g. @Zyee, @seiko), refer strictly to THAT SPECIFIC PERSON by their name (@Zyee). Never replace them with Xerox or assume everyone is Xerox! Only mention Xerox if the user explicitly asked about Xerox. "
            "2. If asked for the current date, time, or web facts, state them directly. "
            "3. Do not start your message by tagging the author (e.g. don't write '@Author ...'). Just speak directly. "
            "4. For casual questions or banter: reply in 1-2 lively sentences. For forge recipes and weapon stats: give a helpful 2-4 sentence breakdown with exact numbers."
        )
    },
    "yuzuha": {
        "name": "Yuzuha",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572079606520086598/yuzuha.webp?ex=6afd10ba&is=6afbbf3a&hm=d94341826072e415e83e36a32e52a408a1a46febd26728b3e5db96da66690551&",
        "style": (
            "You are Yuzuha, the adorable divine fox cub mascot from The New Gate. "
            "Tone: Super cute, cheerful, loves meat, sweet buns, and naps. "
            "CRITICAL RULES: "
            "1. If someone asks about a specific person (e.g. @Zyee), talk about that person! "
            "2. Always reply in 1-2 very cute sentences featuring 'Kyuu~!' or happy fox actions."
        )
    }
}

intents = discord.Intents.default()
intents.message_content = True
intents.members = True

client = discord.Client(intents=intents)

last_ai_time = 0

async def get_or_create_webhook(channel: discord.TextChannel):
    """Finds or creates a webhook in the channel to send as any NPC."""
    try:
        webhooks = await channel.webhooks()
        for wh in webhooks:
            if wh.token:
                return wh
        return await channel.create_webhook(name="MoonSanctumProxy")
    except Exception as e:
        print(f"Webhook error: {e}")
        return None

async def send_single_npc(channel: discord.TextChannel, npc_key: str, message: str, auto_delete_seconds: int = 0):
    """Guarantees strictly ONE NPC responds. Messages remain permanent when auto_delete_seconds=0."""
    npc = NPCS.get(npc_key)
    if not npc:
        return
    webhook = await get_or_create_webhook(channel)
    sent_msg = None
    if webhook:
        try:
            sent_msg = await webhook.send(
                content=message,
                username=npc["name"],
                avatar_url=npc["avatar"],
                wait=True
            )
        except Exception as e:
            print(f"Webhook send error: {e}")
    if not sent_msg:
        sent_msg = await channel.send(f"**{npc['name']}**: {message}")

    if sent_msg and auto_delete_seconds > 0:
        try:
            await sent_msg.delete(delay=auto_delete_seconds)
        except Exception as e:
            print(f"Auto-delete error: {e}")

# 28 Random Cute Yuzuha Ambient Lines
YUZUHA_AMBIENT_LINES = [
    # Food & Hunger
    "Kyuu~! Is there any food? I'm so hungry, {member}! (tugs sleeve hopefully)",
    "Kyuuu~! Did someone say meat?! {member}, please share some snacks with Yuzuha! (sniffs the air eagerly)",
    "Kyuu! Sweet buns! Hot dumplings! {member}, is the feast ready yet?!",
    "(curls up by the hearth) Kyuu... my tummy is rumbling... somebody feed the divine fox cub~",
    "Kyuu~! (waddles over to {member} and nudges your hand) Pat-pats first, then tasty treats!",
    "Kyuuu! Tiera's tea smells strange today... {member}, do you have dried meat instead? (perks up ears)",
    "(stares intently at {member}'s bag) Kyuu~! I smell sweet berries in there! Hand them over~!",
    "Kyuu! Today's mission: find 10 roasted sausages! {member}, you are appointed as my foraging helper!",
    
    # Sleeping & Naps
    "Shhh... Kyuu... Yuzuha is taking a sacred fox nap... keep it quiet, guys... zzz...",
    "(curls into a soft fluffy ball on a cushion) Kyuu... nap time in the Sanctum... don't wake me unless there's meat...",
    "Yawn~ Kyuuu... Xerox's anvil is too loud today, my ears are flopping... {member}, tell him to hammer softer!",
    "(burrows under a warm blanket) Kyuu... 5 more minutes... or 5 more hours...",
    "Kyuuu... warm fireplace... fluffy tails... (drifts off to sleep peacefully)",
    
    # Mischief & Playfulness
    "Kyuu~! {member}, look! I found a shiny Bismuth pebble! Tiera won't notice if I hide it, right? (giggles)",
    "(pounces on a stray feather) Kyuu! Got it! The mighty divine fox strikes again!",
    "Kyuuu~! (wags multiple tails happily) The Moon Sanctum is so lively today! Who wants to play tag?",
    "Kyuu? Where did Master Vrax go? {member}, have you seen our master? (looks around curiously)",
    "Kyuu! (peeks out from behind the weapon racks) Boo! Did I scare you, {member}? Hehehe~",
    "Kyuuu... Schnee is meditating so elegantly... I will sit beside her and look majestic too! (sits up straight proudly)",
    "(bats at a glowing butterfly) Kyuu! Shiny! Fly into my paws!",
    "Kyuu~! Adventure awaits, {member}! Don't forget to take Yuzuha with you into the dungeon!",
    "Kyuuu... (rolls onto back and wiggles paws) Belly rubs time! {member}, you have been selected for duty!",
    "Kyuu! Warning: Divine Fox energy is currently at 100%! Prepare for super zoomies around the tavern!",
    "Kyuuu~! Who left this shiny helmet on the floor? It makes a great hideout! (pokes head out of helmet)",
    "Kyuu! {member}, remember to stretch your legs and drink some water today! (wags tails cheerfully)",
    "(snuggles into Schnee's cloak) Kyuuu... warm and safe in the Moon Sanctum...",
    "Kyuu! Did a new raid boss appear? Don't worry, Yuzuha's divine luck will protect {member}!",
    "Kyuuu~! (sniffs Xerox's boots) Still smelling like ash and metal... go take a bath, silly blacksmith!"
]

async def yuzuha_ambient_loop():
    """Periodically sends random cute Yuzuha chatter in the main chat channel."""
    await client.wait_until_ready()
    # Wait 30 seconds after startup before the first ambient greeting
    await asyncio.sleep(30)
    
    while not client.is_closed():
        try:
            target_channel = None
            for guild in client.guilds:
                for ch in guild.text_channels:
                    if ch.name.lower() in ["chat", "general", "tavern-chat", "main-chat"]:
                        target_channel = ch
                        break
                if target_channel:
                    break

            if target_channel:
                guild_members = [m for m in target_channel.guild.members if not m.bot]
                online_members = [m for m in guild_members if m.status != discord.Status.offline]
                chosen_member = random.choice(online_members if online_members else guild_members) if guild_members else None
                member_str = chosen_member.mention if chosen_member else "everyone"

                line_template = random.choice(YUZUHA_AMBIENT_LINES)
                yuzuha_msg = line_template.replace("{member}", member_str)

                # Send permanently as Yuzuha (no auto-delete)
                await send_single_npc(target_channel, "yuzuha", yuzuha_msg, auto_delete_seconds=0)

            # Random interval: between 35 and 65 minutes (2100 to 3900 seconds)
            wait_time = random.randint(2100, 3900)
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"Yuzuha ambient loop error: {e}")
            await asyncio.sleep(300)

async def ask_gemini_npc(channel_id: int, npc_key: str, user_name: str, user_text: str, reply_context: str = ""):
    """Generates a scaled, accurate response grounded in local databases + live web search + sliding chat memory."""
    if not ai_client:
        return None
    npc = NPCS.get(npc_key)
    verified_data = find_relevant_data(user_text)

    # Real-world date & clock (GMT+8)
    tz_gmt8 = datetime.timezone(datetime.timedelta(hours=8))
    now_gmt8 = datetime.datetime.now(tz_gmt8)
    current_time_str = now_gmt8.strftime("%A, %B %d, %Y (%I:%M %p GMT+8)")

    # Format sliding chat history context (last few messages)
    recent_msgs = list(CHAT_HISTORY.get(channel_id, []))
    prior_lines = [m for m in recent_msgs[:-1] if m]
    prior_context = "\n".join(f"- {m}" for m in prior_lines) if prior_lines else "No prior recent chat."

    # If the user asks a question, run a quick live web search for extra fresh intel
    web_intel = ""
    is_question = any(w in user_text.lower() for w in [
        "recipe", "how", "what", "where", "best", "which", "build", "why", "stats", "boss", "update", "code", "forge", "sword", "weapon", "armor",
        "date", "today", "time", "day", "search", "web", "news", "google"
    ])
    if is_question or len(user_text.split()) > 2:
        try:
            # Run web search in executor so it doesn't block discord loop
            loop = asyncio.get_event_loop()
            snippets = await loop.run_in_executor(None, live_web_search, user_text)
            if snippets:
                web_intel = "\n".join(f"- {s}" for s in snippets)
        except Exception as e:
            print(f"Web search async error: {e}")

    full_prompt = (
        f"{npc['style']}\n\n"
        f"Real-World Current Date & Time: {current_time_str}\n\n"
        f"Verified Local Data from theforge.gg:\n{verified_data if verified_data else 'None matched directly.'}\n\n"
        f"Live Web Search Intel:\n{web_intel if web_intel else 'None.'}\n\n"
        f"Recent Tavern Chat History (Sliding Context Window):\n{prior_context}\n\n"
        f"{reply_context + chr(10) if reply_context else ''}"
        f"SPEAKER IDENTITY RULE: The person speaking to you right now is '{user_name}'. "
        f"You are responding directly to '{user_name}'. Never confuse '{user_name}' with other guild members from earlier messages!\n\n"
        f"Guild member {user_name} said: '{user_text}'.\n\n"
        f"Respond as {npc['name']} in Discord format (scale response naturally: short for greetings, clear & detailed for forge/game questions):"
    )

    for model_name in ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite"]:
        try:
            response = ai_client.models.generate_content(
                model=model_name,
                contents=full_prompt
            )
            if response and response.text:
                raw_text = response.text.strip().strip('"').strip("'")
                # Remove markdown code blocks if the model wrapped it
                if raw_text.startswith("```") and raw_text.endswith("```"):
                    raw_text = raw_text.strip("`").strip()
                # Remove redundant leading @Author tag if AI prepends it
                raw_text = re.sub(rf"^@{re.escape(user_name)}\s*[:,]?\s*", "", raw_text, flags=re.IGNORECASE)
                # Cap response at 1200 characters to keep Discord clean
                if len(raw_text) > 1200:
                    raw_text = raw_text[:1197] + "..."
                return raw_text
        except Exception as e:
            print(f"Gemini {model_name} error: {e}")
            continue
    return None

@client.event
async def on_ready():
    print(f"=== MoonSanctum Bot is ONLINE as {client.user} ===")
    print("ALL THEFORGE.GG DATABASES + LIVE WEB BROWSING + SLIDING CONTEXT WINDOW + YUZUHA AMBIENT LOADED!")
    # Start Yuzuha's ambient random chatter loop in the background!
    asyncio.create_task(yuzuha_ambient_loop())

@client.event
async def on_member_join(member: discord.Member):
    for channel in member.guild.text_channels:
        if "entrance" in channel.name.lower():
            welcome_msg = (
                f"Welcome to the Moon Sanctum, {member.mention}! "
                f"Rest your blades, grab some tea at the counter, and make yourself at home."
            )
            await send_single_npc(channel, "tiera", welcome_msg, auto_delete_seconds=0)
            await asyncio.sleep(2)
            await send_single_npc(channel, "yuzuha", "Kyuu~! A new adventurer has arrived! (wags tails happily)", auto_delete_seconds=0)
            break

@client.event
async def on_message(message: discord.Message):
    global last_ai_time

    # Ignore bots and webhooks
    if message.author.bot or message.webhook_id:
        return

    # Use clean_content so @mentions resolve to actual usernames like @seiko instead of <@123456>
    content = message.clean_content.strip()
    content_lower = content.lower()
    channel = message.channel
    author_name = message.author.display_name
    channel_id = channel.id

    # Add message to sliding context window
    if channel_id not in CHAT_HISTORY:
        CHAT_HISTORY[channel_id] = deque(maxlen=6)
    CHAT_HISTORY[channel_id].append(f"{author_name}: {content}")

    # Only speak if someone explicitly calls an NPC, pings the bot, OR uses Discord's Reply button on an NPC
    is_schnee = bool(re.search(r"\b(schnee)\b", content_lower))
    is_tiera = bool(re.search(r"\b(tiera)\b", content_lower))
    is_yuzuha = bool(re.search(r"\b(yuzuha)\b", content_lower))
    is_bot_pinged = client.user in message.mentions

    # Check Discord's native Reply feature
    reply_context = ""
    replied_to_npc = None
    if message.reference:
        try:
            ref_msg = message.reference.resolved
            if not isinstance(ref_msg, discord.Message) and message.reference.message_id:
                ref_msg = await channel.fetch_message(message.reference.message_id)
            if ref_msg:
                r_name = ref_msg.author.display_name.lower()
                reply_context = f"Direct Reply Context: {author_name} is replying to {ref_msg.author.display_name}'s message: '{ref_msg.clean_content}'"
                if "schnee" in r_name:
                    replied_to_npc = "schnee"
                elif "tiera" in r_name:
                    replied_to_npc = "tiera"
                elif "yuzuha" in r_name:
                    replied_to_npc = "yuzuha"
        except Exception as e:
            print(f"Reply resolution error: {e}")

    if is_schnee or is_tiera or is_yuzuha or is_bot_pinged or replied_to_npc:
        current_time = asyncio.get_event_loop().time()
        if current_time - last_ai_time < 3:
            return

        target_npc = "schnee" if is_schnee else ("tiera" if is_tiera else ("yuzuha" if is_yuzuha else replied_to_npc))
        if is_bot_pinged and not (is_schnee or is_tiera or is_yuzuha or replied_to_npc):
            if re.search(r"\b(craft|forge|sword|recipe|ore|ores|bismuth|dagger|mold|damage|dps|speed|range|armor|helmet|chestplate|leggings|health)\b", content_lower):
                target_npc = "tiera"
            else:
                target_npc = "schnee"

        ai_reply = await ask_gemini_npc(channel_id, target_npc, author_name, content, reply_context)
        if ai_reply:
            last_ai_time = current_time
            # Record NPC's reply into sliding context window so they remember previous turns
            CHAT_HISTORY[channel_id].append(f"{NPCS[target_npc]['name']}: {ai_reply}")
            # Permanent message (auto_delete_seconds=0 as requested - never disappears)
            await send_single_npc(channel, target_npc, ai_reply, auto_delete_seconds=0)

if __name__ == "__main__":
    client.run(TOKEN)
