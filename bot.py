import discord
from discord.ext import commands, tasks
import aiohttp
import os
import json
import asyncio
import re
from datetime import datetime

# ── CONFIG ────────────────────────────────────────────────────────────────────
DISCORD_TOKEN      = os.environ.get("DISCORD_TOKEN")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY")
TWITCH_CLIENT_ID   = os.environ.get("TWITCH_CLIENT_ID")
TWITCH_SECRET      = os.environ.get("TWITCH_SECRET")

TWITCH_USERNAME    = "Cappetta"
TIKTOK_USERNAME    = "cappetta_art"
INSTAGRAM_USERNAME = "cappetta_art"

SALON_LIVE    = "en live"       # contenu partiel du nom de salon
SALON_SOCIAL  = "social-media"
SALON_SUPPORT = "support"

# ── INTENTS ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
intents.presences = True

bot = commands.Bot(command_prefix="!", intents=intents)

# ── ÉTAT ──────────────────────────────────────────────────────────────────────
twitch_token       = None
twitch_was_live    = False
last_tiktok_url    = None
last_instagram_url = None

# ── UTILITAIRES ───────────────────────────────────────────────────────────────
def get_channel(guild, keyword):
    for ch in guild.text_channels:
        if keyword.lower() in ch.name.lower():
            return ch
    return None

# ── MODÉRATION IA ─────────────────────────────────────────────────────────────
async def analyze_message(content: str) -> dict:
    headers = {
        "x-api-key": ANTHROPIC_API_KEY,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    payload = {
        "model": "claude-haiku-4-5-20251001",
        "max_tokens": 150,
        "messages": [{
            "role": "user",
            "content": (
                "Tu es modérateur d'un serveur Discord d'art manga francophone. "
                "Analyse ce message. Réponds UNIQUEMENT en JSON strict, sans markdown :\n"
                '{"violation": true/false, "type": "insulte|harcèlement|contenu_adulte|spam|aucun", "raison": "..."}\n\n'
                f"Message : {content[:500]}"
            )
        }]
    }
    try:
        async with aiohttp.ClientSession() as s:
            async with s.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers, json=payload,
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                data = await resp.json()
                text = data["content"][0]["text"].strip()
                text = text.replace("```json", "").replace("```", "").strip()
                return json.loads(text)
    except Exception as e:
        print(f"[Modération] Erreur : {e}")
        return {"violation": False, "type": "aucun", "raison": ""}

# ── TWITCH ────────────────────────────────────────────────────────────────────
async def refresh_twitch_token():
    global twitch_token
    async with aiohttp.ClientSession() as s:
        async with s.post("https://id.twitch.tv/oauth2/token", params={
            "client_id": TWITCH_CLIENT_ID,
            "client_secret": TWITCH_SECRET,
            "grant_type": "client_credentials"
        }) as resp:
            data = await resp.json()
            twitch_token = data.get("access_token")

async def is_twitch_live():
    global twitch_token
    if not TWITCH_CLIENT_ID:
        return False
    if not twitch_token:
        await refresh_twitch_token()
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://api.twitch.tv/helix/streams?user_login={TWITCH_USERNAME}",
                headers={"Client-ID": TWITCH_CLIENT_ID, "Authorization": f"Bearer {twitch_token}"}
            ) as resp:
                if resp.status == 401:
                    await refresh_twitch_token()
                    return False
                data = await resp.json()
                streams = data.get("data", [])
                return streams[0] if streams else False
    except Exception as e:
        print(f"[Twitch] Erreur : {e}")
        return False

# ── TIKTOK ────────────────────────────────────────────────────────────────────
async def get_latest_tiktok():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://www.tiktok.com/@{TIKTOK_USERNAME}",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                html = await resp.text()
                matches = re.findall(
                    rf'https://www\.tiktok\.com/@{TIKTOK_USERNAME}/video/(\d+)', html
                )
                if matches:
                    vid_id = matches[0]
                    return f"https://www.tiktok.com/@{TIKTOK_USERNAME}/video/{vid_id}"
    except Exception as e:
        print(f"[TikTok] Erreur : {e}")
    return None

# ── INSTAGRAM ─────────────────────────────────────────────────────────────────
async def get_latest_instagram():
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(
                f"https://www.instagram.com/{INSTAGRAM_USERNAME}/",
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=10)
            ) as resp:
                html = await resp.text()
                matches = re.findall(r'"shortcode":"([^"]+)"', html)
                if matches:
                    return f"https://www.instagram.com/p/{matches[0]}/"
    except Exception as e:
        print(f"[Instagram] Erreur : {e}")
    return None

# ── TÂCHES ────────────────────────────────────────────────────────────────────
@tasks.loop(minutes=2)
async def check_twitch():
    global twitch_was_live
    stream = await is_twitch_live()
    for guild in bot.guilds:
        ch = get_channel(guild, SALON_LIVE)
        if not ch:
            continue
        if stream and not twitch_was_live:
            twitch_was_live = True
            embed = discord.Embed(
                title="🔴 CAPPETTA EST EN LIVE !",
                description=f"**{stream.get('title', 'Stream en cours')}**\n{'🎮 ' + stream.get('game_name','') if stream.get('game_name') else ''}",
                color=0x9146FF,
                url=f"https://twitch.tv/{TWITCH_USERNAME}"
            )
            embed.add_field(name="👀 Rejoindre", value=f"[twitch.tv/{TWITCH_USERNAME}](https://twitch.tv/{TWITCH_USERNAME})")
            embed.set_footer(text=f"Live démarré • {datetime.now().strftime('%H:%M')}")
            await ch.send("@everyone", embed=embed)
        elif not stream and twitch_was_live:
            twitch_was_live = False

@tasks.loop(minutes=15)
async def check_tiktok():
    global last_tiktok_url
    url = await get_latest_tiktok()
    if url and url != last_tiktok_url:
        last_tiktok_url = url
        for guild in bot.guilds:
            ch = get_channel(guild, SALON_SOCIAL)
            if ch:
                embed = discord.Embed(
                    title="🎵 Nouvelle vidéo TikTok !",
                    description=f"**Cappetta** vient de poster une nouvelle vidéo !",
                    color=0x010101, url=url
                )
                embed.add_field(name="▶️ Voir la vidéo", value=url)
                embed.set_footer(text=f"TikTok • {datetime.now().strftime('%d/%m %H:%M')}")
                await ch.send(embed=embed)

@tasks.loop(minutes=20)
async def check_instagram():
    global last_instagram_url
    url = await get_latest_instagram()
    if url and url != last_instagram_url:
        last_instagram_url = url
        for guild in bot.guilds:
            ch = get_channel(guild, SALON_SOCIAL)
            if ch:
                embed = discord.Embed(
                    title="📸 Nouvelle publication Instagram !",
                    description=f"**Cappetta** vient de poster sur Instagram !",
                    color=0xE1306C, url=url
                )
                embed.add_field(name="🔗 Voir la publication", value=url)
                embed.set_footer(text=f"Instagram • {datetime.now().strftime('%d/%m %H:%M')}")
                await ch.send(embed=embed)

@tasks.loop(minutes=14)
async def keep_alive():
    """Empêche Render de mettre le bot en veille."""
    url = os.environ.get("RENDER_EXTERNAL_URL")
    if url:
        try:
            async with aiohttp.ClientSession() as s:
                await s.get(url, timeout=aiohttp.ClientTimeout(total=5))
        except:
            pass

# ── EVENTS ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"✅ {bot.user} connecté — {len(bot.guilds)} serveur(s)")
    check_twitch.start()
    check_tiktok.start()
    check_instagram.start()
    keep_alive.start()
    await bot.change_presence(activity=discord.Activity(
        type=discord.ActivityType.watching, name="le sanctuaire 🎨"
    ))

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    if message.author.guild_permissions.administrator:
        await bot.process_commands(message)
        return

    result = await analyze_message(message.content)

    if result.get("violation"):
        try:
            await message.delete()
        except discord.Forbidden:
            pass

        # DM à l'auteur
        try:
            await message.author.send(
                f"⚠️ **Message supprimé — Cappetta | Le Sanctuaire**\n"
                f"Raison : {result.get('raison', 'Contenu inapproprié')}\n"
                f"Merci de respecter les règles du serveur 🙏"
            )
        except discord.Forbidden:
            pass

        # Log dans #Support
        for guild in bot.guilds:
            log_ch = get_channel(guild, SALON_SUPPORT)
            if log_ch:
                embed = discord.Embed(title="🚨 Message supprimé", color=0xFF4444)
                embed.add_field(name="Auteur", value=f"{message.author.mention}", inline=True)
                embed.add_field(name="Salon", value=f"{message.channel.mention}", inline=True)
                embed.add_field(name="Type", value=result.get("type", "?"), inline=True)
                embed.add_field(name="Raison", value=result.get("raison", "?"), inline=False)
                embed.add_field(name="Contenu", value=f"||{message.content[:200]}||", inline=False)
                embed.set_footer(text=datetime.now().strftime("%d/%m/%Y %H:%M"))
                await log_ch.send(embed=embed)

    await bot.process_commands(message)

# ── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name="live")
@commands.has_permissions(administrator=True)
async def annonce_live(ctx, *, titre="Stream en cours !"):
    """!live [titre] — Annonce manuelle dans #En LIVE"""
    ch = get_channel(ctx.guild, SALON_LIVE)
    if ch:
        embed = discord.Embed(
            title="🔴 CAPPETTA EST EN LIVE !",
            description=f"**{titre}**",
            color=0x9146FF,
            url=f"https://twitch.tv/{TWITCH_USERNAME}"
        )
        embed.add_field(name="👀 Rejoindre", value=f"[twitch.tv/{TWITCH_USERNAME}](https://twitch.tv/{TWITCH_USERNAME})")
        await ch.send("@everyone", embed=embed)
        await ctx.message.delete()

@bot.command(name="status")
@commands.has_permissions(administrator=True)
async def bot_status(ctx):
    """!status — Vérifie que tout tourne"""
    stream = await is_twitch_live()
    embed = discord.Embed(title="📊 Cappetta Bot — Status", color=0x4a9068)
    embed.add_field(name="🤖 Bot",       value="✅ En ligne",              inline=True)
    embed.add_field(name="🎮 Twitch",    value="🔴 EN LIVE" if stream else "⚫ Offline", inline=True)
    embed.add_field(name="🎵 TikTok",    value="✅ Surveillance active",    inline=True)
    embed.add_field(name="📸 Instagram", value="✅ Surveillance active",    inline=True)
    await ctx.send(embed=embed)

# ── RUN ───────────────────────────────────────────────────────────────────────
bot.run(DISCORD_TOKEN)
