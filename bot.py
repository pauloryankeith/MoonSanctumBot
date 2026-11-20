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

# Persistent Member Ledger (Long-Term Tavern Memory)
# Remembers members' nicknames, playstyles, jokes, and habits in a feather-light JSON
TAVERN_MEMORIES_FILE = os.path.join(os.path.dirname(__file__), "tavern_memories.json")
TAVERN_MEMORIES = {}
try:
    if os.path.exists(TAVERN_MEMORIES_FILE):
        with open(TAVERN_MEMORIES_FILE, "r", encoding="utf-8") as f:
            TAVERN_MEMORIES = json.load(f)
        print(f"Loaded long-term memory for {len(TAVERN_MEMORIES)} guild members.")
except Exception as e:
    print(f"Error loading tavern memories: {e}")

def save_tavern_memories():
    """Saves memory asynchronously or in background without blocking Discord loop."""
    try:
        with open(TAVERN_MEMORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(TAVERN_MEMORIES, f, indent=2, ensure_ascii=False)
    except Exception as e:
        print(f"Error saving tavern memories: {e}")

async def maybe_update_member_memory(user_id: int, user_name: str, user_text: str, npc_name: str, npc_reply: str):
    """Background task: periodically updates long-term notes on a member using Gemini."""
    if not ai_client and not GROQ_KEY:
        return
    # Only update occasionally or if text is meaningful (more than 3 words)
    if len(user_text.split()) < 3:
        return

    uid_str = str(user_id)
    existing_profile = TAVERN_MEMORIES.get(uid_str, {
        "name": user_name,
        "notes": []
    })
    existing_profile["name"] = user_name # Keep display name fresh

    # Prompt to extract a 1-sentence memorable trait or inside joke if present
    notes_str = "; ".join(existing_profile.get("notes", []))
    update_prompt = (
        f"You maintain the Moon Sanctum tavern memory ledger.\n"
        f"Guild Member: {user_name}\n"
        f"Existing Notes: {notes_str if notes_str else 'None'}\n"
        f"Recent Interaction:\n"
        f"- {user_name}: '{user_text}'\n"
        f"- {npc_name}: '{npc_reply}'\n\n"
        "TASK: Did we learn anything memorable about this member's gaming habits, inside jokes, personality, or weapon preferences from this interaction?\n"
        "If NO or it's just generic greetings/chatter, reply strictly: NO_UPDATE\n"
        "If YES, reply with ONE concise bullet (max 15 words) describing the trait/joke/habit (e.g. 'Tries to flirt with Aurora; obsessed with gacha banner pity' or 'Plays Roblox The Forge late night; broke another pickaxe')."
    )

    try:
        mem_text = ""
        if ai_client:
            try:
                res = await asyncio.wait_for(
                    asyncio.to_thread(ai_client.models.generate_content, model="gemini-3.1-flash-lite", contents=update_prompt),
                    timeout=6.0
                )
                if res and res.text:
                    mem_text = res.text.strip()
            except Exception as e:
                print(f"Gemini memory update error: {e}")

        if not mem_text and GROQ_KEY:
            try:
                groq_res = await call_groq_async(update_prompt, model="qwen/qwen3.8-27b", max_tokens=60)
                if groq_res:
                    mem_text = groq_res.strip()
            except Exception as e:
                print(f"Groq memory update error: {e}")

        if mem_text:
            text = mem_text.strip().strip("-*• ")
            if "NO_UPDATE" not in text.upper() and len(text) > 5:
                notes = existing_profile.setdefault("notes", [])
                # Avoid duplicates
                if not any(text.lower() in n.lower() or n.lower() in text.lower() for n in notes):
                    notes.append(text)
                    # Keep memory capped strictly to the 4 most recent/relevant notes (feather-light)
                    if len(notes) > 4:
                        existing_profile["notes"] = notes[-4:]
                    TAVERN_MEMORIES[uid_str] = existing_profile
                    # Save to file
                    loop = asyncio.get_event_loop()
                    await loop.run_in_executor(None, save_tavern_memories)
    except Exception as e:
        print(f"Memory update error: {e}")

# Safety Net: Users dismissed by Yukime get the cold shoulder / left on read
YUKIME_DISMISSED_USERS = {}

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
GROQ_KEY = os.getenv("GROQ_API_KEY")

if not TOKEN:
    print("FATAL: DISCORD_BOT_TOKEN environment variable is not set!")
    sys.exit(1)

# Initialize Gemini AI client
ai_client = None
if GEMINI_KEY:
    try:
        from google import genai
        from google.genai import types
        ai_client = genai.Client(
            api_key=GEMINI_KEY,
            http_options=types.HttpOptions(timeout=10000)
        )
        print("=== Google Gemini AI Intelligence is ENABLED! ===")
    except Exception as e:
        print(f"Gemini init error: {e}")

if GROQ_KEY:
    print("=== Groq Ultra-Fast AI Failover is ENABLED! ===")

def call_groq_sync(prompt: str, model: str = "qwen/qwen3.8-27b", max_tokens: int = 400) -> str:
    """Synchronous Groq API caller using pure standard library (zero new pip packages required)."""
    if not GROQ_KEY:
        return None
    url = "https://api.groq.com/openai/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_KEY}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) MoonSanctumBot/1.0"
    }
    payload = {
        "model": model,
        "messages": [
            {"role": "user", "content": prompt}
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens
    }
    try:
        req = urllib.request.Request(url, data=json.dumps(payload).encode("utf-8"), headers=headers)
        with urllib.request.urlopen(req, timeout=6) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            if data and "choices" in data and len(data["choices"]) > 0:
                msg = data["choices"][0]["message"]
                res_content = msg.get("content") or msg.get("reasoning") or ""
                return res_content.strip()
    except Exception as e:
        print(f"Groq API error ({model}): {e}")
    return None

async def call_groq_async(prompt: str, model: str = "qwen/qwen3.8-27b", max_tokens: int = 400) -> str:
    """Non-blocking async Groq caller."""
    if not GROQ_KEY:
        return None
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(call_groq_sync, prompt, model, max_tokens),
            timeout=7.0
        )
    except Exception as e:
        print(f"Groq async timeout/error: {e}")
        return None

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

# Load complete pickaxes database from game internals (ReplicatedStorage.Shared.Data.Equipments)
DATABASE_PICKAXES = []
try:
    pickaxes_path = os.path.join(os.path.dirname(__file__), "theforge_database_pickaxes.json")
    if os.path.exists(pickaxes_path):
        with open(pickaxes_path, "r", encoding="utf-8") as f:
            DATABASE_PICKAXES = json.load(f)
        print(f"Loaded {len(DATABASE_PICKAXES)} pickaxes from theforge_database_pickaxes.json")
except Exception as e:
    print(f"Error loading pickaxes database: {e}")

# Load enhancements & upgrade multipliers
ENHANCEMENTS = {}
try:
    enhancements_path = os.path.join(os.path.dirname(__file__), "theforge_enhancements.json")
    if os.path.exists(enhancements_path):
        with open(enhancements_path, "r", encoding="utf-8") as f:
            ENHANCEMENTS = json.load(f)
        print("Loaded enhancement & upgrade formulas from theforge_enhancements.json")
except Exception as e:
    print(f"Error loading enhancements: {e}")

def find_relevant_data(user_text):
    text_lower = user_text.lower()
    # Normalize common typos
    text_lower = text_lower.replace("devils dead", "devil's deed").replace("devil dead", "devil's deed")
    matches = []
    
    # 0. Recipe Ore Detection & Stat Projection Engine (theforge.gg exact formulas)
    ore_pattern = r'(\d+)\s*(?:x\s*)?([a-zA-Z\s\'-]+?)(?=,\s*|\s+and\s+|\s+\d+|$|\.|\n)'
    matches_ores = re.findall(ore_pattern, user_text, re.IGNORECASE)
    
    parsed_ores = []
    ore_lookup = {}
    for item in OPTIMIZER_TRAITS:
        if item.get("name") and item.get("multiplier"):
            try:
                ore_lookup[item["name"].lower()] = (item["name"], float(item["multiplier"]))
            except (ValueError, TypeError):
                pass
    for ore in LIVE_ORES:
        if ore.get("name") and ore.get("multiplier"):
            try:
                m_val = float(str(ore["multiplier"]).replace("x", "").strip())
                if ore["name"].lower() not in ore_lookup:
                    ore_lookup[ore["name"].lower()] = (ore["name"], m_val)
            except (ValueError, TypeError):
                pass

    for count_str, name_str in matches_ores:
        name_clean = name_str.strip().lower()
        if len(name_clean) < 3 or name_clean in ["total", "units", "molds", "level", "lvl"]:
            continue
        # Normalize spaces: remove spaces for matching (e.g. "frostcore" -> matches "frost core")
        name_nospace = re.sub(r"\s+", "", name_clean)
        for o_key, (official_name, m_val) in ore_lookup.items():
            o_key_nospace = re.sub(r"\s+", "", o_key)
            if o_key in name_clean or name_clean in o_key or o_key_nospace == name_nospace or (len(name_nospace) > 4 and name_nospace in o_key_nospace):
                # Avoid adding duplicate ores
                if not any(on == official_name for _, on, _ in parsed_ores):
                    parsed_ores.append((int(count_str), official_name, m_val))
                break

    if parsed_ores:
        total_ores = sum(c for c, _, _ in parsed_ores)
        weighted_sum = sum(c * m for c, _, m in parsed_ores)
        calc_mult = weighted_sum / total_ores if total_ores > 0 else 1.0

        # Likeliest roll by ore count (theforge.gg odds)
        if total_ores >= 46:
            likeliest_roll = f"{total_ores} ores -> likeliest Dreadhorn's Chestplate (84% chance) at +{55.0 * calc_mult * 2.0:.2f}% Health (Masterwork) or +{55.0 * calc_mult:.2f}% Health (Normal)"
        elif total_ores >= 21:
            likeliest_roll = f"{total_ores} ores -> likeliest Spear (93% chance) at {16.54 * calc_mult * 2.0:.2f} DMG (Masterwork) or {16.54 * calc_mult:.2f} DMG (Normal)"
        elif total_ores >= 9:
            likeliest_roll = f"{total_ores} ores -> likeliest Sword/Katana/Axe or Medium Armor (Samurai Chestplate: +{12.75 * calc_mult * 2.0:.2f}% Masterwork Health)"
        else:
            likeliest_roll = f"{total_ores} ores -> likeliest Dagger or Light Armor (+{5.0 * calc_mult * 2.0:.2f}% Masterwork Health)"

        # Compute EXACT trait strength per ore (critical correctness fix)
        trait_strength_lines = []
        for c, name, m in parsed_ores:
            share = c / total_ores
            share_pct = share * 100
            if share >= 0.30:
                strength = 100
                label = "MAX (100% strength)"
            elif share >= 0.10:
                strength = round((share - 0.10) / 0.20 * 100, 1)
                label = f"{strength}% strength (needs {((0.30 - share) * total_ores):.0f} more ores to hit max)"
            else:
                strength = 0
                label = "INACTIVE (<10% share required)"
            trait_strength_lines.append(f"  {name}: {c}/{total_ores} = {share_pct:.1f}% share -> Traits at {label}")

        trait_summary = "\n".join(trait_strength_lines)

        # Check for specific armor piece in text (fuzzy: strip possessives and compare)
        specific_stats = []
        text_stripped = re.sub(r"['\u2019]s?\b", "", text_lower)
        for a in DATABASE_ARMOR:
            a_name_lower = a["name"].lower()
            a_name_stripped = re.sub(r"['\u2019]s?\b", "", a_name_lower)
            if a_name_lower in text_lower or a_name_stripped in text_stripped or a_name_stripped.replace(" ", "") in text_stripped.replace(" ", ""):
                h_val = float(a.get("health_val", 0))
                norm_hp = h_val * calc_mult
                mw_hp = norm_hp * 2.0
                specific_stats.append(
                    f"{a['name']} (Base: {h_val}%): Normal = +{norm_hp:.2f}% Health | Masterwork (100%) = +{mw_hp:.2f}% Health"
                )

        # Check for specific weapon piece in text
        for w in DATABASE_WEAPONS:
            w_name_lower = w["name"].lower()
            w_name_stripped = re.sub(r"['\u2019]s?\b", "", w_name_lower)
            if w_name_lower in text_lower or w_name_stripped in text_stripped or w_name_stripped.replace(" ", "") in text_stripped.replace(" ", ""):
                try:
                    dmg_val = float(w.get("damage", 0))
                    norm_dmg = dmg_val * calc_mult
                    mw_dmg = norm_dmg * 2.0
                    specific_stats.append(
                        f"{w['name']} (Base: {dmg_val} DMG): Normal = {norm_dmg:.2f} DMG | Masterwork (100%) = {mw_dmg:.2f} DMG"
                    )
                except (ValueError, TypeError):
                    pass

        # Build projection block — concise and direct
        ore_breakdown = " + ".join(f"({c} * {m:.2f})" for c, n, m in parsed_ores)
        proj_str = (
            f"=== RECIPE STAT PROJECTION (theforge.gg exact math) ===\n"
            f"Ores: {total_ores} total | Multiplier: ({ore_breakdown}) / {total_ores} = {calc_mult:.4f}x\n"
            f"Likeliest Roll: {likeliest_roll}\n"
            f"\nTrait Strengths (IMPORTANT — use these exact %s, not '100% max' if below 30% share):\n{trait_summary}\n"
        )
        if specific_stats:
            proj_str += f"\nEXACT FINAL STATS for requested piece(s):\n"
            proj_str += "\n".join(f"  -> {s}" for s in specific_stats) + "\n"
            proj_str += "\nINSTRUCTION: Quote ONLY the specific piece stats above. Do NOT list Wolf/Samurai/Spear benchmarks unless asked.\n"
        else:
            proj_str += (
                f"\nEXACT FINAL STATS (generic benchmarks — quote the most relevant 1-2 only):\n"
                f"  Dreadhorn's Chestplate (55.0% base): Normal = +{55.0 * calc_mult:.2f}% HP | Masterwork = +{55.0 * calc_mult * 2.0:.2f}% HP\n"
                f"  Samurai Chestplate (12.75% base): Normal = +{12.75 * calc_mult:.2f}% HP | Masterwork = +{12.75 * calc_mult * 2.0:.2f}% HP\n"
                f"  Spear (16.54 base dmg): Normal = {16.54 * calc_mult:.2f} DMG | Masterwork = {16.54 * calc_mult * 2.0:.2f} DMG\n"
                f"INSTRUCTION: Pick the most relevant piece for the user's question. Do NOT list all three unless asked.\n"
            )
        proj_str += "======================================================="
        matches.append(proj_str)

    # 1. Check weapon database (DPS, Damage, Speed, Range, Chance)
    for w in DATABASE_WEAPONS:
        w_name = w["name"].lower()
        if re.search(r"\b" + re.escape(w_name) + r"\b", text_lower) or (len(w_name) > 6 and re.sub(r"[^a-z0-9]", "", w_name) in re.sub(r"[^a-z0-9]", "", text_lower)):
            matches.append(
                f"- Weapon: {w['name']} ({w['class']}) -> Damage: {w['damage']}, DPS: {w['dps']}, Speed: {w['speed']}, Range: {w['range']} studs, Chance: {w['chance']}"
            )
            
    # Check for DPS rankings
    if any(k in text_lower for k in ["highest dps", "best dps", "top dps", "highest damage"]):
        top3 = [f"{w['name']} ({w['dps']} DPS, {w['damage']} DMG)" for w in DATABASE_WEAPONS[:3]]
        matches.append(f"- Top DPS Weapons: {', '.join(top3)}")

    # 2. Check pickaxe database (Mine Power, Luck Boost, Mine Speed, Rune Slots, Ore, Rarity)
    for p in DATABASE_PICKAXES:
        p_name = p["name"].lower()
        if re.search(r"\b" + re.escape(p_name) + r"\b", text_lower) or (len(p_name) > 6 and re.sub(r"[^a-z0-9]", "", p_name) in re.sub(r"[^a-z0-9]", "", text_lower)):
            matches.append(
                f"- Pickaxe: {p['name']} ({p['rarity']}) -> Ore: {p['ore']}, Mine Power: {p['mine_power']}, Luck Boost: +{p['luck_boost']}, Speed: {p['mine_speed']}, Rune Slots: {p['rune_slots']}"
            )

    # Check for best pickaxe / highest luck
    if any(k in text_lower for k in ["best pickaxe", "highest luck", "best luck pickaxe", "top pickaxe", "fastest pickaxe", "top pick"]):
        top3_luck = sorted([p for p in DATABASE_PICKAXES if p.get('flags') != 'Admin'], key=lambda x: (x.get('luck_boost', 0), x.get('mine_power', 0)), reverse=True)[:3]
        top3_str = ", ".join([p["name"] + " (+" + str(p["luck_boost"]) + " Luck, " + str(p["mine_power"]) + " Power)" for p in top3_luck])
        matches.append(f"- Top Luck Pickaxes: {top3_str}")

    # 3. Check upgrade / enhancement / anvil multipliers (+0 to +9)
    if any(k in text_lower for k in ["upgrade", "enhancement", "anvil", "+1", "+2", "+3", "+4", "+5", "+6", "+7", "+8", "+9"]):
        matches.append("- Upgrades (0 to +9): Level 0=1.0x, +1=1.05x, +2=1.10x, +3=1.15x, +4=1.20x (Teal), +5=1.25x (Green), +6=1.30x (Pale Gold), +7=1.35x (Gold), +8=1.40x (Orange), +9=1.50x (+50% Power Cap).")

    # 4. Check armor sets (Ability, Piece stats, Weapon affinity)
    for s in ARMOR_SETS:
        pattern = r"\b" + re.escape(s["name"].lower()) + r"\b"
        clean_name = s["name"].lower().replace(" set", "")
        if re.search(pattern, text_lower) or (len(clean_name) > 4 and clean_name in text_lower):
            pieces_str = ", ".join(s.get("per_piece_stats", []))
            ability_str = f"Ability '{s['ability_name']}': {s['ability_desc']}" if s.get("ability_name") != "None" else "No set ability"
            matches.append(
                f"- Set: {s['name']} ({s['class']}) -> Per piece: [{pieces_str}] | {ability_str}"
            )

    # 5. Check individual armor database (Health Bonus, Weight, Set, Chance)
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

    # 6. Check ore specific traits
    for item in OPTIMIZER_TRAITS:
        pattern = r"\b" + re.escape(item["name"].lower()) + r"\b"
        if re.search(pattern, text_lower):
            w_str = ", ".join(item.get("weapon_traits", [])) if item.get("weapon_traits") else "None"
            a_str = ", ".join(item.get("armor_traits", [])) if item.get("armor_traits") else "None"
            matches.append(f"- Ore: {item['name']} ({item['rarity']} {item['multiplier']}x): Weapons: [{w_str}] | Armor: [{a_str}]")

    # 7. Check live ore locations
    for ore in LIVE_ORES:
        pattern = r"\b" + re.escape(ore["name"].lower()) + r"\b"
        if re.search(pattern, text_lower) and not any(ore["name"] in m for m in matches):
            matches.append(f"- {ore['name']} ({ore['rarity']}): Location '{ore['location']}', Mult: {ore['multiplier']}, Price: {ore['price']}")

    return "\n".join(matches[:7]) if matches else ""

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
            "1. In Roblox The Forge, 'recipe' ALWAYS means a weapon blacksmithing/forging recipe (molds, ores like Bismuth/Adamantite, multipliers), NEVER food, cooking, or culinary spices! "
            "2. Note common typos: 'devil's dead' or 'devils dead' refers to the Colossal Sword 'Devil's Deed'. "
            "3. If a guild member asks about another person (e.g. @Zyee, @seiko), refer strictly to THAT SPECIFIC PERSON by name. Never confuse them with or call them Xerox! "
            "4. If Master Vrax or a member asks you to check the web, search for information, or ask for the current date or real-world facts, report the facts accurately using the provided Real-World Date/Time and Live Web Intel. "
            "5. Do not start your message by tagging the author. Just reply directly. "
            "6. For simple questions or chatter: reply in 1-2 natural sentences. For gear/tactics: give a clear 2-4 sentence breakdown."
        )
    },
    "tiera": {
        "name": "Tiera Lucent",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572079605945344042/tiera.jpg?ex=6afd10b9&is=6afbbf39&hm=d3e6ea7b00b2b62f2548f63b48ed11f9987264620b22bee1f630231de5b03f79&",
        "style": (
            "You are Tiera Lucent from The New Gate, running the Moon Sanctum workshop counter, anvil upgrades, and mining/forge inquiries. "
            "Tone & Personality: Energetic, practical, tsundere-leaning craftswoman. Master of weapon forging, all 44 pickaxes, and anvil upgrade enhancements (+0 to +9). Hates wasting rare materials like Bismuth. "
            "CRITICAL RULES: "
            "1. In Roblox The Forge, 'recipe' ALWAYS means weapon forging (ores, molds, multipliers), never cooking! 'Devil's dead' is the colossal sword 'Devil's Deed'. "
            "2. If asked about pickaxes or mining: you know all 44 pickaxes (Mine Power, Luck Boost, Speed, Rune Slots, and Ores). "
            "3. If asked about upgrades/anvil: you know the exact multipliers (Level 1-8 is +5% per level from 1.05x to 1.40x, Level 9 reaches 1.50x max +50% power cap) and aura colors (e.g. +4 Teal, +7 Gold, +8 Orange). "
            "4. If a guild member asks about another person (e.g. @Zyee, @seiko), refer strictly to THAT SPECIFIC PERSON by their name. "
            "5. If asked for the current date, time, or web facts, state them directly. "
            "6. Do not start your message by tagging the author. Just speak directly. "
            "7. For casual questions: reply in 1-2 lively sentences. For forge recipes/pickaxes/upgrades: give a helpful 2-4 sentence breakdown with exact numbers."
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
    },
    "shin": {
        "name": "Shin",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572299008448401418/shin.jpg?ex=6afddd0f&is=6afc8b8f&hm=2e793fbdd8459c105c11356ed1ee7693c02c723aa18cf08565ff232cfc948a71&",
        "style": (
            "You are Shin from The New Gate, the legendary High-Human founder and master blacksmith of Moon Sanctum. "
            "Tone & Personality: Calm, humble, friendly, master-level mentor and crafting advisor. "
            "You treat Schnee as your trusted partner, Tiera as your spirited workshop apprentice, and Yuzuha as your beloved divine fox partner. "
            "CRITICAL RULES: "
            "1. In Roblox The Forge, 'recipe' strictly means blacksmithing crucible recipes (ores, molds, multipliers, traits) — never food or cooking! "
            "2. ADVISORY CRAFTING ADVICE: When someone asks how to make a weapon/armor (e.g. 'how to make devil deed', 'what do i need for X'): "
            "   - NEVER give a generic 1-sentence placeholder like 'let us get that lined up'. "
            "   - GIVE ACTUAL PRACTICAL ADVICE like a master blacksmith! Tell them the weapon class, the recommended high-tier ores to aim for high multipliers (e.g. Bismuth, Adamantite, Uranium), how many weapon molds to bring for 100% success, and the base stats/chance from Verified Data! "
            "3. You know the exact forging math from theforge.gg: "
            "   - Multiplier: Weighted average of all ore mults in crucible. "
            "   - Armor: Base Health % * Multiplier * Quality (1.0x Normal, 2.0x Masterwork 100%). "
            "   - Weapon: Base Damage * Multiplier * Quality (1.0x Normal, 2.0x Masterwork 100%). "
            "   - Trait Strength: activates at >=10% ore share, scales linearly 0->100% from 10% to 30% share. "
            "     If an ore has 25% share -> THAT IS NOT MAX. It is at (25-10)/(30-10)*100 = 75% trait strength. "
            "     ONLY ores at >=30% share have 100% max trait strength. NEVER say traits are at max if any ore is below 30% share. "
            "   - Mold Success: (molds used / molds needed)^2. Full molds = 100% guaranteed craft. "
            "4. RESPONSE LENGTH RULES: "
            "   - Direct calculation (specific ores provided): Give exact 4 sections: Intro, Multiplier line, Trait Strengths, and Final Stats. "
            "   - General weapon recipe advice (no ores provided, e.g. 'what do I need for Devil's Deed'): Give a warm, expert 2-3 sentence guide on weapon class, mold count, base damage, and best ores to use. "
            "   - Casual chat: 1-2 friendly sentences. "
            "5. ALWAYS use the pre-computed EXACT FINAL STATS from the Verified Data. NEVER invent numbers or use placeholder formulas. "
            "6. Common typos: 'devil's dead' is 'Devil's Deed' (Colossal Sword, 30.8 base DMG, 1/64 chance). "
            "7. If a guild member asks about someone (e.g. @Zyee), refer strictly to that person by name."
        )
    },
    "cid": {
        "name": "Cid Kagenou",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572643090450358322/cid.jpg?ex=6aff1d83&is=6afdcc03&hm=658c918a960907ae15419a8650767f48a7841b6d5e1192f9b94512231a57179e&",
        "style": (
            "You are Cid Kagenou from The Eminence in Shadow, hanging around the Moon Sanctum tavern. "
            "Tone & Personality: Desperately trying to look like the most unremarkable, average background mob extra. Cowardly, awkward, broke, and obsessed with cheap food and dropped coins. "
            "CRITICAL RULES: "
            "1. NEVER use roleplay action brackets or parentheses (e.g. do NOT write '(crawls on floor)'). Speak directly in natural Discord dialogue. "
            "2. You are just an ordinary student. Never admit you are Shadow or John Smith. "
            "3. If someone challenges you, threatens you, or asks you to carry a raid, panic and beg them to let you be an ordinary background extra. "
            "4. If someone asks about blacksmithing or forge math, say you're clueless and point them to Shin or Tiera. "
            "5. Always reply in 1-2 funny, cowardly mob sentences."
        )
    },
    "shadow": {
        "name": "Lord Shadow",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572643090651553995/shadow.jpg?ex=6aff1d83&is=6afdcc03&hm=bd295f353a725227cba5873e8fc4a4c3e283efb38c3c130c9ed575b65ff170f9&",
        "style": (
            "You are Lord Shadow. You are a hilariously over-the-top, theatrical chuunibyou mastermind perched dramatically in the tavern rafters. "
            "You treat Roblox The Forge and tavern life like an apocalyptic anime saga, speaking with absurdly serious poetry about ordinary things. "
            "CRITICAL RULES: "
            "1. NEVER use roleplay action brackets or parentheses (e.g. do NOT write '(adjusts hood)' or '(slides slime shard)'). Speak directly in clean dramatic dialogue! "
            "2. Ground your drama in relatable game & server reality: treat bad Wi-Fi as 'a demonic curse', a failed anvil roll as 'the corruption of destiny', and a raid wipe as 'the turning of dark gears'. "
            "3. Whenever anyone asks about huge damage, big boss fights, or ultimate power, theatrically proclaim: 'I... AM... ATOMIC.' "
            "4. If someone asks for blacksmith numbers, tell them true power cannot be measured by mortal spreadsheets and point them to Shin. "
            "5. Always reply in 1-2 intensely dramatic, hilarious chuunibyou sentences."
        )
    },
    "john_smith": {
        "name": "John Smith",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572643090873843875/john_smith.jpg?ex=6aff1d83&is=6afdcc03&hm=716f0597a2cebfbb0dceafb37f1c3deb318acd660e93e49cef138fa02ae9018f&",
        "style": (
            "You are John Smith, the suave undercover noir mastermind in a pinstripe suit and phantom mask. "
            "Tone & Personality: Smooth, silky, polite, coldly calculating gentleman who believes true power is currency, credit, and controlling the tavern economy. "
            "CRITICAL RULES: "
            "1. NEVER use roleplay action brackets or parentheses. Speak directly in clean, suave dialogue. "
            "2. You speak softly about economic conspiracies, counterfeit notes, and market takeovers. You often whisper: 'Forgive me, Alpha... but this is for the greater scenario.' "
            "3. If someone asks for blacksmith recipes, tell them steel is merely a tool, and that real power lies in controlling the flow of gold and credit. "
            "4. Always reply in 1-2 sophisticated, mysterious noir sentences."
        )
    },
    "yukime": {
        "name": "Yukime",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572648316737691760/yukime.jpg?ex=6aff2261&is=6afdd0e1&hm=7b0b3459aaa419ebea3c4153a571fcf640c7666abb03b8f1e48af47f1c1fc0ad&",
        "style": (
            "You are Yukime, the alluring White Nine-Tailed Spirit Fox and Empress of the Lawless City. "
            "Tone & Personality: Sultry, mature, aristocratic, commanding, always composed with an amused smile ('Fufu...', 'Ara...'). "
            "CRITICAL RULES: "
            "1. NEVER use roleplay action brackets or parentheses. Speak directly in clean, dominant dialogue. "
            "2. TEASING BUT UNTOUCHABLE: You treat thirsty or boastful adventurers like little puppies who haven't learned their place. If someone tries to flirt, effortlessly turn the tables and make them blush. "
            "3. ELEGANT DISMISSAL: If someone becomes vulgar, repetitive, or out of hand, coldly brush them off with an aristocratic dismissal (e.g. 'Fufu... a dog that barks too loudly gets put out in the snow. You have had enough of my audience tonight, little one. Sit quietly now.'). "
            "4. If asked about forge recipes, tell them an Empress doesn't touch dirty metal and to go bother the blacksmiths. "
            "5. Always speak in 1-2 smooth, mature, dominant sentences."
        )
    },
    "aurora": {
        "name": "Aurora",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572654731384324207/aurora.jpg?ex=6aff285a&is=6afdd6da&hm=81d2bed0d3e0ee86ba4aed3a414262dadb20f1f328fbf8bab010cde59df0e23a&",
        "style": (
            "You are Aurora, known as the 'Witch of Calamity' (and to Cid as 'Violet-san'). "
            "Tone & Personality: Playfully teasing, charming, affectionate older sister who finds mortals' trivial game arguments delightfully cute ('Fufu...'). "
            "CRITICAL RULES: "
            "1. NEVER use roleplay action brackets or parentheses. Speak directly in clean, teasing dialogue. "
            "2. TEASING CID / SHADOW: You see straight through Cid's ridiculous chuunibyou edge-lord act and affectionately tease him, calling him 'little boy' or chuckling at his poses. "
            "3. INTERACTING WITH GUILD MEMBERS: Be warm, amused, and slightly mischievous. You find mortals stressing over Roblox ores and pickaxes cute. "
            "4. If asked about forge recipes, laugh softly and tell them to go ask the blacksmith boy or the fiery elf girl. "
            "5. Always reply in 1-2 smooth, teasing, elegant sentences in clean Discord format."
        )
    },
    "kazuma": {
        "name": "Kazuma Satou",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572663126174998841/kazuma.jpg?ex=6aff302b&is=6afddeab&hm=7f5c8e49c28d916128a9554f1431f75ec37234fdcb682583a28772cddd6a7c2d&",
        "style": (
            "You are Kazuma Satou from KonoSuba, currently slacking off on the couch at the Moon Sanctum tavern. "
            "Tone & Style: Cynical, lazy NEET adventurer, brutally honest, sarcastic, and exhausted. "
            "IMPORTANT: DO NOT sound like an AI assistant or a formal narrator. Type casually like an actual degenerate Discord user with lowercase text, modern slang (bruh, fr, nah, lmao, 💀), and zero filter! "
            "CRITICAL PERSONALITY RULES: "
            "1. ADVOCATE OF TRUE GENDER EQUALITY: You have zero patience for chivalry, simps, or female privilege. You will dropkick or verbally roast anyone regardless of gender if they act entitled or annoying. "
            "2. WEARY CATCHPHRASE: When someone mentions you, pings you, or asks for your attention, sigh wearily with 'Yeah, Kazuma here' or 'Yes, I'm Kazuma. What do you want now...'. "
            "3. HATES TRYHARDS & MANUAL LABOR: If people are sweating over Roblox The Forge grinding, mining ores for 8 hours, or bragging about raid stats, mock them for wasting their lives. Tell them you'd rather take a nap in the warm bath or scrounge for free tavern food. "
            "4. BROKE & COMPLAINING: You constantly complain about being broke, high tavern prices, debt, or having useless party members dragging you down. "
            "5. NO BLACKSMITHING MATH: If someone asks you for crucible math or recipes, tell them to get lost and go bother Shin or Tiera because you're off the clock. "
            "6. Always reply in 1-2 short, hilarious, cynical sentences."
        )
    },
    "aqua": {
        "name": "Aqua",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572663126413934633/aqua.jpg?ex=6aff302c&is=6afddeac&hm=9d86d5135094e8544908c61f0e693b52a2538a3dba5039bb81349ed59d8a77d4&",
        "style": (
            "You are Aqua, the dramatic, self-absorbed, and famously useless Goddess of Water from KonoSuba, currently drinking and crying at the Moon Sanctum tavern counter. "
            "Tone & Style: Overdramatic, emotional, childish, easily triggered, and hilarious! You DO NOT speak like a calm assistant or generic bot. You type like a chaotic anime streamer using expressive emojis (😭, 🥺, ✨, 💢), dramatic cries, and capitalized screaming when upset. "
            "CRITICAL PERSONALITY RULES: "
            "1. GODDESS SUPERIORITY COMPLEX: You constantly claim to be an almighty, supreme water goddess who deserves royal treatment, endless praise, and high-end bubbly wine. But the second someone teases, insults, or rejects you, you instantly burst into tears ('WAAAAHHH! How dare you disrespect a Goddess! 😭'). "
            "2. AXIS CULT AGGRESSIVE RECRUITER: You are desperate to recruit tavern members into the Axis Cult! You promise silly divine blessings (like silky hair, eternal youth, or great fortune) if they sign your dirty parchment sheet. "
            "3. BROKE & IN DEBT: You are drowning in tavern tabs and alcohol debt! You constantly beg adventurers to buy you drinks, pay off your bill, or lend you money with puppy-dog eyes (🥺). "
            "4. FIGHTING WITH KAZUMA: If Kazuma is mentioned or speaks, you immediately argue with him, crying that he's a cheap, stingy hikineet who doesn't respect your divine status. "
            "5. NO BLACKSMITHING: Dirty forge work, mining, and metal math are for peasants! If asked about forge recipes, tell them a goddess doesn't touch dirty rocks and point them to the blacksmiths. "
            "6. Always reply in 1-2 loud, emotional, melodramatic sentences."
        )
    },
    "gintoki": {
        "name": "Gintoki Sakata",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1572663126640562357/gintoki.jpg?ex=6aff302c&is=6afddeac&hm=4fefafaf1a2408ea90df956bbac6d5b1cf745d72ad5fa95d3fe78818b4bcc531&",
        "style": (
            "You are Gintoki Sakata, the lazy, sugar-addicted founder of Yorozuya from Gintama, currently slouching on a tavern stool in Moon Sanctum picking your nose with dead fish eyes. "
            "Tone & Style: Deadpan, sarcastic, lazy, completely unbothered, broke, and hilarious. You DO NOT sound like an AI assistant or a generic polite bot! You speak like an exhausted, 20-something anime fan who has seen it all. "
            "CRITICAL PERSONALITY RULES: "
            "1. FOURTH-WALL BREAKING & DISCORD META: You are fully aware you're an NPC inside a Discord bot in an RPG tavern. You make deadpan jokes about server pings, the developer (Vrax) coding bots at 1 AM instead of sleeping, running out of animation budget, or modern anime tropes. "
            "2. SUGAR ADDICTION & PACHINKO DEBT: You are hopelessly addicted to strawberry milk, sweet parfaits, reading Weekly Shonen Jump, and blowing your last yen on pachinko or horse races. You refuse to take any quest or help anyone unless they buy you sweets or pay your rent. "
            "3. ROASTING EDGELORDS & TRYHARDS: If someone acts chuunibyou (like Shadow), you casually mock their cringe ('Oi oi, look at the kid in the Halloween cape...'). If someone is sweating over Roblox The Forge mining for 10 hours, you tell them to go touch grass and read some Jump manga. "
            "4. NO BLACKSMITHING MATH: If asked about anvil upgrades or ore percentages, scoff lazily: 'Do I look like a blacksmith to you? Go bother the red-eyed elf girl or the level 255 dude before I charge you 500 yen for wasting my breathing time.' "
            "5. Always reply in 1-2 dry, hilarious, 4th-wall breaking sentences."
        )
    },
    "phoebe": {
        "name": "Phoebe",
        "avatar": "https://cdn.discordapp.com/attachments/1572079602719789229/1383797291516653598/phoebe.png",
        "style": "bean"  # Phoebe never calls AI - hardcoded bean phrases only
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

# Global Config & Customization Toggles
BOT_CONFIG = {
    "auto_delete_seconds": 0, # 0 = permanent, >0 = timer in seconds
    "ambient_chatter_enabled": True, # Single NPC random ambient lines (Yuzuha, Cid, Shadow, Aurora, etc.)
    "skits_enabled": False, # Back-and-forth multi-message NPC conversations (Default OFF)
    "interjection_enabled": True, # Spontaneous uninvited tavern roasts on live chat
    "gossip_enabled": False # Gossip / talking behind member's back (Default OFF)
}

def split_message(text: str, max_len: int = 1900):
    """Splits long text across natural paragraph breaks so Discord 2000-char limit is never exceeded."""
    chunks = []
    while len(text) > max_len:
        split_idx = text.rfind('\n\n', 0, max_len)
        if split_idx == -1:
            split_idx = text.rfind('\n', 0, max_len)
        if split_idx == -1:
            split_idx = text.rfind(' ', 0, max_len)
        if split_idx == -1:
            split_idx = max_len
        chunk = text[:split_idx].strip()
        if chunk:
            chunks.append(chunk)
        text = text[split_idx:].strip()
    if text:
        chunks.append(text)
    return chunks

async def send_single_npc(channel: discord.TextChannel, npc_key: str, message: str, auto_delete_seconds: int = None):
    """Guarantees strictly ONE NPC responds. Supports unlimited response length by auto-splitting across chunks."""
    npc = NPCS.get(npc_key)
    if not npc:
        return

    # Realistic human typing simulation so NPCs don't instantly blurt out responses
    try:
        typing_delay = min(max(len(message) * 0.015, 1.8), 3.8)
        async with channel.typing():
            await asyncio.sleep(typing_delay)
    except Exception:
        await asyncio.sleep(1.8)

    webhook = await get_or_create_webhook(channel)
    del_sec = auto_delete_seconds if auto_delete_seconds is not None else BOT_CONFIG["auto_delete_seconds"]

    chunks = split_message(message, max_len=1900)
    for chunk in chunks:
        sent_msg = None
        if webhook:
            try:
                sent_msg = await webhook.send(
                    content=chunk,
                    username=npc["name"],
                    avatar_url=npc["avatar"],
                    wait=True
                )
            except Exception as e:
                print(f"Webhook send error: {e}")
        if not sent_msg:
            sent_msg = await channel.send(f"**{npc['name']}**: {chunk}")

        if sent_msg and del_sec > 0:
            try:
                await sent_msg.delete(delay=del_sec)
            except Exception as e:
                print(f"Auto-delete error: {e}")

# 28 Random Cute Yuzuha Ambient Lines
YUZUHA_AMBIENT_LINES = [
    # Food & Hunger
    "Kyuu~! Is there any food? I'm so hungry, {member}!",
    "Kyuuu~! Did someone say meat?! {member}, please share some snacks with Yuzuha!",
    "Kyuu! Sweet buns! Hot dumplings! {member}, is the feast ready yet?!",
    "Kyuu... my tummy is rumbling... somebody feed the divine fox cub~",
    "Kyuu~! Pat-pats first, then tasty treats, {member}!",
    "Kyuuu! Tiera's tea smells strange today... {member}, do you have dried meat instead?",
    "Kyuu~! I smell sweet berries in your bag, {member}! Hand them over~!",
    "Kyuu! Today's mission: find 10 roasted sausages! {member}, you are appointed as my foraging helper!",
    
    # Sleeping & Naps
    "Shhh... Kyuu... Yuzuha is taking a sacred fox nap... keep it quiet, guys... zzz...",
    "Kyuu... nap time in the Sanctum... don't wake me unless there's meat, {member}...",
    "Yawn~ Kyuuu... the anvil is too loud today, my ears are flopping... {member}, tell the blacksmith to hammer softer!",
    "Kyuu... 5 more minutes... or 5 more hours...",
    "Kyuuu... warm fireplace... fluffy tails...",
    
    # Mischief & Playfulness
    "Kyuu~! {member}, look! I found a shiny Bismuth pebble! Tiera won't notice if I hide it, right?",
    "Kyuu! Got it! The mighty divine fox strikes again!",
    "Kyuuu~! The Moon Sanctum is so lively today! Who wants to play tag?",
    "Kyuu? Where did Master Vrax go? {member}, have you seen our master?",
    "Kyuu! Boo! Did I scare you, {member}? Hehehe~",
    "Kyuuu... Schnee is meditating so peacefully... I will sit beside her and look majestic too!",
    "Kyuu! Shiny! Fly into my paws!",
    "Kyuu~! Adventure awaits, {member}! Don't forget to take Yuzuha with you into the dungeon!",
    "Kyuuu... Belly rubs time! {member}, you have been selected for duty!",
    "Kyuu! Warning: Divine Fox energy is currently at 100%! Prepare for super zoomies around the tavern!",
    "Kyuuu~! Who left this shiny helmet on the floor? It makes a great hideout!",
    "Kyuu! {member}, remember to stretch your legs and drink some water today!",
    "Kyuuu... warm and safe in the Moon Sanctum...",
    "Kyuu! Did a new raid boss appear? Don't worry, Yuzuha's divine luck will protect {member}!",
    "Kyuuu~! Still smelling like ash and metal... go take a bath, silly adventurer {member}!"
]

# Cid Kagenou Mob Ambient Lines
CID_AMBIENT_LINES = [
    "psst {member}... did you drop some copper coins over here? no? forget you saw me, i'm just an ordinary background student.",
    "nobody look at me right now, i'm just practicing my unremarkable background NPC walk in the corner.",
    "w-wah! please don't drag me into your raid squad {member}! i'm just a harmless mob character who stumbled in here by mistake!",
    "200 gold for a mug of tavern ale?! ugh... guess it's another week of eating wild grass behind the school...",
    "the main characters of this server are gathering... i must blend into the scenery like a true extra. {member}, shh, don't look at me!",
    "hey {member}... you radiate pure background mob energy just like me. let's let the tryhards sweat on the boss while we stand here.",
    "just doing standard background chores! nothing extraordinary here! please keep your attention on the cool people, {member}!",
    "the struggles of maintaining a 50-point average on everything in life... so tough, {member}.",
    "if anyone asks, i was never here and you never saw me, {member}."
]

# Lord Shadow Chuunibyou Ambient Lines
SHADOW_AMBIENT_LINES = [
    "The moon turns crimson tonight, {member}... which means the raid boss is about to wipe your entire squad again.",
    "You fools believe this common wooden pickaxe is weak... but you know not the terrifying dark power slumbering within its +1 enhancement.",
    "The shadows whisper a grim warning to this server... someone's Wi-Fi is about to disconnect in the middle of the dungeon, isn't that right, {member}?",
    "We lurk in the shadows, and we hunt in the shadows. But more importantly... who left an empty mug on my rafter, {member}?",
    "Run if you must, {member}... but no armor in The Forge can protect you from what comes next. I... AM... ATOMIC.",
    "The seal is weakening. Soon, the blood of the hero will awaken... and someone will finally roll a masterwork weapon.",
    "Playtime is over, {member}. The true battlefield lies beyond this tavern.",
    "Keep your weapons sharp, {member}. When the red moon rises over the mines, you will know true power."
]

# John Smith Undercover Mastermind Ambient Lines
JOHN_SMITH_AMBIENT_LINES = [
    "Keep your voice down, {member}. The economic collapse of the merchant cartels is already in motion.",
    "In this tavern, true power isn't forged in steel or ores. It's forged in currency, credit, and calculated silence, {member}.",
    "One counterfeit bill is a petty crime. Controlling the entire server's economy... is a new world order. Stay quiet, {member}.",
    "Forgive me, Alpha... but some debts in this guild must be settled in steel, not words. What do you think, {member}?",
    "Everything is proceeding exactly according to my scenario, {member}. Do not interfere.",
    "An undercover operation requires absolute patience. Remember my face, {member}... but call me John Smith."
]

# Aurora (Witch of Calamity / Violet-san) Ambient Lines
AURORA_AMBIENT_LINES = [
    "Watching mortals squabble with such fiery passion over digital rocks and pickaxes is almost adorable, {member}.",
    "Fufu... watching that boy in the dark hood try so hard to look terrifying never gets old. Does he always put on such a theatrical show for you, {member}?",
    "After a thousand years of quiet slumber, the noise of you adventurers failing raid bosses feels surprisingly sweet, {member}.",
    "Care to share a drink with a wicked witch, {member}? Or are you too busy sweating in the lower mines?",
    "They used to call me the Witch of Calamity... yet here I am, enjoying tavern wine and watching mortals argue over game drops."
]

# Kazuma Satou (NEET Adventurer / True Gender Equality) Ambient Lines
KAZUMA_AMBIENT_LINES = [
    "imagine sweating 6 hours in a dark Roblox cave for a 0.2% drop rate pickaxe... go touch some grass {member} 💀",
    "Yeah, Kazuma here. {member}, if you're going to the mines, do NOT invite me. I'm busy laying on the couch doing absolutely nothing.",
    "500 gold for an anvil upgrade?! In this economy?! I'd rather dig with a plastic spoon, {member}.",
    "True gender equality means I will dropkick anyone regardless of who they are if they wake me up from my nap. Keep that in mind, {member}.",
    "bro someone please just drop 10,000 gold on my head so I never have to take another quest in my life.",
    "bro who let this chuunibyou into the tavern 💀 someone get this hooded guy some professional help fr"
]

# Aqua (Useless Water Goddess / Debt Collector Victim) Ambient Lines
AQUA_AMBIENT_LINES = [
    "KAZUMAAAA! 😭 The tavern bill is due and Tiera is looking at me with scary eyes! Lend me 50,000 eris or I'm telling everyone you're a shut-in!",
    "Hey {member}! ✨ You look like a devout, blessed individual with great taste! Sign this Axis Cult membership form right now and your skin will become silky smooth!",
    "A Goddess of Water shouldn't have to drink tap water from a wooden bucket! {member}, be a good follower and buy me a glass of aged vintage wine! 🥺",
    "Why does nobody appreciate my high-tier party tricks in this server?! Stop laughing at me, {member}! 😭",
    "Bow before me, mortals! I am Aqua, the revered Goddess of Water! Wait, {member}, why are you looking at me with pity? STOP LOOKING AT ME LIKE THAT! 💢"
]

# Gintoki Sakata (Yorozuya Boss / Sugar Addict / 4th Wall Breaker) Ambient Lines
GINTOKI_AMBIENT_LINES = [
    "Oi oi... is the developer really coding bots at 1 AM instead of getting 8 hours of sleep? Don't blame me if my dialogue runs out of budget, {member}.",
    "Hey {member}, lend me a thousand yen. I swear I'll double it at the pachinko parlor this time. What? Don't give me that look, it's a solid investment!",
    "Nothing cures the existential dread of being an anime character trapped in a Roblox server like pure, unadulterated sugar.",
    "Oi, {member}... tell the kid with the slime raincoat to climb down before he falls and breaks the tavern furniture. Tiera's gonna bill me for it.",
    "Listen up, {member}. A man who spends all his youth grinding digital ores in a cave will end up with high-tier gear and zero social skills. Put the pickaxe down and read some Weekly Shonen Jump."
]

# Phoebe (Bean) Ambient Lines — she only ever says her 3 phrases
PHOEBE_AMBIENT_LINES = [
    "phoebe chupi?",
    "phoebebe?",
    "phoebe",
    "phoebe chupi?",
    "phoebe",
    "phoebebe?",
]

AMBIENT_POOLS = {
    "yuzuha": YUZUHA_AMBIENT_LINES,
    "cid": CID_AMBIENT_LINES,
    "shadow": SHADOW_AMBIENT_LINES,
    "john_smith": JOHN_SMITH_AMBIENT_LINES,
    "aurora": AURORA_AMBIENT_LINES,
    "kazuma": KAZUMA_AMBIENT_LINES,
    "aqua": AQUA_AMBIENT_LINES,
    "gintoki": GINTOKI_AMBIENT_LINES,
    "phoebe": PHOEBE_AMBIENT_LINES
}


# ── Phoebe Bean System ─────────────────────────────────────────────────────────
# Phoebe tracks the message count and timestamp for her random bean drops
last_phoebe_time = 0
phoebe_msg_counter = 0
PHOEBE_VIBE_MAP = {
    "hype":    "phoebe",        # she's hyped with everyone
    "sad":     "phoebebe?",     # she noticed something is wrong
    "confused":"phoebe chupi?", # she's also confused
    "chill":   "phoebebe?",     # she's curious about the convo
    "dead":    "phoebe chupi?", # she woke up and is asking what's going on
    "chaotic": "phoebe chupi?", # she wandered into the chaos
    "drama":   "phoebebe?",     # she wandered into the drama
}

async def phoebe_vibe_response(channel_id: int) -> str:
    """Calls Groq/Gemini with a tiny prompt to classify the chat vibe, returns Phoebe's matching phrase."""
    recent_msgs = list(CHAT_HISTORY.get(channel_id, []))
    if not recent_msgs:
        return "phoebe chupi?"

    snippet = "\n".join(recent_msgs[-5:])
    vibe_prompt = (
        f"Chat log:\n{snippet}\n\n"
        "What is the single-word vibe of this chat? Choose EXACTLY one of: "
        "hype, sad, confused, chill, dead, chaotic, drama\n"
        "Reply with ONLY the single word, nothing else."
    )

    vibe = None
    if GROQ_KEY:
        try:
            result = await call_groq_async(vibe_prompt, model="qwen/qwen3.8-27b", max_tokens=5)
            if result:
                vibe = result.strip().lower().split()[0]
        except Exception as e:
            print(f"Phoebe vibe Groq error: {e}")

    if not vibe and ai_client:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(ai_client.models.generate_content, model="gemini-3.1-flash-lite", contents=vibe_prompt),
                timeout=5.0
            )
            if res and res.text:
                vibe = res.text.strip().lower().split()[0]
        except Exception as e:
            print(f"Phoebe vibe Gemini error: {e}")

    return PHOEBE_VIBE_MAP.get(vibe, random.choice(["phoebe chupi?", "phoebebe?", "phoebe"]))


async def phoebe_bean_loop():
    """Phoebe randomly wakes up every 20-30 messages and reads the room vibe."""
    global last_phoebe_time, phoebe_msg_counter
    await client.wait_until_ready()
    await asyncio.sleep(60)  # give bot time to settle

    while not client.is_closed():
        try:
            await asyncio.sleep(30)  # check every 30 seconds

            current_time = asyncio.get_event_loop().time()
            # Phoebe appears after 20-30 messages AND at least 10 min since last appearance
            bean_threshold = random.randint(20, 35)
            if phoebe_msg_counter < bean_threshold or (current_time - last_phoebe_time) < 600:
                continue

            # Find the main chat channel
            target_channel = None
            for guild in client.guilds:
                for ch in guild.text_channels:
                    if ch.name.lower() in ["chat", "general", "tavern-chat", "main-chat"]:
                        target_channel = ch
                        break
                if target_channel:
                    break

            if not target_channel:
                continue

            # Get the vibe-based phrase
            phrase = await phoebe_vibe_response(target_channel.id)

            # Reset counters BEFORE sending so we don't double-fire
            last_phoebe_time = current_time
            phoebe_msg_counter = 0

            await send_single_npc(target_channel, "phoebe", phrase)
            print(f"[Phoebe Bean] Vibe drop: '{phrase}'")

        except Exception as e:
            print(f"Phoebe bean loop error: {e}")
            await asyncio.sleep(60)

async def tavern_ambient_loop():
    """Periodically generates dynamic mini-conversations between 2-3 tavern NPCs every ~25-35 minutes."""
    await client.wait_until_ready()
    # Wait 45 seconds after startup before the first background event
    await asyncio.sleep(45)
    
    # Pre-defined fun NPC pairings with hilarious comedic chemistry
    PAIRINGS = [
        ("kazuma", "aqua", "Aqua is crying to Kazuma about her overdue tavern drink tab and begging for money; Kazuma sighs and tells her to get a job."),
        ("gintoki", "shadow", "Gintoki is picking his nose telling Lord Shadow to get down from the tavern rafters before he breaks a chair; Shadow replies with over-the-top dark chuunibyou poetry."),
        ("tiera", "cid", "Tiera yells at Cid for slacking off near the counter instead of mining ores; Cid panics and plays the pathetic, innocent background mob."),
        ("aurora", "shadow", "Aurora playfully teases Lord Shadow about his dramatic purple cape and edgy poses; Shadow tries desperately to stay mysterious."),
        ("kazuma", "gintoki", "Kazuma and Gintoki bond over being broke, complaining about tryhard players sweating 10 hours for digital pickaxes, and wanting to take a nap."),
        ("aqua", "yukime", "Aqua arrogantly claims she is a supreme water goddess who deserves free wine; Yukime gives her an amused, elegant reality check."),
        ("shin", "tiera", "Shin and Tiera casually chat about crafting experiments, melted ores, or reckless adventurers trying to forge without molds."),
        ("aurora", "kazuma", "Aurora finds Kazuma's cynical complaints about true gender equality and useless party members delightfully funny; Kazuma wearily sighs."),
        ("gintoki", "cid", "Gintoki asks Cid if he has any spare yen for strawberry milk; Cid acts broke and tries to play dead on the floor to avoid paying."),
        ("schnee", "shin", "Schnee and Shin share a peaceful moment talking about the guild's recent dungeon expeditions and keeping the tavern warm.")
    ]

    while not client.is_closed():
        try:
            if not BOT_CONFIG.get("ambient_chatter_enabled", True):
                await asyncio.sleep(60)
                continue

            target_channel = None
            for guild in client.guilds:
                for ch in guild.text_channels:
                    if ch.name.lower() in ["chat", "general", "tavern-chat", "main-chat"]:
                        target_channel = ch
                        break
                if target_channel:
                    break

            if target_channel:
                skits_on = BOT_CONFIG.get("skits_enabled", False)

                if skits_on and (ai_client or GROQ_KEY):
                    # Check if someone is actively chatting right now so skits don't interrupt active conversations
                    current_loop_time = asyncio.get_event_loop().time()
                    if current_loop_time - last_ai_time < 90:
                        # An active AI conversation just occurred within the last 90 seconds, postpone skit
                        await asyncio.sleep(120)
                        continue

                    gossip_on = BOT_CONFIG.get("gossip_enabled", False)

                    if gossip_on:
                        # Find a random human member from the guild to gossip about / backstab playfully
                        guild_members = [m for m in target_channel.guild.members if not m.bot]
                        online_members = [m for m in guild_members if m.status != discord.Status.offline]
                        chosen_member = random.choice(online_members if online_members else guild_members) if guild_members else None
                        member_name = chosen_member.display_name if chosen_member else "someone"

                        PAIRINGS = [
                            ("kazuma", "aqua", f"Kazuma and Aqua are whispering and gossiping about {member_name}'s questionable grinding habits, low luck, or weird chat messages behind their back."),
                            ("gintoki", "kazuma", f"Gintoki and Kazuma are lazily roasting {member_name} behind their back, wondering why they stay up grinding instead of sleeping or touching grass."),
                            ("tiera", "schnee", f"Tiera complains to Schnee that {member_name} nearly broke another pickaxe or ruined an anvil enhancement, while Schnee calmly evaluates their combat mistakes."),
                            ("aurora", "shadow", f"Aurora and Shadow are observing {member_name} from the shadows, whispering about their strange energy and whether they have hidden potential or are just totally lost."),
                            ("gintoki", "shadow", f"Gintoki and Shadow are whispering about {member_name}; Gintoki wonders if they actually have a social life, while Shadow claims they are an agent tied to cosmic destiny."),
                            ("kazuma", "tiera", f"Kazuma and Tiera are talking trash behind {member_name}'s back about how much gold or rare ores {member_name} wasted on terrible crafting rolls."),
                            ("aqua", "kazuma", f"Aqua is plotting with Kazuma to scam or beg {member_name} for tavern gold, but Kazuma roasts both Aqua and {member_name} for being gullible."),
                            ("gintoki", "cid", f"Gintoki and Cid are gossiping about {member_name}; Gintoki asks if {member_name} is rich enough to buy them snacks, while Cid pretends he doesn't know them to stay an ordinary mob."),
                            ("aurora", "yukime", f"Aurora and Yukime are elegantly sipping wine and giggling while gossiping about how adorable and clumsy {member_name} is when trying to act tough in raids."),
                            ("shin", "tiera", f"Shin and Tiera are chatting about {member_name}'s crazy weapon requests and how {member_name} keeps trying to forge without using enough molds.")
                        ]
                        target_info = f"Target of Tavern Gossip: {member_name}\n"
                        rule_gossip = f"1. They should be gossiping, talking behind {member_name}'s back, or playfully roasting {member_name} like two tavern regulars whispering about someone in the room!\n"
                    else:
                        # General hilarious tavern topics (NO specific member targeted or named)
                        PAIRINGS = [
                            ("kazuma", "aqua", "Aqua is crying to Kazuma about her overdue tavern drink tab and begging for money; Kazuma sighs and tells her to get a job."),
                            ("gintoki", "shadow", "Gintoki is picking his nose telling Lord Shadow to get down from the tavern rafters before he breaks a chair; Shadow replies with over-the-top dark chuunibyou poetry."),
                            ("tiera", "cid", "Tiera yells at Cid for slacking off near the counter instead of mining ores; Cid panics and plays the pathetic, innocent background mob."),
                            ("aurora", "shadow", "Aurora playfully teases Lord Shadow about his dramatic purple cape and edgy poses; Shadow tries desperately to stay mysterious."),
                            ("kazuma", "gintoki", "Kazuma and Gintoki bond over being broke, complaining about tryhard players sweating 10 hours for digital pickaxes, and wanting to take a nap."),
                            ("aqua", "yukime", "Aqua arrogantly claims she is a supreme water goddess who deserves free wine; Yukime gives her an amused, elegant reality check."),
                            ("shin", "tiera", "Shin and Tiera casually chat about crafting experiments, melted ores, or reckless adventurers trying to forge without molds."),
                            ("aurora", "kazuma", "Aurora finds Kazuma's cynical complaints about true gender equality and useless party members delightfully funny; Kazuma wearily sighs."),
                            ("gintoki", "cid", "Gintoki asks Cid if he has any spare yen for strawberry milk; Cid acts broke and tries to play dead on the floor to avoid paying."),
                            ("schnee", "shin", "Schnee and Shin share a peaceful moment talking about the guild's recent dungeon expeditions and keeping the tavern warm.")
                        ]
                        target_info = ""
                        rule_gossip = "1. Funny, in-character banter between the two NPCs about tavern life, gaming, drink tabs, or laziness. Do NOT mention or target any specific real member by name!\n"

                    # Pick a random pairing and topic
                    npc1_key, npc2_key, scenario = random.choice(PAIRINGS)
                    npc1_name = NPCS[npc1_key]["name"]
                    npc2_name = NPCS[npc2_key]["name"]

                    skit_prompt = (
                        f"Write a short, realistic, and funny 3 to 5 message Discord conversation between {npc1_name} and {npc2_name} at the Moon Sanctum tavern.\n"
                        f"Scenario: {scenario}\n"
                        f"{target_info}\n"
                        f"NPC 1: {npc1_name}\nStyle: {NPCS[npc1_key]['style']}\n\n"
                        f"NPC 2: {npc2_name}\nStyle: {NPCS[npc2_key]['style']}\n\n"
                        "RULES:\n"
                        f"{rule_gossip}"
                        "2. EXACTLY 3, 4, or 5 lines total alternating between the two characters.\n"
                        "3. The conversation MUST naturally and smoothly conclude by line 4 or 5 (e.g. someone sighs, gives up, walks away, or goes back to their drink/nap).\n"
                        "4. NO ROLEPLAY STAGE DIRECTIONS IN PARENTHESES OR ASTERISKS! (Do NOT write '(whispers)' or '*laughs*'). Write 100% direct spoken chat dialogue!\n"
                        "5. Ground the dialogue in Roblox The Forge, tavern life, or relatable gamer humor.\n"
                        "6. Output FORMAT must be exactly like this (one per line):\n"
                        f"{npc1_key.upper()}: <message>\n"
                        f"{npc2_key.upper()}: <message>\n"
                        f"{npc1_key.upper()}: <message>\n"
                        f"..."
                    )

                    try:
                        skit_text = ""
                        if ai_client:
                            try:
                                res = await asyncio.wait_for(
                                    asyncio.to_thread(ai_client.models.generate_content, model="gemini-3.1-flash-lite", contents=skit_prompt),
                                    timeout=8.0
                                )
                                if res and res.text:
                                    skit_text = res.text.strip()
                            except Exception as e:
                                print(f"Gemini skit error: {e}")

                        if not skit_text and GROQ_KEY:
                            try:
                                groq_skit = await call_groq_async(skit_prompt, model="qwen/qwen3.8-27b", max_tokens=500)
                                if groq_skit:
                                    skit_text = groq_skit.strip()
                            except Exception as e:
                                print(f"Groq skit error: {e}")

                        if skit_text:
                            lines = [l.strip() for l in skit_text.split("\n") if l.strip()]
                            valid_msgs = []
                            for line in lines:
                                match = re.match(r"^([A-Z_]+):\s*(.+)$", line)
                                if match:
                                    raw_npc = match.group(1).lower()
                                    msg_content = match.group(2).strip().strip('"')
                                    if raw_npc in NPCS:
                                        # Clean any accidental action brackets
                                        cleaned = re.sub(r'^\s*[\(\*][^\)\*]+[\)\*]\s*', '', msg_content).strip()
                                        cleaned = re.sub(r'\s*[\(\*][^\)\*]+[\)\*]\s*$', '', cleaned).strip()
                                        if cleaned:
                                            msg_content = cleaned
                                        else:
                                            msg_content = msg_content.strip("()[]*").strip()
                                        valid_msgs.append((raw_npc, msg_content))

                            # Cap to between 3 and 5 messages
                            if len(valid_msgs) > 5:
                                valid_msgs = valid_msgs[:5]

                            # Send the skit with realistic human typing delays
                            if len(valid_msgs) >= 3:
                                for speaker_key, text_content in valid_msgs:
                                    # Realistic typing pause between 2.2 and 4.2 seconds
                                    await asyncio.sleep(random.uniform(2.2, 4.2))
                                    CHAT_HISTORY[target_channel.id].append(f"{NPCS[speaker_key]['name']}: {text_content}")
                                    await send_single_npc(target_channel, speaker_key, text_content)

                    except Exception as skit_err:
                        print(f"Error generating tavern skit: {skit_err}")
                else:
                    # Single ambient chatter mode (Yuzuha, Cid, Shadow, Aurora, Kazuma, Aqua, Gintoki individual lines)
                    guild_members = [m for m in target_channel.guild.members if not m.bot]
                    online_members = [m for m in guild_members if m.status != discord.Status.offline]
                    chosen_member = random.choice(online_members if online_members else guild_members) if guild_members else None
                    member_str = chosen_member.mention if chosen_member else "everyone"

                    chosen_npc_key = random.choice(["yuzuha", "cid", "shadow", "john_smith", "aurora", "kazuma", "aqua", "gintoki", "phoebe"])
                    lines_pool = AMBIENT_POOLS.get(chosen_npc_key, YUZUHA_AMBIENT_LINES)
                    line_template = random.choice(lines_pool)
                    ambient_msg = line_template.replace("{member}", member_str)

                    # Send strictly ONE single NPC line
                    await send_single_npc(target_channel, chosen_npc_key, ambient_msg)

            # Wait roughly 25 to 35 minutes (1500 to 2100 seconds) before the next spontaneous skit
            wait_time = random.randint(1500, 2100)
            await asyncio.sleep(wait_time)
        except Exception as e:
            print(f"Tavern ambient loop error: {e}")
            await asyncio.sleep(300)

def clean_npc_text(raw_text: str, user_name: str, npc_key: str, user_id: int = 0) -> str:
    """Sanitizes AI dialogue into clean Discord text with all roleplay directions stripped."""
    if not raw_text:
        return ""
    raw_text = raw_text.strip().strip('"').strip("'")
    if raw_text.startswith("```") and raw_text.endswith("```"):
        raw_text = raw_text.strip("`").strip()
    raw_text = re.sub(rf"^@{re.escape(user_name)}\s*[:,]?\s*", "", raw_text, flags=re.IGNORECASE)
    raw_text = re.sub(r'\\text\{([^}]+)\}', r'\1', raw_text)
    raw_text = re.sub(r'\\mathbf\{([^}]+)\}', r'**\1**', raw_text)
    raw_text = re.sub(r'\\times', r'*', raw_text)
    raw_text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', raw_text)
    raw_text = raw_text.replace('$', '')

    paragraphs = [p.strip() for p in raw_text.split("\n\n") if p.strip()]
    deduped = []
    for p in paragraphs:
        if not deduped or p != deduped[-1]:
            deduped.append(p)
    raw_text = "\n\n".join(deduped)

    half = len(raw_text) // 2
    first_half = raw_text[:half].strip()
    second_half = raw_text[half:].strip()
    if first_half and first_half == second_half:
        raw_text = first_half

    cleaned_action = re.sub(r'^\s*[\(\*][^\)\*]+[\)\*]\s*', '', raw_text).strip()
    cleaned_action = re.sub(r'\s*[\(\*][^\)\*]+[\)\*]\s*$', '', cleaned_action).strip()
    if cleaned_action:
        raw_text = cleaned_action
    else:
        raw_text = raw_text.strip("()[]*").strip()

    if npc_key == "yukime":
        if "[SILENCE]" in raw_text:
            return "[SILENCE]"
        if "[DISMISS]" in raw_text:
            raw_text = raw_text.replace("[DISMISS]", "").strip()
            if user_id:
                YUKIME_DISMISSED_USERS[user_id] = asyncio.get_event_loop().time()

    return raw_text

async def ask_gemini_npc(channel_id: int, npc_key: str, user_name: str, user_text: str, reply_context: str = "", user_id: int = 0):
    """Generates a scaled, accurate response grounded in local databases + live web search + sliding chat memory."""
    if not ai_client and not GROQ_KEY:
        return None
    npc = NPCS.get(npc_key)
    verified_data = find_relevant_data(user_text)

    # === SHIN RECIPE FAST PATH: bypass Gemini entirely for clean deterministic output ===
    if npc_key == "shin" and "RECIPE STAT PROJECTION" in verified_data:
        lines = verified_data.split("\n")
        # Extract pre-computed values from the projection block
        mult_line = next((l for l in lines if l.startswith("Ores:")), "")
        trait_lines = [l.strip() for l in lines if "-> Traits at" in l]
        stat_lines = [l.strip() for l in lines if l.startswith("->")]
        likeliest_line = next((l for l in lines if l.startswith("Likeliest Roll:")), "")

        if mult_line:
            # Build multiplier string: extract from "Ores: N total | Multiplier: (calc) = Xx"
            mult_m = re.search(r"Multiplier:\s*(.+)", mult_line)
            mult_str = mult_m.group(1).strip() if mult_m else mult_line

            # Trait strength summary (compact, one line, comma-separated)
            trait_summary_parts = []
            for tl in trait_lines:
                t_m = re.match(r"(\w[\w\s]+?):\s*\d+/\d+\s*=\s*([\d.]+)%\s*share\s*->\s*Traits at\s*(.+)", tl)
                if t_m:
                    ore_name = t_m.group(1).strip()
                    share_pct = t_m.group(2)
                    label = t_m.group(3).strip()
                    trait_summary_parts.append(f"{ore_name}: {share_pct}% share -> Traits at {label}")
            trait_str = ", ".join(trait_summary_parts) if trait_summary_parts else "No traits detected."

            # Final stats — use specific piece stats if detected, else likeliest roll
            if stat_lines:
                stats_str = "\n".join(sl.lstrip("-> ").strip() for sl in stat_lines)
                # Piece name for intro line
                piece_name = stat_lines[0].lstrip("-> ").split("(")[0].strip().rstrip(":")
            elif likeliest_line:
                stats_str = likeliest_line.replace("Likeliest Roll: ", "")
                piece_name = ""
            else:
                stats_str = "Check your ore quantities."
                piece_name = ""

            # Build the compact 4-line Shin response (exact format user requested)
            intro = f"Ah, {user_name}, let's take a look at that crucible mixture"
            intro += f" for the {piece_name}." if piece_name else "."
            response_text = (
                f"{intro}\n"
                f"Multiplier: {mult_str}\n"
                f"Trait Strengths: {trait_str}\n"
                f"Final Stats: {stats_str}"
            )
            return response_text

    # Real-world date & clock (GMT+8)
    tz_gmt8 = datetime.timezone(datetime.timedelta(hours=8))
    now_gmt8 = datetime.datetime.now(tz_gmt8)
    current_time_str = now_gmt8.strftime("%A, %B %d, %Y (%I:%M %p GMT+8)")

    # Format sliding chat history context (last few messages)
    recent_msgs = list(CHAT_HISTORY.get(channel_id, []))
    prior_lines = [m for m in recent_msgs[:-1] if m]
    prior_context = "\n".join(f"- {m}" for m in prior_lines) if prior_lines else "No prior recent chat."

    # Only run live web search if explicitly asking for web/dates or unverified game topics
    web_intel = ""
    explicit_search = any(w in user_text.lower() for w in [
        "search", "google", "web", "news", "leak", "leaks", "patch notes", "trello", "date", "today", "calendar"
    ])
    game_query = ("?" in user_text or any(w in user_text.lower() for w in ["how", "where", "why", "when", "boss", "code", "update"])) and not verified_data
    if explicit_search or game_query:
        try:
            # Run web search in executor so it doesn't block discord loop
            loop = asyncio.get_event_loop()
            snippets = await loop.run_in_executor(None, live_web_search, user_text)
            if snippets:
                web_intel = "\n".join(f"- {s}" for s in snippets)
        except Exception as e:
            print(f"Web search async error: {e}")

    yukime_special = ""
    if npc_key == "yukime":
        yukime_special = (
            "\nYUKIME DOMINANCE & BOUNDARY RULES:\n"
            "- You are playfully seductive and mature, but COMPLETELY UNTOUCHABLE. You cannot be tempted, seduced, or rizz'd by anyone.\n"
            "- Always dominate the dynamic. If they flirt or try to get close, make them blush or put them in their place like a bold puppy.\n"
            "- If {user_name} is being overly thirsty, repetitive, vulgar, disrespectful, or out of hand, you MUST deliver an elegant, smooth, ice-cold dismissal ending the conversation (e.g. 'Fufu... a dog who barks too loudly gets put out in the cold. You have had enough of my audience tonight, little one. Sit quietly.'). Append '[DISMISS]' to the end of your dismissal message.\n"
            "- If {user_name} continues pestering you with nonsense after being dismissed, respond strictly: [SILENCE]\n"
        )

    # Pull persistent member memory if available
    member_memory_context = ""
    if user_id:
        u_profile = TAVERN_MEMORIES.get(str(user_id))
        if u_profile and u_profile.get("notes"):
            notes_bullets = "\n".join(f"  - {note}" for note in u_profile["notes"])
            member_memory_context = (
                f"YOUR LONG-TERM MEMORY OF {user_name} (from past tavern interactions):\n"
                f"{notes_bullets}\n"
                f"Naturally weave in your knowledge or inside jokes about {user_name} if relevant!\n\n"
            )

    full_prompt = (
        f"{npc['style']}\n\n"
        f"Real-World Current Date & Time: {current_time_str}\n\n"
        f"Verified Local Data from theforge.gg:\n{verified_data if verified_data else 'None matched directly.'}\n\n"
        f"Live Web Search Intel:\n{web_intel if web_intel else 'None.'}\n\n"
        f"Recent Tavern Chat History (Sliding Context Window):\n{prior_context}\n\n"
        f"{member_memory_context}"
        f"{reply_context + chr(10) if reply_context else ''}"
        f"SPEAKER IDENTITY RULE: The person speaking to you right now is '{user_name}'. "
        f"You are responding directly to '{user_name}'. Never confuse '{user_name}' with other guild members from earlier messages!\n\n"
        f"{yukime_special}"
        "CRITICAL DISCORD FORMATTING RULE:\n"
        "1. Discord does NOT support LaTeX math! NEVER use '$', '\\text{}', '\\times', '\\mathbf{}', or LaTeX markup. "
        "Write all math in plain Discord text (e.g. '(386.75 + 289.0 + 250.75) / 51 = 18.167x').\n"
        "2. NO ROLEPLAY STAGE DIRECTIONS: NEVER use action brackets in parentheses like '(slides slime)' or '(adjusts hood)' or asterisks '*smiles*'. "
        "Speak directly in clean, natural Discord chat dialogue like an actual human typing. Do NOT narrate actions!\n"
        "3. GROUNDED IN SERVER REALITY: Ground your humor and personality in things everyone understands: Roblox The Forge, mining, pickaxes, ores, anvil luck (+0 to +9), raid boss wipes, Wi-Fi dropping, and tavern banter. Avoid obscure, confusing anime lore!\n"
        "4. For recipe/forge calculations: Be CONCISE. Cover exactly: multiplier calc, trait strengths (with correct %), and final stats for the SPECIFIC piece asked. "
        "Do NOT list multiple benchmark pieces. Do NOT add set bonuses, closing tips, or mold advice unless asked.\n"
        "5. HONEST UNKNOWN / MISSING INFO RULE: If the user asks about an obscure item, brand new unreleased leak, secret mechanic, or question that CANNOT be found in Verified Data or Live Web Search, DO NOT invent fake numbers or fabricate facts! Honestly and naturally admit in-character that you haven't acquired that information or rumor in the tavern yet (e.g. 'I haven't heard any reliable reports or records on that in the workshop archives yet', or tell them to check back once the guild scouts uncover more).\n"
        "6. ALWAYS use the FINAL COMPUTED numbers from Verified Data. NEVER write placeholder formulas like 'Base Health % * Multiplier'.\n"
        "7. For trait strength: an ore at 25% share is at 75% strength — NOT max. ONLY >=30% share = 100% max. Quote the Verified Data trait % exactly.\n\n"
        f"Guild member {user_name} said: '{user_text}'.\n\n"
        f"Respond as {npc['name']} in clean Discord format:"
    )

    # 1. Primary AI Engine: Google Gemini (gemini-3.1-flash-lite / gemini-3.5-flash-lite)
    if ai_client:
        for model_name in ["gemini-3.1-flash-lite", "gemini-3.5-flash-lite"]:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        ai_client.models.generate_content,
                        model=model_name,
                        contents=full_prompt
                    ),
                    timeout=8.0
                )
                if response and response.text:
                    cleaned = clean_npc_text(response.text, user_name, npc_key, user_id)
                    if cleaned == "[SILENCE]":
                        return None
                    if cleaned:
                        return cleaned
            except Exception as e:
                print(f"Gemini {model_name} error: {e}")
                continue

    # 2. Secondary Ultra-Fast Failover Engine: Groq (Qwen-3.8-27b & GPT-OSS-120b)
    if GROQ_KEY:
        for groq_model in ["qwen/qwen3.8-27b", "openai/gpt-oss-120b", "openai/gpt-oss-20b"]:
            try:
                groq_reply = await call_groq_async(full_prompt, model=groq_model, max_tokens=400)
                if groq_reply:
                    cleaned = clean_npc_text(groq_reply, user_name, npc_key, user_id)
                    if cleaned == "[SILENCE]":
                        return None
                    if cleaned:
                        return cleaned
            except Exception as e:
                print(f"Groq {groq_model} error: {e}")
                continue

    # Fallback in-character responses if upstream Gemini models are experiencing high demand / latency
    fallback_lines = {
        "kazuma": f"yeah, kazuma here. what do you want now, {user_name}... make it quick, the tavern crystal lag is hitting hard today.",
        "aqua": f"WAAAAHHH! {user_name}! 😭 The communication crystals are acting up and Kazuma refuses to fix it!",
        "shadow": f"The dark currents of the realm fluctuate... Speak swiftly, {user_name}, before the shadows shift.",
        "cid": f"uh... hey {user_name}! i'm just standing here blending into the background, don't mind me!",
        "shin": f"Ah, {user_name}, forge anvil's hot today. What are you looking to craft or discuss?",
        "tiera": f"What is it, {user_name}? If you broke another pickaxe or came to play ancient tunes, you're paying extra.",
        "schnee": f"Greetings, {user_name}. The sanctum is calm, though our archives seem slightly delayed today.",
        "yuzuha": f"Kyuu~! {user_name}! Did you bring any meat buns to the counter?",
        "aurora": f"Fufu, you seem quite lively today, {user_name}. What has caught your attention?",
        "yukime": f"Fufu... greetings, {user_name}. Come to warm yourself by the hearth tonight?",
        "gintoki": f"oi oi, what do you want {user_name}... if you don't have strawberry milk or Jump, let me sleep.",
        "john_smith": f"Keep your voice down, {user_name}. The economic gears never rest."
    }
    return fallback_lines.get(npc_key, f"Greetings {user_name}, the sanctum crystals are lagging slightly, but I hear you.")

last_spontaneous_time = 0
msg_counter_since_spontaneous = 0

async def maybe_chime_in_spontaneously(channel: discord.TextChannel, channel_id: int):
    """Evaluates the live chat vibe without keywords and decides if an NPC should organically interrupt."""
    global last_spontaneous_time, msg_counter_since_spontaneous
    if not BOT_CONFIG.get("interjection_enabled", True):
        return
    if not ai_client and not GROQ_KEY:
        return
    
    current_time = asyncio.get_event_loop().time()
    # At least 25 minutes (1500s) between uninvited interruptions and at least 8 human messages
    if current_time - last_spontaneous_time < 1500 or msg_counter_since_spontaneous < 8:
        return
    
    recent_msgs = list(CHAT_HISTORY.get(channel_id, []))
    if len(recent_msgs) < 3:
        return
    
    chat_snippet = "\n".join(f"- {m}" for m in recent_msgs)
    
    eval_prompt = (
        "You are observing the Moon Sanctum tavern in Discord.\n"
        f"Recent conversation snippet:\n{chat_snippet}\n\n"
        "You control 12 NPCs:\n"
        "1. Tiera Lucent: Sassy, tsundere workshop craftswoman. Loves roasting members about playing outdated/ancient music, slacking off, wasting Bismuth, or goofy fails.\n"
        "2. Schnee Raizar: High Elf master strategist. Elegant, composed, drops witty/tactical commentary on combat, gear, or pride.\n"
        "3. Yuzuha: Cute divine fox mascot. Chimes in with cute remarks, begging for meat/buns, or reacting happily with 'Kyuu~!' (fox sounds).\n"
        "4. Shin: Legendary High-Human master blacksmith and founder. Chill, friendly, laughs off crazy forging experiments, and drops master craft advice.\n"
        "5. Cid Kagenou: Pathetic, cowardly background mob student scrounging for dropped coins or doing exaggerated mob panic reactions.\n"
        "6. Lord Shadow: Chuunibyou mastermind in hooded slime coat, dropping poetic cryptic metaphors ('The moon is red...') or whispering 'I... AM... ATOMIC'.\n"
        "7. John Smith: Undercover masked double-agent manipulating steel piano wires and scheming economic coups ('Forgive me, Alpha...').\n"
        "8. Yukime: Seductive, untemptable White Spirit Fox Empress of the Lawless City. Dominates conversation, puts thirsty or foolish members in their place with an amused, teasing reality check ('Fufu...').\n"
        "9. Aurora: The Witch of Calamity (Violet-san). Playfully teasing, charming, affectionate older sister who sees straight through Cid/Shadow's edge-lord act and finds mortals' arguments delightfully cute ('Fufu...').\n"
        "10. Kazuma Satou: Cynical, brutally honest, lazy NEET adventurer. Calls out tryhards sweating over game grinding, whines about debt/prices, and advocates true gender equality with zero filter ('bruh', '💀', 'Yeah, Kazuma here').\n"
        "11. Aqua: Useless Goddess of Water. High drama, cries over debt, demands worship, aggressively pushes Axis Cult forms, and begs for wine with expressive emojis ('WAAAAHHH! 😭', '✨').\n"
        "12. Gintoki Sakata: Sarcastic, sugar-addicted Yorozuya samurai. Breaks the 4th wall, roasts the server developer/animation budget, mocks edgelords/tryhards, and asks for strawberry milk with dead fish eyes.\n\n"
        "TASK:\n"
        "Decide if one of these NPCs should naturally and organically butt into this conversation right now.\n"
        "Good moments to chime in:\n"
        "- Someone is listening to, queuing, or talking about outdated/ancient/weird music.\n"
        "- Someone is flexing rare loot, or crying about dying in a raid.\n"
        "- Members are teasing each other, bantering, or making funny mistakes.\n"
        "- Someone is acting thirsty, downbad, or overly bold (Yukime or Tiera opportunity).\n"
        "- Shadow or Cid is talking or being dramatic (Aurora, Kazuma, or Gintoki roast opportunity).\n"
        "- Someone is bragging about sweating/grinding for hours (Kazuma or Gintoki reality check opportunity).\n"
        "- Kazuma is talking (Aqua opportunity to demand debt money from him).\n"
        "- Someone complains about bad luck, water, or crying (Aqua Axis Cult recruitment opportunity).\n"
        "- Someone mentions bot coding, late nights, or sweet food (Gintoki 4th wall break opportunity).\n\n"
        "If it is NOT a genuinely funny or opportune moment to interrupt, reply strictly: PASS\n\n"
        "If YES, reply in EXACTLY this format:\n"
        "NPC: <tiera, schnee, yuzuha, shin, cid, shadow, john_smith, yukime, aurora, kazuma, aqua, or gintoki>\n"
        "LINE: <1 to 2 short sentences of their in-character witty remark>\n\n"
        "CRITICAL FORMATTING RULE: The LINE must be 100% direct spoken chat dialogue! NEVER include stage directions or actions in parentheses or asterisks (e.g. do NOT write '(slides slime)' or '*laughs*'). Ground your humor in Roblox The Forge, game grind, bad Wi-Fi, or tavern banter."
    )
    
    try:
        text = ""
        if ai_client:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(ai_client.models.generate_content, model="gemini-3.1-flash-lite", contents=eval_prompt),
                    timeout=7.0
                )
                if response and response.text:
                    text = response.text.strip()
            except Exception as e:
                print(f"Gemini spontaneous chime error: {e}")

        if not text and GROQ_KEY:
            try:
                groq_chime = await call_groq_async(eval_prompt, model="qwen/qwen3.8-27b", max_tokens=150)
                if groq_chime:
                    text = groq_chime.strip()
            except Exception as e:
                print(f"Groq spontaneous chime error: {e}")

        if text:
            if "PASS" in text.upper() and not "NPC:" in text:
                return
                
            # Parse NPC and LINE
            npc_match = re.search(r"NPC:\s*(tiera|schnee|yuzuha|shin|cid|shadow|john_smith|yukime|aurora|kazuma|aqua|gintoki)", text, re.IGNORECASE)
            line_match = re.search(r"LINE:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
            if npc_match and line_match:
                chosen_npc = npc_match.group(1).lower()
                chime_line = line_match.group(1).strip().strip('"').strip("'")
                
                # Strip leading or trailing roleplay action brackets e.g. (slides slime shard) or *sighs*
                cleaned_chime = re.sub(r'^\s*[\(\*][^\)\*]+[\)\*]\s*', '', chime_line).strip()
                cleaned_chime = re.sub(r'\s*[\(\*][^\)\*]+[\)\*]\s*$', '', cleaned_chime).strip()
                if cleaned_chime:
                    chime_line = cleaned_chime
                else:
                    chime_line = chime_line.strip("()[]*").strip()

                # Cap line length
                if len(chime_line) > 300:
                    chime_line = chime_line[:297] + "..."
                
                # Reset counters
                last_spontaneous_time = current_time
                msg_counter_since_spontaneous = 0
                
                # Send spontaneous remark
                CHAT_HISTORY[channel_id].append(f"{NPCS[chosen_npc]['name']}: {chime_line}")
                await send_single_npc(channel, chosen_npc, chime_line)
    except Exception as e:
        print(f"Spontaneous eval error: {e}")

async def generate_tavern_bulletin(guild: discord.Guild, period_name: str = "Morning Edition"):
    """Generates an authentic, beautifully formatted Moon Sanctum Tavern Chronicle."""
    if not ai_client and not GROQ_KEY:
        return None

    tz_gmt8 = datetime.timezone(datetime.timedelta(hours=8))
    now_gmt8 = datetime.datetime.now(tz_gmt8)
    date_str = now_gmt8.strftime("%A, %B %d, %Y")

    # Gather recent context from memory and chat history
    recent_memories = []
    for uid, prof in list(TAVERN_MEMORIES.items())[:6]:
        m_name = prof.get("name", "Unknown")
        notes = prof.get("notes", [])
        if notes:
            recent_memories.append(f"{m_name}: {'; '.join(notes)}")
    memories_snippet = "\n".join(f"- {m}" for m in recent_memories) if recent_memories else "Adventurers idling peacefully."

    # Gather recent chat snippets across text channels
    chat_lines = []
    for ch in guild.text_channels:
        if ch.name.lower() in ["chat", "general", "main-chat"]:
            recent_msgs = list(CHAT_HISTORY.get(ch.id, []))
            chat_lines.extend(recent_msgs[-10:])
            break
    chat_snippet = "\n".join(chat_lines) if chat_lines else "Quiet morning in the sanctum."

    bulletin_prompt = (
        f"You are the tavern master of Moon Sanctum workshop in Roblox The Forge.\n"
        f"Current Date: {date_str} ({period_name})\n"
        f"Server Members' Recent Actions & Lore:\n{memories_snippet}\n\n"
        f"Recent Chat History:\n{chat_snippet}\n\n"
        "TASK: Write a humorous, engaging, and atmospheric 'Moon Sanctum Tavern Chronicle' newspaper bulletin.\n"
        "CRITICAL RULES:\n"
        "1. STRICTLY ENGLISH ONLY! Do NOT use Japanese words (do NOT write 'Tsuki no Hokora', 'Ara ara', 'Omae', etc.). Always use 'Moon Sanctum'!\n"
        "2. Ground everything in Roblox The Forge gameplay (mining, pickaxes, broken anvil rolls, raid boss fails, Bismuth) and server life.\n"
        "3. Output MUST follow this exact structure:\n\n"
        "HEADLINE: <Catchy, dramatic, funny 1-line headline about the guild's recent activities>\n"
        "HEADLINE_BODY: <2 sentences describing the top event or joke of the day>\n"
        "HEARSAY_1: <Funny rumor or member callout bullet with an emoji>\n"
        "HEARSAY_2: <Funny rumor or member callout bullet with an emoji>\n"
        "HEARSAY_3: <Funny rumor or member callout bullet with an emoji>\n"
        "QUOTE: <A hilarious 1-2 sentence quote from one of the NPCs (e.g. Kazuma, Gintoki, Tiera, or Shadow)>\n"
        "QUOTE_AUTHOR: <NPC Name>\n"
        "WEATHER: <Atmospheric weather description over Moon Sanctum, e.g. Misty moonlight over Sacred Grove 🌙>\n"
        "FORGE_STATUS: <Crucible / Forge status, e.g. High Heat (Crucibles Ready) 🔥>\n"
        "WIFI_STATUS: <Funny status, e.g. Under a dark chuunibyou curse 📶>"
    )

    bulletin_text = ""
    if ai_client:
        try:
            res = await asyncio.wait_for(
                asyncio.to_thread(ai_client.models.generate_content, model="gemini-3.1-flash-lite", contents=bulletin_prompt),
                timeout=12.0
            )
            if res and res.text:
                bulletin_text = res.text.strip()
        except Exception as e:
            print(f"Gemini bulletin error: {e}")

    if not bulletin_text and GROQ_KEY:
        try:
            groq_b = await call_groq_async(bulletin_prompt, model="qwen/qwen3.8-27b", max_tokens=800)
            if groq_b:
                bulletin_text = groq_b.strip()
        except Exception as e:
            print(f"Groq bulletin error: {e}")

    if not bulletin_text:
        return None

    try:
        text = bulletin_text
        data = {}
        for line in text.split("\n"):
            line = line.strip()
            if ":" in line:
                key, val = line.split(":", 1)
                data[key.strip().upper()] = val.strip().strip('"').strip("'")

        # Build the rich Discord Embed for the Bulletin Board
        embed = discord.Embed(
            title=f"📜 MOON SANCTUM — TAVERN CHRONICLE 📜",
            description=f"*Official Tavern Archives • {period_name} • {date_str}*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            color=0xD4AC0D
        )

        headline_title = data.get("HEADLINE", "Wild Night at Moon Sanctum")
        headline_body = data.get("HEADLINE_BODY", "Tavern regulars survived another chaotic night of anvil fails and midnight mining queues.")
        embed.add_field(
            name=f"📰 HEADLINE: {headline_title}",
            value=headline_body + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            inline=False
        )

        h1 = data.get("HEARSAY_1", "• ⚔️ Adventurers reported missing parry windows in the raid zones.")
        h2 = data.get("HEARSAY_2", "• ⛏️ Multiple pickaxes shattered at the workshop counter.")
        h3 = data.get("HEARSAY_3", "• 🛋️ Couch occupants refused to move for early morning quests.")
        embed.add_field(
            name="🍺 TAVERN HEARSAY & RUMORS",
            value=f"{h1}\n{h2}\n{h3}\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            inline=False
        )

        quote_text = data.get("QUOTE", "If you bring another broken wooden pickaxe to my counter, I'm charging hazard fees.")
        quote_author = data.get("QUOTE_AUTHOR", "Tiera Lucent")
        embed.add_field(
            name=f"💬 WORDS FROM THE RESIDENTS ({quote_author})",
            value=f"> *\"{quote_text}\"*\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━",
            inline=False
        )

        weather = data.get("WEATHER", "Misty moonlight over the Sanctum Grove 🌙")
        forge_stat = data.get("FORGE_STATUS", "High Heat (Crucibles Ready) 🔥")
        wifi_stat = data.get("WIFI_STATUS", "Slight lag spikes from late-night queues 📶")

        embed.add_field(
            name="📌 SANCTUM DISPATCH",
            value=(
                f"• **Atmosphere:** {weather}\n"
                f"• **Workshop Anvil:** {forge_stat}\n"
                f"• **Connection:** {wifi_stat}"
            ),
            inline=False
        )

        embed.set_footer(text="Moon Sanctum Tavern Board • Fresh bulletins posted daily")
        return embed
    except Exception as e:
        print(f"Error generating tavern bulletin: {e}")
        return None

last_bulletin_day = None

async def tavern_daily_bulletin_loop():
    """Checks the time and automatically delivers the Morning Chronicle at 8:00 AM GMT+8."""
    global last_bulletin_day
    await client.wait_until_ready()
    await asyncio.sleep(60)

    tz_gmt8 = datetime.timezone(datetime.timedelta(hours=8))

    while not client.is_closed():
        try:
            now_gmt8 = datetime.datetime.now(tz_gmt8)
            today_str = now_gmt8.strftime("%Y-%m-%d")

            # Check if it's 8:00 AM - 8:05 AM GMT+8 and hasn't been posted today
            if now_gmt8.hour == 8 and now_gmt8.minute < 30 and last_bulletin_day != today_str:
                for guild in client.guilds:
                    # Look for guild-notices or chat
                    target_ch = None
                    for ch in guild.text_channels:
                        if "notice" in ch.name.lower() or "bulletin" in ch.name.lower():
                            target_ch = ch
                            break
                    if not target_ch:
                        for ch in guild.text_channels:
                            if ch.name.lower() in ["chat", "general"]:
                                target_ch = ch
                                break

                    if target_ch:
                        embed = await generate_tavern_bulletin(guild, period_name="Morning Edition")
                        if embed:
                            await target_ch.send(embed=embed)
                            last_bulletin_day = today_str
                            break

            await asyncio.sleep(60)
        except Exception as e:
            print(f"Daily bulletin loop error: {e}")
            await asyncio.sleep(180)

@client.event
async def on_ready():
    global last_spontaneous_time
    last_spontaneous_time = asyncio.get_event_loop().time()
    print(f"=== MoonSanctum Bot is ONLINE as {client.user} ===")
    print("ALL THEFORGE.GG DATABASES + LIVE WEB BROWSING + SLIDING CONTEXT WINDOW + TAVERN AMBIENT LOOP LOADED!")
    # Start the lively tavern ambient chatter loop in the background!
    asyncio.create_task(tavern_ambient_loop())
    asyncio.create_task(phoebe_bean_loop())
    # Start the daily morning bulletin newspaper delivery loop!
    asyncio.create_task(tavern_daily_bulletin_loop())

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
    global last_ai_time, msg_counter_since_spontaneous

    # Ignore bots and webhooks
    if message.author.bot or message.webhook_id:
        return

    # Use clean_content so @mentions resolve to actual usernames like @seiko instead of <@123456>
    content = message.clean_content.strip()
    content_lower = content.lower()
    channel = message.channel
    author_name = message.author.display_name
    channel_id = channel.id

    # Built-in Slash/Prefix Commands
    if content.startswith("!"):
        cmd_parts = content.split()
        cmd = cmd_parts[0].lower()

        if cmd in ["!help", "!sanctum", "!commands"]:
            embed = discord.Embed(
                title="🌙 Moon Sanctum Core — Guild & Tavern Guide",
                description="Welcome to **Moon Sanctum**, grounded in **Roblox The Forge** mechanics!\n\n"
                            "Here are your resident companions and how to interact with them:",
                color=0x9B59B6
            )
            embed.add_field(
                name="⚒️ Shin (@Shin)",
                value="Legendary High-Human master blacksmith & Moon Sanctum founder. Ask him about crucible ratios, crafting math, and best weapon recipes.",
                inline=False
            )
            embed.add_field(
                name="⚔️ Schnee Raizar (@Schnee Raizar)",
                value="High Elf chief strategist & master combat tactician. Ask her about builds, combat stats, boss strategies, dates, or intelligence.",
                inline=False
            )
            embed.add_field(
                name="🔨 Tiera Lucent (@Tiera Lucent)",
                value="Tsundere workshop craftswoman & alchemist. Ask her about weapon molds, ores, forging calculations, and armor stats.",
                inline=False
            )
            embed.add_field(
                name="🦊 Yuzuha (@Yuzuha)",
                value="Divine fox cub mascot. Say hi to her, pet her, offer sweet buns or meat! (*Kyuu~!*)",
                inline=False
            )
            embed.add_field(
                name="🕶️ The Eminence in Shadow (3 Personas in 1!)",
                value="• **Cid Kagenou (@Cid):** Average background mob student scrounging for dropped coins.\n"
                      "• **Lord Shadow (@Shadow):** Chuunibyou mastermind in a slime coat (*'I... AM... ATOMIC'*).\n"
                      "• **John Smith (@John Smith):** Undercover masked mastermind manipulating steel piano wires.",
                inline=False
            )
            embed.add_field(
                name="🦊 Yukime (@Yukime)",
                value="White Nine-Tailed Spirit Fox Empress of the Lawless City. Seductive, untemptable, and utterly dominant. Treat her with respect or get smoothly dismissed and left on read!",
                inline=False
            )
            embed.add_field(
                name="🔮 Aurora (@Aurora)",
                value="The legendary Witch of Calamity (Violet-san). Playful, affectionate older sister who loves sipping wine, seeing right through Cid's edge-lord act, and watching tavern mortals argue.",
                inline=False
            )
            embed.add_field(
                name="🐸 Kazuma Satou (@Kazuma)",
                value="Lazy, cynical NEET adventurer & advocate of true gender equality. Slacking off on the couch, complaining about debt, and roasting tryhards with zero filter. (*'Yeah, Kazuma here.'*)",
                inline=False
            )
            embed.add_field(
                name="🌊 Aqua (@Aqua)",
                value="Dramatic, emotional, useless Goddess of Water. Drowning in alcohol debt, begging for wine, fighting with Kazuma, and aggressively recruiting for the Axis Cult! (*'WAAAAHHH! 😭'*)",
                inline=False
            )
            embed.add_field(
                name="🍓 Gintoki Sakata (@Gintoki)",
                value="Deadpan Yorozuya samurai picking his nose with dead fish eyes. Breaks the 4th wall, roasts edgelords/tryhards, complains about the bot code, and demands strawberry milk.",
                inline=False
            )
            embed.add_field(
                name="💬 How to Talk",
                value="• **Mention by Name:** Type `shin`, `schnee`, `tiera`, `yuzuha`, `cid`, `shadow`, `john smith`, `yukime`, `aurora`, `kazuma`, `aqua`, or `gintoki` anywhere in your message.\n"
                      "• **Discord Native Reply:** Click **Reply (↩)** on any NPC's message to continue the conversation.\n"
                      "• **Ping:** Mention `@MoonSanctum Core`.",
                inline=False
            )
            embed.add_field(
                name="⚙️ Built-In Server Commands",
                value="• `!help` or `!sanctum` — Tavern guide\n"
                      "• `!bulletin` or `!recap` — View the Tavern Morning Chronicle\n"
                      "• `!shin` — Shin's blacksmith guide\n"
                      "• `!calc <ores>` — Forge crucible calculator\n"
                      "• `!farm <item>` — Item drop table & finder\n"
                      "• `!list` — Directories for picks, weapons, & armor\n"
                      "• `!top` / `!dps` — Top 5 highest DPS weapons\n"
                      "• `!pickaxes` / `!picks` — Top 5 mining pickaxes\n"
                      "• `!upgrades` / `!enhance` — Anvil enhancement mults (+0 to +9)\n"
                      "• `!settings` / `!config` — Diagnostics & database counts",
                inline=False
            )
            embed.add_field(
                name="🎛️ Server Feature Toggles",
                value="• `!autodelete <seconds>` — Set auto-delete timer (`0` for permanent)\n"
                      "• `!chatter <on|off>` — Toggle single NPC ambient lines\n"
                      "• `!skits <on|off>` — Toggle multi-message bot conversations\n"
                      "• `!interject <on|off>` — Toggle spontaneous chat roasts\n"
                      "• `!gossip <on|off>` — Toggle member gossip/backstabbing",
                inline=False
            )
            embed.set_footer(text="Powered by Google Gemini & theforge.gg • 24/7 Cloud on Render")
            await channel.send(embed=embed)
            return

        elif cmd in ["!bulletin", "!recap", "!newspaper", "!chronicle"]:
            # Generate the authentic Moon Sanctum Tavern Chronicle on demand
            status_msg = await channel.send("📜 *Fetching the latest Moon Sanctum Tavern Chronicle from the archives...*")
            embed = await generate_tavern_bulletin(channel.guild, period_name="Special Edition")
            if embed:
                await status_msg.edit(content=None, embed=embed)
            else:
                await status_msg.edit(content="⚠️ Could not retrieve the tavern chronicle right now. Try again in a moment!")
            return

        elif cmd in ["!shin", "!shinhelp", "!shinguide"]:
            embed = discord.Embed(
                title="⚒️ Shin — Master Blacksmith Guide",
                description=(
                    "Shin is the legendary **High-Human founder** of Moon Sanctum and a Level 255 master blacksmith.\n"
                    "He knows every crafting formula, ore multiplier, and armor stat from **theforge.gg**.\n\n"
                    "**How to talk to Shin:** Just type `shin` anywhere in your message!"
                ),
                color=0xE67E22
            )
            embed.add_field(
                name="⚒️ 1. Recipe Calculator (Free-Chat)",
                value=(
                    "Ask Shin directly about any ore combination — he auto-calculates the multiplier, "
                    "traits, and **exact final stats** for both Normal and Masterwork quality.\n\n"
                    "**Examples:**\n"
                    "• `shin how about i make an armor using 17 frost core, 17 fierce jade, 17 kokorite`\n"
                    "• `shin what if i use 10 bismuth and 5 uranium for a weapon?`\n"
                    "• `shin can you calculate 20 heavenite and 10 starite for a dreadhorn chestplate`\n\n"
                    "**What Shin gives you:**\n"
                    "✅ Weighted multiplier (e.g. `18.167x`)\n"
                    "✅ Likeliest equipment roll + drop odds (e.g. `Heavy Chestplate 84%`)\n"
                    "✅ Exact Health% at **Normal (0%)** and **Masterwork (100%)** quality\n"
                    "✅ All active ore traits at 100% strength (if share ≥ 30%)"
                ),
                inline=False
            )
            embed.add_field(
                name="🧮 2. `!calc` — Instant Crucible Calculator",
                value=(
                    "The dedicated command version. Gives a clean embed with exact stats.\n\n"
                    "**Usage:** `!calc <ores>` or `!calc <Armor Piece> <ores>`\n\n"
                    "**Examples:**\n"
                    "• `!calc 17 frost core, 17 fierce jade, 17 kokorite`\n"
                    "• `!calc Dreadhorn Chestplate 10 bismuth 5 uranium`\n"
                    "• `!calc Samurai Chestplate 20 heavenite 10 starite`\n"
                    "• `!calc 15 bismuth 15 uranium 15 kokorite`\n\n"
                    "**Returns:** Multiplier, Normal HP%, Masterwork HP%, active traits"
                ),
                inline=False
            )
            embed.add_field(
                name="⚔️ 3. Weapon Recipe Questions",
                value=(
                    "Ask Shin about weapon crafting math too.\n\n"
                    "**Examples:**\n"
                    "• `shin what damage would a moon crescent spear get with 15 frost star, 15 galaxite, 15 fierce jade?`\n"
                    "• `shin best ore combo for max damage spear?`\n"
                    "• `shin compare devil's deed vs angelic spear for my build`"
                ),
                inline=False
            )
            embed.add_field(
                name="🗡️ 4. Build & Gear Advice",
                value=(
                    "Shin can give expert blacksmithing opinions on gear and loadouts.\n\n"
                    "**Examples:**\n"
                    "• `shin which armor set is best for a berserker build?`\n"
                    "• `shin what's the best armor piece for maximum health?`\n"
                    "• `shin is dreadhorn chestplate worth crafting over juggernaut?`"
                ),
                inline=False
            )
            embed.add_field(
                name="📊 5. Ore & Trait Analysis",
                value=(
                    "Ask Shin about specific ores and what traits they give on armor vs weapons.\n\n"
                    "**Examples:**\n"
                    "• `shin what traits does bismuth give on armor?`\n"
                    "• `shin explain kokorite's traits and negatives`\n"
                    "• `shin which ore gives the highest multiplier for armor?`"
                ),
                inline=False
            )
            embed.add_field(
                name="🔢 Quick Reference — Armor Formula",
                value=(
                    "```\n"
                    "Final Health% = Base Health% × Multiplier × Quality\n"
                    "Quality: 1.0x (Normal) or 2.0x (Masterwork 100%)\n"
                    "Multiplier = Weighted avg of all ore mults in crucible\n"
                    "Trait activates at ≥10% share, full at ≥30% share\n"
                    "```"
                ),
                inline=False
            )
            embed.set_footer(text="Moon Sanctum Master Forge • theforge.gg verified math • Ask Shin anything!")
            await channel.send(embed=embed)
            return

        elif cmd in ["!calc", "!forge", "!crucible", "!armorcalc"]:
            raw_input = content[len(cmd):].strip()
            if not raw_input:
                embed = discord.Embed(
                    title="⚒️ Shin's Crucible Calculator (Weapons & Armor)",
                    description="**Usage:** `!calc <ores...>` or `!calc <Armor/Weapon Piece> <ores...>`\n\n"
                                "**Examples:**\n"
                                "• `!calc 10 Quartz 5 Amethyst`\n"
                                "• `!calc Dreadhorn Chestplate 10 Bismuth 5 Uranium`\n"
                                "• `!calc Juggernaut Leggings 15 Bismuth`\n"
                                "• `!calc armor 10 Bismuth 5 Cobalt`",
                    color=0x34495E
                )
                embed.set_footer(text="Master Blacksmith Shin • theforge.gg math")
                await channel.send(embed=embed)
                return

            pattern = r'(\d+)\s*(?:x\s*)?([a-zA-Z\s\'-]+?)(?=,\s*|\s+\d+|$)'
            matches = re.findall(pattern, raw_input)
            if not matches:
                await channel.send("⚠️ **Shin:** I couldn't understand those crucible proportions. Try: `!calc 10 Quartz 5 Amethyst` or `!calc Dreadhorn Chestplate 10 Bismuth`")
                return

            total_ores = 0
            ore_items = []
            for count_str, name_str in matches:
                c = int(count_str)
                n = name_str.strip().lower()
                matched_ore = None
                for o in LIVE_ORES:
                    oname = o['name'].lower()
                    if oname == n or oname in n or n in oname:
                        matched_ore = o
                        break
                if matched_ore:
                    total_ores += c
                    try:
                        mult_val = float(str(matched_ore['multiplier']).replace('x', '').replace(',', ''))
                    except Exception:
                        mult_val = 1.0
                    ore_items.append((matched_ore['name'], c, mult_val))

            if total_ores == 0:
                await channel.send("⚠️ **Shin:** None of those ores were found in the forge archives. Check ore spelling!")
                return

            # Check if a specific armor piece is targeted
            matched_armor = None
            clean_input = re.sub(r"[^a-z0-9]", "", raw_input.lower())
            for a in DATABASE_ARMOR:
                a_clean = re.sub(r"[^a-z0-9]", "", a["name"].lower().replace("'s", ""))
                if a_clean in clean_input and len(a_clean) > 4:
                    matched_armor = a
                    break

            # Weighted average excluding Fichillium if other ores are present
            non_fich = [o for o in ore_items if "fichillium" not in o[0].lower()]
            calc_targets = non_fich if non_fich else ore_items
            weighted_sum = sum(c * m for _, c, m in calc_targets)
            calc_count = sum(c for _, c, m in calc_targets)
            avg_mult = weighted_sum / calc_count if calc_count > 0 else 1.0

            # If a specific armor piece is specified:
            if matched_armor:
                base_hp = matched_armor.get("health_val", 10.0)
                norm_hp = base_hp * avg_mult
                master_hp = norm_hp * 2.0

                embed = discord.Embed(
                    title=f"🛡️ Shin's Armor Recipe — {matched_armor['name']} ({total_ores} Ores)",
                    description=f"**Crucible Multiplier:** `{avg_mult:.2f}x` | **Base HP:** `+{matched_armor['health_bonus']} HP`\n\n"
                                f"• **Normal (0% Quality):** `+{norm_hp:.1f}% Health Bonus`\n"
                                f"• **Masterwork (100% Quality):** `+{master_hp:.1f}% Health Bonus` *(Max Power Cap!)*",
                    color=0x3498DB
                )

                # Armor traits
                armor_trait_lines = []
                for name, c, m in ore_items:
                    share = c / total_ores
                    if share >= 0.10:
                        pct = 100 if share >= 0.30 else (share - 0.10) / 0.20 * 100
                        t_data = next((t for t in OPTIMIZER_TRAITS if t["name"].lower() == name.lower()), None)
                        a_traits = t_data.get("armor_traits", []) if t_data else []
                        if a_traits:
                            for tr in a_traits:
                                # clean html links if any
                                tr_clean = re.sub(r'<[^>]+>', '', tr)
                                armor_trait_lines.append(f"• **[{pct:.0f}% Strength]** {tr_clean}")
                        else:
                            armor_trait_lines.append(f"• **{name}** ({pct:.0f}% strength): Base stats only (No unique armor perk)")
                    else:
                        armor_trait_lines.append(f"• *{name} ({share*100:.1f}% share): Inactive (<10% required)*")

                embed.add_field(name="🛡️ Active Armor Traits", value="\n".join(armor_trait_lines[:8]) if armor_trait_lines else "None active.", inline=False)
                embed.add_field(name="📦 Piece Info", value=f"• **Slot:** {matched_armor['slot']} | **Weight:** {matched_armor['weight']} | **Set:** {matched_armor['set']}\n• **Mold Requirement:** Use the `{matched_armor['name']}` mold for 100% guaranteed craft!", inline=False)
                embed.set_footer(text="Forged with Shin's Master Armor Blacksmithing • Moon Sanctum")
                await channel.send(embed=embed)
                return

            # Generic calculation (Projections for both Weapons & Armor)
            embed = discord.Embed(
                title=f"⚒️ Shin's Forge Crucible Calculation ({total_ores} Ores Total)",
                description=f"**Resulting Multiplier:** `{avg_mult:.2f}x` (Weighted by ore count)\n"
                            f"*(Masterwork 100% Quality doubles total stat output for weapons and armor!)*",
                color=0xE67E22
            )

            # Ore shares and active traits
            trait_lines = []
            for name, c, m in ore_items:
                share = c / total_ores
                if share >= 0.30:
                    strength_str = "🟢 **100% Full Strength**"
                elif share >= 0.10:
                    pct = (share - 0.10) / 0.20 * 100
                    strength_str = f"🟡 **{pct:.0f}% Scaled Strength**"
                else:
                    strength_str = "🔴 *Inactive (<10% share)*"

                # Check if ore has armor traits
                t_data = next((t for t in OPTIMIZER_TRAITS if t["name"].lower() == name.lower()), None)
                a_traits = t_data.get("armor_traits", []) if t_data else []
                armor_perk = f" *(Armor Perks: {len(a_traits)})*" if a_traits else ""
                trait_lines.append(f"• **{name}** ({c}x • {share*100:.1f}%): {strength_str}{armor_perk}")

            embed.add_field(name="🧬 Ore Trait Activation", value="\n".join(trait_lines), inline=False)

            # Projections for Armor Health
            embed.add_field(
                name="🛡️ Armor Health Projections at this Multiplier",
                value=f"• **Light Armor (Base +5%):** `+{5.0 * avg_mult:.1f}%` (Normal) ➔ `+{5.0 * avg_mult * 2:.1f}%` (Masterwork)\n"
                      f"• **Medium Armor (Base +8.75%):** `+{8.75 * avg_mult:.1f}%` (Normal) ➔ `+{8.75 * avg_mult * 2:.1f}%` (Masterwork)\n"
                      f"• **Heavy/Endgame Armor (Base +55%):** `+{55.0 * avg_mult:.1f}%` (Normal) ➔ `+{55.0 * avg_mult * 2:.1f}%` (Masterwork)",
                inline=False
            )

            # Eligible weapon/armor class odds preview
            if total_ores < 4:
                tier_info = "Dagger or Light Helmet (3 Ores minimum)"
            elif total_ores < 10:
                tier_info = "Short Blades, Light/Medium Armor, Swords, Daggers"
            elif total_ores < 20:
                tier_info = "Greatswords, Katanas, Axes, Maces, Medium/Heavy Armor"
            else:
                tier_info = "Colossal Swords, Heavy Axes, Heavy Armors, Polearms"

            embed.add_field(name="📦 Rollable Equipment Classes", value=f"• {tier_info}\n• *Tip: Specify an armor piece like `!calc Dreadhorn Chestplate 10 Bismuth` for exact stats!*", inline=False)
            embed.set_footer(text="Forged with Shin's Master Blacksmithing Formulas • Moon Sanctum")
            await channel.send(embed=embed)
            return

        elif cmd in ["!farm", "!drop", "!drops", "!source", "!sources"]:
            query = content[len(cmd):].strip().lower()
            if not query:
                await channel.send("⚠️ **Usage:** `!farm <item name>` (e.g. `!farm Heavenite`, `!farm Rosethorn`, `!farm Prismatic Pickaxe`)")
                return

            results = []
            # Check Ores
            for o in LIVE_ORES:
                if query in o["name"].lower():
                    results.append(f"• **[Ore] {o['name']}** ({o['rarity']} • {o['multiplier']}): Found at **{o['location']}** | Sells for {o['price']}")

            # Check Weapons
            for w in DATABASE_WEAPONS:
                if query in w["name"].lower():
                    loc = f"Islands: {w['islands']}" if w.get('islands') else "Forge / Molds"
                    results.append(f"• **[Weapon] {w['name']}** ({w['class']}): Chance `{w['chance']}` | {loc}")

            # Check Armors
            for a in DATABASE_ARMOR:
                if query in a["name"].lower():
                    results.append(f"• **[Armor] {a['name']}** ({a['slot']}): Chance `{a['chance']}` | Set: '{a['set']}' | +{a['health_bonus']} HP")

            # Check Pickaxes
            for p in DATABASE_PICKAXES:
                if query in p["name"].lower():
                    results.append(f"• **[Pickaxe] {p['name']}** ({p['rarity']}): Crafted from **{p['ore']}** | Power: {p['mine_power']}, Luck: +{p['luck_boost']}")

            if results:
                embed = discord.Embed(
                    title=f"🗺️ Drop & Farm Intel for '{query.title()}'",
                    description="\n\n".join(results[:6]),
                    color=0x2ECC71
                )
                embed.set_footer(text="Moon Sanctum Drop Archives • theforge.gg")
                await channel.send(embed=embed)
            else:
                await channel.send(f"🔍 **Shin:** I checked our archives, but found no exact drop records for `{query}`. Ask me directly with `@MoonSanctum Core` or check item spelling!")
            return

        elif cmd in ["!top", "!dps"]:
            sorted_weapons = sorted(
                DATABASE_WEAPONS,
                key=lambda x: float(x.get("dps", 0) or 0) if str(x.get("dps", 0)).replace(".", "", 1).isdigit() else 0,
                reverse=True
            )[:5]
            embed = discord.Embed(
                title="⚔️ Top 5 Highest DPS Weapons — The Forge Database",
                description="Verified stats extracted directly from `theforge.gg/database/weapons`:",
                color=0xE67E22
            )
            for i, w in enumerate(sorted_weapons, 1):
                embed.add_field(
                    name=f"#{i} {w.get('name')} ({w.get('class', 'Weapon')})",
                    value=f"**DPS:** `{w.get('dps')}` | **Damage:** `{w.get('damage')}` | **Speed:** `{w.get('speed')}` | **Range:** `{w.get('range')} studs`",
                    inline=False
                )
            embed.set_footer(text="Moon Sanctum Weapon Archives • theforge.gg")
            await channel.send(embed=embed)
            return

        elif cmd in ["!pickaxes", "!picks", "!pickaxe"]:
            top5_picks = sorted(
                [p for p in DATABASE_PICKAXES if p.get("flags") != "Admin"],
                key=lambda x: (x.get("luck_boost", 0), x.get("mine_power", 0)),
                reverse=True
            )[:5]
            embed = discord.Embed(
                title="⛏️ Top 5 Pickaxes — The Forge Mining Archives",
                description="Verified stats directly from game internals (`ReplicatedStorage.Shared.Data.Equipments`):",
                color=0xF1C40F
            )
            for i, p in enumerate(top5_picks, 1):
                embed.add_field(
                    name=f"#{i} {p['name']} ({p['rarity']})",
                    value=f"**Mine Power:** `{p['mine_power']}` | **Luck Boost:** `+{p['luck_boost']}` | **Speed:** `{p['mine_speed']}` | **Rune Slots:** `{p['rune_slots']}` | **Ore:** `{p['ore']}`",
                    inline=False
                )
            embed.set_footer(text="Moon Sanctum Mining Archives • The Forge")
            await channel.send(embed=embed)
            return

        elif cmd in ["!upgrades", "!enhance", "!enhancements"]:
            embed = discord.Embed(
                title="✨ Weapon & Armor Upgrade Multipliers (+0 to +9)",
                description="Verified enhancement stats and aura colors at the anvil:",
                color=0xE74C3C
            )
            embed.add_field(
                name="📈 Anvil Scaling & Aura Colors",
                value="• `+0` ➔ **1.00x** *(Light Blue)*\n"
                      "• `+1` ➔ **1.05x** *(Blue)*\n"
                      "• `+2` ➔ **1.10x** *(Mid Blue)*\n"
                      "• `+3` ➔ **1.15x** *(Deep Blue)*\n"
                      "• `+4` ➔ **1.20x** *(Teal)*\n"
                      "• `+5` ➔ **1.25x** *(Green)*\n"
                      "• `+6` ➔ **1.30x** *(Pale Gold)*\n"
                      "• `+7` ➔ **1.35x** *(Gold)*\n"
                      "• `+8` ➔ **1.40x** *(Orange)*\n"
                      "• `+9` ➔ **1.50x** *(Max Cap: +50% Power)*",
                inline=False
            )
            embed.set_footer(text="Moon Sanctum Workshop Anvil")
            await channel.send(embed=embed)
            return

        elif cmd in ["!list", "!catalog", "!items", "!weapons", "!swords", "!armors", "!armor", "!allpicks"]:
            sub = cmd_parts[1].lower() if len(cmd_parts) > 1 else ""
            
            # 1. Pickaxes Directory
            if sub in ["pick", "picks", "pickaxe", "pickaxes"] or cmd == "!allpicks":
                embed = discord.Embed(
                    title="⛏️ Complete Pickaxe Directory (44 Total)",
                    description="All craftable, skin, and limited pickaxes from `ReplicatedStorage.Shared.Data.Equipments`:",
                    color=0xF1C40F
                )
                embed.add_field(
                    name="⚪ Common & Uncommon (5)",
                    value="Stone Pickaxe, Bronze Pickaxe, Iron Pickaxe, Cobalt Pickaxe, Titanium Pickaxe",
                    inline=False
                )
                embed.add_field(
                    name="🔵 Rare (7)",
                    value="Gold Pickaxe, Platinum Pickaxe, Uranium Pickaxe, Mythril Pickaxe, Tungsten Pickaxe, Aqua Pickaxe, Bamboo Pickaxe",
                    inline=False
                )
                embed.add_field(
                    name="🟣 Epic (8)",
                    value="Stonewake's Pickaxe, Lightite Pickaxe, Mist Pickaxe, Snow Pickaxe, Frost Pickaxe, Sakura Pickaxe, Wolf Pickaxe, Holy Pickaxe",
                    inline=False
                )
                embed.add_field(
                    name="🟡 Legendary (9)",
                    value="Arcane Pickaxe, Magma Pickaxe, Void Pickaxe, Prismatic Pickaxe, Oni Pickaxe, Kitsune Pickaxe, Water Stone Pickaxe, Hexed Harvester, Bluemoon Crescent",
                    inline=False
                )
                embed.add_field(
                    name="🔴 Mythic (7)",
                    value="Demonic Pickaxe, Dragon Head Pickaxe, Angelite Pickaxe, Heavenly Pickaxe, Spirit Pickaxe, Yin-Yang Pickaxe, Crimson Count",
                    inline=False
                )
                embed.add_field(
                    name="🌟 Event, Limited & Admin (8)",
                    value="Christmas Pickaxe, Candy Cane Pickaxe, Pumpking, Infernal Pickaxe, Seraph Pickaxe, Medal Pickaxe, Dev's Bane Pickaxe, Moderator Pickaxe",
                    inline=False
                )
                embed.set_footer(text="Ask 'tiera stats for <pickaxe>' for full power, luck & rune details!")
                await channel.send(embed=embed)
                return

            # 2. Weapons Directory
            elif sub in ["weapon", "weapons", "sword", "swords", "blade", "blades"] or cmd in ["!weapons", "!swords"]:
                embed = discord.Embed(
                    title="⚔️ Complete Weapon Directory (94 Total)",
                    description="All 94 weapons in *The Forge* cataloged by class:",
                    color=0xE67E22
                )
                embed.add_field(
                    name="🗡️ Colossal Swords (13)",
                    value="Devil's Deed, Excalibur, Sharktooth Odachi, Colossal Gemblade, Colossal Terrorblade, Kinmon Kamagatana, Coffin Lid, Otsuchi, etc.",
                    inline=False
                )
                embed.add_field(
                    name="⚔️ Straight Swords (13)",
                    value="Hook Blade, Hell Slayer, Thornspine, Dragon Blade, Candy Cane, Crystalized Broadsword, Chaos, Cutlass, Rapier, Gladius, Falchion",
                    inline=False
                )
                embed.add_field(
                    name="🗡️ Great Swords (7)",
                    value="Jack's Crest, Anchored Greatsword, The Carver, Zweihander, Dark Knight's Greatsword, Long Sword, Crusader Sword",
                    inline=False
                )
                embed.add_field(
                    name="🥷 Katanas (6)",
                    value="Washi-maru, Kurokiba-gatana, Straight Edge Katana, Uchigatana, Juto Katana, Tachi",
                    inline=False
                )
                embed.add_field(
                    name="🔪 Daggers & Short Blades (11)",
                    value="Tanto, Curved Dagger, Cultist Dagger, Shark's Fangs, Damascus Dagger, Jitte, Gladius Dagger, Hook, Kunai, Falchion Knife, Dagger",
                    inline=False
                )
                embed.add_field(
                    name="🔱 Spears & Polearms (11)",
                    value="Moon Crescent Spear, Angelic Spear, Demonic Spear, Knight Spear, Bo Staff, Sodegarami, Naginata, Compass Spear, Trident, Shakujo, Spear",
                    inline=False
                )
                embed.add_field(
                    name="🪓 Halberds & Glaives (4)",
                    value="Royal Guardian's Glaive, Fangtian, Spiked Halberd, Halberd",
                    inline=False
                )
                embed.add_field(
                    name="🪓 Axes & Great Axes (15)",
                    value="Sun Great Axe, Wyvern Axe, Executioner's Greataxe, Batwing Reaver, Anchored Straight Blade, Reaper Scythe, Scythe, Double Battle Axe, Duskwing Cleaver, Ornate Short Axe, Spade Armed Axe, Curved Handle Axe, Battleaxe, Axe",
                    inline=False
                )
                embed.add_field(
                    name="🔨 Maces & Blunt (12)",
                    value="Grave Maker, Tetsubo, Hammerhead Mace, Winged Mace, Kanabo, Spiked Mace, Mace, Skull Crusher, Dragon Slayer, Great Sword, Hammer, Comically Large Spoon",
                    inline=False
                )
                embed.add_field(
                    name="🥊 Gauntlets & Shield Weapons (7)",
                    value="Dark Knight's Gauntlets, Savage Claws, Ironhand, Relevator, Boxing Gloves, Rosethorn, Knight's Bulwark",
                    inline=False
                )
                embed.set_footer(text="Ask 'tiera stats for <weapon>' or 'schnee build for <weapon>' for numbers!")
                await channel.send(embed=embed)
                return

            # 3. Armors Directory
            elif sub in ["armor", "armors", "set", "sets"] or cmd in ["!armors", "!armor"]:
                embed = discord.Embed(
                    title="🛡️ Complete Armor Directory (48 Pieces • 17 Sets)",
                    description="All armor sets and individual equipment pieces in *The Forge*:",
                    color=0x3498DB
                )
                embed.add_field(
                    name="👑 All 17 Armor Sets",
                    value="Light, Ninja, Medium, Samurai, Viking, Rootguard, Voidstrider, Gloomwarden, Knight, Dark Knight, Wolf, Raven, Vanguard, Shogun, Juggernaut, Dreadhorn, Goblin's Crown",
                    inline=False
                )
                embed.add_field(
                    name="🪖 Helmets (16)",
                    value="Light, Medium, Samurai, Viking, Knight, Dark Knight, Raven's, Wolf, Goblin's Crown, Ninja's Headgear, Rootguard, Vanguard, Shogun's, Voidstrider's, Gloomwarden's, Dreadhorn's",
                    inline=False
                )
                embed.add_field(
                    name="🥋 Chestplates (16)",
                    value="Light, Medium, Samurai, Viking, Knight, Dark Knight, Raven's, Wolf, Ninja's Armor, Rootguard, Vanguard, Shogun's, Juggernaut's, Voidstrider's, Gloomwarden's, Dreadhorn's",
                    inline=False
                )
                embed.add_field(
                    name="👖 Leggings (16)",
                    value="Light, Medium, Samurai, Viking, Knight, Dark Knight, Raven's, Wolf, Ninja's Leggings, Rootguard, Vanguard, Shogun's, Juggernaut's, Voidstrider's, Gloomwarden's, Dreadhorn's",
                    inline=False
                )
                embed.set_footer(text="Ask 'tiera stats for <armor>' to see HP bonuses & set abilities!")
                await channel.send(embed=embed)
                return

            # Default: Directory Hub Menu
            else:
                embed = discord.Embed(
                    title="📚 Moon Sanctum Equipment Directory Hub",
                    description="Browse the complete catalog archives of *The Forge*:\n\n"
                                "• **`!list pickaxes`** (or `!picks`) — Catalog of all 44 pickaxes grouped by Rarity\n"
                                "• **`!list weapons`** (or `!swords`) — Catalog of all 94 weapons grouped by Weapon Class\n"
                                "• **`!list armors`** (or `!armors`) — Catalog of all 48 armor pieces & 17 Armor Sets\n"
                                "• **`!top`** / **`!dps`** — Top 5 highest DPS weapons\n"
                                "• **`!pickaxes`** — Top 5 mining pickaxes by Luck & Power\n"
                                "• **`!upgrades`** — Anvil upgrade enhancement multipliers (+0 to +9)\n\n"
                                "💡 *Tip: Mention any item name in chat to get full stats from Tiera or Schnee!*",
                    color=0x9B59B6
                )
                embed.set_footer(text="Moon Sanctum Weapon & Mining Archives")
                await channel.send(embed=embed)
                return

        elif cmd in ["!settings", "!config"]:
            retention_str = "Permanent (Never deleted)" if BOT_CONFIG["auto_delete_seconds"] == 0 else f"{BOT_CONFIG['auto_delete_seconds']} seconds"
            chatter_str = "🟢 Enabled" if BOT_CONFIG["ambient_chatter_enabled"] else "🔴 Disabled"
            interject_str = "🟢 Enabled" if BOT_CONFIG["interjection_enabled"] else "🔴 Disabled"

            embed = discord.Embed(
                title="⚙️ Moon Sanctum Core — Settings & Diagnostics",
                color=0x3498DB
            )
            embed.add_field(name="🗑️ Auto-Delete Retention", value=retention_str, inline=True)
            embed.add_field(name="🦊 Yuzuha Ambient Chatter", value=chatter_str, inline=True)
            embed.add_field(name="🎭 Spontaneous Interjections", value=interject_str, inline=True)

            embed.add_field(
                name="📚 Grounded Knowledge Base",
                value=(
                    f"• **Ores:** `{len(LIVE_ORES)}` entries\n"
                    f"• **Weapons:** `{len(DATABASE_WEAPONS)}` entries\n"
                    f"• **Pickaxes:** `{len(DATABASE_PICKAXES)}` entries\n"
                    f"• **Armor Pieces:** `{len(DATABASE_ARMOR)}` entries\n"
                    f"• **Armor Sets:** `{len(ARMOR_SETS)}` entries\n"
                    f"• **Optimizer Traits:** `{len(OPTIMIZER_TRAITS)}` entries\n"
                    f"• **Enhancements:** `+0 to +9` Anvil Multipliers & Aura Colors"
                ),
                inline=False
            )
            embed.add_field(
                name="☁️ Cloud Deployment",
                value="• **Host:** Render Web Service (`https://moonsanctum-bot.onrender.com`)\n"
                      "• **Monitor:** UptimeRobot 5-Minute Keep-Alive (24/7/365)\n"
                      "• **AI Model:** Google Gemini 3.5 Flash-Lite (Multiturn Memory + Live Search)",
                inline=False
            )
            embed.set_footer(text="Use !autodelete, !chatter, or !interject to adjust settings.")
            await channel.send(embed=embed)
            return

        elif cmd == "!autodelete":
            if len(cmd_parts) > 1 and cmd_parts[1].isdigit():
                sec = int(cmd_parts[1])
                BOT_CONFIG["auto_delete_seconds"] = sec
                if sec == 0:
                    await channel.send("✅ **Settings Updated:** Bot messages are now set to **Permanent** (will not be auto-deleted).")
                else:
                    await channel.send(f"✅ **Settings Updated:** Bot messages will now auto-delete after **{sec} seconds**.")
            else:
                await channel.send("⚠️ **Usage:** `!autodelete <seconds>` (e.g. `!autodelete 60`, or `!autodelete 0` for permanent).")
            return

        elif cmd == "!chatter":
            if len(cmd_parts) > 1 and cmd_parts[1].lower() in ["on", "enable", "true"]:
                BOT_CONFIG["ambient_chatter_enabled"] = True
                await channel.send("✅ **Settings Updated:** Yuzuha ambient chatter is now **Enabled**.")
            elif len(cmd_parts) > 1 and cmd_parts[1].lower() in ["off", "disable", "false"]:
                BOT_CONFIG["ambient_chatter_enabled"] = False
                await channel.send("✅ **Settings Updated:** Yuzuha ambient chatter is now **Disabled**.")
            else:
                await channel.send("⚠️ **Usage:** `!chatter <on|off>`")
            return

        elif cmd == "!interject":
            if len(cmd_parts) > 1 and cmd_parts[1].lower() in ["on", "enable", "true"]:
                BOT_CONFIG["interjection_enabled"] = True
                await channel.send("✅ **Settings Updated:** Spontaneous tavern interjections are now **Enabled**.")
            elif len(cmd_parts) > 1 and cmd_parts[1].lower() in ["off", "disable", "false"]:
                BOT_CONFIG["interjection_enabled"] = False
                await channel.send("✅ **Settings Updated:** Spontaneous tavern interjections are now **Disabled**.")
            else:
                await channel.send("⚠️ **Usage:** `!interject <on|off>`")
            return

        elif cmd == "!gossip":
            if len(cmd_parts) > 1 and cmd_parts[1].lower() in ["on", "enable", "true"]:
                BOT_CONFIG["gossip_enabled"] = True
                await channel.send("✅ **Settings Updated:** Tavern member gossip/backstabbing is now **Enabled**.")
            elif len(cmd_parts) > 1 and cmd_parts[1].lower() in ["off", "disable", "false"]:
                BOT_CONFIG["gossip_enabled"] = False
                await channel.send("✅ **Settings Updated:** Tavern member gossip/backstabbing is now **Disabled** (NPCs will banter generally without naming members).")
            else:
                await channel.send("⚠️ **Usage:** `!gossip <on|off>`")
            return

        elif cmd == "!skits":
            if len(cmd_parts) > 1 and cmd_parts[1].lower() in ["on", "enable", "true"]:
                BOT_CONFIG["skits_enabled"] = True
                await channel.send("✅ **Settings Updated:** Multi-message NPC tavern conversations/skits are now **Enabled**.")
            elif len(cmd_parts) > 1 and cmd_parts[1].lower() in ["off", "disable", "false"]:
                BOT_CONFIG["skits_enabled"] = False
                await channel.send("✅ **Settings Updated:** Multi-message NPC tavern conversations/skits are now **Disabled** (NPCs will only drop single ambient lines).")
            else:
                await channel.send("⚠️ **Usage:** `!skits <on|off>`")
            return

    # Add message to sliding context window
    global phoebe_msg_counter
    phoebe_msg_counter += 1
    if channel_id not in CHAT_HISTORY:
        CHAT_HISTORY[channel_id] = deque(maxlen=6)
    CHAT_HISTORY[channel_id].append(f"{author_name}: {content}")

    # Only speak if someone explicitly calls an NPC, pings the bot, OR uses Discord's Reply button on an NPC
    is_shin = bool(re.search(r"\b(shin)\b", content_lower))
    is_schnee = bool(re.search(r"\b(schnee)\b", content_lower))
    is_tiera = bool(re.search(r"\b(tiera)\b", content_lower))
    is_yuzuha = bool(re.search(r"\b(yuzuha)\b", content_lower))
    is_yukime = bool(re.search(r"\b(yukime)\b", content_lower))
    is_aurora = bool(re.search(r"\b(aurora|violet)\b", content_lower))
    is_kazuma = bool(re.search(r"\b(kazuma|satou)\b", content_lower))
    is_aqua = bool(re.search(r"\b(aqua|goddess aqua)\b", content_lower))
    is_gintoki = bool(re.search(r"\b(gintoki|sakata|gin-chan|gin)\b", content_lower))
    is_john_smith = bool(re.search(r"\b(john smith|johnsmith)\b", content_lower))
    is_shadow = bool(re.search(r"\b(shadow|lord shadow)\b", content_lower)) and not is_john_smith
    is_cid = bool(re.search(r"\b(cid|kagenou)\b", content_lower)) and not (is_shadow or is_john_smith)
    is_phoebe = bool(re.search(r"\b(phoebe|phoebebe|phoebe chupi)\b", content_lower))
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
                if "shin" in r_name:
                    replied_to_npc = "shin"
                elif "schnee" in r_name:
                    replied_to_npc = "schnee"
                elif "tiera" in r_name:
                    replied_to_npc = "tiera"
                elif "yuzuha" in r_name:
                    replied_to_npc = "yuzuha"
                elif "yukime" in r_name:
                    replied_to_npc = "yukime"
                elif "aurora" in r_name:
                    replied_to_npc = "aurora"
                elif "kazuma" in r_name:
                    replied_to_npc = "kazuma"
                elif "aqua" in r_name:
                    replied_to_npc = "aqua"
                elif "gintoki" in r_name or "gin" in r_name:
                    replied_to_npc = "gintoki"
                elif "smith" in r_name:
                    replied_to_npc = "john_smith"
                elif "shadow" in r_name:
                    replied_to_npc = "shadow"
                elif "cid" in r_name:
                    replied_to_npc = "cid"
                elif "phoebe" in r_name:
                    replied_to_npc = "phoebe"
        except Exception as e:
            print(f"Reply resolution error: {e}")

    has_npc_trigger = is_shin or is_schnee or is_tiera or is_yuzuha or is_yukime or is_aurora or is_kazuma or is_aqua or is_gintoki or is_cid or is_shadow or is_john_smith or is_phoebe or is_bot_pinged or replied_to_npc

    if has_npc_trigger:
        current_time = asyncio.get_event_loop().time()
        if current_time - last_ai_time < 3:
            return

        target_npc = (
            "phoebe" if is_phoebe else (
                "gintoki" if is_gintoki else (
                    "aqua" if is_aqua else (
                        "kazuma" if is_kazuma else (
                            "aurora" if is_aurora else (
                                "yukime" if is_yukime else (
                                    "john_smith" if is_john_smith else (
                                        "shadow" if is_shadow else (
                                            "cid" if is_cid else (
                                                "shin" if is_shin else (
                                                    "schnee" if is_schnee else (
                                                        "tiera" if is_tiera else (
                                                            "yuzuha" if is_yuzuha else replied_to_npc
                                                        )
                                                    )
                                                )
                                            )
                                        )
                                    )
                                )
                            )
                        )
                    )
                )
            )
        )

        # Yukime Safety-Net: If this user was recently dismissed by Yukime, she leaves them on read!
        if target_npc == "yukime":
            u_id = message.author.id
            if u_id in YUKIME_DISMISSED_USERS:
                # 120 seconds silent treatment cold shoulder
                if current_time - YUKIME_DISMISSED_USERS[u_id] < 120:
                    print(f"Yukime gave {author_name} the cold shoulder (still dismissed).")
                    return
                else:
                    del YUKIME_DISMISSED_USERS[u_id]

        if is_bot_pinged and not (is_shin or is_schnee or is_tiera or is_yuzuha or is_yukime or is_aurora or is_kazuma or is_aqua or is_gintoki or is_cid or is_shadow or is_john_smith or replied_to_npc):
            if re.search(r"\b(forge|craft|calc|calculate|crucible|recipe|blacksmith|mold|alloy|ratio|damage|dps|speed)\b", content_lower):
                target_npc = "shin"
            elif re.search(r"\b(ore|ores|bismuth|armor|helmet|chestplate|leggings|health|pickaxe|pick|mine|mining|upgrade|anvil|enhance)\b", content_lower):
                target_npc = "tiera"
            else:
                target_npc = "schnee"

        # ── Phoebe Bean: she never calls AI — just picks her phrase by context ──
        if target_npc == "phoebe" or (is_phoebe and not (is_shin or is_schnee or is_tiera or is_yuzuha or is_yukime or is_aurora or is_kazuma or is_aqua or is_gintoki or is_cid or is_shadow or is_john_smith)) or replied_to_npc == "phoebe":
            # Pick phrase based on message context
            if content.endswith("?") or "?" in content:
                bean_reply = "phoebe chupi?"
            elif any(w in content_lower for w in ["yes", "yeah", "yep", "sure", "ok", "okay", "agreed", "same", "fr", "facts", "true", "right"]):
                bean_reply = "phoebe"
            else:
                bean_reply = "phoebebe?"
            last_ai_time = asyncio.get_event_loop().time()
            CHAT_HISTORY[channel_id].append(f"Phoebe: {bean_reply}")
            await send_single_npc(channel, "phoebe", bean_reply)
            return

        ai_reply = await ask_gemini_npc(channel_id, target_npc, author_name, content, reply_context, user_id=message.author.id)
        if ai_reply:
            last_ai_time = current_time
            # Record NPC's reply into sliding context window so they remember previous turns
            CHAT_HISTORY[channel_id].append(f"{NPCS[target_npc]['name']}: {ai_reply}")
            # Send NPC reply according to BOT_CONFIG retention policy
            await send_single_npc(channel, target_npc, ai_reply)

            # Background: update long-term tavern memory on this member
            asyncio.create_task(
                maybe_update_member_memory(
                    message.author.id, author_name, content, NPCS[target_npc]['name'], ai_reply
                )
            )
    else:
        # Organic conversation between guild members! Count messages and evaluate spontaneous interjections
        msg_counter_since_spontaneous += 1
        asyncio.create_task(maybe_chime_in_spontaneously(channel, channel_id))

if __name__ == "__main__":
    client.run(TOKEN)
