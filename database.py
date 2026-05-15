"""
database.py – All persistence for Phonebooth V2.

Tables
------
guild_config    – one row per server that has run f.setup
queue           – channels currently waiting for a match
connections     – live, active calls between two channels
call_history    – completed / hung-up calls (for stats)
blocked_guilds  – server-level block list
banned_users    – bot-wide user ban list
gif_reports     – pending/reported GIF URLs awaiting owner review
gif_url_list    – blacklisted and whitelisted GIF URLs
"""

from __future__ import annotations

import asyncio
import aiosqlite
import inspect
from datetime import datetime
from typing import Optional

import config


class Database:
    def __init__(self, path: str = config.DB_PATH):
        self.path = path
        self._conn = None
        self._conn_lock = asyncio.Lock()

    def __getattribute__(self, name):
        attr = object.__getattribute__(self, name)
        if name.startswith("_") or name in {"init", "__class__"}:
            return attr
        if inspect.iscoroutinefunction(attr):
            async def guarded(*args, **kwargs):
                await object.__getattribute__(self, "_ensure_connection")()
                return await attr(*args, **kwargs)

            return guarded
        return attr

    async def _ensure_connection(self) -> None:
        """Ensure the shared DB connection exists. Only reconnects if None."""
        conn = object.__getattribute__(self, "_conn")
        if conn is not None:
            return
        async with object.__getattribute__(self, "_conn_lock"):
            conn = object.__getattribute__(self, "_conn")
            if conn is None:
                await object.__getattribute__(self, "init")()

    # ── Initialise ────────────────────────────────────────────────────────────

    async def init(self) -> None:
        old_conn = self._conn
        if old_conn is not None:
            try:
                await old_conn.close()
            except Exception:
                pass
        self._conn = await aiosqlite.connect(self.path)
        await self._conn.execute("PRAGMA journal_mode = WAL;")
        await self._conn.execute("PRAGMA synchronous = NORMAL;")
        await self._conn.execute("PRAGMA cache_size = -8000;")
        await self._conn.execute("PRAGMA temp_store = MEMORY;")
        await self._conn.execute("PRAGMA mmap_size = 134217728;")
        await self._conn.executescript("""
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
                CREATE INDEX IF NOT EXISTS idx_conn_a ON connections (channel_a);
                CREATE INDEX IF NOT EXISTS idx_conn_b ON connections (channel_b);

                CREATE TABLE IF NOT EXISTS custom_words (
                    word       TEXT PRIMARY KEY,
                    added_by   INTEGER,
                    created_at TEXT NOT NULL
                );

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
                CREATE TABLE IF NOT EXISTS notify_subscribers (
                    user_id    INTEGER PRIMARY KEY,
                    enabled    INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT    NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gif_url_list (
                    norm_url    TEXT PRIMARY KEY,
                    url         TEXT NOT NULL,
                    status      TEXT NOT NULL,
                    added_by    INTEGER,
                    added_at    TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS gif_mode_settings (
                    guild_id    INTEGER PRIMARY KEY,
                    mode        TEXT NOT NULL DEFAULT 'enabled',
                    updated_at  TEXT NOT NULL
                );

                -- ── Group Rooms ───────────────────────────────────────────
                -- A "room" is a group chat between up to 6 servers.
                -- status: 'waiting' (1 server, awaiting others) → 'active' → 'closed'
                CREATE TABLE IF NOT EXISTS rooms (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    status      TEXT NOT NULL DEFAULT 'waiting',
                    max_size    INTEGER NOT NULL DEFAULT 6,
                    created_at  TEXT NOT NULL,
                    closed_at   TEXT,
                    msg_count   INTEGER NOT NULL DEFAULT 0
                );

                -- One row per server currently in a room.
                -- channel_id is UNIQUE so a channel can only be in one room at a time.
                CREATE TABLE IF NOT EXISTS room_members (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    room_id     INTEGER NOT NULL,
                    channel_id  INTEGER NOT NULL,
                    guild_id    INTEGER NOT NULL,
                    webhook_url TEXT,
                    station     TEXT NOT NULL,
                    joined_at   TEXT NOT NULL,
                    msg_count   INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(channel_id)
                );

                CREATE INDEX IF NOT EXISTS idx_room_member_channel ON room_members (channel_id);
                CREATE INDEX IF NOT EXISTS idx_room_member_room    ON room_members (room_id);

                CREATE TABLE IF NOT EXISTS call_reports (
                    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                    reporter_guild_id   INTEGER NOT NULL,
                    reporter_user_id    INTEGER NOT NULL,
                    reported_guild_id   INTEGER NOT NULL,
                    reason              TEXT NOT NULL,
                    call_started_at     TEXT,
                    call_ended_at       TEXT,
                    status              TEXT NOT NULL DEFAULT 'open',
                    created_at          TEXT NOT NULL
                );
            """)
        await self._conn.commit()

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
        db = self._conn
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
            (guild_id, channel_id, webhook_url, user_id, datetime.utcnow().isoformat()),
        )
        await db.commit()

    async def delete_guild(self, guild_id: int) -> None:
        db = self._conn
        await db.execute("DELETE FROM guild_config WHERE guild_id = ?", (guild_id,))
        await db.commit()

    async def get_guild_config(self, guild_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_config WHERE guild_id = ?", (guild_id,)) as cur:
            return self._row(await cur.fetchone())

    async def get_config_by_channel(self, channel_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM guild_config WHERE channel_id = ?", (channel_id,)) as cur:
            return self._row(await cur.fetchone())

    async def toggle_anonymous(self, guild_id: int) -> bool:
        db = self._conn
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
        db = self._conn
        await db.execute("UPDATE guild_config SET webhook_url = ? WHERE channel_id = ?", (webhook_url, channel_id))
        await db.commit()

    # ── Queue ─────────────────────────────────────────────────────────────────

    async def add_to_queue(self, channel_id, guild_id, user_id, webhook_url) -> None:
        db = self._conn
        await db.execute(
            "INSERT OR REPLACE INTO queue (channel_id, guild_id, user_id, webhook_url, joined_at) VALUES (?, ?, ?, ?, ?)",
            (channel_id, guild_id, user_id, webhook_url, datetime.utcnow().isoformat()),
        )
        await db.commit()

    async def remove_from_queue(self, channel_id: int) -> None:
        db = self._conn
        await db.execute("DELETE FROM queue WHERE channel_id = ?", (channel_id,))
        await db.commit()

    async def get_queue_entry(self, channel_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM queue WHERE channel_id = ?", (channel_id,)) as cur:
            return self._row(await cur.fetchone())

    async def get_queue_match(self, guild_id: int, channel_id: int) -> Optional[dict]:
        db = self._conn
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
        db = self._conn
        async with db.execute("SELECT COUNT(*) FROM queue") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    # ── Connections ───────────────────────────────────────────────────────────

    async def create_connection(self, channel_a, guild_a, webhook_a, channel_b, guild_b, webhook_b) -> int:
        db = self._conn
        cur = await db.execute(
            "INSERT INTO connections (channel_a, guild_a, webhook_a, channel_b, guild_b, webhook_b, started_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (channel_a, guild_a, webhook_a, channel_b, guild_b, webhook_b, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid

    async def get_connection(self, channel_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM connections WHERE channel_a = ? OR channel_b = ?",
            (channel_id, channel_id),
        ) as cur:
            return self._row(await cur.fetchone())

    async def increment_message_count(self, connection_id: int) -> None:
        db = self._conn
        await db.execute("UPDATE connections SET msg_count = msg_count + 1 WHERE id = ?", (connection_id,))
        await db.commit()

    async def remove_connection(self, connection_id: int, ended_by: Optional[int] = None) -> Optional[dict]:
        db = self._conn
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
        db = self._conn
        async with db.execute("SELECT COUNT(*) FROM connections") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_total_calls(self) -> int:
        db = self._conn
        async with db.execute("SELECT COUNT(*) FROM call_history") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def get_total_guilds(self) -> int:
        db = self._conn
        async with db.execute("SELECT COUNT(*) FROM guild_config") as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    # ── Blocked guilds ────────────────────────────────────────────────────────

    async def block_guild(self, guild_id: int, blocked_id: int, user_id: int) -> None:
        now = datetime.utcnow().isoformat()
        db = self._conn
        await db.execute(
            "INSERT OR IGNORE INTO blocked_guilds (guild_id, blocked_guild_id, blocked_by, created_at) VALUES (?, ?, ?, ?)",
            (guild_id, blocked_id, user_id, now),
        )
        await db.commit()

    async def unblock_guild(self, guild_id: int, blocked_id: int) -> int:
        db = self._conn
        cur = await db.execute(
            "DELETE FROM blocked_guilds WHERE guild_id = ? AND blocked_guild_id = ?",
            (guild_id, blocked_id),
        )
        await db.commit()
        return cur.rowcount

    async def get_blocked_guilds(self, guild_id: int) -> list[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM blocked_guilds WHERE guild_id = ? ORDER BY created_at DESC", (guild_id,)
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── User ban list ─────────────────────────────────────────────────────────

    async def ban_user(self, user_id: int, banned_by: int, reason: str) -> None:
        db = self._conn
        await db.execute(
            "INSERT OR REPLACE INTO banned_users (user_id, banned_by, reason, created_at) VALUES (?, ?, ?, ?)",
            (user_id, banned_by, reason, datetime.utcnow().isoformat()),
        )
        await db.commit()

    async def unban_user(self, user_id: int) -> int:
        db = self._conn
        cur = await db.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
        await db.commit()
        return cur.rowcount

    async def is_user_banned(self, user_id: int) -> bool:
        db = self._conn
        async with db.execute("SELECT 1 FROM banned_users WHERE user_id = ?", (user_id,)) as cur:
            return await cur.fetchone() is not None

    # ── GIF Reports ───────────────────────────────────────────────────────────

    async def add_gif_report(self, url: str, msg_id: Optional[int], channel_id: int, guild_id: int) -> int:
        """Create a pending GIF report row. Returns the new row id."""
        norm = self._normalize_url(url)
        db = self._conn
        cur = await db.execute(
            "INSERT INTO gif_reports (url, norm_url, msg_id, channel_id, guild_id, status, created_at) VALUES (?, ?, ?, ?, ?, 'pending', ?)",
            (url, norm, msg_id, channel_id, guild_id, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid

    async def get_gif_report(self, report_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM gif_reports WHERE id = ?", (report_id,)) as cur:
            return self._row(await cur.fetchone())

    async def mark_gif_reported(self, report_id: int, reporter_id: int) -> None:
        """Record that a user clicked the report button."""
        db = self._conn
        await db.execute(
            "UPDATE gif_reports SET status = 'reported', reporter_id = ?, reported_at = ? WHERE id = ?",
            (reporter_id, datetime.utcnow().isoformat(), report_id),
        )
        await db.commit()

    async def resolve_gif_report(self, report_id: int, resolution: str) -> None:
        """Mark a report resolved after owner acts (pass 'blacklisted' or 'whitelisted')."""
        db = self._conn
        await db.execute("UPDATE gif_reports SET status = ? WHERE id = ?", (resolution, report_id))
        await db.commit()

    async def get_pending_gif_reports(self) -> list[dict]:
        """Return all reports that users have clicked (status='reported') awaiting review."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM gif_reports WHERE status = 'reported' ORDER BY reported_at ASC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    # ── GIF URL list (whitelist / blacklist) ──────────────────────────────────

    async def check_gif_url(self, url: str) -> Optional[str]:
        """Returns 'blacklist', 'whitelist', or None."""
        norm = self._normalize_url(url)
        db = self._conn
        async with db.execute("SELECT status FROM gif_url_list WHERE norm_url = ?", (norm,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

    async def set_gif_url_status(self, url: str, status: str, added_by: int) -> None:
        norm = self._normalize_url(url)
        db = self._conn
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
        db = self._conn
        cur = await db.execute("DELETE FROM gif_url_list WHERE norm_url = ?", (norm,))
        await db.commit()
        return cur.rowcount

    async def get_gif_mode(self, guild_id: int) -> str:
        """Return per-guild GIF mode. Defaults to 'enabled'."""
        db = self._conn
        async with db.execute(
            "SELECT mode FROM gif_mode_settings WHERE guild_id = ?", (guild_id,)
        ) as cur:
            row = await cur.fetchone()
            mode = (row[0] if row else "enabled")
        mode = (mode or "enabled").lower()
        return mode if mode in {"enabled", "limited", "disabled"} else "enabled"

    async def get_gif_modes_bulk(self, guild_id_a: int, guild_id_b: int) -> tuple[str, str]:
        """Return GIF modes for two guilds in a single query."""
        db = self._conn
        async with db.execute(
            "SELECT guild_id, mode FROM gif_mode_settings WHERE guild_id IN (?, ?)",
            (guild_id_a, guild_id_b),
        ) as cur:
            rows = {row[0]: row[1] for row in await cur.fetchall()}
        def _resolve(gid):
            mode = rows.get(gid, "enabled")
            mode = (mode or "enabled").lower()
            return mode if mode in {"enabled", "limited", "disabled"} else "enabled"
        return _resolve(guild_id_a), _resolve(guild_id_b)

    async def set_gif_mode(self, guild_id: int, mode: str) -> None:
        """Persist per-guild GIF mode ('enabled', 'limited', 'disabled')."""
        new_mode = (mode or "enabled").lower().strip()
        if new_mode not in {"enabled", "limited", "disabled"}:
            raise ValueError("Invalid GIF mode")
        db = self._conn
        await db.execute(
            """
            INSERT INTO gif_mode_settings (guild_id, mode, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(guild_id) DO UPDATE SET
                mode = excluded.mode,
                updated_at = excluded.updated_at
            """,
            (guild_id, new_mode, datetime.utcnow().isoformat()),
        )
        await db.commit()

    # ── Custom censor words ───────────────────────────────────────────────────

    async def add_custom_word(self, word: str, added_by: int) -> bool:
        """Add a custom word. Returns True if added, False if already exists."""
        try:
            db = self._conn
            await db.execute(
                "INSERT OR IGNORE INTO custom_words (word, added_by, created_at) VALUES (?, ?, ?)",
                (word.lower().strip(), added_by, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        except Exception:
            return False

    async def remove_custom_word(self, word: str) -> bool:
        """Remove a custom word. Returns True if removed."""
        db = self._conn
        cur = await db.execute(
            "DELETE FROM custom_words WHERE word = ?", (word.lower().strip(),)
        )
        await db.commit()
        return cur.rowcount > 0

    async def get_custom_words(self) -> list[str]:
        """Return all custom censored words."""
        db = self._conn
        async with db.execute("SELECT word FROM custom_words ORDER BY word") as cur:
            return [row[0] for row in await cur.fetchall()]

    # ── Group Rooms ───────────────────────────────────────────────────────────

    async def create_room(self, max_size: int = 6) -> int:
        """Create a new waiting room. Returns the new room id."""
        db = self._conn
        cur = await db.execute(
            "INSERT INTO rooms (status, max_size, created_at) VALUES ('waiting', ?, ?)",
            (max_size, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return cur.lastrowid

    async def get_room_by_id(self, room_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM rooms WHERE id = ?", (room_id,)) as cur:
            return self._row(await cur.fetchone())

    async def get_available_room(self, guild_id: int) -> Optional[dict]:
        """
        Find an active or waiting room that has space and doesn't already
        contain the requesting guild. Prefers active rooms, then fuller ones.
        """
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT r.*
            FROM   rooms r
            WHERE  r.status IN ('waiting', 'active')
              AND  (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) < r.max_size
              AND  NOT EXISTS (
                       SELECT 1 FROM room_members rm
                       WHERE  rm.room_id = r.id AND rm.guild_id = :gid
                   )
            ORDER BY
                CASE r.status WHEN 'active' THEN 0 ELSE 1 END ASC,
                (SELECT COUNT(*) FROM room_members rm WHERE rm.room_id = r.id) DESC
            LIMIT 1
            """,
            {"gid": guild_id},
        ) as cur:
            return self._row(await cur.fetchone())

    async def add_room_member(
        self,
        room_id: int,
        channel_id: int,
        guild_id: int,
        webhook_url: Optional[str],
        station: str,
    ) -> None:
        db = self._conn
        await db.execute(
            """
            INSERT OR IGNORE INTO room_members
                (room_id, channel_id, guild_id, webhook_url, station, joined_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (room_id, channel_id, guild_id, webhook_url, station, datetime.utcnow().isoformat()),
        )
        await db.commit()

    async def get_room_member(self, channel_id: int) -> Optional[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM room_members WHERE channel_id = ?", (channel_id,)
        ) as cur:
            return self._row(await cur.fetchone())

    async def get_room_members(self, room_id: int) -> list[dict]:
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM room_members WHERE room_id = ? ORDER BY joined_at ASC",
            (room_id,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def get_room_member_count(self, room_id: int) -> int:
        db = self._conn
        async with db.execute(
            "SELECT COUNT(*) FROM room_members WHERE room_id = ?", (room_id,)
        ) as cur:
            row = await cur.fetchone()
            return row[0] if row else 0

    async def remove_room_member(self, channel_id: int) -> Optional[dict]:
        """Remove a member from their room. Returns the removed member row or None."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM room_members WHERE channel_id = ?", (channel_id,)
        ) as cur:
            row = self._row(await cur.fetchone())
        if not row:
            return None
        await db.execute("DELETE FROM room_members WHERE channel_id = ?", (channel_id,))
        await db.commit()
        return row

    async def activate_room(self, room_id: int) -> None:
        db = self._conn
        await db.execute(
            "UPDATE rooms SET status = 'active' WHERE id = ?", (room_id,)
        )
        await db.commit()

    async def close_room(self, room_id: int) -> None:
        db = self._conn
        await db.execute(
            "UPDATE rooms SET status = 'closed', closed_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), room_id),
        )
        await db.commit()

    async def increment_room_msg_count(self, room_id: int) -> None:
        db = self._conn
        await db.execute(
            "UPDATE rooms SET msg_count = msg_count + 1 WHERE id = ?", (room_id,)
        )
        await db.commit()

    async def increment_room_member_msg_count(self, channel_id: int) -> None:
        db = self._conn
        await db.execute(
            "UPDATE room_members SET msg_count = msg_count + 1 WHERE channel_id = ?",
            (channel_id,),
        )
        await db.commit()

    async def get_used_stations(self, room_id: int) -> list[str]:
        """Return list of station names already assigned in this room."""
        db = self._conn
        async with db.execute(
            "SELECT station FROM room_members WHERE room_id = ?", (room_id,)
        ) as cur:
            return [row[0] for row in await cur.fetchall()]

    # ── Notify subscribers ────────────────────────────────────────────────────

    async def toggle_notify(self, user_id: int) -> bool:
        """Toggle queue notifications for a user. Returns True if now enabled."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT enabled FROM notify_subscribers WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
        if row is None:
            await db.execute(
                "INSERT INTO notify_subscribers (user_id, enabled, created_at) VALUES (?, 1, ?)",
                (user_id, datetime.utcnow().isoformat()),
            )
            await db.commit()
            return True
        new_val = 0 if row["enabled"] else 1
        await db.execute(
            "UPDATE notify_subscribers SET enabled = ? WHERE user_id = ?",
            (new_val, user_id),
        )
        await db.commit()
        return bool(new_val)

    async def get_notify_subscribers(self) -> list[int]:
        """Return all user IDs with notifications enabled."""
        db = self._conn
        async with db.execute(
            "SELECT user_id FROM notify_subscribers WHERE enabled = 1"
        ) as cur:
            rows = await cur.fetchall()
            return [r[0] for r in rows]

    async def get_notify_status(self, user_id: int) -> bool:
        """Return True if notifications are currently enabled for this user."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT enabled FROM notify_subscribers WHERE user_id = ?", (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return bool(row["enabled"]) if row else False

    # ── Call Reports ──────────────────────────────────────────────────────────────

    async def add_call_report(
        self,
        reporter_guild_id,
        reporter_user_id,
        reported_guild_id,
        reason,
        call_started_at,
        call_ended_at,
    ):
        """Store a new call report. Returns the new row id."""
        db = self._conn
        cur = await db.execute(
            "INSERT INTO call_reports (reporter_guild_id, reporter_user_id, reported_guild_id, reason, call_started_at, call_ended_at, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                reporter_guild_id,
                reporter_user_id,
                reported_guild_id,
                reason,
                call_started_at,
                call_ended_at,
                datetime.utcnow().isoformat(),
            ),
        )
        await db.commit()
        return cur.lastrowid

    async def get_open_call_reports(self):
        """Return all reports with status 'open', oldest first."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM call_reports WHERE status = 'open' ORDER BY created_at ASC"
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]

    async def resolve_call_report(self, report_id):
        """Mark a report resolved. Returns True if it existed and was open."""
        db = self._conn
        cur = await db.execute(
            "UPDATE call_reports SET status = 'resolved' WHERE id = ? AND status = 'open'",
            (report_id,),
        )
        await db.commit()
        return cur.rowcount > 0

    async def get_recent_call_for_guild(self, guild_id):
        """Return the most recent call_history row involving this guild."""
        db = self._conn
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT * FROM call_history
            WHERE guild_a = ? OR guild_b = ?
            ORDER BY ended_at DESC
            LIMIT 1
            """,
            (guild_id, guild_id),
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

