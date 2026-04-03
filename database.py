"""
database.py – All persistence for Phonebooth V2.

Tables
------
guild_config    – one row per server that has run c.setup
queue           – channels currently waiting for a match
connections     – live, active calls between two channels
call_history    – completed / hung-up calls (for stats)
blocked_guilds  – server-level block list
banned_users    – bot-wide user ban list
gif_reports     – pending/reported GIF URLs awaiting owner review
gif_url_list    – blacklisted and whitelisted GIF URLs
"""

from __future__ import annotations

import aiosqlite
from datetime import datetime
from typing import Optional

import config


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.path = path

    # ── Initialise ────────────────────────────────────────────────────────────

    async def init(self) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.executescript("""
                PRAGMA journal_mode = WAL;
                PRAGMA foreign_keys = ON;

                CREATE TABLE IF NOT EXISTS guild_config (
                    guild_id    INTEGER PRIMARY KEY,
                    channel_id  INTEGER NOT NULL,
                    webhook_url TEXT,
                    anonymous   INTEGER NOT NULL DEFAULT 0,
                    setup_by    INTEGER,
                    created_at  TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS queue (
                    channel_id  INTEGER PRIMARY KEY,
                    guild_id    INTEGER NOT NULL,
                    user_id     INTEGER NOT NULL,
                    webhook_url TEXT,
                    joined_at   TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS connections (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    channel_a   INTEGER NOT NULL,
                    guild_a     INTEGER NOT NULL,
                    webhook_a   TEXT,
                    channel_b   INTEGER NOT NULL,
                    guild_b     INTEGER NOT NULL,
                    webhook_b   TEXT,
                    started_at  TEXT NOT NULL,
                    msg_count   INTEGER NOT NULL DEFAULT 0
                );

                UPDATE guild_config SET anonymous = 0 WHERE anonymous = 1;

                CREATE INDEX IF NOT EXISTS idx_conn_a ON connections (channel_a);
                CREATE INDEX IF NOT EXISTS idx_conn_b ON connections (channel_b);

                CREATE TABLE IF NOT EXISTS banned_users (
                    user_id    INTEGER PRIMARY KEY,
                    banned_by  INTEGER,
                    reason     TEXT,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS call_history (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    guild_a     INTEGER NOT NULL,
                    guild_b     INTEGER NOT NULL,
                    started_at  TEXT NOT NULL,
                    ended_at    TEXT NOT NULL,
                    msg_count   INTEGER NOT NULL DEFAULT 0,
                    ended_by    INTEGER
                );

                CREATE TABLE IF NOT EXISTS blocked_guilds (
                    guild_id         INTEGER NOT NULL,
                    blocked_guild_id INTEGER NOT NULL,
                    blocked_by       INTEGER,
                    created_at       TEXT NOT NULL,
                    PRIMARY KEY (guild_id, blocked_guild_id)
                );

                -- GIF reports: one row per relayed GIF message that can be reported.
                -- status flow: 'pending' -> 'reported' (user clicked) -> 'reviewed' (owner acted)
                CREATE TABLE IF NOT EXISTS gif_reports (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    url         TEXT NOT NULL,
                    norm_url    TEXT NOT NULL,
                    msg_id      INTEGER,
                    channel_id  INTEGER NOT NULL,
                    guild_id    INTEGER NOT NULL,
                    reporter_id INTEGER,
                    status      TEXT NOT NULL DEFAULT 'pending',
                    created_at  TEXT NOT NULL,
                    reported_at TEXT
                );

                -- Whitelist / blacklist for GIF URLs keyed on normalised URL.
                CREATE TABLE IF NOT EXISTS gif_url_list (
                    norm_url    TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    added_by    INTEGER,
                    added_at    TEXT NOT NULL
                );
            """)
            await db.commit()

    # ── Internal helpers ──────────────────────────────────────────────────────

    @staticmethod
    def _row(row) -> Optional[dict]:
        return dict(row) if row else None

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Strip query params for consistent URL comparisons."""
        return url.split("?")[0].rstrip("/").lower()

    # ── Guild config ──────────────────────────────────────────────────────────

    async def setup_guild(self, guild_id, channel_id, webhook_url, user_id) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO guild_config
                    (guild_id, channel_id, webhook_url, setup_by, created_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(guild_id) DO UPDATE SET
                    channel_id  = excluded.channel_id,
                    webhook_url = excluded.webhook_url,
                    setup_by    = excluded.setup_by,
                    created_at  = excluded.created_at
                """,
                (guild_id, channel_id, webhook_url, user_id,
                 datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def delete_guild(self, guild_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM guild_config WHERE guild_id = ?", (guild_id,))
            await db.commit()

    async def get_guild_config(self, guild_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)) as cur:
                return self._row(await cur.fetchone())

    async def get_config_by_channel(self, channel_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM guild_config WHERE channel_id = ?", (channel_id,)) as cur:
                return self._row(await cur.fetchone())

    async def toggle_anonymous(self, guild_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT anonymous FROM guild_config WHERE guild_id = ?", (guild_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return True
                new_val = 0 if row["anonymous"] else 1
            await db.execute("UPDATE guild_config SET anonymous = ? WHERE guild_id = ?", (new_val, guild_id))
            await db.commit()
            return bool(new_val)

    async def update_webhook(self, channel_id: int, webhook_url: Optional[str]) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE guild_config SET webhook_url = ? WHERE channel_id = ?", (webhook_url, channel_id))
            await db.commit()

    # ── Queue ─────────────────────────────────────────────────────────────────

    async def add_to_queue(self, channel_id, guild_id, user_id, webhook_url) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO queue (channel_id, guild_id, user_id, webhook_url, joined_at) VALUES (?, ?, ?, ?, ?)",
                (channel_id, guild_id, user_id, webhook_url, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def remove_from_queue(self, channel_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("DELETE FROM queue WHERE channel_id = ?", (channel_id,))
            await db.commit()

    async def get_queue_entry(self, channel_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM queue WHERE channel_id = ?", (channel_id,)) as cur:
                return self._row(await cur.fetchone())

    async def get_queue_match(self, guild_id: int, channel_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                """
                SELECT q.*
                FROM   queue q
                WHERE  q.guild_id   != :gid
                  AND  q.channel_id != :cid
                  AND  NOT EXISTS (
                           SELECT 1 FROM blocked_guilds b
                           WHERE  (b.guild_id = :gid AND b.blocked_guild_id = q.guild_id)
                              OR  (b.guild_id = q.guild_id AND b.blocked_guild_id = :gid)
                       )
                ORDER BY q.joined_at ASC
                LIMIT 1
                """,
                {"gid": guild_id, "cid": channel_id},
            ) as cur:
                return self._row(await cur.fetchone())

    async def get_queue_size(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM queue") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    # ── Connections ───────────────────────────────────────────────────────────

    async def create_connection(self, channel_a, guild_a, webhook_a, channel_b, guild_b, webhook_b) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO connections (channel_a, guild_a, webhook_a, channel_b, guild_b, webhook_b, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (channel_a, guild_a, webhook_a, channel_b, guild_b, webhook_b, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return cur.lastrowid

    async def get_connection(self, channel_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM connections WHERE channel_a = ? OR channel_b = ?",
                (channel_id, channel_id),
            ) as cur:
                return self._row(await cur.fetchone())

    async def increment_message_count(self, connection_id: int) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE connections SET msg_count = msg_count + 1 WHERE id = ?", (connection_id,))
            await db.commit()

    async def remove_connection(self, connection_id: int, ended_by: Optional[int] = None) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM connections WHERE id = ?", (connection_id,)) as cur:
                row = await cur.fetchone()
                if not row:
                    return None
                conn = dict(row)
            await db.execute(
                "INSERT INTO call_history (guild_a, guild_b, started_at, ended_at, msg_count, ended_by) VALUES (?, ?, ?, ?, ?, ?)",
                (conn["guild_a"], conn["guild_b"], conn["started_at"], datetime.utcnow().isoformat(), conn["msg_count"], ended_by),
            )
            await db.execute("DELETE FROM connections WHERE id = ?", (connection_id,))
            await db.commit()
            return conn

    async def get_active_connection_count(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM connections") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_total_calls(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM call_history") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    async def get_total_guilds(self) -> int:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT COUNT(*) FROM guild_config") as cur:
                row = await cur.fetchone()
                return row[0] if row else 0

    # ── Blocked guilds ────────────────────────────────────────────────────────

    async def block_guild(self, guild_id: int, blocked_id: int, user_id: int) -> None:
        now = datetime.utcnow().isoformat()
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR IGNORE INTO blocked_guilds (guild_id, blocked_guild_id, blocked_by, created_at) VALUES (?, ?, ?, ?)",
                (guild_id, blocked_id, user_id, now),
            )
            await db.commit()

    async def unblock_guild(self, guild_id: int, blocked_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "DELETE FROM blocked_guilds WHERE guild_id = ? AND blocked_guild_id = ?",
                (guild_id, blocked_id),
            )
            await db.commit()
            return cur.rowcount

    async def get_blocked_guilds(self, guild_id: int) -> list[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM blocked_guilds WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # ── User ban list ─────────────────────────────────────────────────────────

    async def ban_user(self, user_id: int, banned_by: int, reason: str) -> None:
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "INSERT OR REPLACE INTO banned_users (user_id, banned_by, reason, created_at) VALUES (?, ?, ?, ?)",
                (user_id, banned_by, reason, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def unban_user(self, user_id: int) -> int:
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
            await db.commit()
            return cur.rowcount

    async def is_user_banned(self, user_id: int) -> bool:
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)) as cur:
                return await cur.fetchone() is not None

    # ── GIF Reports ───────────────────────────────────────────────────────────

    async def add_gif_report(self, url: str, msg_id: Optional[int], channel_id: int, guild_id: int) -> int:
        """Create a pending GIF report row. Returns the new row id."""
        norm = self._normalize_url(url)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute(
                "INSERT INTO gif_reports (url, norm_url, msg_id, channel_id, guild_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
                (url, norm, msg_id, channel_id, guild_id, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return cur.lastrowid

    async def get_gif_report(self, report_id: int) -> Optional[dict]:
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute("SELECT * FROM gif_reports WHERE id = ?", (report_id,)) as cur:
                return self._row(await cur.fetchone())

    async def mark_gif_reported(self, report_id: int, reporter_id: int) -> None:
        """Record that a user clicked the report button."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                "UPDATE gif_reports SET status = 'reported', reporter_id = ?, reported_at = ? WHERE id = ?",
                (reporter_id, datetime.utcnow().isoformat(), report_id),
            )
            await db.commit()

    async def resolve_gif_report(self, report_id: int, resolution: str) -> None:
        """Mark a report resolved after owner acts (pass 'blacklisted' or 'whitelisted')."""
        async with aiosqlite.connect(self.path) as db:
            await db.execute("UPDATE gif_reports SET status = ? WHERE id = ?", (resolution, report_id))
            await db.commit()

    async def get_pending_gif_reports(self) -> list[dict]:
        """Return all reports that users have clicked (status='reported') awaiting review."""
        async with aiosqlite.connect(self.path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(
                "SELECT * FROM gif_reports WHERE status = 'reported' ORDER BY reported_at ASC"
            ) as cur:
                return [dict(r) for r in await cur.fetchall()]

    # ── GIF URL list (whitelist / blacklist) ──────────────────────────────────

    async def check_gif_url(self, url: str) -> Optional[str]:
        """Returns 'blacklist', 'whitelist', or None."""
        norm = self._normalize_url(url)
        async with aiosqlite.connect(self.path) as db:
            async with db.execute("SELECT status FROM gif_url_list WHERE norm_url = ?", (norm,)) as cur:
                row = await cur.fetchone()
                return row[0] if row else None

    async def set_gif_url_status(self, url: str, status: str, added_by: int) -> None:
        norm = self._normalize_url(url)
        async with aiosqlite.connect(self.path) as db:
            await db.execute(
                """
                INSERT INTO gif_url_list (norm_url, url, status, added_by, added_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(norm_url) DO UPDATE SET
                    status = excluded.status, added_by = excluded.added_by, added_at = excluded.added_at
                """,
                (norm, url, status, added_by, datetime.utcnow().isoformat()),
            )
            await db.commit()

    async def remove_gif_url(self, url: str) -> int:
        norm = self._normalize_url(url)
        async with aiosqlite.connect(self.path) as db:
            cur = await db.execute("DELETE FROM gif_url_list WHERE norm_url = ?", (norm,))
            await db.commit()
            return cur.rowcount
