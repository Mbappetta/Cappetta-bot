import discord
from discord.ext import commands, tasks
import aiohttp
import asyncio
import os
import json
import re
from datetime import datetime
from aiohttp import web

# ── SERVEUR HTTP (requis pour Render free tier) ───────────────────────────────
async def handle_ping(request):
    return web.Response(text="Cappetta Bot is alive! 🤖")

async def start_webserver():
    app = web.Application()
    app.router.add_get("/", handle_ping)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.environ.get("PORT", 10000))
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    print(f"[Web] Serveur HTTP démarré sur le port {port} ✓")

# ── CONFIG ────────────────────────────────────────────────────────────────────
DISCORD_TOKEN      = os.environ.get("DISCORD_TOKEN")
ANTHROPIC_API_KEY  = os.environ.get("ANTHROPIC_API_KEY")
TWITCH_CLIENT_ID   = os.environ.get("TWITCH_CLIENT_ID")
TWITCH_SECRET      = os.environ.get("TWITCH_SECRET")

TWITCH_USERNAME    = "Cappetta"
TIKTOK_USERNAME    = "cappetta_art"
INSTAGRAM_USERNAME = "cappetta_art"

SALON_LIVE         = "en-live"
SALON_SOCIAL       = "| Social-media"
SALON_SUPPORT      = "| Support"

# ── INTENTS ───────────────────────────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)

# ── STATE ─────────────────────────────────────────────────────────────────────
twitch_access_token = None
was_live            = False
last_tiktok_url     = None
last_instagram_url  = None

# ── UTILS ─────────────────────────────────────────────────────────────────────
def get_channel(guild, name):
    return discord.utils.get(guild.text_channels, name=name)

# ── MODÉRATION ────────────────────────────────────────────────────────────────
async def moderer_message(message):
    if not ANTHROPIC_API_KEY:
        return
    prompt = (
        "Analyse ce message Discord et réponds UNIQUEMENT en JSON valide, "
        "sans aucun texte avant ou après : "
        "{\"problematique\": true/false, \"raison\": \"courte raison ou null\"}\n\n"
        "Considère problématique : insultes, racisme, sexisme, homophobie, "
        "contenu pornographique, harcèlement, spam agressif.\n\n"
        f"Message : {message.content}"
    )
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_API_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json"
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 100,
                    "messages": [{"role": "user", "content": prompt}]
                }
            ) as resp:
                data = await resp.json()
                text = re.sub(r"```json|```", "", data["content"][0]["text"]).strip()
                result = json.loads(text)

                if result.get("problematique"):
                    await message.delete()
                    raison = result.get("raison", "contenu inapproprié")

                    try:
                        await message.author.send(
                            f"⚠️ **Cappetta | Le Sanctuaire** — Ton message a été supprimé.\n"
                            f"Raison : **{raison}**\n"
                            f"Merci de respecter les règles de la communauté 🙏"
                        )
                    except Exception:
                        pass

                    log_channel = get_channel(message.guild, SALON_SUPPORT)
                    if log_channel:
                        embed = discord.Embed(
                            title="🚨 Message supprimé",
                            color=0xe05050,
                            timestamp=datetime.utcnow()
                        )
                        embed.add_field(name="Utilisateur", value=f"{message.author.mention} ({message.author})", inline=False)
                        embed.add_field(name="Salon",       value=f"#{message.channel.name}", inline=True)
                        embed.add_field(name="Raison",      value=raison, inline=True)
                        embed.add_field(name="Message",     value=message.content[:500] or "—", inline=False)
                        await log_channel.send(embed=embed)
    except Exception as e:
        print(f"[Modération] Erreur : {e}")

# ── TWITCH ────────────────────────────────────────────────────────────────────
async def get_twitch_token():
    global twitch_access_token
    if not TWITCH_CLIENT_ID or not TWITCH_SECRET:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://id.twitch.tv/oauth2/token",
                params={
                    "client_id": TWITCH_CLIENT_ID,
                    "client_secret": TWITCH_SECRET,
                    "grant_type": "client_credentials"
                }
            ) as resp:
                data = await resp.json()
                twitch_access_token = data.get("access_token")
                print(f"[Twitch] Token OK")
    except Exception as e:
        print(f"[Twitch] Token error: {e}")

async def check_twitch():
    global was_live, twitch_access_token
    if not TWITCH_CLIENT_ID or not twitch_access_token:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"https://api.twitch.tv/helix/streams?user_login={TWITCH_USERNAME}",
                headers={
                    "Client-ID": TWITCH_CLIENT_ID,
                    "Authorization": f"Bearer {twitch_access_token}"
                }
            ) as resp:
                data   = await resp.json()
                streams = data.get("data", [])
                is_live = len(streams) > 0

                if is_live and not was_live:
                    was_live = True
                    stream   = streams[0]
                    for guild in bot.guilds:
                        channel = get_channel(guild, SALON_LIVE)
                        if channel:
                            embed = discord.Embed(
                                title=f"🔴 Cappetta est en LIVE sur Twitch !",
                                description=stream.get("title", ""),
                                color=0x9146FF,
                                url=f"https://twitch.tv/{TWITCH_USERNAME}"
                            )
                            embed.add_field(name="🎮 Jeu",      value=stream.get("game_name", "—"), inline=True)
                            embed.add_field(name="👀 Viewers",  value=stream.get("viewer_count", 0), inline=True)
                            embed.set_footer(text="Twitch • Cappetta")
                            await channel.send("@everyone", embed=embed)

                elif not is_live and was_live:
                    was_live = False
    except Exception as e:
        print(f"[Twitch] Check error: {e}")
        await get_twitch_token()

# ── TIKTOK ────────────────────────────────────────────────────────────────────
async def check_tiktok():
    global last_tiktok_url
    try:
        async with aiohttp.ClientSession() as session:
            url     = f"https://www.tiktok.com/@{TIKTOK_USERNAME}"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                text    = await resp.text()
                matches = re.findall(rf'/@{TIKTOK_USERNAME}/video/(\d+)', text)
                if matches:
                    latest_url = f"https://www.tiktok.com/@{TIKTOK_USERNAME}/video/{matches[0]}"
                    if last_tiktok_url is None:
                        last_tiktok_url = latest_url  # Init sans notifier
                    elif latest_url != last_tiktok_url:
                        last_tiktok_url = latest_url
                        for guild in bot.guilds:
                            channel = get_channel(guild, SALON_SOCIAL)
                            if channel:
                                embed = discord.Embed(
                                    title="🎵 Nouveau tuto TikTok !",
                                    description=f"[Voir la vidéo]({latest_url})",
                                    color=0x010101,
                                    url=latest_url
                                )
                                embed.set_footer(text="TikTok • @cappetta_art")
                                await channel.send(embed=embed)
    except Exception as e:
        print(f"[TikTok] Error: {e}")

# ── INSTAGRAM ─────────────────────────────────────────────────────────────────
async def check_instagram():
    global last_instagram_url
    try:
        async with aiohttp.ClientSession() as session:
            url     = f"https://www.instagram.com/{INSTAGRAM_USERNAME}/"
            headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
            async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=15)) as resp:
                text    = await resp.text()
                matches = re.findall(r'"shortcode":"([A-Za-z0-9_-]+)"', text)
                if matches:
                    latest_url = f"https://www.instagram.com/p/{matches[0]}/"
                    if last_instagram_url is None:
                        last_instagram_url = latest_url
                    elif latest_url != last_instagram_url:
                        last_instagram_url = latest_url
                        for guild in bot.guilds:
                            channel = get_channel(guild, SALON_SOCIAL)
                            if channel:
                                embed = discord.Embed(
                                    title="📸 Nouveau post Instagram !",
                                    description=f"[Voir le post]({latest_url})",
                                    color=0xE1306C,
                                    url=latest_url
                                )
                                embed.set_footer(text="Instagram • @cappetta_art")
                                await channel.send(embed=embed)
    except Exception as e:
        print(f"[Instagram] Error: {e}")

# ── LOOPS ─────────────────────────────────────────────────────────────────────
@tasks.loop(minutes=14)
async def keep_alive():
    try:
        async with aiohttp.ClientSession() as session:
            url = os.environ.get("RENDER_EXTERNAL_URL", "http://localhost:10000")
            async with session.get(url) as resp:
                print(f"[Keep-alive] {resp.status} ✓")
    except Exception as e:
        print(f"[Keep-alive] Erreur: {e}")
       
@tasks.loop(hours=24)
async def refresh_token_loop():
    await get_twitch_token()

@tasks.loop(minutes=2)
async def twitch_loop():
    await check_twitch()

@tasks.loop(minutes=30)
async def social_loop():
    await check_tiktok()
    await check_instagram()

# ── EVENTS ────────────────────────────────────────────────────────────────────
@bot.event
async def on_ready():
    print(f"[Bot] ✅ Connecté en tant que {bot.user}")
    await get_twitch_token()
    keep_alive.start()
    twitch_loop.start()
    social_loop.start()
    refresh_token_loop.start()

async def main():
    await start_webserver()
    await bot.start(DISCORD_TOKEN)

@bot.event
async def on_message(message):
    if message.author.bot:
        return
    await moderer_message(message)
    await bot.process_commands(message)

# ── COMMANDES ADMIN ───────────────────────────────────────────────────────────
@bot.command(name="status")
@commands.has_permissions(administrator=True)
async def status(ctx):
    embed = discord.Embed(title="🤖 Cappetta Bot — Statut", color=0x4a9068)
    embed.add_field(name="🛡️ Modération",       value="✅ Active",       inline=True)
    embed.add_field(name="🎮 Twitch",            value="✅ Surveillance", inline=True)
    embed.add_field(name="📱 TikTok/Instagram",  value="✅ Surveillance", inline=True)
    embed.add_field(name="🔴 Live en cours",     value="Oui" if was_live else "Non", inline=True)
    embed.add_field(name="Dernier TikTok",       value=last_tiktok_url or "—",      inline=False)
    embed.add_field(name="Dernier Instagram",    value=last_instagram_url or "—",   inline=False)
    await ctx.send(embed=embed)

@bot.command(name="testlive")
@commands.has_permissions(administrator=True)
async def testlive(ctx):
    channel = get_channel(ctx.guild, SALON_LIVE)
    if channel:
        embed = discord.Embed(
            title="🔴 Cappetta est en LIVE sur Twitch ! [TEST]",
            description="Ceci est un test d'alerte",
            color=0x9146FF,
            url=f"https://twitch.tv/{TWITCH_USERNAME}"
        )
        embed.set_footer(text="Test • Cappetta Bot")
        await channel.send(embed=embed)
        await ctx.send(f"✅ Test envoyé dans #{SALON_LIVE}")
    else:
        await ctx.send(f"❌ Salon '{SALON_LIVE}' introuvable")

if __name__ == "__main__":
    asyncio.run(main())
