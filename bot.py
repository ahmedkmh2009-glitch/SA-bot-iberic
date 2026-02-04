import discord
from discord.ext import commands
from discord import app_commands
import aiohttp
from flask import Flask, request, jsonify
import threading

# --- CONFIG ---
TOKEN = "TU_DISCORD_BOT_TOKEN"
OWNER_ID = 1456619228915568671  # Solo este usuario puede usar los comandos
SELLAUTH_API_KEY = "TU_API_KEY"
SELLAUTH_SHOP_ID = "TU_SHOP_ID"

# --- DISCORD BOT ---
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# --- FLASK ---
app = Flask(__name__)

# --- UTILS ---
async def fetch_products():
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products"
    headers = {"Authorization": f"Bearer {SELLAUTH_API_KEY}", "Content-Type": "application/json"}
    async with aiohttp.ClientSession() as session:
        async with session.get(url, headers=headers) as r:
            data = await r.json()
            return data.get("data", [])

async def add_stock(pid, items):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/deliverables"
    headers = {"Authorization": f"Bearer {SELLAUTH_API_KEY}", "Content-Type": "application/json"}
    body = {"deliverables": items}
    async with aiohttp.ClientSession() as session:
        async with session.post(url, headers=headers, json=body) as r:
            try: js = await r.json()
            except: js = await r.text()
            return r.status, js

async def replace_stock(pid, items):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/deliverables/overwrite/0"
    headers = {"Authorization": f"Bearer {SELLAUTH_API_KEY}", "Content-Type": "application/json"}
    body = {"deliverables": items}
    async with aiohttp.ClientSession() as session:
        async with session.put(url, headers=headers, json=body) as r:
            try: js = await r.json()
            except: js = await r.text()
            return r.status, js

def is_owner(interaction: discord.Interaction):
    return interaction.user.id == OWNER_ID

# --- DISCORD MODALS ---
class RestockModal(discord.ui.Modal, title="Add Stock"):
    stock = discord.ui.TextInput(label="Stock (one per line)", style=discord.TextStyle.paragraph)
    def __init__(self, pid, pname):
        super().__init__()
        self.pid = pid
        self.pname = pname
    async def on_submit(self, interaction: discord.Interaction):
        if not is_owner(interaction):
            return await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        items = [x.strip() for x in self.stock.value.splitlines() if x.strip()]
        if not items: return await interaction.response.send_message("No stock provided", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        status, js = await add_stock(self.pid, items)
        if status < 200 or status >= 300:
            return await interaction.followup.send(f"Error updating stock: {js}", ephemeral=True)
        await interaction.followup.send(f"✅ Added {len(items)} items to {self.pname}", ephemeral=True)

class ReplaceModal(discord.ui.Modal, title="Replace Stock"):
    stock = discord.ui.TextInput(label="New stock (one per line)", style=discord.TextStyle.paragraph)
    def __init__(self, pid, pname):
        super().__init__()
        self.pid = pid
        self.pname = pname
    async def on_submit(self, interaction: discord.Interaction):
        if not is_owner(interaction):
            return await interaction.response.send_message("❌ You are not authorized.", ephemeral=True)
        items = [x.strip() for x in self.stock.value.splitlines() if x.strip()]
        if not items: return await interaction.response.send_message("No stock provided", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        status, js = await replace_stock(self.pid, items)
        if status < 200 or status >= 300:
            return await interaction.followup.send(f"Error replacing stock: {js}", ephemeral=True)
        await interaction.followup.send(f"🟠 Replaced stock of {self.pname} with {len(items)} items", ephemeral=True)

# --- DISCORD AUTOCOMPLETE ---
async def product_autocomplete(interaction: discord.Interaction, current: str):
    products = await fetch_products()
    choices = [app_commands.Choice(name=p["name"], value=str(p["id"])) for p in products if current.lower() in p["name"].lower()]
    return choices[:25]

# --- DISCORD SLASH COMMANDS ---
@bot.tree.command(name="restock", description="Add stock to a product")
@app_commands.describe(product="Choose the product")
@app_commands.autocomplete(product=product_autocomplete)
async def restock(interaction: discord.Interaction, product: str):
    if not is_owner(interaction): return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
    products = await fetch_products()
    prod = next((p for p in products if str(p["id"]) == product), None)
    if not prod: return await interaction.response.send_message("❌ Product not found", ephemeral=True)
    modal = RestockModal(pid=prod["id"], pname=prod["name"])
    await interaction.response.send_modal(modal)

@bot.tree.command(name="replace", description="Replace stock of a product")
@app_commands.describe(product="Choose the product")
@app_commands.autocomplete(product=product_autocomplete)
async def replace(interaction: discord.Interaction, product: str):
    if not is_owner(interaction): return await interaction.response.send_message("❌ Not authorized.", ephemeral=True)
    products = await fetch_products()
    prod = next((p for p in products if str(p["id"]) == product), None)
    if not prod: return await interaction.response.send_message("❌ Product not found", ephemeral=True)
    modal = ReplaceModal(pid=prod["id"], pname=prod["name"])
    await interaction.response.send_modal(modal)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user}")
    try:
        await bot.tree.sync()
        print("Commands synced")
    except Exception as e:
        print(e)

# --- FLASK ENDPOINTS ---
@app.route("/restock", methods=["POST"])
def flask_restock():
    data = request.json
    pid = data.get("product_id")
    items = data.get("items", [])
    if not pid or not items:
        return jsonify({"error": "Missing product_id or items"}), 400

    import asyncio
    status, resp = asyncio.run(add_stock(pid, items))
    return jsonify({"status": status, "response": resp})

@app.route("/replace", methods=["POST"])
def flask_replace():
    data = request.json
    pid = data.get("product_id")
    items = data.get("items", [])
    if not pid or not items:
        return jsonify({"error": "Missing product_id or items"}), 400

    import asyncio
    status, resp = asyncio.run(replace_stock(pid, items))
    return jsonify({"status": status, "response": resp})

# --- RUN BOTH FLASK + DISCORD ---
def run_flask():
    app.run(host="0.0.0.0", port=5000)

threading.Thread(target=run_flask).start()
bot.run(TOKEN)
