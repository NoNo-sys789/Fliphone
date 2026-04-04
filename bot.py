"""bot.py – PhoneboothBot class."""

import discord
from discord.ext import commands

import config
from database import Database


class PhoneboothBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True   # Required: read message text for relay
        intents.members = True           # Required: full member data for avatars

        super().__init__(
            command_prefix=config.PREFIX,
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self.db = Database()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        await self.db.init()
        await self.load_extension("cogs.phonebooth")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.help")
        print("✅ Extensions loaded.")

    async def on_ready(self) -> None:
        guilds = len(self.guilds)
        print(f"📞 Fliphone  |  {self.user}  |  {guilds} server(s)")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"c.call  •  {guilds} servers  •  Fliphone",
            )
        )

    # ── Global error handler ──────────────────────────────────────────────────

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=discord.Embed(
                    description="❌ You need **Manage Channels** permission for that.",
                    color=config.COLOR_ERR,
                )
            )
            return
        if isinstance(error, commands.CommandOnCooldown):
            await ctx.send(
                embed=discord.Embed(
                    description=f"⏳ Slow down! Try again in **{error.retry_after:.1f}s**.",
                    color=config.COLOR_WARN,
                )
            )
            return
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.send(
                embed=discord.Embed(
                    description="❌ This command can't be used in DMs.",
                    color=config.COLOR_ERR,
                )
            )
            return
        if isinstance(error, commands.BadArgument):
            await ctx.send(
                embed=discord.Embed(
                    description=f"❌ Bad argument: {error}",
                    color=config.COLOR_ERR,
                )
            )
            return
        raise error
