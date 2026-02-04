import os
import discord
from discord import app_commands
from discord.ext import commands
import requests
import io

# --- Config ---
TOKEN = os.environ["TOKEN"]
SELLAUTH_API_KEY = os.environ["SELLAUTH_API_KEY"]
SELLAUTH_SHOP_ID = os.environ["SELLAUTH_SHOP_ID"]
LOG_CHANNEL_ID = 1456619335014547549  # Canal de logs

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

# Headers para API Sellauth
headers = {"Authorization": f"Bearer {SELLAUTH_API_KEY}", "Content-Type": "application/json"}

# --- Funciones API ---
def get_products():
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products"
    resp = requests.get(url, headers=headers)
    return resp.json().get("data", [])

def update_stock(product_id, variant_id, new_stock):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{product_id}/stock/{variant_id}"
    data = {"stock": new_stock}
    requests.put(url, headers=headers, json=data)

def get_variant_stock(product):
    stock_info = []
    for variant in product.get("variants", []):
        stock_info.append(f"{variant['id']} - {variant['name']}: {variant['stock']}")
    return "\n".join(stock_info)

# --- Evento on_ready ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Logged in as {bot.user}")

# --- /products ---
@bot.tree.command(name="products", description="Lista productos y variantes (IDs y stock)")
async def products(interaction: discord.Interaction):
    products = get_products()
    msg = ""
    for p in products:
        msg += f"**{p['name']}** (ID: {p['id']})\n"
        for v in p.get("variants", []):
            msg += f" - {v['name']} (Variant ID: {v['id']}): {v['stock']} en stock\n"
    await interaction.response.send_message(msg or "No hay productos.")

# --- /stock ---
@bot.tree.command(name="stock", description="Ver stock de un producto/variante")
@app_commands.describe(product_id="ID del producto", variant_id="ID de la variante")
async def stock(interaction: discord.Interaction, product_id: int, variant_id: int = None):
    products = get_products()
    for p in products:
        if p["id"] == product_id:
            if variant_id:
                for v in p.get("variants", []):
                    if v["id"] == variant_id:
                        await interaction.response.send_message(f"Stock {v['name']}: {v['stock']}")
                        return
            else:
                await interaction.response.send_message(get_variant_stock(p))
                return
    await interaction.response.send_message("Producto/Variante no encontrado.")

# --- /addstock ---
@bot.tree.command(name="addstock", description="Añade stock desde un TXT")
@app_commands.describe(file="TXT con cuentas (mail:pass) por línea", product_id="ID del producto", variant_id="ID de la variante")
async def addstock(interaction: discord.Interaction, file: discord.Attachment, product_id: int, variant_id: int):
    await interaction.response.defer()
    content = await file.read()
    lines = content.decode().splitlines()
    products = get_products()
    for p in products:
        if p["id"] == product_id:
            for v in p.get("variants", []):
                if v["id"] == variant_id:
                    new_stock = (v["stock"] or 0) + len(lines)
                    update_stock(product_id, variant_id, new_stock)
                    await interaction.followup.send(f"Se añadieron {len(lines)} al stock de {v['name']} (Nuevo stock: {new_stock})")
                    # Log
                    log_channel = bot.get_channel(LOG_CHANNEL_ID)
                    if log_channel:
                        await log_channel.send(f"ADDSTOCK: {len(lines)} cuentas añadidas a {v['name']} (Producto ID {product_id})")
                    return
    await interaction.followup.send("Producto o variante no encontrado.")

# --- /invoice ---
@bot.tree.command(name="invoice", description="Mostrar invoice de un pedido")
@app_commands.describe(invoice_id="ID del invoice")
async def invoice(interaction: discord.Interaction, invoice_id: str):
    url = f"https://api.sellauth.com/v1/invoices/{invoice_id}"
    resp = requests.get(url, headers=headers)
    if resp.status_code != 200:
        await interaction.response.send_message("Invoice no encontrado.")
        return
    inv = resp.json()
    embed = discord.Embed(title=f"Invoice {invoice_id}", description=f"Total: {inv.get('total')}", color=discord.Color.green())
    for item in inv.get("items", []):
        embed.add_field(name=item["name"], value=f"Cantidad: {item['quantity']} - Precio: {item['price']}", inline=False)
    await interaction.response.send_message(embed=embed)

# --- /replace ---
@bot.tree.command(name="replace", description="Hacer replace de un producto y enviar cuentas al DM del comprador")
@app_commands.describe(product_id="ID del producto", variant_id="ID de la variante", amount="Cantidad a enviar", user="Usuario comprador")
async def replace(interaction: discord.Interaction, product_id: int, variant_id: int, amount: int, user: discord.User):
    products = get_products()
    for p in products:
        if p["id"] == product_id:
            for v in p.get("variants", []):
                if v["id"] == variant_id:
                    current_stock = v["stock"] or 0
                    if amount > current_stock:
                        await interaction.response.send_message("No hay suficiente stock para enviar.")
                        return
                    # Reducir stock
                    update_stock(product_id, variant_id, current_stock - amount)
                    # Preparar cuentas (ejemplo ficticio)
                    cuentas = [f"account{i+1}@example.com:pass{i+1}" for i in range(amount)]
                    cuentas_txt = "\n".join(cuentas)
                    # Enviar DM al usuario
                    try:
                        await user.send(f"Tus cuentas:\n```\n{cuentas_txt}\n```")
                        await interaction.response.send_message(f"{amount} cuentas enviadas a {user.name}")
                    except:
                        await interaction.response.send_message("No se pudo enviar DM al usuario.")
                    # Log
                    log_channel = bot.get_channel(LOG_CHANNEL_ID)
                    if log_channel:
                        await log_channel.send(f"REPLACE: {amount} cuentas de {v['name']} enviadas a {user} (Stock anterior: {current_stock}, Nuevo stock: {current_stock-amount})")
                    return
    await interaction.response.send_message("Producto o variante no encontrado.")

# --- Run Bot ---
bot.run(TOKEN)
