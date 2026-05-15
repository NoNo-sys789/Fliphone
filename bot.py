"""bot.py – PhoneboothBot class."""

import aiohttp
import discord
from discord.ext import commands, tasks

import config
from database import Database

# Required permissions integer (View Channel + Send Messages + Manage Webhooks +
# Embed Links + Attach Files + Read Message History + Add Reactions)
REQUIRED_PERMISSIONS = discord.Permissions(
    view_channel=True,
    send_messages=True,
    manage_webhooks=True,
    embed_links=True,
    attach_files=True,
    read_message_history=True,
    add_reactions=True,
)


class PhoneboothBot(commands.Bot):
    def __init__(self) -> None:
        intents = discord.Intents.default()
        intents.message_content = True

        super().__init__(
            command_prefix=config.PREFIXES,
            intents=intents,
            help_command=None,
            case_insensitive=True,
        )
        self.db = Database()

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def setup_hook(self) -> None:
        self.http_session = aiohttp.ClientSession()
        await self.db.init()
        await self.load_extension("cogs.phonebooth")
        await self.load_extension("cogs.admin")
        await self.load_extension("cogs.help")
        await self.load_extension("cogs.room")
        await self.load_extension("cogs.vote")
        await self.load_extension("cogs.report")
        from cogs.phonebooth import GifReportView
        self.add_view(GifReportView())
        # Load custom censor words from DB into filter
        import filter as flt
        words = await self.db.get_custom_words()
        flt.load_custom_words(words)
        print(f"✅ Extensions loaded. {len(words)} custom censor word(s) loaded.")
        await self.tree.sync()
        print("✅ Slash commands synced.")

    async def on_ready(self) -> None:
        print(f"📞 Fliphone  |  {self.user}  |  {len(self.guilds)} server(s)")
        await self._update_presence()
        if not self._presence_sync.is_running():
            self._presence_sync.start()
        if not self._topgg_sync.is_running():
            self._topgg_sync.start()
        await self._post_topgg_stats()

    async def close(self) -> None:
        await super().close()
        if hasattr(self, "http_session") and not self.http_session.closed:
            await self.http_session.close()

    # ── Presence ──────────────────────────────────────────────────────────────

    async def _update_presence(self) -> None:
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.listening,
                name=f"f.call  •  {len(self.guilds)} servers  •  Fliphone",
            )
        )

    @tasks.loop(hours=1)
    async def _presence_sync(self) -> None:
        await self._update_presence()

    # ── Top.gg server count ───────────────────────────────────────────────────

    async def _post_topgg_stats(self) -> None:
        """Post current server count to top.gg."""
        if not config.TOPGG_TOKEN:
            return
        try:
            async with aiohttp.ClientSession() as session:
                await session.post(
                    f"https://top.gg/api/bots/{self.user.id}/stats",
                    headers={"Authorization": config.TOPGG_TOKEN},
                    json={"server_count": len(self.guilds)},
                )
        except Exception as exc:
            print(f"[top.gg] Failed to post stats: {exc}")

    @tasks.loop(minutes=30)
    async def _topgg_sync(self) -> None:
        await self._post_topgg_stats()

    @_topgg_sync.before_loop
    async def _topgg_sync_before(self) -> None:
        await self.wait_until_ready()

    async def on_guild_join(self, guild: discord.Guild) -> None:
        print(f"➕ Joined: {guild.name} ({guild.id})")
        await self._update_presence()
        await self._post_topgg_stats()

        # ── Check missing permissions ─────────────────────────────────────────
        missing = []
        bot_member = guild.me
        if bot_member:
            perms = bot_member.guild_permissions
            if not perms.send_messages:   missing.append("Send Messages")
            if not perms.manage_webhooks: missing.append("Manage Webhooks")
            if not perms.embed_links:     missing.append("Embed Links")
            if not perms.attach_files:    missing.append("Attach Files")
            if not perms.read_message_history: missing.append("Read Message History")

        # ── Try to send welcome in first available text channel ───────────────
        target = None
        if guild.system_channel and guild.system_channel.permissions_for(guild.me).send_messages:
            target = guild.system_channel
        else:
            for ch in guild.text_channels:
                if ch.permissions_for(guild.me).send_messages:
                    target = ch
                    break

        if target:
            try:
                embed = discord.Embed(
                    title="📞 Thanks for adding Fliphone!",
                    description=(
                        "Fliphone connects your server with random strangers from other Discord servers.\n\n"
                        "**To get started:**\n"
                        "1. Go to the channel you want to use for calls\n"
                        "2. Run `f.setup` in that channel\n"
                        "3. Type `f.call` to connect with someone!\n\n"
                        "**Commands:** `f.call` · `f.hangup` · `f.skip` · `f.anon` · `f.fr`\n\n"
                        "Need help? [Join our support server](<https://discord.gg/fliphone>)"
                    ),
                    color=0x5865F2,
                )
                if missing:
                    embed.add_field(
                        name="⚠️ Missing Permissions",
                        value=(
                            f"I'm missing: **{', '.join(missing)}**\n"
                            f"Please grant these in Server Settings → Roles → Fliphone\n"
                            f"or re-invite me with the correct permissions."
                        ),
                        inline=False,
                    )
                embed.set_footer(text="Fliphone • Cross-server chat roulette")
                await target.send(embed=embed)
            except discord.HTTPException:
                pass

    async def on_guild_remove(self, guild: discord.Guild) -> None:
        print(f"➖ Left: {guild.name} ({guild.id})")
        await self._update_presence()
        await self._post_topgg_stats()

    # ── Global error handler ──────────────────────────────────────────────────

    async def on_command_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        if isinstance(error, commands.CommandNotFound):
            return
        if isinstance(error, commands.MissingPermissions):
            await ctx.send(
                embed=discord.Embed(
                    description="❌ Only a server admin can run this command.",
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
