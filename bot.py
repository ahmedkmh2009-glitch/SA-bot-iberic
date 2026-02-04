import os
import discord
from discord import app_commands
from discord.ext import commands
import requests
import io

# Variables de entorno
SELLAUTH_API_KEY = os.getenv("SELLAUTH_API_KEY")
SELLAUTH_SHOP_ID = os.getenv("SELLAUTH_SHOP_ID")
TOKEN = os.getenv("TOKEN")
LOGS_CHANNEL_ID = int(os.getenv("LOGS_CHANNEL_ID"))

# Bot
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# Encabezados de la API
headers = {
    "Authorization": f"Bearer {SELLAUTH_API_KEY}",
    "Content-Type": "application/json"
}

# =====================
# FUNCIONES API
# =====================

def get_products():
    """Devuelve la lista de productos con sus variantes y stock"""
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        return []
    data = r.json().get("data", [])
    products_list = []
    for p in data:
        for v in p.get("variants", []):
            products_list.append({
                "product_id": p["id"],
                "variant_id": v["id"],
                "name": p["name"],
                "variant": v["name"],
                "stock": v.get("stock", 0)
            })
    return products_list

def update_stock(product_id, variant_id, new_stock):
    """Actualiza el stock de una variante"""
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{product_id}/stock/{variant_id}"
    r = requests.put(url, headers=headers, json={"stock": new_stock})
    return r.status_code == 200

def get_stock(product_id, variant_id):
    """Obtiene stock de una variante"""
    products = get_products()
    for p in products:
        if p["product_id"] == product_id and p["variant_id"] == variant_id:
            return p["stock"]
    return None

# =====================
# COMANDOS SLASH
# =====================

@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot listo como {bot.user}")

# --- LISTAR PRODUCTOS ---
@bot.tree.command(name="products", description="Lista todos los productos con sus variantes y stock")
async def products(interaction: discord.Interaction):
    products = get_products()
    if not products:
        await interaction.response.send_message("No se pudieron obtener los productos.", ephemeral=True)
        return
    desc = ""
    for p in products:
        desc += f"**{p['name']}** | Variante: {p['variant']} | Product ID: {p['product_id']} | Variant ID: {p['variant_id']} | Stock: {p['stock']}\n"
    embed = discord.Embed(title="Productos y variantes", description=desc, color=0x00ff00)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# --- VER STOCK ---
@bot.tree.command(name="stock", description="Ver stock de un producto/variante")
@app_commands.describe(product_id="ID del producto", variant_id="ID de la variante")
async def stock(interaction: discord.Interaction, product_id: int, variant_id: int):
    s = get_stock(product_id, variant_id)
    if s is None:
        await interaction.response.send_message("Producto o variante no encontrado.", ephemeral=True)
    else:
        await interaction.response.send_message(f"Stock actual: {s}", ephemeral=True)

# --- ADD STOCK ---
@bot.tree.command(name="addstock", description="Añade stock a un producto desde un archivo txt")
@app_commands.describe(product_id="ID del producto", variant_id="ID de la variante")
async def addstock(interaction: discord.Interaction, product_id: int, variant_id: int):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No tienes permisos.", ephemeral=True)
        return

    await interaction.response.send_message("Envía el archivo TXT con las cuentas.", ephemeral=True)

    def check(m):
        return m.author == interaction.user and m.attachments

    msg = await bot.wait_for('message', check=check, timeout=60)
    file = msg.attachments[0]
    content = await file.read()
    lines = content.decode().splitlines()

    current_stock = get_stock(product_id, variant_id) or 0
    new_stock = current_stock + len(lines)
    success = update_stock(product_id, variant_id, new_stock)

    if success:
        # Log en canal
        log_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="📦 Stock añadido", color=0x00ff00)
            embed.add_field(name="Producto ID", value=product_id, inline=True)
            embed.add_field(name="Variante ID", value=variant_id, inline=True)
            embed.add_field(name="Stock anterior", value=current_stock, inline=True)
            embed.add_field(name="Stock actual", value=new_stock, inline=True)
            embed.add_field(name="Cantidad de cuentas añadidas", value=len(lines), inline=True)
            await log_channel.send(embed=embed)

        await interaction.followup.send(f"Stock actualizado correctamente. Total: {new_stock}", ephemeral=True)
    else:
        await interaction.followup.send("Error al actualizar stock.", ephemeral=True)

# --- REPLACE ---
@bot.tree.command(name="replace", description="Hacer replace de un producto y enviar cuentas al comprador")
@app_commands.describe(product_id="ID del producto", variant_id="ID de la variante", user="Usuario comprador")
async def replace(interaction: discord.Interaction, product_id: int, variant_id: int, user: discord.User):
    if not interaction.user.guild_permissions.administrator:
        await interaction.response.send_message("No tienes permisos.", ephemeral=True)
        return

    await interaction.response.send_message("Envía el archivo TXT con las cuentas a entregar.", ephemeral=True)

    def check(m):
        return m.author == interaction.user and m.attachments

    msg = await bot.wait_for('message', check=check, timeout=60)
    file = msg.attachments[0]
    content = await file.read()
    lines = content.decode().splitlines()

    current_stock = get_stock(product_id, variant_id) or 0
    if current_stock < len(lines):
        await interaction.followup.send(f"No hay suficiente stock. Actual: {current_stock}", ephemeral=True)
        return

    new_stock = current_stock - len(lines)
    success = update_stock(product_id, variant_id, new_stock)

    if success:
        # Enviar DM al comprador
        dm = await user.create_dm()
        msg_content = f"📦 Tu replace ha sido procesado\nProducto ID: {product_id}\nVariante ID: {variant_id}\nCantidad entregada: {len(lines)}\nCuentas:\n" + "\n".join(lines)
        await dm.send(msg_content)

        # Log en canal
        log_channel = bot.get_channel(LOGS_CHANNEL_ID)
        if log_channel:
            embed = discord.Embed(title="🔄 Replace procesado", color=0xffa500)
            embed.add_field(name="Producto ID", value=product_id, inline=True)
            embed.add_field(name="Variante ID", value=variant_id, inline=True)
            embed.add_field(name="Stock anterior", value=current_stock, inline=True)
            embed.add_field(name="Stock actual", value=new_stock, inline=True)
            embed.add_field(name="Cantidad entregada", value=len(lines), inline=True)
            embed.add_field(name="Comprador", value=user.mention, inline=True)
            embed.add_field(name="Acción realizada por", value=interaction.user.mention, inline=True)
            embed.add_field(name="Cuentas enviadas", value="\n".join(lines), inline=False)
            await log_channel.send(embed=embed)

        await interaction.followup.send(f"Replace realizado con éxito. Se enviaron {len(lines)} cuentas a {user.mention}", ephemeral=True)
    else:
        await interaction.followup.send("Error al actualizar stock.", ephemeral=True)

# --- INVOICE ---
@bot.tree.command(name="invoice", description="Ver invoice de un pedido")
@app_commands.describe(invoice_id="ID de la invoice")
async def invoice(interaction: discord.Interaction, invoice_id: str):
    url = f"https://api.sellauth.com/v1/invoices/{invoice_id}"
    r = requests.get(url, headers=headers)
    if r.status_code != 200:
        await interaction.response.send_message("Invoice no encontrada.", ephemeral=True)
        return

    data = r.json()
    embed = discord.Embed(title=f"Invoice #{invoice_id}", color=0x0000ff)
    embed.add_field(name="Cliente", value=data.get("customer_name", "Desconocido"))
    embed.add_field(name="Total", value=data.get("total", "0"))
    embed.add_field(name="Estado", value=data.get("status", "Desconocido"))
    embed.add_field(name="Productos", value="\n".join([f"{p['name']} x{p['quantity']}" for p in data.get("items", [])]) or "Ninguno", inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

# =====================
# RUN BOT
# =====================
bot.run(TOKEN)
