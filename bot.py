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
OWNER_ID = 1456619228915568671  # Solo este usuario puede usar comandos

# --- BOT ---
intents = discord.Intents.default()
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

async def get_variants(pid):
    p = await get_product(pid)
    if not p: return []
    if isinstance(p.get("variants"), list) and p["variants"]:
        return p["variants"]
    for k in ("variant", "default_variant"):
        v = p.get(k)
        if isinstance(v, dict) and v.get("id"):
            return [v]
    return []

async def get_stock(pid, vid):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/deliverables/{vid}"
    status, raw, js = await request("GET", url)
    return js if isinstance(js, list) else js.get("deliverables") if js else []

async def update_stock(pid, vid, items):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/stock/{vid}"
    return await request("PUT", url, {"deliverables": items})

async def get_invoice(invoice_id):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/invoices/{invoice_id}"
    status, raw, js = await request("GET", url)
    return status, js

# --- PERMISOS ---
def is_owner():
    async def predicate(interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ You are not authorized to use this command.", ephemeral=True)
            return False
        return True
    return app_commands.check(predicate)

# --- COMANDOS BOT ---
@bot.tree.command(name="products_text")
@is_owner()
async def products_text(interaction: discord.Interaction):
    """Lista todos los productos disponibles"""
    products = await list_products()
    if not products:
        return await interaction.response.send_message("No products found.", ephemeral=True)

    message = "**Available products:**\n"
    for p in products:
        pid = p.get("id")
        pname = p.get("name")
        message += f"- `{pid}`: {pname}\n"
    message += "\nType `/addtocart <product_id>` to add it to your command."
    await interaction.response.send_message(message, ephemeral=True)

@bot.tree.command(name="addtocart")
@app_commands.describe(product_id="ID of the product to add")
@is_owner()
async def addtocart(interaction: discord.Interaction, product_id: str):
    """Añade un producto al comando SBS"""
    product = await get_product(product_id)
    if not product:
        return await interaction.response.send_message("Product not found.", ephemeral=True)
    
    await interaction.response.send_message(f"✅ Added **{product.get('name')}** to your command.", ephemeral=True)

@bot.tree.command(name="stock")
@app_commands.describe(product_id="ID of the product to check stock")
@is_owner()
async def stock(interaction: discord.Interaction, product_id: str):
    """Muestra el stock de un producto"""
    variants = await get_variants(product_id)
    if not variants:
        return await interaction.response.send_message("No variants found for this product.", ephemeral=True)
    
    msg = f"**Stock for {product_id}:**\n"
    for v in variants:
        vid = v.get("id")
        vname = v.get("name") or str(vid)
        stock_list = await get_stock(product_id, vid)
        msg += f"- Variant `{vname}`: {len(stock_list)} items\n"
        if stock_list:
            msg += "  Preview: ```" + "\n".join(stock_list[:10]) + "```\n"
    await interaction.response.send_message(msg, ephemeral=True)

@bot.tree.command(name="addstock")
@app_commands.describe(product_id="ID of the product", variant_id="ID of the variant", items="Items to add, comma-separated")
@is_owner()
async def addstock(interaction: discord.Interaction, product_id: str, variant_id: str, items: str):
    """Añade stock a un producto"""
    item_list = [x.strip() for x in items.split(",") if x.strip()]
    if not item_list:
        return await interaction.response.send_message("No items provided.", ephemeral=True)
    status, raw, js = await update_stock(product_id, variant_id, item_list)
    if status < 200 or status >= 300:
        return await interaction.response.send_message(f"Error updating stock: {js or raw}", ephemeral=True)
    await interaction.response.send_message(f"✅ Added {len(item_list)} items to product `{product_id}` variant `{variant_id}`.", ephemeral=True)

@bot.tree.command(name="invoice")
@app_commands.describe(invoice_id="Invoice ID to check")
@is_owner()
async def invoice(interaction: discord.Interaction, invoice_id: str):
    """Consulta una factura"""
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

@bot.tree.command(name="replace")
@app_commands.describe(user="Usuario al que enviar los items", product_id="ID del producto", variant_id="ID de la variante", quantity="Cantidad a remover")
@is_owner()
async def replace(interaction: discord.Interaction, user: discord.Member, product_id: str, variant_id: str, quantity: int):
    """Quita items de stock y los envía a un usuario"""
    stock_list = await get_stock(product_id, variant_id)
    if not stock_list:
        return await interaction.response.send_message("No stock available for this product/variant.", ephemeral=True)
    
    if quantity > len(stock_list):
        return await interaction.response.send_message(f"❌ Not enough stock. Available: {len(stock_list)}", ephemeral=True)
    
    removed = stock_list[:quantity]
    remaining = stock_list[quantity:]
    
    # Actualizamos stock
    await update_stock(product_id, variant_id, remaining)
    
    # Enviamos los items al usuario por DM
    try:
        await user.send(f"Here are your items:\n```{chr(10).join(removed)}```")
    except:
        await interaction.response.send_message("⚠️ Could not DM the user.", ephemeral=True)
    
    # Log en canal
    log_channel = bot.get_channel(LOGS_CHANNEL_ID)
    if log_channel:
        await log_channel.send(f"{interaction.user} removed {quantity} items from {product_id}/{variant_id} and sent them to {user}")
    
    await interaction.response.send_message(f"✅ Removed {quantity} items from `{product_id}` variant `{variant_id}` and sent to {user.mention}", ephemeral=True)

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
