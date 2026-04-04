"""
cogs/admin.py – Admin/setup/moderation commands for Phonebooth V2.

c.setup          – Register current channel as phonebooth
c.teardown       – Remove phonebooth from this server
c.stats          – Global statistics
c.invite         – Show bot invite link
c.blocklist      – List blocked servers
c.unblock <id>   – Unblock a server
c.kick           – Force-disconnect the active call
c.ban <user_id>  – Ban a user from using the bot (bot-wide)  [owner]
c.unban <user_id>– Unban a user                              [owner]
c.reports        – List pending GIF reports                  [owner]
c.gifbl          – Blacklist a GIF URL or report             [owner]
c.gifwl          – Whitelist a GIF URL or report             [owner]
c.gifcheck <url> – Check if a URL is listed                  [owner]
c.pb             – Legacy command group (still works)
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

import discord
from discord.ext import commands

import config
from database import Database


class Admin(commands.Cog, name="Admin"):
    def __init__(self, bot) -> None:
        self.bot = bot
        self.db: Database = bot.db

    # ── c.setup ───────────────────────────────────────────────────────────────

    @commands.command(name="setup")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def setup(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        """Register a Fliphone channel for this server."""
        target = channel or ctx.channel
        perms  = target.permissions_for(ctx.guild.me)

        if not perms.send_messages:
            await ctx.send(f"❌ I don't have **Send Messages** permission in {target.mention}.")
            return

        pb_cog = self.bot.get_cog("Phonebooth")
        wh_url: Optional[str] = None
        if pb_cog and perms.manage_webhooks:
            wh_url = await pb_cog.get_or_create_webhook(target)

        await self.db.setup_guild(
            guild_id=ctx.guild.id, channel_id=target.id,
            webhook_url=wh_url, user_id=ctx.author.id,
        )

        wh_note = "✅ Webhook relay active" if wh_url else "⚠️ No webhook (grant Manage Webhooks for better relay)"
        await ctx.send(
            f"📞 **Fliphone set up in {target.mention}!**\n"
            f"{wh_note}\n"
            f"Anonymous mode: OFF (toggle with `c.anon`)\n"
            f"Users can now run `c.call` in {target.mention}!"
        )

        if target != ctx.channel:
            try:
                await target.send(
                    "📞 **This channel is now a Fliphone!**\n"
                    "Type `c.call` to connect with a random server."
                )
            except discord.HTTPException:
                pass

    # ── c.teardown ────────────────────────────────────────────────────────────

    @commands.command(name="teardown", aliases=["remove"])
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def teardown(self, ctx: commands.Context) -> None:
        """Remove the Fliphone configuration for this server."""
        guild_cfg = await self.db.get_guild_config(ctx.guild.id)
        if not guild_cfg:
            await ctx.send("❌ Fliphone isn't configured in this server.")
            return

        ch_id = guild_cfg["channel_id"]
        conn  = await self.db.get_connection(ch_id)
        if conn:
            other_cid = conn["channel_b"] if ch_id == conn["channel_a"] else conn["channel_a"]
            await self.db.remove_connection(conn["id"])
            other_ch = self.bot.get_channel(other_cid)
            if other_ch:
                try:
                    await other_ch.send("📵 Other server has ended the call!")
                except discord.HTTPException:
                    pass

        await self.db.remove_from_queue(ch_id)

        try:
            pb_channel = self.bot.get_channel(ch_id)
            if pb_channel:
                for wh in await pb_channel.webhooks():
                    if wh.user == self.bot.user and wh.name == "Fliphone":
                        await wh.delete(reason="Fliphone teardown")
        except Exception:
            pass

        await self.db.delete_guild(ctx.guild.id)
        await ctx.send("📵 Fliphone removed. Run `c.setup` to set it up again.")

    # ── c.stats ───────────────────────────────────────────────────────────────

    @commands.command(name="stats")
    async def stats(self, ctx: commands.Context) -> None:
        """Display global Fliphone statistics."""
        embed = discord.Embed(title="📊 Fliphone — Statistics", color=config.COLOR_WAIT, timestamp=datetime.utcnow())
        embed.add_field(name="🔴 Active Calls",       value=str(await self.db.get_active_connection_count()), inline=True)
        embed.add_field(name="⏳ In Queue",           value=str(await self.db.get_queue_size()),              inline=True)
        embed.add_field(name="📚 All-Time Calls",     value=str(await self.db.get_total_calls()),             inline=True)
        embed.add_field(name="🏠 Configured Servers", value=str(await self.db.get_total_guilds()),            inline=True)
        embed.add_field(name="🤖 Bot In Servers",     value=str(len(self.bot.guilds)),                       inline=True)
        embed.set_footer(text=config.FOOTER)
        await ctx.send(embed=embed)

    # ── c.invite ─────────────────────────────────────────────────────────────

    @commands.command(name="invite")
    async def invite(self, ctx: commands.Context) -> None:
        """Get the bot invite link."""
        client_id = self.bot.user.id
        url = (
            f"https://discord.com/api/oauth2/authorize"
            f"?client_id={client_id}"
            f"&permissions={config.BOT_PERMISSIONS}"
            f"&scope=bot"
        )
        embed = discord.Embed(
            title="📞 Add Phonebooth V2 to Your Server",
            description=(
                f"**[➕ Click here to invite the bot]({url})**\n\n"
                "Phonebooth connects your server to a random server for an anonymous "
                "cross-server chat. Run `c.setup` in any channel after inviting!"
            ),
            color=0x5865F2,
        )
        embed.add_field(
            name="Required Permissions",
            value=(
                "• Send Messages\n"
                "• Manage Webhooks *(for avatar relay)*\n"
                "• Embed Links\n"
                "• Attach Files\n"
                "• Read Message History"
            ),
            inline=False,
        )
        embed.add_field(
            name="Getting Started",
            value=(
                "1. Invite the bot\n"
                "2. Run `c.setup` in your chosen channel\n"
                "3. Type `c.call` to connect!"
            ),
            inline=False,
        )
        embed.set_footer(text=config.FOOTER)
        await ctx.send(embed=embed)

    # ── c.blocklist ───────────────────────────────────────────────────────────

    @commands.command(name="blocklist", aliases=["blocked"])
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def blocklist(self, ctx: commands.Context) -> None:
        """List servers blocked by this server."""
        blocked = await self.db.get_blocked_guilds(ctx.guild.id)
        if not blocked:
            await ctx.send("✅ You haven't blocked any servers.")
            return

        lines = []
        for entry in blocked:
            g    = self.bot.get_guild(entry["blocked_guild_id"])
            name = g.name if g else "Unknown Server"
            lines.append(f"• **{name}** — ID: `{entry['blocked_guild_id']}`")

        embed = discord.Embed(title="🚫 Blocked Servers", description="\n".join(lines), color=config.COLOR_ERR)
        embed.set_footer(text=f"Use c.unblock <id> to unblock  •  {config.FOOTER}")
        await ctx.send(embed=embed)

    # ── c.unblock ─────────────────────────────────────────────────────────────

    @commands.command(name="unblock")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def unblock(self, ctx: commands.Context, server_id: int) -> None:
        """Unblock a server."""
        removed = await self.db.unblock_guild(ctx.guild.id, server_id)
        if not removed:
            await ctx.send(f"❌ Server `{server_id}` isn't in your blocklist.")
            return
        g    = self.bot.get_guild(server_id)
        name = g.name if g else f"Server {server_id}"
        await ctx.send(f"✅ **{name}** has been unblocked.")

    # ── c.kick ────────────────────────────────────────────────────────────────

    @commands.command(name="kick")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def kick(self, ctx: commands.Context) -> None:
        """Force-disconnect the active call."""
        guild_cfg = await self.db.get_guild_config(ctx.guild.id)
        if not guild_cfg:
            await ctx.send("❌ Phonebooth isn't configured. Run `c.setup` first.")
            return

        conn = await self.db.get_connection(guild_cfg["channel_id"])
        if not conn:
            await ctx.send("❌ No active call to disconnect.")
            return

        ch_id     = guild_cfg["channel_id"]
        other_cid = conn["channel_b"] if ch_id == conn["channel_a"] else conn["channel_a"]
        await self.db.remove_connection(conn["id"], ended_by=ctx.author.id)
        await ctx.send("📵 Call force-disconnected by admin.")

        other_ch = self.bot.get_channel(other_cid)
        if other_ch:
            try:
                await other_ch.send("📵 Other server has ended the call!")
            except discord.HTTPException:
                pass

    # ── c.ban ─────────────────────────────────────────────────────────────────

    @commands.command(name="ban")
    @commands.is_owner()
    async def ban_user(self, ctx: commands.Context, user_id: int, *, reason: str = "No reason given") -> None:
        """[Bot owner only] Ban a user by ID from using Phonebooth across all servers."""
        await self.db.ban_user(user_id, ctx.author.id, reason)
        user = self.bot.get_user(user_id)
        name = str(user) if user else f"User {user_id}"
        await ctx.send(f"🔨 **{name}** (`{user_id}`) has been banned from Phonebooth.\nReason: {reason}")

    # ── c.unban ───────────────────────────────────────────────────────────────

    @commands.command(name="unban")
    @commands.is_owner()
    async def unban_user(self, ctx: commands.Context, user_id: int) -> None:
        """[Bot owner only] Unban a user from Phonebooth."""
        removed = await self.db.unban_user(user_id)
        if not removed:
            await ctx.send(f"❌ User `{user_id}` isn't banned.")
            return
        user = self.bot.get_user(user_id)
        name = str(user) if user else f"User {user_id}"
        await ctx.send(f"✅ **{name}** has been unbanned.")

    # ── c.reports ─────────────────────────────────────────────────────────────

    @commands.command(name="reports")
    @commands.is_owner()
    async def reports(self, ctx: commands.Context) -> None:
        """[Bot owner only] List all GIF reports awaiting review."""
        pending = await self.db.get_pending_gif_reports()
        if not pending:
            await ctx.send("✅ No pending GIF reports.")
            return

        lines = []
        for r in pending[:20]:  # cap at 20 to avoid embed overflow
            reported_at = r["reported_at"][:10] if r["reported_at"] else "?"
            url_short   = r["url"][:60] + "…" if len(r["url"]) > 60 else r["url"]
            reporter    = f"<@{r['reporter_id']}>" if r["reporter_id"] else "unknown"
            lines.append(
                f"**#{r['id']}** — {reported_at} — {reporter}\n"
                f"└ `{url_short}`"
            )

        embed = discord.Embed(
            title=f"🚩 Pending GIF Reports ({len(pending)})",
            description="\n".join(lines),
            color=config.COLOR_WARN,
        )
        embed.set_footer(
            text="c.gifbl <id or url>  →  blacklist  |  c.gifwl <id or url>  →  whitelist"
        )
        await ctx.send(embed=embed)

    # ── c.gifbl ───────────────────────────────────────────────────────────────

    @commands.command(name="gifbl")
    @commands.is_owner()
    async def gifbl(self, ctx: commands.Context, *, id_or_url: str) -> None:
        """
        [Bot owner only] Blacklist a GIF URL.
        Pass either a report ID (number) or a full URL.
        """
        url = await self._resolve_gif_arg(ctx, id_or_url, action="blacklist")
        if not url:
            return

        await self.db.set_gif_url_status(url, "blacklist", ctx.author.id)

        # Resolve report if applicable
        if id_or_url.strip().isdigit():
            await self.db.resolve_gif_report(int(id_or_url.strip()), "blacklisted")

        embed = discord.Embed(
            title="🚫 GIF Blacklisted",
            description=f"This URL is now blocked. Future relay attempts will be rejected.\n```\n{url[:900]}\n```",
            color=config.COLOR_ERR,
        )
        await ctx.send(embed=embed)

    # ── c.gifwl ───────────────────────────────────────────────────────────────

    @commands.command(name="gifwl")
    @commands.is_owner()
    async def gifwl(self, ctx: commands.Context, *, id_or_url: str) -> None:
        """
        [Bot owner only] Whitelist a GIF URL (future reports on this URL are ignored).
        Pass either a report ID (number) or a full URL.
        """
        url = await self._resolve_gif_arg(ctx, id_or_url, action="whitelist")
        if not url:
            return

        await self.db.set_gif_url_status(url, "whitelist", ctx.author.id)

        if id_or_url.strip().isdigit():
            await self.db.resolve_gif_report(int(id_or_url.strip()), "whitelisted")

        embed = discord.Embed(
            title="✅ GIF Whitelisted",
            description=f"This URL is now trusted. The report button will not work for it.\n```\n{url[:900]}\n```",
            color=config.COLOR_OK,
        )
        await ctx.send(embed=embed)

    # ── c.gifcheck ────────────────────────────────────────────────────────────

    @commands.command(name="gifcheck")
    @commands.is_owner()
    async def gifcheck(self, ctx: commands.Context, *, url: str) -> None:
        """[Bot owner only] Check whether a URL is on the blacklist or whitelist."""
        status = await self.db.check_gif_url(url)
        if status == "blacklist":
            await ctx.send(f"🚫 **Blacklisted** — this URL will be blocked when relayed.")
        elif status == "whitelist":
            await ctx.send(f"✅ **Whitelisted** — this URL is trusted and cannot be reported.")
        else:
            await ctx.send(f"❔ **Not listed** — this URL has no special status.")

    # ── Helper ────────────────────────────────────────────────────────────────

    async def _resolve_gif_arg(self, ctx, id_or_url: str, action: str) -> Optional[str]:
        """
        If the argument looks like a number, treat it as a report_id and fetch
        the URL from the DB.  Otherwise treat the argument as the URL directly.
        Returns the URL string, or None if resolution failed.
        """
        id_or_url = id_or_url.strip()
        if id_or_url.isdigit():
            report = await self.db.get_gif_report(int(id_or_url))
            if not report:
                await ctx.send(f"❌ No report found with ID `{id_or_url}`.")
                return None
            return report["url"]
        elif id_or_url.startswith("http"):
            return id_or_url
        else:
            await ctx.send(
                f"❌ Pass a report ID (number) or a full URL starting with `http`.\n"
                f"Example: `c.gif{action[:2]} 42` or `c.gif{action[:2]} https://tenor.com/view/...`"
            )
            return None

    # ── c.pb (legacy group kept for backwards compat) ─────────────────────────

    @commands.group(name="pb", invoke_without_command=True, case_insensitive=True)
    async def pb(self, ctx: commands.Context) -> None:
        """Phonebooth admin commands. Use c.setup, c.teardown, etc. directly now."""
        await ctx.send(
            "📞 **Phonebooth V2** — Commands:\n"
            "`c.call` `c.hangup` `c.skip` `c.block` `c.fr` `c.anon`\n"
            "`c.setup` `c.teardown` `c.stats` `c.invite` `c.blocklist` `c.unblock` `c.kick`\n"
            "`c.ban <id>` `c.unban <id>` *(bot owner only)*\n"
            "`c.reports` `c.gifbl <id/url>` `c.gifwl <id/url>` `c.gifcheck <url>` *(bot owner only)*"
        )

    @pb.command(name="setup")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def pb_setup(self, ctx: commands.Context, channel: Optional[discord.TextChannel] = None) -> None:
        await ctx.invoke(self.setup, channel=channel)

    @pb.command(name="teardown")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def pb_teardown(self, ctx: commands.Context) -> None:
        await ctx.invoke(self.teardown)

    @pb.command(name="anon")
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def pb_anon(self, ctx: commands.Context) -> None:
        pb_cog = self.bot.get_cog("Phonebooth")
        if pb_cog:
            await ctx.invoke(pb_cog.anon)

    @pb.command(name="stats")
    async def pb_stats(self, ctx: commands.Context) -> None:
        await ctx.invoke(self.stats)

    # ── Error handler ─────────────────────────────────────────────────────────

    async def cog_command_error(self, ctx: commands.Context, error) -> None:
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need **Manage Channels** permission for that.")
        elif isinstance(error, commands.NotOwner):
            await ctx.send("❌ Only the bot owner can use that command.")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"❌ Bad argument: `{error}`")
        else:
            raise error


async def setup(bot):
    await bot.add_cog(Admin(bot))
