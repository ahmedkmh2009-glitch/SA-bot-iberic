import os
import asyncio
from flask import Flask
from discord.ext import commands

TOKEN = os.getenv("TOKEN")

app = Flask(__name__)
bot = commands.Bot(command_prefix="!")

# Ruta de prueba Flask
@app.route("/")
def index():
    return "Flask está funcionando ✅"

# Evento de Discord
@bot.event
async def on_ready():
    print(f"Bot conectado como {bot.user}")

async def main():
    # Ejecuta Flask en background
    loop = asyncio.get_event_loop()
    loop.run_in_executor(None, lambda: app.run(host="0.0.0.0", port=5000))
    
    # Ejecuta Discord
    await bot.start(TOKEN)

asyncio.run(main())
