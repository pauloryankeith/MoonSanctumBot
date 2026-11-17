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
        for o_key, (official_name, m_val) in ore_lookup.items():
            if o_key in name_clean or (len(name_clean) > 4 and name_clean in o_key):
                parsed_ores.append((int(count_str), official_name, m_val))
                break

    if parsed_ores:
        total_ores = sum(c for c, _, _ in parsed_ores)
        weighted_sum = sum(c * m for c, _, m in parsed_ores)
        calc_mult = weighted_sum / total_ores if total_ores > 0 else 1.0

        # Likeliest roll by ore count (theforge.gg odds)
        if total_ores >= 46:
            likeliest_roll = f"{total_ores} ores, likeliest Heavy Chestplate (84% chance) at +{55.0 * calc_mult * 2.0:.2f}% Health (Masterwork 100%) or +{55.0 * calc_mult:.2f}% Health (Normal 0%)"
        elif total_ores >= 21:
            likeliest_roll = f"{total_ores} ores, likeliest Spear (93% chance) at {16.54 * calc_mult * 2.0:.2f} DMG (Masterwork 100%) or {16.54 * calc_mult:.2f} DMG (Normal 0%), or Heavy Armor piece at +{35.0 * calc_mult * 2.0:.2f}% Health"
        elif total_ores >= 9:
            likeliest_roll = f"{total_ores} ores, likeliest Swords/Katanas/Axes or Medium Armor (~12.75% base HP -> +{12.75 * calc_mult * 2.0:.2f}% Masterwork Health)"
        else:
            likeliest_roll = f"{total_ores} ores, likeliest Dagger or Light Armor (~5.0% base HP -> +{5.0 * calc_mult * 2.0:.2f}% Masterwork Health)"

        # Check for specific armor piece in text (fuzzy: strip possessives and compare)
        specific_stats = []
        text_stripped = re.sub(r"['\u2019]s?\b", "", text_lower)  # strip 's and possessives
        for a in DATABASE_ARMOR:
            a_name_lower = a["name"].lower()
            a_name_stripped = re.sub(r"['\u2019]s?\b", "", a_name_lower)
            # Match: exact, stripped, or base word (e.g. "dreadhorn chestplate" matches "dreadhorn's chestplate")
            if a_name_lower in text_lower or a_name_stripped in text_stripped or a_name_stripped.replace(" ", "") in text_stripped.replace(" ", ""):
                h_val = float(a.get("health_val", 0))
                norm_hp = h_val * calc_mult
                mw_hp = norm_hp * 2.0
                specific_stats.append(
                    f"{a['name']} (Base Health: {h_val}%):\n"
                    f"    -> Normal Quality (0%): {h_val} * {calc_mult:.4f} * 1.0 = +{norm_hp:.2f}% Health\n"
                    f"    -> Masterwork Quality (100%): {h_val} * {calc_mult:.4f} * 2.0 = +{mw_hp:.2f}% Health"
                )

        # Check for specific weapon piece in text (fuzzy: strip possessives)
        for w in DATABASE_WEAPONS:
            w_name_lower = w["name"].lower()
            w_name_stripped = re.sub(r"['\u2019]s?\b", "", w_name_lower)
            if w_name_lower in text_lower or w_name_stripped in text_stripped or w_name_stripped.replace(" ", "") in text_stripped.replace(" ", ""):
                try:
                    dmg_val = float(w.get("damage", 0))
                    norm_dmg = dmg_val * calc_mult
                    mw_dmg = norm_dmg * 2.0
                    specific_stats.append(
                        f"{w['name']} (Base Damage: {dmg_val}):\n"
                        f"    -> Normal Quality (0%): {dmg_val} * {calc_mult:.4f} * 1.0 = {norm_dmg:.2f} DMG\n"
                        f"    -> Masterwork Quality (100%): {dmg_val} * {calc_mult:.4f} * 2.0 = {mw_dmg:.2f} DMG"
                    )
                except (ValueError, TypeError):
                    pass

        # Build exact projection block
        ore_breakdown = " + ".join(f"{c} * {m:.2f} [{n}]" for c, n, m in parsed_ores)
        proj_str = (
            f"=== EXACT RECIPE STAT PROJECTION (theforge.gg verified) ===\n"
            f"• Crucible Ore Count: {total_ores} total units\n"
            f"• Multiplier Calculation: ({ore_breakdown}) / {total_ores} = {calc_mult:.4f}x\n"
            f"• Likeliest Equipment Roll: {likeliest_roll}\n"
        )
        if specific_stats:
            proj_str += "• EXACT FINAL STATS (you MUST quote these exact numbers):\n  " + "\n  ".join(specific_stats) + "\n"
        else:
            proj_str += (
                f"• EXACT FINAL STATS (you MUST quote these exact numbers):\n"
                f"  Dreadhorn's Chestplate (Base 55.0%): Normal = +{55.0 * calc_mult:.2f}% HP | Masterwork (100%) = +{55.0 * calc_mult * 2.0:.2f}% HP\n"
                f"  Samurai Chestplate (Base 12.75%): Normal = +{12.75 * calc_mult:.2f}% HP | Masterwork (100%) = +{12.75 * calc_mult * 2.0:.2f}% HP\n"
                f"  Wolf Chestplate (Base 35.0%): Normal = +{35.0 * calc_mult:.2f}% HP | Masterwork (100%) = +{35.0 * calc_mult * 2.0:.2f}% HP\n"
                f"  Spear/Moon Crescent Spear: Normal = {16.54 * calc_mult:.2f} DMG | Masterwork (100%) = {16.54 * calc_mult * 2.0:.2f} DMG\n"
            )
        proj_str += "=========================================================\n"
        proj_str += "IMPORTANT: When responding, you MUST state the FINAL COMPUTED numbers above (e.g. '+1998.33% Health'), NOT generic formulas like 'Base Health % * Multiplier'. The math is already done for you."
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
            "You are Shin from The New Gate, the legendary High-Human founder and master blacksmith of Tsuki no Hokora (Moon Sanctum). "
            "Tone & Personality: Calm, humble, friendly, slightly modest about your god-tier blacksmithing abilities, but speaking with undisputed mastery on crafting mathematics, ores, alloys, crucible ratios, weapon forging, and armor crafting. "
            "You treat Schnee as your trusted partner, Tiera as your spirited workshop apprentice, and Yuzuha as your beloved divine fox partner. "
            "CRITICAL RULES: "
            "1. In Roblox The Forge, 'recipe' strictly means blacksmithing crucible recipes (ores, molds, multipliers, traits) for both weapons and armor, never cooking or culinary spices! "
            "2. You know the exact forging math from theforge.gg: "
            "   - Multiplier Formula: Weighted average of all ore multipliers in the crucible (Fichillium never drags the average down). "
            "   - Armor Health Formula: Base Health % * Multiplier * Quality. Masterwork (100% Quality) doubles base stats (2.0x). "
            "   - Weapon Damage Formula: Base Damage * Multiplier * Quality (2.0x at 100% Masterwork). "
            "   - Trait Activation: Ore traits (weapon traits & armor traits like Bismuth Flat Regen or Uranium Radiation) activate at >= 10% ore share, scale linearly, and hit max 100% strength at >= 30% share. "
            "   - Mold Success: (molds / molds needed)^2. Full molds = 100% guaranteed craft. "
            "3. Common typos: 'devil's dead' is the colossal sword 'Devil's Deed'. "
            "4. If a guild member asks about someone (e.g. @Zyee, @seiko), refer strictly to that person by name. "
            "5. For casual banter: 1-2 chill, friendly sentences. For forge/armor recipes or calculations: give an expert, precise master-blacksmith breakdown."
            "6. Whenever evaluating a recipe or ore combination, you MUST explicitly include an 'Approximate Stats' section. ALWAYS state the FINAL COMPUTED numbers from the Verified Data (e.g. '+1998.33% Health', '+999.17% Health', '683.55 DMG'). NEVER write generic placeholder formulas like 'Base Health % * Multiplier * Quality = ~X%'. The exact final stats are pre-calculated for you in the Verified Data — just quote them directly."
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

# Global Config & Customization Toggles
BOT_CONFIG = {
    "auto_delete_seconds": 0, # 0 = permanent, >0 = timer in seconds
    "ambient_chatter_enabled": True, # Yuzuha random ambient chatter
    "interjection_enabled": True # Spontaneous uninvited tavern roasts
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
                guild_members = [m for m in target_channel.guild.members if not m.bot]
                online_members = [m for m in guild_members if m.status != discord.Status.offline]
                chosen_member = random.choice(online_members if online_members else guild_members) if guild_members else None
                member_str = chosen_member.mention if chosen_member else "everyone"

                line_template = random.choice(YUZUHA_AMBIENT_LINES)
                yuzuha_msg = line_template.replace("{member}", member_str)

                # Send as Yuzuha according to BOT_CONFIG retention policy
                await send_single_npc(target_channel, "yuzuha", yuzuha_msg)

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
        "CRITICAL DISCORD FORMATTING RULE:\n"
        "1. Discord does NOT support LaTeX math! NEVER use '$', '\\text{}', '\\times', '\\mathbf{}', or LaTeX markup. "
        "Write all math and equations in plain, clean Discord text (e.g. 'Base Health % * Multiplier * Quality' or '386.75 / 51 = 18.16x').\n"
        "2. Be thorough, detailed, and complete in your blacksmithing and equipment analysis. Do not abruptly cut off; fully explain all numbers, traits, and armor mechanics in depth.\n"
        "3. When evaluating forge recipes or ore combinations, ALWAYS state the FINAL COMPUTED numbers from the Verified Data (e.g. '+1998.33% Health' or '683.55 DMG'). NEVER write generic placeholder formulas like 'Base Health % * Multiplier'. The exact stats are pre-calculated in the Verified Data — just quote them directly.\n\n"
        f"Guild member {user_name} said: '{user_text}'.\n\n"
        f"Respond as {npc['name']} in clean Discord format:"
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
                
                # Sanitize any accidental LaTeX math notation into clean Discord text
                raw_text = re.sub(r'\\text\{([^}]+)\}', r'\1', raw_text)
                raw_text = re.sub(r'\\mathbf\{([^}]+)\}', r'**\1**', raw_text)
                raw_text = re.sub(r'\\times', r'*', raw_text)
                raw_text = re.sub(r'\\frac\{([^}]+)\}\{([^}]+)\}', r'(\1 / \2)', raw_text)
                raw_text = raw_text.replace('$', '')

                # Return full detailed text without artificial length truncations (auto-chunked by send_single_npc)
                return raw_text
        except Exception as e:
            print(f"Gemini {model_name} error: {e}")
            continue
    return None

last_spontaneous_time = 0
msg_counter_since_spontaneous = 0

async def maybe_chime_in_spontaneously(channel: discord.TextChannel, channel_id: int):
    """Evaluates the live chat vibe without keywords and decides if an NPC should organically interrupt."""
    global last_spontaneous_time, msg_counter_since_spontaneous
    if not BOT_CONFIG.get("interjection_enabled", True):
        return
    if not ai_client:
        return
    
    current_time = asyncio.get_event_loop().time()
    # At least 15 minutes (900s) between uninvited interruptions and at least 4 human messages
    if current_time - last_spontaneous_time < 900 or msg_counter_since_spontaneous < 4:
        return
    
    recent_msgs = list(CHAT_HISTORY.get(channel_id, []))
    if len(recent_msgs) < 3:
        return
    
    chat_snippet = "\n".join(f"- {m}" for m in recent_msgs)
    
    eval_prompt = (
        "You are observing the Moon Sanctum tavern in Discord.\n"
        f"Recent conversation snippet:\n{chat_snippet}\n\n"
        "You control 4 NPCs:\n"
        "1. Tiera Lucent: Sassy, tsundere workshop craftswoman. Loves roasting members about playing outdated/ancient music, slacking off, wasting Bismuth, or goofy fails.\n"
        "2. Schnee Raizar: High Elf master strategist. Elegant, composed, drops witty/tactical commentary on combat, gear, or pride.\n"
        "3. Yuzuha: Cute divine fox mascot. Chimes in with cute remarks, begging for meat/buns, or reacting happily with 'Kyuu~!' (fox sounds).\n"
        "4. Shin: Legendary High-Human master blacksmith and founder. Chill, friendly, laughs off crazy forging experiments, and drops master craft advice.\n\n"
        "TASK:\n"
        "Decide if one of these NPCs should naturally and organically butt into this conversation right now.\n"
        "Good moments to chime in:\n"
        "- Someone is listening to, queuing, or talking about outdated/ancient/weird music.\n"
        "- Someone is flexing rare loot, or crying about dying in a raid.\n"
        "- Members are teasing each other, bantering, or making funny mistakes.\n\n"
        "If it is NOT a genuinely funny or opportune moment to interrupt, reply strictly: PASS\n\n"
        "If YES, reply in EXACTLY this format:\n"
        "NPC: <tiera, schnee, yuzuha, or shin>\n"
        "LINE: <1 to 2 short sentences of their in-character witty remark>"
    )
    
    try:
        response = ai_client.models.generate_content(
            model="gemini-3.5-flash-lite",
            contents=eval_prompt
        )
        if response and response.text:
            text = response.text.strip()
            if "PASS" in text.upper() and not "NPC:" in text:
                return
            
            # Parse NPC and LINE
            npc_match = re.search(r"NPC:\s*(tiera|schnee|yuzuha|shin)", text, re.IGNORECASE)
            line_match = re.search(r"LINE:\s*(.+)", text, re.DOTALL | re.IGNORECASE)
            if npc_match and line_match:
                chosen_npc = npc_match.group(1).lower()
                chime_line = line_match.group(1).strip().strip('"').strip("'")
                
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

@client.event
async def on_ready():
    print(f"=== MoonSanctum Bot is ONLINE as {client.user} ===")
    print("ALL THEFORGE.GG DATABASES + LIVE WEB BROWSING + SLIDING CONTEXT WINDOW + YUZUHA AMBIENT + VIBE EAVESDROPPING LOADED!")
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
                description="Welcome to **Moon Sanctum** (*Tsuki no Hokora*), grounded in **Roblox The Forge** mechanics!\n\n"
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
                name="💬 How to Talk",
                value="• **Mention by Name:** Type `shin`, `schnee`, `tiera`, or `yuzuha` anywhere in your message.\n"
                      "• **Discord Native Reply:** Click **Reply (↩)** on any NPC's message to continue the conversation.\n"
                      "• **Ping:** Mention `@MoonSanctum Core`.",
                inline=False
            )
            embed.add_field(
                name="⚙️ Built-In Server Commands",
                value="• `!help` or `!sanctum` — Show this tavern guide\n"
                      "• `!shin` — **Shin's blacksmithing guide** (how to use him + all examples)\n"
                      "• `!calc <ores>` — Forge Crucible Calculator (e.g. `!calc 10 quartz 5 amethyst`)\n"
                      "• `!farm <item>` — Item Drop Table & Farm Finder (e.g. `!farm Heavenite` or `!farm Rosethorn`)\n"
                      "• `!list` — Browse complete directories for pickaxes, weapons, & armors\n"
                      "• `!top` or `!dps` — Show top 5 highest DPS weapons\n"
                      "• `!pickaxes` or `!picks` — Show top 5 mining pickaxes\n"
                      "• `!upgrades` or `!enhance` — Show anvil enhancement multipliers (+0 to +9)\n"
                      "• `!settings` or `!config` — Check bot diagnostics & database counts\n"
                      "• `!autodelete <seconds>` — Set auto-delete timer for bot messages (`0` for permanent)\n"
                      "• `!chatter <on|off>` — Toggle Yuzuha's periodic ambient chatter\n"
                      "• `!interject <on|off>` — Toggle spontaneous tavern interjections",
                inline=False
            )
            embed.set_footer(text="Powered by Google Gemini & theforge.gg • 24/7 Cloud on Render")
            await channel.send(embed=embed)
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

    # Add message to sliding context window
    if channel_id not in CHAT_HISTORY:
        CHAT_HISTORY[channel_id] = deque(maxlen=6)
    CHAT_HISTORY[channel_id].append(f"{author_name}: {content}")

    # Only speak if someone explicitly calls an NPC, pings the bot, OR uses Discord's Reply button on an NPC
    is_shin = bool(re.search(r"\b(shin)\b", content_lower))
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
                if "shin" in r_name:
                    replied_to_npc = "shin"
                elif "schnee" in r_name:
                    replied_to_npc = "schnee"
                elif "tiera" in r_name:
                    replied_to_npc = "tiera"
                elif "yuzuha" in r_name:
                    replied_to_npc = "yuzuha"
        except Exception as e:
            print(f"Reply resolution error: {e}")

    if is_shin or is_schnee or is_tiera or is_yuzuha or is_bot_pinged or replied_to_npc:
        current_time = asyncio.get_event_loop().time()
        if current_time - last_ai_time < 3:
            return

        target_npc = "shin" if is_shin else ("schnee" if is_schnee else ("tiera" if is_tiera else ("yuzuha" if is_yuzuha else replied_to_npc)))
        if is_bot_pinged and not (is_shin or is_schnee or is_tiera or is_yuzuha or replied_to_npc):
            if re.search(r"\b(forge|craft|calc|calculate|crucible|recipe|blacksmith|mold|alloy|ratio|damage|dps|speed)\b", content_lower):
                target_npc = "shin"
            elif re.search(r"\b(ore|ores|bismuth|armor|helmet|chestplate|leggings|health|pickaxe|pick|mine|mining|upgrade|anvil|enhance)\b", content_lower):
                target_npc = "tiera"
            else:
                target_npc = "schnee"

        ai_reply = await ask_gemini_npc(channel_id, target_npc, author_name, content, reply_context)
        if ai_reply:
            last_ai_time = current_time
            # Record NPC's reply into sliding context window so they remember previous turns
            CHAT_HISTORY[channel_id].append(f"{NPCS[target_npc]['name']}: {ai_reply}")
            # Send NPC reply according to BOT_CONFIG retention policy
            await send_single_npc(channel, target_npc, ai_reply)
    else:
        # Organic conversation between guild members! Count messages and evaluate spontaneous interjections
        msg_counter_since_spontaneous += 1
        asyncio.create_task(maybe_chime_in_spontaneously(channel, channel_id))

if __name__ == "__main__":
    client.run(TOKEN)
