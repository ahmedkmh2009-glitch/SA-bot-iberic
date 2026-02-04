import os
import aiohttp
import discord
from discord import app_commands
from discord.ext import commands

# Variables de entorno
TOKEN = os.getenv("TOKEN")
SELLAUTH_API_KEY = os.getenv("SELLAUTH_API_KEY")
SELLAUTH_SHOP_ID = os.getenv("SELLAUTH_SHOP_ID")
LOGS_CHANNEL_ID = 1456619335014547549

# Setup bot
intents = discord.Intents.default()
intents.members = True
bot = commands.Bot(command_prefix="/", intents=intents)

# --- UTILIDADES DE API ---
def headers():
    return {"Authorization": f"Bearer {SELLAUTH_API_KEY}"}

async def request(method, url, json_body=None):
    async with aiohttp.ClientSession() as s:
        async with s.request(method, url, headers=headers(), json=json_body) as r:
            raw = await r.text()
            try:
                js = await r.json(content_type=None)
            except Exception:
                js = None
            return r.status, raw, js

# --- PRODUCTS ---
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
    return await request("GET", url)

async def update_stock(pid, vid, items):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{pid}/stock/{vid}"
    return await request("PUT", url, {"deliverables": items})

# --- INVOICE ---
async def get_invoice(invoice_id):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/invoices/{invoice_id}"
    status, raw, js = await request("GET", url)
    return status, js

# --- INTERFACES DISCORD ---
def split_lines(text):
    return [x.strip() for x in text.splitlines() if x.strip()]

class RestockModal(discord.ui.Modal, title="Add Stock"):
    stock = discord.ui.TextInput(label="Stock (one per line)", style=discord.TextStyle.paragraph)

    def __init__(self, pid, vid, pname, vname):
        super().__init__()
        self.pid = pid
        self.vid = vid
        self.pname = pname
        self.vname = vname

    async def on_submit(self, interaction: discord.Interaction):
        items = split_lines(self.stock.value)
        if not items:
            return await interaction.response.send_message("No stock provided", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        status, raw, js = await update_stock(self.pid, self.vid, items)
        embed = discord.Embed(
            title="Stock Added",
            description=f"{self.pname} / {self.vname}\nAdded {len(items)} items",
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

class VariantSelect(discord.ui.Select):
    def __init__(self, action, pid, pname, variants):
        options = [discord.SelectOption(label=v.get("name") or str(v.get("id")), value=str(v.get("id"))) for v in variants]
        super().__init__(placeholder="Select variant", options=options)
        self.action = action
        self.pid = pid
        self.pname = pname

    async def callback(self, interaction: discord.Interaction):
        vid = int(self.values[0])
        vname = next(o.label for o in self.options if o.value == str(vid))
        if self.action == "restock":
            await interaction.response.send_modal(RestockModal(self.pid, vid, self.pname, vname))
        elif self.action == "stock":
            status, raw, js = await get_stock(self.pid, vid)
            stock_list = js if isinstance(js, list) else js.get("deliverables") if js else []
            embed = discord.Embed(title=f"{self.pname} / {vname} Stock", description=f"Available: {len(stock_list)}", color=discord.Color.blurple())
            if stock_list:
                preview = "\n".join(stock_list[:10])
                embed.add_field(name="Preview", value=f"```{preview}```", inline=False)
            await interaction.response.send_message(embed=embed, ephemeral=True)

class VariantView(discord.ui.View):
    def __init__(self, action, pid, pname, variants):
        super().__init__(timeout=180)
        self.add_item(VariantSelect(action, pid, pname, variants))

class ProductSelect(discord.ui.Select):
    def __init__(self, action, products):
        options = [discord.SelectOption(label=p.get("name") or str(p.get("id")), value=str(p.get("id"))) for p in products]
        super().__init__(placeholder="Select product", options=options)
        self.action = action

    async def callback(self, interaction: discord.Interaction):
        pid = int(self.values[0])
        pname = next(o.label for o in self.options if o.value == str(pid))
        variants = await get_variants(pid)
        await interaction.response.send_message(embed=discord.Embed(title=pname), view=VariantView(self.action, pid, pname, variants), ephemeral=True)

class ProductView(discord.ui.View):
    def __init__(self, action, products):
        super().__init__(timeout=180)
        self.add_item(ProductSelect(action, products))

# --- COMANDOS ---
@bot.tree.command(name="products")
async def products(interaction: discord.Interaction):
    prods = await list_products()
    await interaction.response.send_message("Select a product:", view=ProductView("stock", prods), ephemeral=True)

@bot.tree.command(name="addstock")
async def addstock(interaction: discord.Interaction):
    prods = await list_products()
    await interaction.response.send_message("Select a product to add stock:", view=ProductView("restock", prods), ephemeral=True)

@bot.tree.command(name="stock")
async def stock(interaction: discord.Interaction):
    prods = await list_products()
    await interaction.response.send_message("Select a product to view stock:", view=ProductView("stock", prods), ephemeral=True)

@bot.tree.command(name="invoice")
@app_commands.describe(invoice_id="Invoice ID to check")
async def invoice(interaction: discord.Interaction, invoice_id: str):
    status, js = await get_invoice(invoice_id)
    if status != 200:
        return await interaction.response.send_message(f"Invoice {invoice_id} not found.", ephemeral=True)
    embed = discord.Embed(title=f"Invoice {invoice_id}", description=f"Status: {js.get('status')}\nPrice: {js.get('price')} {js.get('currency')}", color=discord.Color.green())
    items = js.get("items") or []
    for it in items:
        embed.add_field(name=it.get("product", {}).get("name") or "Item", value=f"Quantity: {it.get('quantity')} | Delivered: {len(it.get('delivered') or [])}", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

class ReplaceModal(discord.ui.Modal, title="Replace Product"):
    quantity = discord.ui.TextInput(label="Quantity to remove", style=discord.TextStyle.short)
    def __init__(self, pid, vid, pname, vname, user):
        super().__init__()
        self.pid = pid
        self.vid = vid
        self.pname = pname
        self.vname = vname
        self.user = user

    async def on_submit(self, interaction: discord.Interaction):
        qty = int(self.quantity.value)
        status, raw, js = await get_stock(self.pid, self.vid)
        stock_list = js if isinstance(js, list) else js.get("deliverables") if js else []
        if qty > len(stock_list):
            return await interaction.response.send_message("Not enough stock to remove.", ephemeral=True)
        removed = stock_list[:qty]
        remaining = stock_list[qty:]
        await update_stock(self.pid, self.vid, remaining)
        # send removed to user
        member = self.user
        try:
            await member.send(f"Here are your replaced accounts:\n```{chr(10).join(removed)}```")
        except:
            pass
        # log in channel
        log_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if log_channel:
            await log_channel.send(f"{interaction.user} removed {qty} from {self.pname}/{self.vname} for {member}")
        await interaction.response.send_message(f"Removed {qty} items and sent to {member.mention}", ephemeral=True)

class ReplaceSelect(discord.ui.Select):
    def __init__(self, pid, pname, variants, user):
        options = [discord.SelectOption(label=v.get("name") or str(v.get("id")), value=str(v.get("id"))) for v in variants]
        super().__init__(placeholder="Select variant", options=options)
        self.pid = pid
        self.pname = pname
        self.user = user

    async def callback(self, interaction: discord.Interaction):
        vid = int(self.values[0])
        vname = next(o.label for o in self.options if o.value == str(vid))
        await interaction.response.send_modal(ReplaceModal(self.pid, vid, self.pname, vname, self.user))

class ReplaceView(discord.ui.View):
    def __init__(self, pid, pname, variants, user):
        super().__init__()
        self.add_item(ReplaceSelect(pid, pname, variants, user))

@bot.tree.command(name="replace")
@app_commands.describe(user="User to send removed accounts")
async def replace(interaction: discord.Interaction, user: discord.Member):
    prods = await list_products()
    await interaction.response.send_message("Select product to replace:", view=ProductView("replace", prods), ephemeral=True)

# --- FLASK PARA 24/7 ---
from flask import Flask
import threading

app = Flask("")

@app.route("/")
def home():
    return "Bot is running", 200

def run_flask():
    app.run(host="0.0.0.0", port=10000)

# --- EJECUTAR FLASK EN HILO ---
threading.Thread(target=run_flask).start()

# --- START BOT ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

bot.run(TOKEN)
