"""bot.py – PhoneboothBot class."""

import discord
from discord.ext import commands, tasks

import config
from database import Database


class PhoneboothBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True

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
        print(f"📞 Fliphone  |  {self.user}  |  {len(self.guilds)} server(s)")
        await self._update_presence()
        if not self._presence_sync.is_running():
            self._presence_sync.start()

    # ── Presence ──────────────────────────────────────────────────────────────

    async def _update_presence(self) -> None:
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"c.call  •  {len(self.guilds)} servers  •  Fliphone",
            )
        )

    @tasks.loop(hours=1)
    async def _presence_sync(self) -> None:
        """Hourly sync as a safety net in case any events were missed."""
        await self._update_presence()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        print(f"➕ Joined: {guild.name} ({guild.id})")
        await self._update_presence()

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        print(f"➖ Left: {guild.name} ({guild.id})")
        await self._update_presence()

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
