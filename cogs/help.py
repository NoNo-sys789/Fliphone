"""
cogs/help.py – Help command for Fliphone.
"""

from __future__ import annotations

from typing import Optional

import discord
from discord.ext import commands

import config

_CAT_COLOUR = {
    "📞 Calling":       0x57F287,
    "📡 Group Rooms":   0x5865F2,
    "⚙️ Server Setup":  0x4ECDC4,
    "🛡️ Moderation":   0xFFA500,
    "🔑 Owner Only":    0xFF6B6B,
}

COMMANDS = [
    # ── Calling ──────────────────────────────────────────────────────────────
    (
        "call", ["c", "dial", "connect"], "f.call",
        "Join the queue and connect to a random server. If someone is already "
        "waiting you connect instantly; otherwise you wait up to "
        f"{config.QUEUE_TIMEOUT} minutes before auto-cancelling.",
        "Everyone", "📞 Calling",
    ),
    (
        "hangup", ["h", "disconnect", "bye"], "f.hangup",
        "End your active call or leave the queue. Both sides get a "
        "goodbye message with the call duration and message count.",
        "Everyone", "📞 Calling",
    ),
    (
        "skip", ["s", "next"], "f.skip",
        "Hang up the current call (or leave the queue) and immediately search "
        "for a new partner. Has a 5-second cooldown per channel.",
        "Everyone", "📞 Calling",
    ),
    (
        "status", ["pbstatus"], "f.status",
        "Shows whether this channel is idle, in the queue, or in an active call. "
        "Displays duration, message count, and the connected server name.",
        "Everyone", "📞 Calling",
    ),
    (
        "block", [], "f.block",
        "Block the server you are currently talking to. The call ends immediately "
        "and the two servers will never be matched again.",
        "Everyone", "📞 Calling",
    ),
    (
        "anon", ["mask", "anonymous"], "f.anon",
        "Toggle anonymous mode for your server. When on, all outgoing messages "
        "appear as Stranger [NATO-name] with a robot avatar instead of your real "
        "display name and profile picture.",
        "Everyone", "📞 Calling",
    ),
    (
        "friendrequest", ["fr"], "f.fr",
        "Share your Discord username with the person you are "
        "talking to as a safe friend-request card. Only works during an active call.",
        "Everyone", "📞 Calling",
    ),
    (
        "notify", ["notifications"], "f.notify",
        "Toggle queue call notifications. When enabled, the bot DMs you whenever "
        "a server enters the queue with nobody to connect to. Run again to turn off.",
        "Everyone", "📞 Calling",
    ),
    (
        "report", [], "f.report",
        "Report the server you are currently in a call with, or your most recent "
        "call. You will be prompted to describe what happened. Reports go directly "
        "to the Fliphone moderation team for review.",
        "Everyone", "📞 Calling",
    ),
    (
        "invite", [], "f.invite",
        "Get the invite link to add Fliphone to another server.",
        "Everyone", "📞 Calling",
    ),
    (
        "stats", [], "f.stats",
        "Show global Fliphone statistics: active calls, queue size, all-time "
        "call count, and how many servers have the bot configured.",
        "Everyone", "📞 Calling",
    ),

    # ── Group Rooms ───────────────────────────────────────────────────────────
    (
        "room", ["r"], "f.room",
        "Join a group room with up to 6 servers. If an active room has space you "
        "slot straight in; otherwise a new room is created and waits for others. "
        "Each server is identified by a NATO station name (Alpha–Foxtrot) — your "
        "real server name is never shown.",
        "Everyone", "📡 Group Rooms",
    ),
    (
        "roomleave", ["rl"], "f.roomleave",
        "Leave your current group room quietly. The room stays open for the "
        "remaining servers unless fewer than 2 are left, in which case it closes.",
        "Everyone", "📡 Group Rooms",
    ),
    (
        "roomskip", ["rs"], "f.roomskip",
        "Leave your current room and immediately search for a new one — the "
        "room equivalent of f.skip.",
        "Everyone", "📡 Group Rooms",
    ),
    (
        "roomstatus", ["rst"], "f.roomstatus",
        "Show a summary of your current room: station name, how many servers "
        "are present, duration, message count, and all active stations.",
        "Everyone", "📡 Group Rooms",
    ),
    (
        "roomkick", ["rk"], "f.roomkick <station>",
        "Start a majority vote to remove a misbehaving station from the room. "
        "Requires at least 3 servers in the room. The initiator automatically "
        "votes to kick. Kicked servers receive a 10-minute room cooldown. "
        "Example: f.roomkick Bravo",
        "Everyone", "📡 Group Rooms",
    ),

    # ── Server Setup ──────────────────────────────────────────────────────────
    (
        "setup", [], "f.setup [#channel]",
        "Register this channel (or an optional other channel) as the Fliphone "
        "channel for your server. Creates a webhook automatically if the bot has "
        "Manage Webhooks permission. Run this once after inviting the bot.",
        "Admin only", "⚙️ Server Setup",
    ),
    (
        "teardown", ["remove"], "f.teardown",
        "Remove the Fliphone configuration from this server. Ends any active "
        "call, removes the channel from the queue, and deletes the relay webhook.",
        "Admin only", "⚙️ Server Setup",
    ),
    (
        "blocklist", ["blocked"], "f.blocklist",
        "List every server your server has blocked. Use f.unblock <id> to "
        "remove an entry.",
        "Admin only", "⚙️ Server Setup",
    ),
    (
        "unblock", [], "f.unblock <server_id>",
        "Remove a server from your blocklist. You will be matchable with them again.",
        "Admin only", "⚙️ Server Setup",
    ),
    (
        "kick", [], "f.kick",
        "Force-disconnect the active call in this server's Fliphone channel. "
        "Useful for moderating calls that go wrong.",
        "Admin only", "⚙️ Server Setup",
    ),
    (
        "gifmode", [], "f.gifmode <enabled|limited|disabled>",
        "Set the GIF mode for this server. "
        "enabled — all GIFs allowed (default). "
        "limited — only Tenor, Giphy, and Klipy links are relayed. "
        "disabled — all GIFs are blocked. "
        "Run f.gifmode with no argument to see the current setting.",
        "Server Admin", "⚙️ Server Setup",
    ),

    # ── Owner Only ────────────────────────────────────────────────────────────
    (
        "ban", [], "f.ban <user_id> [reason]",
        "Permanently ban a user by ID from using Fliphone across all servers. "
        "Bot owner only — not server admins.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "unban", [], "f.unban <user_id>",
        "Lift a bot-wide ban on a user. Bot owner only.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "gifreports", [], "f.gifreports",
        "List all GIF URLs that have been reported by users and are awaiting "
        "review. Use f.gifbl or f.gifwl to action each one.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "userreports", [], "f.userreports",
        "List all open call/conversation reports submitted by users via f.report. "
        "Use f.resolvereport <id> to close a report once actioned.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "resolvereport", [], "f.resolvereport <id>",
        "Mark a call report as resolved. Get the report ID from f.userreports.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "gifbl", [], "f.gifbl <report_id or url>",
        "Blacklist a GIF URL. Pass a report ID from f.gifreports or paste the raw "
        "URL. Blacklisted GIFs are stripped from future relay messages.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "gifwl", [], "f.gifwl <report_id or url>",
        "Whitelist a GIF URL so the report button has no effect on it.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "gifcheck", [], "f.gifcheck <url>",
        "Check whether a URL is currently on the blacklist, whitelist, or neither.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "notifyignore", [], "f.notifyignore <user_id>",
        "Toggle a user ID on or off the notify ignore list. Users on this list will "
        "not trigger queue notification DMs when they join the queue — useful for "
        "testers and developers.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "censor", [], "f.censor <word or phrase>",
        "Add or remove a word from the custom censor list. Toggles — if the word "
        "is already censored it will be removed. Changes take effect immediately.",
        "Bot Owner", "🔑 Owner Only",
    ),
    (
        "censorlist", [], "f.censorlist",
        "List all custom censored words you have added. Does not show the "
        "hardcoded built-in word list.",
        "Bot Owner", "🔑 Owner Only",
    ),
]

_CMD_MAP: dict[str, tuple] = {}
for entry in COMMANDS:
    _CMD_MAP[entry[0].lower()] = entry
    for alias in entry[1]:
        _CMD_MAP[alias.lower()] = entry


class Help(commands.Cog):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.command(name="help", aliases=["commands", "cmds"])
    async def help(self, ctx: commands.Context, *, command: Optional[str] = None) -> None:
        """Show all commands, or detailed info about one command."""

        if command:
            key = command.strip().lower().removeprefix(config.PREFIX.lower())
            entry = _CMD_MAP.get(key)
            if not entry:
                await ctx.send(
                    embed=discord.Embed(
                        description=f"❌ No command named `{command}` found. Run `f.help` for the full list.",
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
            embed.add_field(name="Usage",      value=f"`{usage}`",   inline=True)
            embed.add_field(name="Category",   value=category,       inline=True)
            embed.add_field(name="Permission", value=perms,          inline=True)
            if aliases:
                alias_str = " · ".join(f"`{config.PREFIX}{a}`" for a in aliases)
                embed.add_field(name="Aliases", value=alias_str, inline=False)
            embed.set_footer(text=f"Tip: f.help <command>  •  {config.FOOTER}")
            await ctx.send(embed=embed)
            return

        # ── Overview ──────────────────────────────────────────────────────────
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
            title="📞 Fliphone — Help",
            description=(
                f"**Prefix:** `{config.PREFIX}`\n"
                "Connect your server to a random server and chat!\n"
                f"Run `{config.PREFIX}help <command>` for detailed info on any command.\n\u200b"
            ),
            color=0x5865F2,
        )

        for cat, entries in categories.items():
            lines = []
            for name, aliases, usage, desc, perms, _ in entries:
                short = desc.split(".")[0]
                if len(short) > 80:
                    short = short[:77] + "…"
                alias_hint = f" *(also: {', '.join(aliases[:2])})*" if aliases else ""
                perm_hint = f" *(admin)*" if perms in ("Admin only", "Server Admin") else ""
                lines.append(f"`{config.PREFIX}{name}`{alias_hint}{perm_hint} — {short}.")
            embed.add_field(name=cat, value="\n".join(lines), inline=False)

        embed.add_field(
            name="\u200b",
            value=(
                f"[Invite Fliphone](https://discord.com/api/oauth2/authorize"
                f"?client_id={self.bot.user.id}"
                f"&permissions={config.BOT_PERMISSIONS}"
                f"&scope=bot+applications.commands)"
                f" • [Vote on top.gg](https://top.gg/bot/1489342959974486158)"
                f" • [Privacy Policy](https://gist.github.com/Kama0f1/431f01bbbf1ae6243505778376ba0fb3)"
                f" • [Terms of Service](https://gist.github.com/Kama0f1/085bf38fb03e3c84d99f2ff9afc410af)"
            ),
            inline=False,
        )
        embed.set_footer(text=config.FOOTER)
        await ctx.send(embed=embed)


async def setup(bot):
    await bot.add_cog(Help(bot))
