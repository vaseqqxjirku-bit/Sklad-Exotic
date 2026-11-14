import os
import asyncio
import threading
import unicodedata
import ast
import operator
from http.server import HTTPServer, BaseHTTPRequestHandler
import discord
from discord.ext import commands

# --- HTTP SERVER PRO RENDER & UPTIMEROBOT (24/7 BĚH) ---
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"Exotic Sklad Bot is online 24/7!")
    def do_HEAD(self):
        self.send_response(200)
        self.end_headers()
    def log_message(self, format, *args):
        pass

def run_web_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), HealthCheckHandler)
    server.serve_forever()

threading.Thread(target=run_web_server, daemon=True).start()
# -------------------------------------------------------------

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents)

def normalize_name(name: str) -> str:
    """Odstraní háčky, čárky, převede na malá písmena a ořízne mezery pro spolehlivé párování."""
    return "".join(
        c for c in unicodedata.normalize("NFD", name)
        if unicodedata.category(c) != "Mn"
    ).lower().strip()

# Bezpečné vyhodnocení matematických operací (kalkulačka ve formuláři)
operator_map = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.USub: operator.neg,
}

def parse_calc(expr_str: str) -> int:
    """Umožňuje psát příklady typu 500+200 nebo 948-550 přímo do políčka."""
    expr_str = expr_str.strip().replace(" ", "").replace(",", ".")
    if not expr_str:
        return 0
    try:
        node = ast.parse(expr_str, mode='eval')
        def _eval(n):
            if isinstance(n, ast.Constant):
                if isinstance(n.value, (int, float)):
                    return n.value
                raise TypeError()
            elif isinstance(n, ast.BinOp):
                if type(n.op) in operator_map:
                    return operator_map[type(n.op)](_eval(n.left), _eval(n.right))
                raise TypeError()
            elif isinstance(n, ast.UnaryOp):
                if type(n.op) in operator_map:
                    return operator_map[type(n.op)](_eval(n.operand))
                raise TypeError()
            else:
                raise TypeError()
        result = _eval(node.body)
        return int(round(result))
    except Exception:
        return int(float(expr_str))

def create_exotic_embed(items_dict: dict, total_money: int, history_list: list):
    embed = discord.Embed(
        title="🏎️ SKLAD EXOTIC – SOUČÁSTKY & FINANCE",
        color=discord.Color.from_rgb(0, 255, 128)
    )
    
    if items_dict:
        items_text = "\n".join([f"**{item}:** `{qty} ks`" for item, qty in sorted(items_dict.items())])
    else:
        items_text = "*Sklad součástek je prázdný*"
    embed.add_field(name="📊 Aktuální stav součástek", value=items_text, inline=False)
    
    embed.add_field(name="💵 Finanční bilance", value=f"Celková částka vložena/přičtena: **`{total_money:,} $`**".replace(",", " "), inline=False)
    
    if history_list:
        history_text = "\n".join(history_list[-5:])
    else:
        history_text = "*Zatím žádné pohyby*"
    embed.add_field(name="📜 Poslední pohyby", value=history_text, inline=False)
    
    embed.set_footer(text="Exotic Skladový a finanční systém")
    return embed

class ExoticModal(discord.ui.Modal):
    def __init__(self, action_type: str):
        title_text = "Přidat součástky & finance" if action_type == "add" else "Odebrat součástky & finance"
        super().__init__(title=title_text)
        self.action_type = action_type
        
        self.item_input = discord.ui.TextInput(
            label="Název součástky (např. soucastky)",
            style=discord.TextStyle.short,
            placeholder="Napiš název součástky...",
            required=True,
            max_length=50
        )
        self.amount_input = discord.ui.TextInput(
            label="Počet kusů (lze i příklad, např. 948-550)",
            style=discord.TextStyle.short,
            placeholder="Např. 949 nebo 948-550",
            required=True,
            max_length=20
        )
        self.money_input = discord.ui.TextInput(
            label="Peníze ($) (lze i příklad)",
            style=discord.TextStyle.short,
            placeholder="Např. 0 nebo 150000",
            required=True,
            max_length=20
        )
        self.reason_input = discord.ui.TextInput(
            label="Důvod / Poznámka",
            style=discord.TextStyle.short,
            placeholder="Např. Dovoz dílů, nákup...",
            required=True,
            max_length=100
        )
        
        self.add_item(self.item_input)
        self.add_item(self.amount_input)
        self.add_item(self.money_input)
        self.add_item(self.reason_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            qty = parse_calc(self.amount_input.value)
            money = parse_calc(self.money_input.value)
            
            # Povolíme zadat kladné číslo pro přičtení/odečtení
            if qty == 0 or money < 0:
                await interaction.response.send_message("❌ Množství nesmí být 0 a peníze nesmí být záporné!", ephemeral=True)
                return

            item_name = self.item_input.value.strip()
            item_key = normalize_name(item_name)
            reason = self.reason_input.value.strip()
            user_name = interaction.user.display_name

            if not interaction.message or not interaction.message.embeds:
                await interaction.response.send_message("❌ Nelze načíst zprávu skladu. Napiš nový příkaz `!exotic`.", ephemeral=True)
                return

            embed = interaction.message.embeds[0]
            items_dict = {}
            items_map = {}
            total_money = 0
            history_list = []
            
            for field in embed.fields:
                if "Aktuální stav součástek" in field.name and field.value != "*Sklad součástek je prázdný*":
                    for line in field.value.split("\n"):
                        if "**" in line and ":" in line:
                            parts = line.split(":", 1)
                            orig_name = parts[0].replace("*", "").strip()
                            try:
                                # Správně načte i záporná čísla (např. -550)
                                q_str = parts[1].replace("ks", "").replace("`", "").strip()
                                q = int(q_str)
                                norm_key = normalize_name(orig_name)
                                items_dict[orig_name] = q
                                items_map[norm_key] = orig_name
                            except ValueError:
                                pass
                elif "Finanční bilance" in field.name:
                    try:
                        val = field.value.split("**`")[1].split(" $`**")[0].replace(" ", "").replace(",", "")
                        total_money = int(val)
                    except Exception:
                        total_money = 0
                elif "Poslední pohyby" in field.name and field.value != "*Zatím žádné pohyby*":
                    history_list = field.value.split("\n")

            real_item_name = items_map.get(item_key, item_name)
            current_qty = items_dict.get(real_item_name, 0)
            
            # MATEMATICKÉ OPERACE (zohledňuje i případný záporný stav)
            if self.action_type == "add":
                items_dict[real_item_name] = current_qty + qty
                total_money += money
                sign_str = f"+{qty}"
                money_str = f"+{money:,} $".replace(",", " ")
                action_desc = "přidal součástky"
            else:
                items_dict[real_item_name] = current_qty - qty
                total_money -= money
                sign_str = f"-{qty}"
                money_str = f"-{money:,} $".replace(",", " ")
                action_desc = "odebral součástky"

            log_entry = f"• **{user_name}** {action_desc}: `{sign_str} {real_item_name}` | Peníze: `{money_str}` (*{reason}*)"
            history_list.append(log_entry)

            new_embed = create_exotic_embed(items_dict, total_money, history_list)
            await interaction.response.edit_message(embed=new_embed, view=ExoticView())

            alert_msg = await interaction.channel.send(
                content=f"🏎️ **POHYB NA SKLADĚ EXOTIC**\nUživatel {interaction.user.mention} **{action_desc}**: `{sign_str} {real_item_name}` (Aktuálně: `{items_dict[real_item_name]} ks`) | Finanční transakce: `{money_str}`\n**Důvod:** *{reason}*\n*(Zpráva se za 5 minut sama smaže)*"
            )
            await asyncio.sleep(300)
            try:
                await alert_msg.delete()
            except discord.HTTPException:
                pass

        except Exception as e:
            if not interaction.response.is_done():
                await interaction.response.send_message(f"❌ Nastala chyba: `{e}`", ephemeral=True)
            else:
                await interaction.followup.send(f"❌ Nastala chyba: `{e}`", ephemeral=True)

class ExoticView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="Přidat součástky", style=discord.ButtonStyle.success, emoji="➕", custom_id="exotic_add_btn")
    async def add_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ExoticModal(action_type="add"))

    @discord.ui.button(label="Odebrat součástky", style=discord.ButtonStyle.danger, emoji="➖", custom_id="exotic_remove_btn")
    async def remove_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ExoticModal(action_type="remove"))

@bot.event
async def on_ready():
    bot.add_view(ExoticView())
    print(f"Bot je online jako {bot.user}")

@bot.command()
@commands.has_permissions(administrator=True)
async def exotic(ctx):
    await ctx.message.delete()
    embed = create_exotic_embed({}, 0, [])
    await ctx.send(embed=embed, view=ExoticView())

TOKEN = os.getenv("DISCORD_TOKEN")
bot.run(TOKEN)
