from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3
import subprocess
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


ROOT = Path(__file__).resolve().parent
DB_PATH = ROOT / "data" / "tixly.db"
SCHEMA_PATH = ROOT / "schema.sql"
QR_SCRIPT_PATH = ROOT / "tools" / "make_qr.swift"


def connect_db() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def init_db() -> None:
    with connect_db() as connection:
        connection.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))
        migrate_db(connection)


def table_columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {row["name"] for row in connection.execute(f"PRAGMA table_info('{table}')")}


def migrate_db(connection: sqlite3.Connection) -> None:
    organizer_columns = table_columns(connection, "ORGANIZER")
    if "PasswordSalt" not in organizer_columns:
        connection.execute("ALTER TABLE ORGANIZER ADD COLUMN PasswordSalt TEXT")
    if "PasswordHash" not in organizer_columns:
        connection.execute("ALTER TABLE ORGANIZER ADD COLUMN PasswordHash TEXT")
    if "CreatedAt" not in organizer_columns:
        connection.execute("ALTER TABLE ORGANIZER ADD COLUMN CreatedAt TEXT")
        connection.execute("UPDATE ORGANIZER SET CreatedAt = CURRENT_TIMESTAMP WHERE CreatedAt IS NULL")

    venue_columns = table_columns(connection, "VENUE")
    if "OrganizerID" not in venue_columns:
        connection.execute("ALTER TABLE VENUE ADD COLUMN OrganizerID INTEGER REFERENCES ORGANIZER(OrganizerID)")

    order_columns = table_columns(connection, "ORDER")
    if "EventDate" not in order_columns:
        connection.execute('ALTER TABLE "ORDER" ADD COLUMN EventDate TEXT')

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS EVENT_DATE (
          EventDateID INTEGER PRIMARY KEY AUTOINCREMENT,
          EventID INTEGER NOT NULL,
          Date TEXT NOT NULL,
          FOREIGN KEY (EventID) REFERENCES EVENT (EventID) ON DELETE CASCADE,
          UNIQUE (EventID, Date)
        )
        """
    )
    connection.execute("INSERT OR IGNORE INTO EVENT_DATE (EventID, Date) SELECT EventID, Date FROM EVENT")


def hash_password(password: str, salt: str | None = None) -> tuple[str, str]:
    salt = salt or secrets.token_hex(16)
    digest = hashlib.sha256(f"{salt}:{password}".encode("utf-8")).hexdigest()
    return salt, digest


def public_user(row: sqlite3.Row) -> dict:
    return {"id": row["UserID"], "username": row["Username"], "email": row["Email"]}


def public_organizer(row: sqlite3.Row) -> dict:
    return {"id": row["OrganizerID"], "name": row["Name"], "email": row["Email"]}


def event_from_row(row: sqlite3.Row) -> dict:
    sold = row["TicketsSold"] or 0
    dates = row["AvailableDates"].split(",") if row["AvailableDates"] else [row["Date"]]
    first_date = dates[0]
    return {
        "id": row["EventID"],
        "name": row["Event"],
        "type": row["Category"],
        "date": datetime.strptime(first_date, "%Y-%m-%d").strftime("%b %d"),
        "dateValue": first_date,
        "availableDates": dates,
        "startTime": row["StartTime"],
        "venueId": row["VenueID"],
        "location": row["Location"],
        "venue": row["Venue"],
        "organizer": row["Organizer"],
        "price": row["Price"],
        "rating": row["Rating"],
        "sold": sold,
        "capacity": row["Capacity"],
        "image": row["ImageUrl"],
        "imagePosition": row["ImagePosition"],
    }


def fetch_events(filters: dict[str, str] | None = None) -> list[dict]:
    filters = filters or {}
    where = []
    params: list[object] = []

    if filters.get("category") and filters["category"] != "All":
        where.append("e.Category = ?")
        params.append(filters["category"])

    if filters.get("location"):
        where.append("v.Location LIKE ?")
        params.append(f"%{filters['location']}%")

    if filters.get("event"):
        where.append("(e.Name LIKE ? OR e.Category LIKE ? OR v.Name LIKE ? OR o.Name LIKE ?)")
        term = f"%{filters['event']}%"
        params.extend([term, term, term, term])
    
    if filters.get("organizerId"):
        where.append("e.organizerID = ?")
        params.append(int(filters["organizerId"]))

    where_sql = f"WHERE {' AND '.join(where)}" if where else ""
    query = f"""
        SELECT
            e.EventID,
            e.Name AS Event,
            e.Date,
            e.StartTime,
            e.VenueID,
            e.Category,
            e.Capacity,
            e.ImageUrl,
            e.ImagePosition,
            e.Rating,
            v.Name AS Venue,
            v.Location,
            o.Name AS Organizer,
            COALESCE(MIN(CASE WHEN t.OrderID IS NULL THEN t.Price END), MIN(t.Price), 0) AS Price,
            SUM(CASE WHEN t.OrderID IS NOT NULL THEN 1 ELSE 0 END) AS TicketsSold,
            GROUP_CONCAT(DISTINCT ed.Date) AS AvailableDates
        FROM EVENT e
        JOIN VENUE v ON e.VenueID = v.VenueID
        JOIN ORGANIZER o ON e.OrganizerID = o.OrganizerID
        LEFT JOIN TICKET t ON t.EventID = e.EventID
        LEFT JOIN EVENT_DATE ed ON ed.EventID = e.EventID
        {where_sql}
        GROUP BY e.EventID
        ORDER BY MIN(ed.Date), e.Date;
    """

    with connect_db() as connection:
        return [event_from_row(row) for row in connection.execute(query, params)]


def make_qr_data_url(payload: dict) -> str | None:
    try:
        qr_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        result = subprocess.run(
            ["swift", str(QR_SCRIPT_PATH), qr_payload],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
        )
        encoded = result.stdout.strip()
        if encoded:
            return f"data:image/png;base64,{encoded}"
    except Exception:
        return None
    return None


class TixlyHandler(SimpleHTTPRequestHandler):
    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/api/events":
            values = parse_qs(parsed.query)
            filters = {key: item[0].strip() for key, item in values.items() if item and item[0].strip()}
            self.send_json({"events": fetch_events(filters)})
            return

        if parsed.path.startswith("/api/organizers/"):
            parts = parsed.path.strip("/").split("/")
            try:
                organizer_id = int(parts[2])
            except (IndexError, ValueError):
                self.send_json({"error": "Invalid organizer id."}, HTTPStatus.BAD_REQUEST)
                return

            with connect_db() as connection:
                organizer = connection.execute(
                    "SELECT * FROM ORGANIZER WHERE OrganizerID = ?", (organizer_id,)
                ).fetchone()

                if not organizer or not organizer["PasswordHash"]:
                    self.send_json({"error": "Organizer session is no longer valid."}, HTTPStatus.NOT_FOUND)
                    return

                if len(parts) == 4 and parts[3] == "venues":
                    venues = [
                        dict(row)
                        for row in connection.execute(
                            """
                            SELECT VenueID AS id, Name AS name, Location AS location, Capacity AS capacity
                            FROM VENUE
                            WHERE OrganizerID = ?
                            ORDER BY Name
                            """,
                            (organizer_id,),
                        )
                    ]
                    self.send_json({"venues": venues})
                    return
                
                if len(parts) == 4 and parts[3] == "events":
                    self.send_json({"events": fetch_events({"organizerId": str(organizer_id)})})
                    return

            self.send_json({"organizer": public_organizer(organizer)})
            return

        if parsed.path.startswith("/api/users/"):
            try:
                user_id = int(parsed.path.rsplit("/", 1)[1])
            except ValueError:
                self.send_json({"error": "Invalid user id."}, HTTPStatus.BAD_REQUEST)
                return

            with connect_db() as connection:
                user = connection.execute("SELECT * FROM USER WHERE UserID = ?", (user_id,)).fetchone()

            if not user:
                self.send_json({"error": "User session is no longer valid."}, HTTPStatus.NOT_FOUND)
                return

            self.send_json({"user": public_user(user)})
            return
        
        # if parsed.path.startswith

        super().do_GET()

    def do_POST(self) -> None:
        routes = {
            "/api/signup": self.handle_signup,
            "/api/login": self.handle_login,
            "/api/reserve": self.handle_reserve,
            "/api/organizer/signup": self.handle_organizer_signup,
            "/api/organizer/login": self.handle_organizer_login,
            "/api/organizer/venues": self.handle_organizer_venue,
            "/api/organizer/events": self.handle_organizer_event,
            "/api/organizer/events/update": self.handle_organizer_event_update,
            "/api/organizer/events/delete": self.handle_organizer_event_delete,
        }
        handler = routes.get(self.path)
        if not handler:
            self.send_json({"error": "Not found."}, HTTPStatus.NOT_FOUND)
            return

        try:
            handler(self.read_json())
        except ValueError as error:
            self.send_json({"error": str(error)}, HTTPStatus.BAD_REQUEST)
        except sqlite3.IntegrityError as error:
            self.send_json({"error": f"Database constraint failed: {error}"}, HTTPStatus.CONFLICT)
        except Exception as error:
            self.send_json({"error": f"Server error: {error}"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def read_json(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        if length <= 0:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def send_json(self, payload: dict, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def handle_signup(self, payload: dict) -> None:
        username = str(payload.get("username") or "").strip()
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")

        if not username:
            raise ValueError("Enter your name to sign up.")
        if "@" not in email:
            raise ValueError("Enter a valid email.")
        if len(password) < 4:
            raise ValueError("Password must be at least 4 characters.")

        salt, digest = hash_password(password)
        with connect_db() as connection:
            existing = connection.execute("SELECT UserID FROM USER WHERE Email = ?", (email,)).fetchone()
            if existing:
                self.send_json({"error": "That email already has an account."}, HTTPStatus.CONFLICT)
                return

            cursor = connection.execute(
                """
                INSERT INTO USER (Username, Email, PasswordSalt, PasswordHash)
                VALUES (?, ?, ?, ?)
                """,
                (username, email, salt, digest),
            )
            user = connection.execute("SELECT * FROM USER WHERE UserID = ?", (cursor.lastrowid,)).fetchone()

        self.send_json({"user": public_user(user)})

    def handle_login(self, payload: dict) -> None:
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")

        with connect_db() as connection:
            user = connection.execute("SELECT * FROM USER WHERE Email = ?", (email,)).fetchone()

        if not user:
            self.send_json({"error": "No account found for that email."}, HTTPStatus.UNAUTHORIZED)
            return

        _, digest = hash_password(password, user["PasswordSalt"])
        if not secrets.compare_digest(digest, user["PasswordHash"]):
            self.send_json({"error": "Incorrect password."}, HTTPStatus.UNAUTHORIZED)
            return

        self.send_json({"user": public_user(user)})

    def handle_organizer_signup(self, payload: dict) -> None:
        name = str(payload.get("name") or "").strip()
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")

        if not name:
            raise ValueError("Enter an organizer name.")
        if "@" not in email:
            raise ValueError("Enter a valid organizer email.")
        if len(password) < 4:
            raise ValueError("Password must be at least 4 characters.")

        salt, digest = hash_password(password)
        with connect_db() as connection:
            existing = connection.execute("SELECT OrganizerID FROM ORGANIZER WHERE Email = ?", (email,)).fetchone()
            if existing:
                self.send_json({"error": "That organizer email already exists."}, HTTPStatus.CONFLICT)
                return

            cursor = connection.execute(
                """
                INSERT INTO ORGANIZER (Name, Email, PasswordSalt, PasswordHash)
                VALUES (?, ?, ?, ?)
                """,
                (name, email, salt, digest),
            )
            organizer = connection.execute(
                "SELECT * FROM ORGANIZER WHERE OrganizerID = ?", (cursor.lastrowid,)
            ).fetchone()

        self.send_json({"organizer": public_organizer(organizer)})

    def handle_organizer_login(self, payload: dict) -> None:
        email = str(payload.get("email") or "").strip().lower()
        password = str(payload.get("password") or "")

        with connect_db() as connection:
            organizer = connection.execute("SELECT * FROM ORGANIZER WHERE Email = ?", (email,)).fetchone()

        if not organizer or not organizer["PasswordHash"]:
            self.send_json({"error": "No organizer account found for that email."}, HTTPStatus.UNAUTHORIZED)
            return

        _, digest = hash_password(password, organizer["PasswordSalt"])
        if not secrets.compare_digest(digest, organizer["PasswordHash"]):
            self.send_json({"error": "Incorrect password."}, HTTPStatus.UNAUTHORIZED)
            return

        self.send_json({"organizer": public_organizer(organizer)})

    def organizer_from_payload(self, connection: sqlite3.Connection, payload: dict) -> sqlite3.Row:
        organizer_id = int(payload.get("organizerId") or 0)
        organizer = connection.execute(
            "SELECT * FROM ORGANIZER WHERE OrganizerID = ?", (organizer_id,)
        ).fetchone()
        if not organizer or not organizer["PasswordHash"]:
            raise ValueError("Please log in as an organizer first.")
        return organizer

    def handle_organizer_venue(self, payload: dict) -> None:
        name = str(payload.get("name") or "").strip()
        location = str(payload.get("location") or "").strip()
        capacity = int(payload.get("capacity") or 0)

        if not name:
            raise ValueError("Enter a venue name.")
        if not location:
            raise ValueError("Enter a venue location.")
        if capacity <= 0:
            raise ValueError("Venue capacity must be greater than zero.")

        with connect_db() as connection:
            organizer = self.organizer_from_payload(connection, payload)
            cursor = connection.execute(
                """
                INSERT INTO VENUE (Name, Location, Capacity, OrganizerID)
                VALUES (?, ?, ?, ?)
                """,
                (name, location, capacity, organizer["OrganizerID"]),
            )
            venue = connection.execute(
                """
                SELECT VenueID AS id, Name AS name, Location AS location, Capacity AS capacity
                FROM VENUE
                WHERE VenueID = ?
                """,
                (cursor.lastrowid,),
            ).fetchone()

        self.send_json({"venue": dict(venue)})

    def handle_organizer_event(self, payload: dict) -> None:
        name = str(payload.get("name") or "").strip()
        category = str(payload.get("category") or "Music").strip()
        venue_id = int(payload.get("venueId") or 0)
        start_time = str(payload.get("startTime") or "").strip()
        dates = [str(date).strip() for date in payload.get("dates", []) if str(date).strip()]
        price = float(payload.get("price") or 0)
        capacity = int(payload.get("capacity") or 0)
        image_url = str(payload.get("imageUrl") or "").strip() or "assets/tixly-hero.png"

        if not name:
            raise ValueError("Enter an event name.")
        if not dates:
            raise ValueError("Add at least one event date.")
        if not start_time:
            raise ValueError("Add an event start time.")
        if price <= 0:
            raise ValueError("Ticket price must be greater than zero.")
        if capacity <= 0:
            raise ValueError("Event capacity must be greater than zero.")

        for date in dates:
            datetime.strptime(date, "%Y-%m-%d")

        with connect_db() as connection:
            organizer = self.organizer_from_payload(connection, payload)
            venue = connection.execute(
                "SELECT * FROM VENUE WHERE VenueID = ? AND OrganizerID = ?",
                (venue_id, organizer["OrganizerID"]),
            ).fetchone()
            if not venue:
                raise ValueError("Choose one of your registered venues.")

            cursor = connection.execute(
                """
                INSERT INTO EVENT
                    (Name, Date, StartTime, VenueID, OrganizerID, Capacity, Category, ImageUrl, ImagePosition, Rating)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, '50% 50%', 4.8)
                """,
                (name, dates[0], start_time, venue_id, organizer["OrganizerID"], capacity, category, image_url),
            )
            event_id = cursor.lastrowid
            for date in dates:
                connection.execute("INSERT INTO EVENT_DATE (EventID, Date) VALUES (?, ?)", (event_id, date))
            connection.execute(
                """
                INSERT INTO TICKET (EventID, OrderID, Type, Price)
                VALUES (?, NULL, 'General Admission', ?)
                """,
                (event_id, price),
            )

        event = next(item for item in fetch_events() if item["id"] == event_id)
        self.send_json({"event": event})

    def handle_organizer_event_update(self, payload: dict) -> None:
        event_id = int(payload.get("eventId") or 0)
        name = str(payload.get("name") or "").strip()
        category = str(payload.get("category") or "Music").strip()
        venue_id = int(payload.get("venueId") or 0)
        start_time = str(payload.get("startTime") or "").strip()
        dates = [str(date).strip() for date in payload.get("dates", []) if str(date).strip()]
        price = float(payload.get("price") or 0)
        capacity = int(payload.get("capacity") or 0)
        image_url = str(payload.get("imageUrl") or "").strip() or "assets/tixly-hero.png"

        if event_id <= 0:
            raise ValueError("Invalid event id.")
        if not name:
            raise ValueError("Enter an event name.")
        if not dates:
            raise ValueError("Add at least one event date.")
        if not start_time:
            raise ValueError("Add an event start time.")
        if price <= 0:
            raise ValueError("Ticket price must be greater than zero.")
        if capacity <= 0:
            raise ValueError("Event capacity must be greater than zero.")

        for date in dates:
            datetime.strptime(date, "%Y-%m-%d")

        with connect_db() as connection:
            organizer = self.organizer_from_payload(connection, payload)

            event = connection.execute(
                """
                SELECT EventID
                FROM EVENT
                WHERE EventID = ? AND OrganizerID = ?
                """,
                (event_id, organizer["OrganizerID"]),
            ).fetchone()

            if not event:
                self.send_json(
                    {"error": "Event not found for this organizer."},
                    HTTPStatus.NOT_FOUND,
                )
                return

            venue = connection.execute(
                """
                SELECT VenueID
                FROM VENUE
                WHERE VenueID = ? AND OrganizerID = ?
                """,
                (venue_id, organizer["OrganizerID"]),
            ).fetchone()

            if not venue:
                raise ValueError("Choose one of your registered venues.")

            sold_tickets = connection.execute(
                """
                SELECT COUNT(*) AS Count
                FROM TICKET
                WHERE EventID = ? AND OrderID IS NOT NULL
                """,
                (event_id,),
            ).fetchone()["Count"]

            if sold_tickets > capacity:
                raise ValueError("Capacity cannot be lower than existing reservations.")

            connection.execute(
                """
                UPDATE EVENT
                SET Name = ?,
                    Date = ?,
                    StartTime = ?,
                    VenueID = ?,
                    Capacity = ?,
                    Category = ?,
                    ImageUrl = ?
                WHERE EventID = ? AND OrganizerID = ?
                """,
                (
                    name,
                    dates[0],
                    start_time,
                    venue_id,
                    capacity,
                    category,
                    image_url,
                    event_id,
                    organizer["OrganizerID"],
                ),
            )

            connection.execute("DELETE FROM EVENT_DATE WHERE EventID = ?", (event_id,))

            for date in dates:
                connection.execute(
                    "INSERT INTO EVENT_DATE (EventID, Date) VALUES (?, ?)",
                    (event_id, date),
                )

            connection.execute(
                """
                UPDATE TICKET
                SET Price = ?
                WHERE EventID = ? AND OrderID IS NULL
                """,
                (price, event_id),
            )

            base_ticket = connection.execute(
                """
                SELECT TicketID
                FROM TICKET
                WHERE EventID = ? AND OrderID IS NULL
                LIMIT 1
                """,
                (event_id,),
            ).fetchone()

            if not base_ticket:
                connection.execute(
                    """
                    INSERT INTO TICKET (EventID, OrderID, Type, Price)
                    VALUES (?, NULL, 'General Admission', ?)
                    """,
                    (event_id, price),
                )

        updated_event = next(item for item in fetch_events({"organizerId": str(organizer["OrganizerID"])}) if item["id"] == event_id)
        self.send_json({"event": updated_event})

    def handle_organizer_event_delete(self, payload: dict) -> None:
        event_id = int(payload.get("eventId") or 0)

        if event_id <= 0:
            raise ValueError("Invalid event id.")

        with connect_db() as connection:
            organizer = self.organizer_from_payload(connection, payload)

            event = connection.execute(
                """
                SELECT EventID, Name
                FROM EVENT
                WHERE EventID = ? AND OrganizerID = ?
                """,
                (event_id, organizer["OrganizerID"]),
            ).fetchone()

            if not event:
                self.send_json(
                    {"error": "Event not found for this organizer."},
                    HTTPStatus.NOT_FOUND,
                )
                return

            sold_tickets = connection.execute(
                """
                SELECT COUNT(*) AS Count
                FROM TICKET
                WHERE EventID = ? AND OrderID IS NOT NULL
                """,
                (event_id,),
            ).fetchone()["Count"]

            if sold_tickets > 0:
                self.send_json(
                    {"error": "This event already has reservations, so it cannot be deleted."},
                    HTTPStatus.CONFLICT,
                )
                return

            connection.execute("DELETE FROM MUSIC_EVENT WHERE EventID = ?", (event_id,))
            connection.execute("DELETE FROM SPORTS_EVENT WHERE EventID = ?", (event_id,))
            connection.execute("DELETE FROM CONFERENCE WHERE EventID = ?", (event_id,))
            connection.execute("DELETE FROM TICKET WHERE EventID = ?", (event_id,))
            connection.execute("DELETE FROM EVENT_DATE WHERE EventID = ?", (event_id,))
            connection.execute("DELETE FROM EVENT WHERE EventID = ?", (event_id,))

        self.send_json({"deleted": True, "eventId": event_id})
    
    def handle_reserve(self, payload: dict) -> None:
        user_id = int(payload.get("userId") or 0)
        event_id = int(payload.get("eventId") or 0)
        quantity = int(payload.get("quantity") or 0)
        if quantity < 1 or quantity > 10:
            raise ValueError("Choose between 1 and 10 people.")
        method = str(payload.get("method") or "Card").strip() or "Card"
        event_date = str(payload.get("eventDate") or "").strip()
        today = datetime.now(timezone.utc).date().isoformat()

        with connect_db() as connection:
            user = connection.execute("SELECT UserID FROM USER WHERE UserID = ?", (user_id,)).fetchone()
            if not user:
                self.send_json({"error": "Please sign in again before reserving."}, HTTPStatus.UNAUTHORIZED)
                return

            event = connection.execute(
                """
                SELECT
                    e.EventID,
                    e.Name,
                    e.Capacity,
                    v.Name AS Venue,
                    v.Location,
                    COALESCE(MIN(CASE WHEN t.OrderID IS NULL THEN t.Price END), MIN(t.Price), 0) AS Price,
                    SUM(CASE WHEN t.OrderID IS NOT NULL THEN 1 ELSE 0 END) AS TicketsSold
                FROM EVENT e
                JOIN VENUE v ON v.VenueID = e.VenueID
                LEFT JOIN TICKET t ON t.EventID = e.EventID
                WHERE e.EventID = ?
                GROUP BY e.EventID
                """,
                (event_id,),
            ).fetchone()
            if not event:
                raise ValueError("Unknown event.")
            if not event_date:
                event_date = connection.execute(
                    "SELECT Date FROM EVENT_DATE WHERE EventID = ? ORDER BY Date LIMIT 1", (event_id,)
                ).fetchone()["Date"]
            available_date = connection.execute(
                "SELECT Date FROM EVENT_DATE WHERE EventID = ? AND Date = ?", (event_id, event_date)
            ).fetchone()
            if not available_date:
                raise ValueError("Choose an available event date.")
            sold = event["TicketsSold"] or 0
            if sold + quantity > event["Capacity"]:
                raise ValueError("Not enough tickets are available for that event.")

            price = float(event["Price"])
            subtotal = price * quantity
            taxes = round(subtotal * 0.1, 2)
            total = subtotal + taxes
            cursor = connection.execute(
                """
                INSERT INTO "ORDER" (UserID, OrderDate, TotalPrice, Status, EventDate)
                VALUES (?, ?, ?, 'Confirmed', ?)
                """,
                (user_id, today, total, event_date),
            )
            order_id = cursor.lastrowid

            ticket_ids = []
            for _ in range(quantity):
                ticket = connection.execute(
                    """
                    INSERT INTO TICKET (EventID, OrderID, Type, Price)
                    VALUES (?, ?, 'General Admission', ?)
                    """,
                    (event_id, order_id, price),
                )
                ticket_ids.append(ticket.lastrowid)

            connection.execute(
                """
                INSERT INTO PAYMENT (OrderID, Method, Amount, PaymentDate)
                VALUES (?, ?, ?, ?)
                """,
                (order_id, method, total, today),
            )

        ticket_payload = {
            "type": "TixlyTicket",
            "orderId": order_id,
            "ticketIds": ticket_ids,
            "event": event["Name"],
            "venue": event["Venue"],
            "location": event["Location"],
            "date": event_date,
            "guestCount": quantity,
            "buyerUserId": user_id,
            "paymentMethod": method,
            "subtotal": subtotal,
            "taxes": taxes,
            "total": total,
        }

        self.send_json(
            {
                "orderId": order_id,
                "ticketIds": ticket_ids,
                "eventName": event["Name"],
                "subtotal": subtotal,
                "taxes": taxes,
                "total": total,
                "guestCount": quantity,
                "qrPayload": ticket_payload,
                "qrDataUrl": make_qr_data_url(ticket_payload),
            }
        )


def main() -> None:
    init_db()
    server = ThreadingHTTPServer(("127.0.0.1", 8000), TixlyHandler)
    print(f"Tixly running at http://localhost:8000/ using {DB_PATH}")
    server.serve_forever()


if __name__ == "__main__":
    main()
