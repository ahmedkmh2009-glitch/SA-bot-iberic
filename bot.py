import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands
from flask import Flask
import threading

# --- CONFIG ---
TOKEN = os.getenv("TOKEN")
SELLAUTH_API_KEY = os.getenv("SELLAUTH_API_KEY")
SELLAUTH_SHOP_ID = os.getenv("SELLAUTH_SHOP_ID")
LOGS_CHANNEL_ID = 1456619335014547549  # Canal de logs
OWNER_ROLE_ID = 1456619228915568671  # Rol de owner

# --- BOT ---
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# --- UTILIDADES API ---
def headers():
    return {"Authorization": f"Bearer {SELLAUTH_API_KEY}"}

async def request(method, url, json_body=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, url, headers=headers(), json=json_body) as r:
            raw = await r.text()
            try:
                js = await r.json(content_type=None)
            except:
                js = None
            return r.status, raw, js

async def list_products():
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products"
    status, raw, js = await request("GET", url)
    data = js.get("data") if isinstance(js, dict) else js
    return data if isinstance(data, list) else []

async def get_product(pid):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}"
    status, raw, js = await request("GET", url)
    return js.get("data") if isinstance(js, dict) else js

async def get_stock(pid):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/deliverables"
    status, raw, js = await request("GET", url)
    if isinstance(js, list):
        return js
    if isinstance(js, dict):
        if "deliverables" in js and isinstance(js["deliverables"], list):
            return js["deliverables"]
        if "data" in js and isinstance(js["data"], list):
            return js["data"]
    return []

async def update_stock(pid, items):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/stock"
    return await request("PUT", url, {"deliverables": items})

async def get_invoice(invoice_id):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/invoices/{invoice_id}"
    status, raw, js = await request("GET", url)
    return status, js

# --- PERMISOS POR ROL ---
def is_owner():
    async def predicate(interaction: discord.Interaction):
        if not isinstance(interaction.user, discord.Member):
            return False
        role_ids = [role.id for role in interaction.user.roles]
        if OWNER_ROLE_ID not in role_ids:
            await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# --- AUTOCOMPLETE PRODUCTOS ---
async def product_autocomplete(interaction: discord.Interaction, current: str):
    products = await list_products()
    return [
        app_commands.Choice(name=p.get("name"), value=str(p.get("id")))
        for p in products
        if current.lower() in (p.get("name") or "").lower()
    ][:25]

# --- COMANDOS ---
@bot.tree.command(name="products_text")
@is_owner()
async def products_text(interaction: discord.Interaction):
    products = await list_products()
    if not products:
        return await interaction.response.send_message("No products found.", ephemeral=True)
    message = "**Available products:**\n"
    for p in products:
        pid = p.get("id")
        pname = p.get("name")
        message += f"- `{pid}`: {pname}\n"
    await interaction.response.send_message(message, ephemeral=True)

@bot.tree.command(name="stock")
@app_commands.describe(product_id="Producto a consultar")
@is_owner()
@app_commands.autocomplete(product_id=product_autocomplete)
async def stock(interaction: discord.Interaction, product_id: str):
    stock_list = await get_stock(product_id)
    if not stock_list:
        return await interaction.response.send_message("❌ No stock for this product.", ephemeral=True)
    preview = "\n".join(stock_list[:10])
    await interaction.response.send_message(
        f"Stock for {product_id}: {len(stock_list)} items\nPreview:\n```{preview}```",
        ephemeral=True
    )

@bot.tree.command(name="addstock")
@app_commands.describe(product_id="Producto al que añadir stock", items="Items a añadir, separados por coma")
@is_owner()
@app_commands.autocomplete(product_id=product_autocomplete)
async def addstock(interaction: discord.Interaction, product_id: str, items: str):
    item_list = [x.strip() for x in items.split(",") if x.strip()]
    if not item_list:
        return await interaction.response.send_message("No items provided.", ephemeral=True)
    status, raw, js = await update_stock(product_id, item_list)
    if status < 200 or status >= 300:
        return await interaction.response.send_message(f"Error updating stock: {js or raw}", ephemeral=True)
    await interaction.response.send_message(f"✅ Added {len(item_list)} items to {product_id}", ephemeral=True)

@bot.tree.command(name="replace")
@app_commands.describe(
    user="Usuario que recibirá los items",
    product_id="Producto a reemplazar",
    quantity="Cantidad de items a remover"
)
@is_owner()
@app_commands.autocomplete(product_id=product_autocomplete)
async def replace(interaction: discord.Interaction, user: discord.Member, product_id: str, quantity: int):
    stock_list = await get_stock(product_id)
    if not stock_list:
        return await interaction.response.send_message("❌ No stock for this product.", ephemeral=True)
    if quantity > len(stock_list):
        return await interaction.response.send_message(f"❌ Not enough stock. Available: {len(stock_list)}", ephemeral=True)
    removed = stock_list[:quantity]
    remaining = stock_list[quantity:]
    await update_stock(product_id, remaining)
    try:
        await user.send(f"📦 Here are your items:\n```{chr(10).join(removed)}```")
    except:
        await interaction.response.send_message("⚠️ Could not DM the user.", ephemeral=True)
    log_channel = bot.get_channel(LOGS_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"{interaction.user} removed {quantity} items from {product_id} and sent to {user}.")
    await interaction.response.send_message(
        f"✅ Removed {quantity} items from `{product_id}` and sent to {user.mention}",
        ephemeral=True
    )

@bot.tree.command(name="invoice")
@app_commands.describe(invoice_id="Invoice ID to check")
@is_owner()
async def invoice(interaction: discord.Interaction, invoice_id: str):
    status, js = await get_invoice(invoice_id)
    if status != 200:
        return await interaction.response.send_message(f"Invoice {invoice_id} not found.", ephemeral=True)
    embed = discord.Embed(
        title=f"Invoice {invoice_id}",
        description=f"Status: {js.get('status')}\nPrice: {js.get('price')} {js.get('currency')}",
        color=discord.Color.green()
    )
    items = js.get("items") or []
    for it in items:
        deliverables = it.get("delivered") or []
        embed.add_field(
            name=it.get("product", {}).get("name") or "Item",
            value=f"Quantity: {it.get('quantity')} | Delivered: {len(deliverables)}\nDeliverables:\n```{chr(10).join(deliverables) if deliverables else 'None'}```",
            inline=False
        )
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- FLASK PARA 24/7 ---
app = Flask("")

@app.route("/")
def home():
    return "Bot is running", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

threading.Thread(target=run_flask).start()

# --- START BOT ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
