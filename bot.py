import os
import discord
from discord import app_commands
from discord.ext import commands
import requests

# --- VARIABLES ---
TOKEN = os.environ["TOKEN"]
SELLAUTH_API_KEY = os.environ["SELLAUTH_API_KEY"]
SELLAUTH_SHOP_ID = os.environ["SELLAUTH_SHOP_ID"]
LOG_CHANNEL_ID = 1456619335014547549  # Canal de logs

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="!", intents=intents)

HEADERS = {"Authorization": f"Bearer {SELLAUTH_API_KEY}", "Content-Type": "application/json"}

# --- FUNCIONES API ---
def get_products():
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products"
    resp = requests.get(url, headers=HEADERS)
    return resp.json().get("data", [])

def update_stock(product_id, variant_id, new_stock):
    url = f"https://api.sellauth.com/v1/shops/{SELLAUTH_SHOP_ID}/products/{product_id}/stock/{variant_id}"
    requests.put(url, headers=HEADERS, json={"stock": new_stock})

def get_variant_stock(product):
    return "\n".join([f"{v['name']} (Variant ID: {v['id']}): {v['stock']}" for v in product.get("variants", [])])

# --- EVENTO ON_READY ---
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"Bot listo - Conectado como {bot.user}")

# --- /products ---
@bot.tree.command(name="products", description="Lista productos y variantes (IDs y stock)")
async def products(interaction: discord.Interaction):
    products_list = get_products()
    if not products_list:
        await interaction.response.send_message("No hay productos.")
        return
    embed = discord.Embed(title="Productos y Variantes", color=discord.Color.blue())
    for p in products_list:
        variants = "\n".join([f"{v['name']} (ID {v['id']}): {v['stock']} en stock" for v in p.get("variants", [])])
        embed.add_field(name=f"{p['name']} (ID {p['id']})", value=variants or "No hay variantes", inline=False)
    await interaction.response.send_message(embed=embed)

# --- /stock ---
@bot.tree.command(name="stock", description="Ver stock de un producto/variante")
@app_commands.describe(product_id="ID del producto", variant_id="ID de la variante opcional")
async def stock(interaction: discord.Interaction, product_id: int, variant_id: int = None):
    products_list = get_products()
    for p in products_list:
        if p["id"] == product_id:
            if variant_id:
                for v in p.get("variants", []):
                    if v["id"] == variant_id:
                        await interaction.response.send_message(f"Stock {v['name']}: {v['stock']}")
                        return
            else:
                embed = discord.Embed(title=f"Stock de {p['name']}", color=discord.Color.green())
                for v in p.get("variants", []):
                    embed.add_field(name=v['name'], value=f"Stock: {v['stock']} (Variant ID {v['id']})", inline=False)
                await interaction.response.send_message(embed=embed)
                return
    await interaction.response.send_message("Producto o variante no encontrado.")

# --- SELECT MENUS ---
class ProductSelect(discord.ui.Select):
    def __init__(self, products, callback):
        options = []
        for p in products:
            for v in p.get("variants", []):
                label = f"{p['name']} - {v['name']} ({v['stock']} en stock)"
                value = f"{p['id']}|{v['id']}"
                options.append(discord.SelectOption(label=label, value=value))
        super().__init__(placeholder="Selecciona producto/variante...", min_values=1, max_values=1, options=options)
        self.callback_func = callback

    async def callback(self, interaction: discord.Interaction):
        product_id, variant_id = map(int, self.values[0].split("|"))
        await self.callback_func(interaction, product_id, variant_id)

class ProductView(discord.ui.View):
    def __init__(self, products, callback):
        super().__init__()
        self.add_item(ProductSelect(products, callback))

# --- /addstock ---
@bot.tree.command(name="addstock", description="Añade stock desde un TXT")
@app_commands.describe(file="TXT con cuentas (mail:pass) por línea")
async def addstock(interaction: discord.Interaction, file: discord.Attachment):
    products_list = get_products()
    async def handle_select(inter, product_id, variant_id):
        content = await file.read()
        lines = content.decode().splitlines()
        for p in products_list:
            if p["id"] == product_id:
                for v in p.get("variants", []):
                    if v["id"] == variant_id:
                        stock_anterior = v["stock"] or 0
                        stock_nuevo = stock_anterior + len(lines)
                        update_stock(product_id, variant_id, stock_nuevo)
                        embed = discord.Embed(
                            title="Stock actualizado",
                            description=f"Producto: {p['name']} - Variante: {v['name']}",
                            color=discord.Color.green()
                        )
                        embed.add_field(name="Stock anterior", value=str(stock_anterior))
                        embed.add_field(name="Stock añadido", value=str(len(lines)))
                        embed.add_field(name="Stock nuevo", value=str(stock_nuevo))
                        await inter.response.send_message(embed=embed)
                        log_channel = bot.get_channel(LOG_CHANNEL_ID)
                        if log_channel:
                            await log_channel.send(f"ADDSTOCK: {len(lines)} cuentas añadidas a {v['name']} (Producto ID {product_id}, Stock anterior {stock_anterior}, Stock nuevo {stock_nuevo})")
                        return
    await interaction.response.send_message("Selecciona el producto/variante a añadir stock:", view=ProductView(products_list, handle_select))

# --- /replace ---
@bot.tree.command(name="replace", description="Hacer replace de un producto y enviar cuentas al DM del comprador")
@app_commands.describe(amount="Cantidad a enviar", user="Usuario comprador")
async def replace(interaction: discord.Interaction, amount: int, user: discord.User):
    products_list = get_products()
    async def handle_select(inter, product_id, variant_id):
        for p in products_list:
            if p["id"] == product_id:
                for v in p.get("variants", []):
                    if v["id"] == variant_id:
                        stock_anterior = v["stock"] or 0
                        if amount > stock_anterior:
                            await inter.response.send_message("No hay suficiente stock para enviar.")
                            return
                        stock_nuevo = stock_anterior - amount
                        update_stock(product_id, variant_id, stock_nuevo)
                        cuentas = [f"account{i+1}@example.com:pass{i+1}" for i in range(amount)]
                        cuentas_txt = "\n".join(cuentas)
                        try:
                            await user.send(f"Tus cuentas:\n```\n{cuentas_txt}\n```")
                            embed = discord.Embed(
                                title="Replace realizado",
                                description=f"{amount} cuentas enviadas a {user.mention}",
                                color=discord.Color.orange()
                            )
                            embed.add_field(name="Producto", value=p['name'])
                            embed.add_field(name="Variante", value=v['name'])
                            embed.add_field(name="Stock anterior", value=str(stock_anterior))
                            embed.add_field(name="Stock nuevo", value=str(stock_nuevo))
                            await inter.response.send_message(embed=embed)
                        except:
                            await inter.response.send_message("No se pudo enviar DM al usuario.")
                        log_channel = bot.get_channel(LOG_CHANNEL_ID)
                        if log_channel:
                            await log_channel.send(f"REPLACE: {amount} cuentas de {v['name']} enviadas a {user} (Stock anterior: {stock_anterior}, Nuevo stock: {stock_nuevo})")
                        return
    await interaction.response.send_message("Selecciona el producto/variante a reemplazar:", view=ProductView(products_list, handle_select))

# --- /invoice ---
@bot.tree.command(name="invoice", description="Mostrar invoice de un pedido")
@app_commands.describe(invoice_id="ID del invoice")
async def invoice(interaction: discord.Interaction, invoice_id: str):
    url = f"https://api.sellauth.com/v1/invoices/{invoice_id}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code != 200:
        await interaction.response.send_message("Invoice no encontrado.")
        return
    inv = resp.json()
    embed = discord.Embed(title=f"Invoice {invoice_id}", description=f"Total: {inv.get('total')}", color=discord.Color.green())
    for item in inv.get("items", []):
        embed.add_field(name=item["name"], value=f"Cantidad: {item['quantity']} - Precio: {item['price']}", inline=False)
    await interaction.response.send_message(embed=embed)

# --- RUN BOT ---
bot.run(TOKEN)
