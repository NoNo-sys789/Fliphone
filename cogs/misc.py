"""
cogs/misc.py — small utility commands (ping, shards)
"""

from __future__ import annotations

import discord
from discord.ext import commands

import config


class Misc(commands.Cog, name="Misc"):
    def __init__(self, bot) -> None:
        self.bot = bot

    @commands.command(name="ping")
    async def ping(self, ctx: commands.Context) -> None:
        """Respond with bot latency (WebSocket)."""
        ws_latency = self.bot.latency or 0.0
        embed = discord.Embed(
            title="Pong!",
            description=f"WebSocket latency: {ws_latency*1000:.0f} ms",
            color=config.COLOR_OK,
        )
        await ctx.send(embed=embed)

    @commands.command(name="shards")
    async def shards(self, ctx: commands.Context) -> None:
        """Show sharding info (if sharded)."""
        shard_count = getattr(self.bot, "shard_count", None)
        shard_id = getattr(self.bot, "shard_id", None)
        if shard_count is None:
            await ctx.send("This bot is not using explicit sharding (auto mode).")
            return
        await ctx.send(f"Shard: {shard_id} / {shard_count}")


async def setup(bot: commands.Bot) -> None:  # for discord.py loader
    await bot.add_cog(Misc(bot))
