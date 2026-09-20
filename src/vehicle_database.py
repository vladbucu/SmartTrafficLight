"""
Lightweight vehicle identity database.
Tracks vehicles by license plate with their attributes (color, first seen, camera, etc).
Uses SQLite for persistence and quick lookup.
"""
import sqlite3
import json
from datetime import datetime
from typing import Dict, Optional, Tuple, List
from pathlib import Path


class VehicleDatabase:
    """
    SQLite-based vehicle tracking database optimized for Raspberry Pi.
    Stores:
    - plate_number (unique identifier)
    - color (B, G, R)
    - first_seen_at (ISO timestamp)
    - last_seen_at (ISO timestamp)
    - last_seen_camera (camera_id: 0 or 1)
    - entry_count (how many times we've seen entry)
    - exit_count (how many times we've seen exit)
    - metadata (JSON: brand_guesses, etc)
    """

    def __init__(self, db_path: str = "data/vehicles.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        """Initialize database schema if it doesn't exist."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS vehicles (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate_number TEXT UNIQUE NOT NULL,
                    color_b INTEGER,
                    color_g INTEGER,
                    color_r INTEGER,
                    first_seen_at TEXT NOT NULL,
                    last_seen_at TEXT NOT NULL,
                    last_seen_camera INTEGER,
                    entry_count INTEGER DEFAULT 0,
                    exit_count INTEGER DEFAULT 0,
                    metadata TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plate_number TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    camera_id INTEGER,
                    timestamp TEXT NOT NULL,
                    color_b INTEGER,
                    color_g INTEGER,
                    color_r INTEGER,
                    FOREIGN KEY(plate_number) REFERENCES vehicles(plate_number)
                )
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_plate ON events(plate_number)
            """)

            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)
            """)

            conn.commit()

    def register_sighting(
        self,
        plate_number: str,
        color: Tuple[int, int, int],
        camera_id: int,
        event_type: str = "sighting"
    ) -> Dict:
        """
        Register a vehicle sighting.
        event_type: 'entry', 'exit', or 'sighting'
        Returns: vehicle record (dict)
        """
        now = datetime.utcnow().isoformat()
        b, g, r = color

        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Check if vehicle exists
            cursor.execute("SELECT * FROM vehicles WHERE plate_number = ?", (plate_number,))
            row = cursor.fetchone()

            if row:
                # Update existing
                if event_type == "entry":
                    entry_count = row[8] + 1
                    exit_count = row[9]
                else:
                    entry_count = row[8]
                    exit_count = row[9] + 1 if event_type == "exit" else row[9]

                cursor.execute("""
                    UPDATE vehicles
                    SET last_seen_at = ?, last_seen_camera = ?,
                        entry_count = ?, exit_count = ?, updated_at = ?
                    WHERE plate_number = ?
                """, (now, camera_id, entry_count, exit_count, now, plate_number))
            else:
                # Insert new
                entry_count = 1 if event_type == "entry" else 0
                exit_count = 1 if event_type == "exit" else 0

                cursor.execute("""
                    INSERT INTO vehicles
                    (plate_number, color_b, color_g, color_r, first_seen_at, last_seen_at,
                     last_seen_camera, entry_count, exit_count, metadata, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (plate_number, b, g, r, now, now, camera_id, entry_count, exit_count,
                      json.dumps({}), now, now))

            # Log event
            cursor.execute("""
                INSERT INTO events (plate_number, event_type, camera_id, timestamp,
                                   color_b, color_g, color_r)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (plate_number, event_type, camera_id, now, b, g, r))

            conn.commit()

        return self.get_vehicle(plate_number)

    def get_vehicle(self, plate_number: str) -> Optional[Dict]:
        """Get vehicle record by plate number."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM vehicles WHERE plate_number = ?", (plate_number,))
            row = cursor.fetchone()

        if not row:
            return None

        return {
            "id": row[0],
            "plate_number": row[1],
            "color": (row[2], row[3], row[4]),
            "first_seen_at": row[5],
            "last_seen_at": row[6],
            "last_seen_camera": row[7],
            "entry_count": row[8],
            "exit_count": row[9],
            "metadata": json.loads(row[10]) if row[10] else {},
        }

    def get_recent_vehicles(self, camera_id: int, hours: int = 1, limit: int = 100) -> List[Dict]:
        """Get recently seen vehicles from a specific camera."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM vehicles
                WHERE last_seen_camera = ? AND datetime(last_seen_at) > datetime('now', '-' || ? || ' hours')
                ORDER BY last_seen_at DESC
                LIMIT ?
            """, (camera_id, hours, limit))

            rows = cursor.fetchall()

        return [
            {
                "plate_number": r["plate_number"],
                "color": (r["color_b"], r["color_g"], r["color_r"]),
                "last_seen_at": r["last_seen_at"],
                "entry_count": r["entry_count"],
                "exit_count": r["exit_count"],
            }
            for r in rows
        ]

    def get_active_vehicles(self) -> List[Dict]:
        """Get all vehicles with entry_count > exit_count (currently in zone)."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()

            cursor.execute("""
                SELECT * FROM vehicles
                WHERE entry_count > exit_count
                ORDER BY last_seen_at DESC
            """)

            rows = cursor.fetchall()

        return [
            {
                "plate_number": r["plate_number"],
                "color": (r["color_b"], r["color_g"], r["color_r"]),
                "first_seen_at": r["first_seen_at"],
                "last_seen_camera": r["last_seen_camera"],
            }
            for r in rows
        ]

    def get_today_summary(self) -> Dict:
        """Get today's traffic summary."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()

            # Total entries
            cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'entry' AND date(timestamp) = date('now')")
            total_entries = cursor.fetchone()[0]

            # Total exits
            cursor.execute("SELECT COUNT(*) FROM events WHERE event_type = 'exit' AND date(timestamp) = date('now')")
            total_exits = cursor.fetchone()[0]

            # Unique vehicles
            cursor.execute("SELECT COUNT(DISTINCT plate_number) FROM events WHERE date(timestamp) = date('now')")
            unique_vehicles = cursor.fetchone()[0]

        return {
            "total_entries": total_entries,
            "total_exits": total_exits,
            "unique_vehicles": unique_vehicles,
            "currently_in_zone": total_entries - total_exits,
        }

    def cleanup_old_events(self, days: int = 30):
        """Remove events older than N days."""
        with sqlite3.connect(self.db_path) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                DELETE FROM events
                WHERE datetime(timestamp) < datetime('now', '-' || ? || ' days')
            """, (days,))
            conn.commit()
