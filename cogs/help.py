"""
cogs/help.py – Beautiful paginated help command for Phonebooth V2.

c.help         – Overview embed with all categories
c.help <cmd>   – Detailed embed for one specific command
"""

from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

import config

# ── Colour per category ────────────────────────────────────────────────────────
_CAT_COLOUR = {
    "📞 Calling":       0x57F287,   # green
    "⚙️ Server Setup":  0x5865F2,   # blurple
    "🛡️ Moderation":   0xFFA500,   # orange
    "🔑 Owner Only":    0xFF6B6B,   # red
}

# ── Full command catalogue ─────────────────────────────────────────────────────
# Each entry: (name, aliases, usage, description, permissions, category)
COMMANDS = [
    # ── Calling ──────────────────────────────────────────────────────────────
    (
        "call", ["c", "dial", "connect"],
        "c.call",
        "Join the queue and connect to a random server. If someone is already "
        "waiting you connect instantly; otherwise you wait up to "
        f"{config.QUEUE_TIMEOUT} minutes before auto-cancelling.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "hangup", ["h", "disconnect", "bye"],
        "c.hangup",
        "End your active call **or** leave the queue. Both sides get a "
        "goodbye message with the call duration and message count.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "skip", ["s", "next"],
        "c.skip",
        "Hang up the current call (or leave the queue) and immediately search "
        "for a new partner. Has a 5-second cooldown per channel.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "status", ["pbstatus"],
        "c.status",
        "Shows whether this channel is idle, in the queue, or in an active call. "
        "Displays duration, message count, and the connected server name.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "block", [],
        "c.block",
        "Block the server you are currently talking to. The call ends immediately "
        "and the two servers will never be matched again.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "anon", ["mask", "anonymous"],
        "c.anon",
        "Toggle **anonymous mode** for your server. When on, all outgoing messages "
        "appear as *Stranger [NATO-name]* with a robot avatar instead of your real "
        "display name and profile picture.",
        "Manage Channels",
        "📞 Calling",
    ),
    (
        "friendrequest", ["fr"],
        "c.fr",
        "Share your Discord username (not password!) with the person you are "
        "talking to as a safe friend-request card. Only works during an active call.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "invite", [],
        "c.invite",
        "Get the invite link to add Phonebooth V2 to another server.",
        "Everyone",
        "📞 Calling",
    ),
    (
        "stats", [],
        "c.stats",
        "Show global Phonebooth statistics: active calls, queue size, all-time "
        "call count, and how many servers have the bot configured.",
        "Everyone",
        "📞 Calling",
    ),

    # ── Server Setup ──────────────────────────────────────────────────────────
    (
        "setup", [],
        "c.setup [#channel]",
        "Register this channel (or an optional other channel) as the Phonebooth "
        "channel for your server. Creates a webhook automatically if the bot has "
        "Manage Webhooks permission. Run this once after inviting the bot.",
        "Manage Channels",
        "⚙️ Server Setup",
    ),
    (
        "teardown", ["remove"],
        "c.teardown",
        "Remove the Phonebooth configuration from this server. Ends any active "
        "call, removes the channel from the queue, and deletes the relay webhook.",
        "Manage Channels",
        "⚙️ Server Setup",
    ),
    (
        "blocklist", ["blocked"],
        "c.blocklist",
        "List every server your server has blocked. Use `c.unblock <id>` to "
        "remove an entry.",
        "Manage Channels",
        "⚙️ Server Setup",
    ),
    (
        "unblock", [],
        "c.unblock <server_id>",
        "Remove a server from your blocklist. You will be matchable with them again.",
        "Manage Channels",
        "⚙️ Server Setup",
    ),
    (
        "kick", [],
        "c.kick",
        "Force-disconnect the active call in this server's phonebooth channel. "
        "Useful for moderating calls that go wrong.",
        "Manage Channels",
        "⚙️ Server Setup",
    ),

    # ── Owner Only ────────────────────────────────────────────────────────────
    (
        "ban", [],
        "c.ban <user_id> [reason]",
        "Permanently ban a user by ID from using Phonebooth across **all** servers. "
        "The ban is bot-wide, not server-specific.",
        "Bot Owner",
        "🔑 Owner Only",
    ),
    (
        "unban", [],
        "c.unban <user_id>",
        "Lift a bot-wide ban on a user.",
        "Bot Owner",
        "🔑 Owner Only",
    ),
    (
        "reports", [],
        "c.reports",
        "List all GIF URLs that have been reported by users and are awaiting your "
        "review. Shows reporter, timestamp and a truncated URL. Use `c.gifbl` or "
        "`c.gifwl` to action each one.",
        "Bot Owner",
        "🔑 Owner Only",
    ),
    (
        "gifbl", [],
        "c.gifbl <report_id or url>",
        "Blacklist a GIF URL. Pass a report ID from `c.reports` or paste the raw "
        "URL. Blacklisted GIFs are silently stripped from future relay messages and "
        "the sender gets a warning.",
        "Bot Owner",
        "🔑 Owner Only",
    ),
    (
        "gifwl", [],
        "c.gifwl <report_id or url>",
        "Whitelist a GIF URL so the report button has no effect on it. Use this "
        "after confirming a flagged GIF is actually safe.",
        "Bot Owner",
        "🔑 Owner Only",
    ),
    (
        "gifcheck", [],
        "c.gifcheck <url>",
        "Check whether a URL is currently on the blacklist, whitelist, or neither.",
        "Bot Owner",
        "🔑 Owner Only",
    ),
]

# Build a fast lookup dict
_CMD_MAP: dict[str, tuple] = {}
for entry in COMMANDS:
    _CMD_MAP[entry[0].lower()] = entry
    for alias in entry[1]:
        _CMD_MAP[alias.lower()] = entry


# ── Cog ───────────────────────────────────────────────────────────────────────

class Help(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.command(name="help", aliases=["commands", "cmds"])
    async def help(self, ctx: commands.Context, *, command: Optional[str] = None) -> None:
        """Show all commands, or detailed info about one command."""

        # ── Specific command lookup ───────────────────────────────────────────
        if command:
            key = command.strip().lower().lstrip(config.PREFIX)
            entry = _CMD_MAP.get(key)
            if not entry:
                await ctx.send(
                    embed=discord.Embed(
                        description=f"❌ No command named `{command}` found. Run `c.help` for the full list.",
                        color=config.COLOR_ERR,
                    )
                )
                return

            name, aliases, usage, description, perms, category = entry
            colour = _CAT_COLOUR.get(category, config.COLOR_WAIT)

            embed = discord.Embed(
                title=f"📖 `{config.PREFIX}{name}`",
                description=description,
                color=colour,
            )
            embed.add_field(name="Usage",       value=f"`{usage}`",                         inline=True)
            embed.add_field(name="Category",    value=category,                              inline=True)
            embed.add_field(name="Permission",  value=f"🔒 {perms}" if perms != "Everyone" else "🌐 Everyone", inline=True)
            if aliases:
                alias_str = " · ".join(f"`{config.PREFIX}{a}`" for a in aliases)
                embed.add_field(name="Aliases", value=alias_str, inline=False)
            embed.set_footer(text=f"Tip: c.help <command>  •  {config.FOOTER}")
            await ctx.send(embed=embed)
            return

        # ── Overview embed ────────────────────────────────────────────────────
        # Group commands by category, preserving insertion order
        categories: dict[str, list[tuple]] = {}
        seen: set[str] = set()
        for entry in COMMANDS:
            name = entry[0]
            if name in seen:
                continue
            seen.add(name)
            cat = entry[5]
            categories.setdefault(cat, []).append(entry)

        embed = discord.Embed(
            title="📞 Phonebooth V2 — Help",
            description=(
                f"**Prefix:** `{config.PREFIX}`\n"
                "Connect your server to a random server and chat anonymously!\n"
                f"Run `{config.PREFIX}help <command>` for detailed info on any command.\n\u200b"
            ),
            color=0x5865F2,
        )

        for cat, entries in categories.items():
            lines = []
            for name, aliases, usage, desc, perms, _ in entries:
                # First sentence of description only (up to 80 chars)
                short = desc.split(".")[0]
                if len(short) > 80:
                    short = short[:77] + "…"
                alias_hint = f" *(also: {', '.join(aliases[:2])})*" if aliases else ""
                lines.append(f"`{config.PREFIX}{name}`{alias_hint} — {short}.")
            embed.add_field(name=cat, value="\n".join(lines), inline=False)

        embed.add_field(
            name="\u200b",
            value=(
                f"🔒 = requires a specific Discord permission\n"
                f"🔑 = bot owner only\n"
                f"[Invite the bot]"
                f"(https://discord.com/api/oauth2/authorize"
                f"?client_id={self.bot.user.id}"
                f"&permissions={config.BOT_PERMISSIONS}"
                f"&scope=bot)"
            ),
            inline=False,
        )
        embed.set_footer(text=config.FOOTER)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
