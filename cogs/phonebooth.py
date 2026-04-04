"""
cogs/phonebooth.py – Core Phonebooth logic.

Commands
--------
c.call / c.c      – Join queue or connect instantly
c.hangup / c.h    – End call or leave queue
c.skip / c.s      – Hang up and immediately redial
c.status          – Show current status
c.block           – Block the server you're talking to
c.anon / c.mask   – Toggle anonymous mode for YOUR server
c.fr              – Share your username as a friend request card
"""

from __future__ import annotations

import asyncio
import io
import random
from datetime import datetime
from typing import Optional

import aiohttp
import discord
from discord.ext import commands, tasks

import config
from database import Database
from filter import filter_message


# ── Helpers ───────────────────────────────────────────────────────────────────

def _duration_str(started_at: str) -> str:
    delta = datetime.utcnow() - datetime.fromisoformat(started_at)
    total = int(delta.total_seconds())
    return f"{total // 60}m {total % 60}s"


def _anon_identity(seed: int) -> tuple[str, str]:
    rng = random.Random(seed)
    name = f"Stranger {rng.choice(config.ANON_NAMES)}"
    avatar = f"https://robohash.org/{seed}?set=set4&size=256x256"
    return name, avatar


def _get_avatar_url(member: discord.Member | discord.User) -> str:
    """
    Return a public PNG avatar URL that Discord webhooks will actually accept.

    Discord CDN URLs with expiry tokens (?ex=...&is=...&hm=...) are rejected
    silently by the execute-webhook endpoint. The clean CDN path without auth
    params works for public profile pictures. We force PNG (not webp) and strip
    any query string.
    """
    # Prefer the server-specific avatar if set
    if isinstance(member, discord.Member) and member.guild_avatar:
        asset = member.guild_avatar
    else:
        asset = member.display_avatar

    # Build a clean static PNG URL — no auth query params
    try:
        url = str(asset.with_static_format("png").with_size(256).url)
        # Strip expiry query params if present — clean CDN path is publicly accessible
        if "?" in url:
            url = url.split("?")[0]
        return url
    except Exception:
        return str(member.default_avatar.url)


# ── GIF Report View ───────────────────────────────────────────────────────────

class GifReportView(discord.ui.View):
    """Persistent view with a Report GIF button shown under relayed GIFs."""

    def __init__(self, gif_url: str = "", report_channel_id: int = 0):
        super().__init__(timeout=None)
        self.gif_url = gif_url
        self.report_channel_id = report_channel_id

    @discord.ui.button(
        label="🚩 Report GIF",
        style=discord.ButtonStyle.danger,
        custom_id="pb_gif_report",
    )
    async def report_gif(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        # Disable the button so it can't be spammed
        button.disabled = True
        button.label = "✅ Reported"
        await interaction.response.edit_message(view=self)

        # Log to the report channel if configured
        report_ch_id = int(config.REPORT_LOG_CHANNEL_ID) if hasattr(config, "REPORT_LOG_CHANNEL_ID") and config.REPORT_LOG_CHANNEL_ID else 0
        if report_ch_id:
            report_ch = interaction.client.get_channel(report_ch_id)
            if report_ch:
                embed = discord.Embed(
                    title="🚩 GIF Reported",
                    color=0xFF6B6B,
                    timestamp=datetime.utcnow(),
                )
                embed.add_field(name="Reported by", value=f"{interaction.user} (`{interaction.user.id}`)", inline=True)
                embed.add_field(name="Server", value=f"{interaction.guild.name} (`{interaction.guild.id}`)" if interaction.guild else "Unknown", inline=True)
                if self.gif_url:
                    embed.add_field(name="GIF URL", value=self.gif_url, inline=False)
                try:
                    await report_ch.send(embed=embed)
                except discord.HTTPException:
                    pass

        await interaction.followup.send("✅ GIF reported! Our team will review it.", ephemeral=True)


_CONNECTED_MSG = (
    "📞 **Call answered! say hi!** 👋\n"
    "You are now in a call!\n"
    "Please remember to respect the user on the other end.\n"
    "To skip a user, use `c.skip`  "
    "To report a user, click on the message and click apps then click "
    "Report Message or reply to the message and do `c.block`\n\n"
    "*By continuing, you agree to be respectful. "
    "To opt out, ask an admin to run `c.setup` in the channel to unconfigure it.*"
)


# ── Cog ───────────────────────────────────────────────────────────────────────

class Phonebooth(commands.Cog):
    """Core Phonebooth commands and message relay."""

    def __init__(self, bot) -> None:
        self.bot = bot
        self.db: Database = bot.db
        self._timeouts: dict[int, asyncio.Task] = {}
        # Cache: webhook_url -> (user_id, avatar_hash)
        # Only update webhook avatar when the sender changes — avoids rate limits
        self._wh_avatar_cache: dict[str, tuple[int, str]] = {}
        self._cleanup_loop.start()

    def cog_unload(self) -> None:
        self._cleanup_loop.cancel()
        for task in self._timeouts.values():
            task.cancel()

    # ── Queue timeout ─────────────────────────────────────────────────────────

    async def _run_timeout(self, channel_id: int) -> None:
        await asyncio.sleep(config.QUEUE_TIMEOUT * 60)
        entry = await self.db.get_queue_entry(channel_id)
        if entry:
            await self.db.remove_from_queue(channel_id)
            channel = self.bot.get_channel(channel_id)
            if channel:
                try:
                    await channel.send(
                        f"📵 No one picked up after **{config.QUEUE_TIMEOUT} minutes**. "
                        f"Use `c.call` to try again."
                    )
                except discord.HTTPException:
                    pass
        self._timeouts.pop(channel_id, None)

    def _start_timeout(self, channel_id: int) -> None:
        self._cancel_timeout(channel_id)
        self._timeouts[channel_id] = asyncio.create_task(self._run_timeout(channel_id))

    def _cancel_timeout(self, channel_id: int) -> None:
        task = self._timeouts.pop(channel_id, None)
        if task:
            task.cancel()

    @tasks.loop(minutes=30)
    async def _cleanup_loop(self) -> None:
        pass

    # ── Webhook helpers ───────────────────────────────────────────────────────

    async def get_or_create_webhook(self, channel: discord.TextChannel) -> Optional[str]:
        try:
            webhooks = await channel.webhooks()
            for wh in webhooks:
                if wh.user == self.bot.user and wh.name == "Phonebooth":
                    return wh.url
            wh = await channel.create_webhook(name="Phonebooth")
            return wh.url
        except discord.Forbidden:
            return None
        except Exception as exc:
            print(f"[webhook] {exc}")
            return None

    async def _get_avatar_bytes(self, member: discord.Member | discord.User) -> Optional[bytes]:
        """Download avatar as PNG bytes using the bot's authenticated session."""
        try:
            asset = (
                member.guild_avatar
                if isinstance(member, discord.Member) and member.guild_avatar
                else member.display_avatar
            )
            return await asset.with_static_format("png").with_size(256).read()
        except Exception as exc:
            print(f"[avatar-bytes] {exc}")
            return None

    async def _send_webhook(
        self,
        url: str,
        content: Optional[str],
        username: str,
        member: discord.Member | discord.User | None,
        files: list[discord.File],
        reply_embed: Optional[discord.Embed] = None,
    ) -> bool:
        """
        Send a webhook message, updating the webhook avatar when the sender changes.

        Discord rejects CDN URLs in avatar_url (known API bug since 2024).
        The fix: PATCH the webhook itself with avatar bytes before sending.
        We cache the last sender per webhook so we only PATCH when the sender changes.
        """
        try:
            async with aiohttp.ClientSession() as session:
                wh = discord.Webhook.from_url(url, session=session)

                # Update webhook avatar only when sender changes
                if member:
                    asset = (
                        member.guild_avatar
                        if isinstance(member, discord.Member) and member.guild_avatar
                        else member.display_avatar
                    )
                    avatar_hash = asset.key
                    cached = self._wh_avatar_cache.get(url)
                    if cached != (member.id, avatar_hash):
                        try:
                            avatar_bytes = await asset.with_static_format("png").with_size(256).read()
                            await wh.edit(avatar=avatar_bytes)
                            self._wh_avatar_cache[url] = (member.id, avatar_hash)
                        except Exception as exc:
                            print(f"[webhook-avatar] {exc}")

                await wh.send(
                    content=content or None,
                    username=username[:80],
                    embeds=[reply_embed] if reply_embed else discord.utils.MISSING,
                    files=files if files else discord.utils.MISSING,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
            return True
        except Exception as exc:
            print(f"[relay-webhook] {exc}")
            return False

    # ── Message relay ─────────────────────────────────────────────────────────

    async def _relay(self, message: discord.Message, conn: dict) -> None:
        is_side_a  = message.channel.id == conn["channel_a"]
        target_cid = conn["channel_b"] if is_side_a else conn["channel_a"]
        target_wh  = conn["webhook_b"] if is_side_a else conn["webhook_a"]

        # ── Check user ban list ───────────────────────────────────────────────
        if await self.db.is_user_banned(message.author.id):
            try:
                await message.channel.send(
                    f"🚫 {message.author.mention} You are banned from using Phonebooth.",
                    delete_after=8,
                )
            except discord.HTTPException:
                pass
            return

        # ── Identity ──────────────────────────────────────────────────────────
        cfg  = await self.db.get_config_by_channel(message.channel.id)
        anon = cfg.get("anonymous", 0) if cfg else 0

        if anon:
            seed = conn["id"] * 1000 + (conn["guild_a"] if is_side_a else conn["guild_b"])
            display_name, avatar_url = _anon_identity(seed)
        else:
            member       = message.author
            display_name = (
                member.nick
                if isinstance(member, discord.Member) and member.nick
                else member.display_name
            )
            avatar_url = _get_avatar_url(member)


        # ── Reply context — embed card with avatar like Discord's native reply ─
        reply_embed: Optional[discord.Embed] = None
        if message.reference:
            ref_msg = message.reference.resolved
            if isinstance(ref_msg, discord.Message):
                # Get the display name — for webhook messages use the webhook username
                if ref_msg.webhook_id:
                    ref_author = ref_msg.author.display_name
                    ref_avatar = None
                else:
                    ref_author = ref_msg.author.display_name
                    ref_avatar = _get_avatar_url(ref_msg.author)

                ref_text = (ref_msg.content or "").strip()
                # Strip relay-added CDN/tenor URLs so quote stays clean
                ref_text = " ".join(
                    l for l in ref_text.splitlines()
                    if not l.startswith("http")
                ).strip()
                if len(ref_text) > 100:
                    ref_text = ref_text[:100] + "…"
                elif not ref_text:
                    # Check for attachments or embeds
                    if ref_msg.attachments:
                        att = ref_msg.attachments[0]
                        ext = att.filename.rsplit(".", 1)[-1].lower() if "." in att.filename else ""
                        ref_text = "GIF" if ext == "gif" else "image"
                    elif ref_msg.embeds:
                        ref_text = "image"
                    else:
                        ref_text = "message"

                reply_embed = discord.Embed(
                    description=ref_text,
                    color=0x2b2d31,  # Discord dark background colour
                )
                reply_embed.set_author(
                    name=f"Replying to {ref_author}",
                    icon_url=ref_avatar,
                )

        # ── Content ───────────────────────────────────────────────────────────
        raw_content = (message.content or "")

        if message.stickers:
            sticker_names = ", ".join(s.name for s in message.stickers)
            raw_content = (raw_content + f"\n🎭 *Sticker: {sticker_names}*").strip()

        # ── Content filter ────────────────────────────────────────────────────
        content, was_censored = filter_message(raw_content)
        if was_censored:
            try:
                await message.channel.send(
                    f"⚠️ {message.author.mention} Your message contained a blocked word "
                    f"and was censored before being sent.",
                    delete_after=8,
                )
            except discord.HTTPException:
                pass

        # ── Attachments ───────────────────────────────────────────────────────
        # GIFs only → send as URL so Discord animates them
        # Regular images (.png, .jpg etc.) → BLOCKED, not relayed
        # Non-media files → re-upload as file attachment
        GIF_EXT    = {".gif"}
        BLOCK_EXTS = {".png", ".jpg", ".jpeg", ".webp"}
        VIDEO_EXTS = {".mp4", ".mov", ".webm"}
        files: list[discord.File] = []
        total_bytes = 0
        LIMIT = 8_000_000

        gif_urls: list[str] = []  # track GIFs so we can add report buttons
        for att in message.attachments:
            ext = ("." + att.filename.rsplit(".", 1)[-1].lower()) if "." in att.filename else ""
            if ext in GIF_EXT:
                content += f"\n{att.url}"
                gif_urls.append(att.url)
            elif ext in VIDEO_EXTS:
                content += f"\n{att.url}"
            elif ext in BLOCK_EXTS:
                # Regular images are silently blocked — not relayed
                pass
            elif total_bytes + att.size <= LIMIT:
                try:
                    data = await att.read()
                    files.append(discord.File(io.BytesIO(data), filename=att.filename))
                    total_bytes += att.size
                except Exception:
                    pass
            else:
                pass

        await self.db.increment_message_count(conn["id"])

        # ── Send via webhook ──────────────────────────────────────────────────
        if target_wh:
            relay_member = message.author if not anon else None
            ok = await self._send_webhook(
                target_wh, content.strip() or None, display_name, relay_member, files,
                reply_embed=reply_embed,
            )
            if ok:
                return

        # ── GIF report buttons → send to TARGET channel after relay ────────────
        if gif_urls:
            target_ch = self.bot.get_channel(target_cid)
            if target_ch:
                for gif_url in gif_urls:
                    try:
                        report_ch_id = int(config.REPORT_LOG_CHANNEL_ID) if hasattr(config, "REPORT_LOG_CHANNEL_ID") and config.REPORT_LOG_CHANNEL_ID else 0
                        view = GifReportView(gif_url=gif_url, report_channel_id=report_ch_id)
                        embed = discord.Embed(
                            title="🚩 GIF Safety Check",
                            description="A GIF was sent in this call.\nIf it contains inappropriate content, tap the button below.\nIt will be **immediately flagged** for review.",
                            color=0x2b2d31,
                        )
                        await target_ch.send(embed=embed, view=view)
                    except discord.HTTPException:
                        pass

        # ── Fallback: plain bot message ───────────────────────────────────────
        target_channel = self.bot.get_channel(target_cid)
        if not target_channel:
            return

        body = content.strip()
        fallback_text = f"**{display_name}**\n{body}" if body else f"**{display_name}**"
        try:
            await target_channel.send(
                content=fallback_text,
                embed=reply_embed or discord.utils.MISSING,
                files=files if files else discord.utils.MISSING,
                allowed_mentions=discord.AllowedMentions.none(),
            )
        except discord.HTTPException as exc:
            print(f"[relay-fallback] {exc}")

    # ── on_message ────────────────────────────────────────────────────────────

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return
        if not message.guild:
            return
        ctx = await self.bot.get_context(message)
        if ctx.valid:
            return

        cfg = await self.db.get_config_by_channel(message.channel.id)
        if not cfg:
            return

        conn = await self.db.get_connection(message.channel.id)
        if not conn:
            return

        await self._relay(message, conn)

    # ── c.call ────────────────────────────────────────────────────────────────

    @commands.command(name="call", aliases=["c", "dial", "connect"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def call(self, ctx: commands.Context) -> None:
        """Dial into the phonebooth queue, or connect instantly."""

        if await self.db.is_user_banned(ctx.author.id):
            await ctx.send("🚫 You are banned from using Phonebooth.")
            return

        cfg = await self.db.get_config_by_channel(ctx.channel.id)
        if not cfg:
            guild_cfg = await self.db.get_guild_config(ctx.guild.id)
            if guild_cfg:
                pb_ch = self.bot.get_channel(guild_cfg["channel_id"])
                await ctx.send(
                    f"❌ Use the phonebooth channel: "
                    f"{pb_ch.mention if pb_ch else '#deleted-channel'}"
                )
            else:
                await ctx.send(
                    f"❌ Phonebooth isn't set up. An admin should run `c.setup` in the target channel."
                )
            return

        conn = await self.db.get_connection(ctx.channel.id)
        if conn:
            await ctx.send(
                f"📞 Already in a call ({_duration_str(conn['started_at'])}). "
                f"Use `c.hangup` to end it first."
            )
            return

        q = await self.db.get_queue_entry(ctx.channel.id)
        if q:
            await ctx.send(
                f"⏳ Already waiting ({_duration_str(q['joined_at'])}). "
                f"Use `c.hangup` to cancel."
            )
            return

        wh_url = await self.get_or_create_webhook(ctx.channel)
        match  = await self.db.get_queue_match(ctx.guild.id, ctx.channel.id)

        if match:
            self._cancel_timeout(match["channel_id"])
            await self.db.remove_from_queue(match["channel_id"])
            await self.db.create_connection(
                channel_a=ctx.channel.id, guild_a=ctx.guild.id, webhook_a=wh_url,
                channel_b=match["channel_id"], guild_b=match["guild_id"], webhook_b=match["webhook_url"],
            )
            await ctx.send(_CONNECTED_MSG)
            partner_channel = self.bot.get_channel(match["channel_id"])
            if partner_channel:
                try:
                    await partner_channel.send(_CONNECTED_MSG)
                except discord.HTTPException:
                    pass
        else:
            await self.db.add_to_queue(
                channel_id=ctx.channel.id, guild_id=ctx.guild.id,
                user_id=ctx.author.id, webhook_url=wh_url,
            )
            self._start_timeout(ctx.channel.id)
            queue_size = await self.db.get_queue_size()
            active     = await self.db.get_active_connection_count()
            await ctx.send(
                f"📳 **Searching for someone to talk to...** "
                f"({queue_size} waiting, {active} active calls)\n"
                f"Use `c.hangup` to cancel. Auto-cancels in {config.QUEUE_TIMEOUT} min."
            )

    # ── c.hangup ──────────────────────────────────────────────────────────────

    @commands.command(name="hangup", aliases=["h", "disconnect", "bye"])
    @commands.guild_only()
    async def hangup(self, ctx: commands.Context) -> None:
        """End an active call or leave the queue."""
        q = await self.db.get_queue_entry(ctx.channel.id)
        if q:
            await self.db.remove_from_queue(ctx.channel.id)
            self._cancel_timeout(ctx.channel.id)
            await ctx.send("📵 Left the queue. Use `c.call` to dial again.")
            return

        conn = await self.db.get_connection(ctx.channel.id)
        if not conn:
            await ctx.send("📵 Not in a call or queue. Use `c.call` to connect!")
            return

        other_cid = conn["channel_b"] if ctx.channel.id == conn["channel_a"] else conn["channel_a"]
        duration  = _duration_str(conn["started_at"])
        msg_count = conn["msg_count"]

        await self.db.remove_connection(conn["id"], ended_by=ctx.author.id)

        await ctx.send(
            f"📵 Call ended. Duration: **{duration}** · Messages: **{msg_count}**\n"
            f"Thanks for calling! Use `c.call` to dial again."
        )

        other = self.bot.get_channel(other_cid)
        if other:
            try:
                await other.send(
                    f"📵 Other server has ended the call!\n"
                    f"Duration: **{duration}** · Messages: **{msg_count}**\n"
                    f"Use `c.call` to find someone new."
                )
            except discord.HTTPException:
                pass

    # ── c.skip ────────────────────────────────────────────────────────────────

    @commands.command(name="skip", aliases=["s", "next"])
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.channel)
    async def skip(self, ctx: commands.Context) -> None:
        """End the current call and immediately search for a new one."""
        cfg = await self.db.get_config_by_channel(ctx.channel.id)
        if not cfg:
            await ctx.send("❌ This isn't a phonebooth channel.")
            return

        conn = await self.db.get_connection(ctx.channel.id)
        if conn:
            other_cid = (
                conn["channel_b"] if ctx.channel.id == conn["channel_a"] else conn["channel_a"]
            )
            await self.db.remove_connection(conn["id"], ended_by=ctx.author.id)
            other_ch = self.bot.get_channel(other_cid)
            if other_ch:
                try:
                    await other_ch.send("📵 The other user skipped. Use `c.call` to find someone new!")
                except discord.HTTPException:
                    pass
        else:
            q = await self.db.get_queue_entry(ctx.channel.id)
            if q:
                await self.db.remove_from_queue(ctx.channel.id)
                self._cancel_timeout(ctx.channel.id)

        await ctx.send("⏭️ you have skipped this caller.")

        # Re-dial immediately
        wh_url = await self.get_or_create_webhook(ctx.channel)
        match  = await self.db.get_queue_match(ctx.guild.id, ctx.channel.id)

        if match:
            self._cancel_timeout(match["channel_id"])
            await self.db.remove_from_queue(match["channel_id"])
            await self.db.create_connection(
                channel_a=ctx.channel.id, guild_a=ctx.guild.id, webhook_a=wh_url,
                channel_b=match["channel_id"], guild_b=match["guild_id"], webhook_b=match["webhook_url"],
            )
            await ctx.send(_CONNECTED_MSG)
            partner_channel = self.bot.get_channel(match["channel_id"])
            if partner_channel:
                try:
                    await partner_channel.send(_CONNECTED_MSG)
                except discord.HTTPException:
                    pass
        else:
            await self.db.add_to_queue(
                channel_id=ctx.channel.id, guild_id=ctx.guild.id,
                user_id=ctx.author.id, webhook_url=wh_url,
            )
            self._start_timeout(ctx.channel.id)
            queue_size = await self.db.get_queue_size()
            await ctx.send(
                f"📳 **Searching for someone to talk to...** ({queue_size} waiting)\n"
                f"Use `c.skip` again to re-roll. Auto-cancels in {config.QUEUE_TIMEOUT} min."
            )

    # ── c.status ──────────────────────────────────────────────────────────────

    @commands.command(name="status", aliases=["pbstatus"])
    @commands.guild_only()
    async def status(self, ctx: commands.Context) -> None:
        """Show the current phonebooth status for this channel."""
        conn = await self.db.get_connection(ctx.channel.id)
        if conn:
            is_a      = ctx.channel.id == conn["channel_a"]
            other_gid = conn["guild_b"] if is_a else conn["guild_a"]
            other_g   = self.bot.get_guild(other_gid)
            embed = discord.Embed(title="📞 In a Call", color=config.COLOR_OK)
            embed.add_field(name="Duration",  value=_duration_str(conn["started_at"]), inline=True)
            embed.add_field(name="Messages",  value=str(conn["msg_count"]),            inline=True)
            embed.add_field(name="Call ID",   value=f"#{conn['id']}",                 inline=True)
            if other_g:
                embed.add_field(name="Connected To", value=other_g.name, inline=False)
            embed.set_footer(text=config.FOOTER)
            await ctx.send(embed=embed)
            return

        q = await self.db.get_queue_entry(ctx.channel.id)
        if q:
            embed = discord.Embed(
                title="⏳ Waiting in Queue",
                description=(
                    f"**Wait time:** {_duration_str(q['joined_at'])}\n"
                    f"**Queue size:** {await self.db.get_queue_size()}"
                ),
                color=config.COLOR_WAIT,
            )
            embed.set_footer(text=config.FOOTER)
            await ctx.send(embed=embed)
            return

        embed = discord.Embed(
            title="📴 Idle",
            description="Not connected. Use `c.call` to connect!",
            color=config.COLOR_WAIT,
        )
        embed.add_field(name="Active Calls",   value=str(await self.db.get_active_connection_count()), inline=True)
        embed.add_field(name="In Queue",       value=str(await self.db.get_queue_size()),              inline=True)
        embed.add_field(name="All-Time Calls", value=str(await self.db.get_total_calls()),             inline=True)
        embed.set_footer(text=config.FOOTER)
        await ctx.send(embed=embed)

    # ── c.block ───────────────────────────────────────────────────────────────

    @commands.command(name="block")
    @commands.guild_only()
    async def block(self, ctx: commands.Context) -> None:
        """Block the server you're currently connected to."""
        conn = await self.db.get_connection(ctx.channel.id)
        if not conn:
            await ctx.send("❌ You can only block a server while in an active call.")
            return

        is_a        = ctx.channel.id == conn["channel_a"]
        other_gid   = conn["guild_b"] if is_a else conn["guild_a"]
        other_cid   = conn["channel_b"] if is_a else conn["channel_a"]
        other_guild = self.bot.get_guild(other_gid)
        other_name  = other_guild.name if other_guild else f"Server {other_gid}"

        await self.db.block_guild(ctx.guild.id, other_gid, ctx.author.id)
        await self.db.remove_connection(conn["id"], ended_by=ctx.author.id)

        await ctx.send(f"🚫 **{other_name}** has been blocked & the call has ended.")

        other_ch = self.bot.get_channel(other_cid)
        if other_ch:
            try:
                await other_ch.send("📵 Other server has ended the call!")
            except discord.HTTPException:
                pass

    # ── c.anon / c.mask ───────────────────────────────────────────────────────

    @commands.command(name="anon", aliases=["mask", "anonymous"])
    @commands.guild_only()
    @commands.has_permissions(manage_channels=True)
    async def anon(self, ctx: commands.Context) -> None:
        """Toggle anonymous mode for this server. Requires Manage Channels."""
        if not await self.db.get_guild_config(ctx.guild.id):
            await ctx.send(f"❌ Phonebooth isn't set up. Run `c.setup` first.")
            return

        is_anon = await self.db.toggle_anonymous(ctx.guild.id)
        if is_anon:
            await ctx.send(
                "🎭 **Anonymous mode ON** — messages from this server will appear as *Stranger [Name]*."
            )
        else:
            await ctx.send(
                "👤 **Anonymous mode OFF** — messages will show your real display name and avatar."
            )

    # ── c.fr / c.friendrequest ────────────────────────────────────────────────

    @commands.command(name="friendrequest", aliases=["fr"])
    @commands.guild_only()
    async def friendrequest(self, ctx: commands.Context) -> None:
        """Share your Discord username with the person you're talking to."""
        conn = await self.db.get_connection(ctx.channel.id)
        if not conn:
            await ctx.send("❌ You can only share your friend request info during an active call.")
            return

        is_a      = ctx.channel.id == conn["channel_a"]
        other_cid = conn["channel_b"] if is_a else conn["channel_a"]
        member    = ctx.author

        embed = discord.Embed(
            title="👋 Friend Request",
            description=(
                "⚠️ **Stay safe online!**\n"
                "We cannot moderate users outside this bot. Accept friend requests at your own risk.\n"
                "Never share passwords or personal info & avoid clicking suspicious links.\n"
                "Report any misconduct to Discord immediately & remember to stay safe."
            ),
            color=0x5865F2,
        )
        embed.add_field(name="Username",     value=f"`{member.name}`",      inline=True)
        embed.add_field(name="Display Name", value=member.display_name,     inline=True)
        embed.set_thumbnail(url=_get_avatar_url(member))
        embed.set_footer(text="Copy the username above to send a friend request.")

        await ctx.send(embed=embed)

        other_ch = self.bot.get_channel(other_cid)
        if other_ch:
            relay_embed = discord.Embed(
                title="👋 Friend Request",
                description=(
                    "⚠️ **Stay safe online!**\n"
                    "We cannot moderate users outside this bot. Accept friend requests at your own risk.\n"
                    "Never share passwords or personal info & avoid clicking suspicious links.\n"
                    "Report any misconduct to Discord immediately & remember to stay safe."
                ),
                color=0x5865F2,
            )
            relay_embed.add_field(name="Username",     value=f"`{member.name}`",  inline=True)
            relay_embed.add_field(name="Display Name", value=member.display_name, inline=True)
            relay_embed.set_thumbnail(url=_get_avatar_url(member))
            relay_embed.set_footer(text="Copy the username above to send a friend request.")
            try:
                await other_ch.send(embed=relay_embed)
            except discord.HTTPException:
                pass


async def setup(bot):
    await bot.add_cog(Phonebooth(bot))
