from __future__ import annotations

import base64
import hashlib
import json
import os
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

QR_DATA_CODEWORDS = {
    1: 19,
    2: 34,
    3: 55,
    4: 80,
    5: 108,
}
QR_ECC_CODEWORDS = {
    1: 7,
    2: 10,
    3: 15,
    4: 20,
    5: 26,
}


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
    user_columns = table_columns(connection, "USER")
    if "CreatedAt" not in user_columns:
        connection.execute("ALTER TABLE USER ADD COLUMN CreatedAt TEXT")
        connection.execute("UPDATE USER SET CreatedAt = CURRENT_TIMESTAMP WHERE CreatedAt IS NULL")

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


def qr_compact_payload(payload: dict) -> str:
    compact = {
        "o": payload.get("orderId"),
        "t": payload.get("ticketIds", []),
        "e": payload.get("event"),
        "d": payload.get("date"),
        "n": payload.get("guestCount"),
    }
    return json.dumps(compact, separators=(",", ":"), sort_keys=True)


def gf_multiply(left: int, right: int) -> int:
    result = 0
    while right:
        if right & 1:
            result ^= left
        left <<= 1
        if left & 0x100:
            left ^= 0x11D
        right >>= 1
    return result


def gf_pow(value: int, power: int) -> int:
    result = 1
    for _ in range(power):
        result = gf_multiply(result, value)
    return result


def rs_generator(degree: int) -> list[int]:
    coefficients = [1]
    for i in range(degree):
        next_coefficients = [0] * (len(coefficients) + 1)
        root = gf_pow(2, i)
        for index, coefficient in enumerate(coefficients):
            next_coefficients[index] ^= gf_multiply(coefficient, root)
            next_coefficients[index + 1] ^= coefficient
        coefficients = next_coefficients
    return coefficients[1:]


def rs_remainder(data: list[int], degree: int) -> list[int]:
    generator = rs_generator(degree)
    result = [0] * degree
    for value in data:
        factor = value ^ result.pop(0)
        result.append(0)
        for index, coefficient in enumerate(generator):
            result[index] ^= gf_multiply(coefficient, factor)
    return result


def append_bits(bits: list[int], value: int, length: int) -> None:
    for shift in range(length - 1, -1, -1):
        bits.append((value >> shift) & 1)


def qr_format_bits(mask: int) -> int:
    data = (1 << 3) | mask
    value = data << 10
    generator = 0x537
    for shift in range(14, 9, -1):
        if (value >> shift) & 1:
            value ^= generator << (shift - 10)
    return ((data << 10) | value) ^ 0x5412


def make_svg_qr(payload_text: str) -> str | None:
    data = payload_text.encode("utf-8")
    version = next(
        (
            candidate
            for candidate, capacity in QR_DATA_CODEWORDS.items()
            if len(data) <= capacity - 2
        ),
        None,
    )
    if not version:
        return None

    data_codewords = QR_DATA_CODEWORDS[version]
    ecc_codewords = QR_ECC_CODEWORDS[version]
    bits: list[int] = []
    append_bits(bits, 0b0100, 4)
    append_bits(bits, len(data), 8)
    for byte in data:
        append_bits(bits, byte, 8)
    append_bits(bits, 0, min(4, data_codewords * 8 - len(bits)))
    while len(bits) % 8:
        bits.append(0)

    codewords = [
        sum(bits[index + shift] << (7 - shift) for shift in range(8))
        for index in range(0, len(bits), 8)
    ]
    pad = 0xEC
    while len(codewords) < data_codewords:
        codewords.append(pad)
        pad = 0x11 if pad == 0xEC else 0xEC

    codewords.extend(rs_remainder(codewords, ecc_codewords))
    size = version * 4 + 17
    modules = [[False] * size for _ in range(size)]
    reserved = [[False] * size for _ in range(size)]

    def set_module(row: int, column: int, value: bool, is_reserved: bool = True) -> None:
        if 0 <= row < size and 0 <= column < size:
            modules[row][column] = value
            if is_reserved:
                reserved[row][column] = True

    def draw_finder(row: int, column: int) -> None:
        for y in range(-1, 8):
            for x in range(-1, 8):
                distance = max(abs(x - 3), abs(y - 3))
                set_module(row + y, column + x, distance in (0, 1, 3))

    draw_finder(0, 0)
    draw_finder(0, size - 7)
    draw_finder(size - 7, 0)

    for index in range(8, size - 8):
        value = index % 2 == 0
        set_module(6, index, value)
        set_module(index, 6, value)

    if version >= 2:
        alignment = 4 * version + 10
        for y in range(-2, 3):
            for x in range(-2, 3):
                distance = max(abs(x), abs(y))
                set_module(alignment + y, alignment + x, distance != 1)

    set_module(size - 8, 8, True)

    data_bits: list[int] = []
    for codeword in codewords:
        append_bits(data_bits, codeword, 8)

    bit_index = 0
    column = size - 1
    upward = True
    while column > 0:
        if column == 6:
            column -= 1
        rows = range(size - 1, -1, -1) if upward else range(size)
        for row in rows:
            for offset in range(2):
                current_column = column - offset
                if reserved[row][current_column]:
                    continue
                bit = data_bits[bit_index] if bit_index < len(data_bits) else 0
                if (row + current_column) % 2 == 0:
                    bit ^= 1
                set_module(row, current_column, bit == 1, False)
                bit_index += 1
        upward = not upward
        column -= 2

    format_bits = qr_format_bits(0)
    for index in range(15):
        value = ((format_bits >> index) & 1) == 1
        if index < 6:
            set_module(8, index, value)
        elif index == 6:
            set_module(8, 7, value)
        elif index == 7:
            set_module(8, 8, value)
        elif index == 8:
            set_module(7, 8, value)
        else:
            set_module(14 - index, 8, value)

        if index < 8:
            set_module(size - 1 - index, 8, value)
        else:
            set_module(8, size - 15 + index, value)

    scale = 8
    quiet = 4
    view_size = (size + quiet * 2) * scale
    squares = []
    for row in range(size):
        for column in range(size):
            if modules[row][column]:
                squares.append(
                    f'<rect x="{(column + quiet) * scale}" y="{(row + quiet) * scale}" width="{scale}" height="{scale}"/>'
                )
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {view_size} {view_size}" '
        f'shape-rendering="crispEdges"><rect width="100%" height="100%" fill="#fff"/>'
        f'<g fill="#000">{"".join(squares)}</g></svg>'
    )


def public_user(row: sqlite3.Row) -> dict:
    return {
        "id": row["UserID"],
        "username": row["Username"],
        "email": row["Email"],
        "createdAt": row["CreatedAt"],
    }


def user_reservations(connection: sqlite3.Connection, user_id: int) -> list[dict]:
    rows = connection.execute(
        """
        SELECT
            ord.OrderID,
            ord.OrderDate,
            ord.EventDate,
            ord.TotalPrice,
            ord.Status,
            e.Name AS Event,
            v.Name AS Venue,
            v.Location,
            COUNT(t.TicketID) AS TicketCount
        FROM "ORDER" ord
        JOIN TICKET t ON t.OrderID = ord.OrderID
        JOIN EVENT e ON e.EventID = t.EventID
        JOIN VENUE v ON v.VenueID = e.VenueID
        WHERE ord.UserID = ?
        GROUP BY ord.OrderID
        ORDER BY ord.OrderID DESC
        """,
        (user_id,),
    )
    return [
        {
            "id": row["OrderID"],
            "event": row["Event"],
            "venue": row["Venue"],
            "location": row["Location"],
            "eventDate": row["EventDate"],
            "orderDate": row["OrderDate"],
            "total": row["TotalPrice"],
            "status": row["Status"],
            "tickets": row["TicketCount"],
        }
        for row in rows
    ]


def ticket_details_for_order(
    connection: sqlite3.Connection, user_id: int, order_id: int
) -> dict | None:
    order = connection.execute(
        """
        SELECT
            ord.OrderID,
            ord.OrderDate,
            ord.EventDate,
            ord.TotalPrice,
            ord.Status,
            u.UserID,
            u.Username,
            e.EventID,
            e.Name AS Event,
            v.Name AS Venue,
            v.Location,
            p.Method AS PaymentMethod
        FROM "ORDER" ord
        LEFT JOIN USER u ON u.UserID = ord.UserID
        JOIN TICKET t ON t.OrderID = ord.OrderID
        JOIN EVENT e ON e.EventID = t.EventID
        JOIN VENUE v ON v.VenueID = e.VenueID
        LEFT JOIN PAYMENT p ON p.OrderID = ord.OrderID
        WHERE ord.UserID = ? AND ord.OrderID = ?
        GROUP BY ord.OrderID
        """,
        (user_id, order_id),
    ).fetchone()

    if not order:
        return None

    ticket_rows = connection.execute(
        """
        SELECT TicketID, Price
        FROM TICKET
        WHERE OrderID = ?
        ORDER BY TicketID
        """,
        (order_id,),
    ).fetchall()
    ticket_ids = [row["TicketID"] for row in ticket_rows]
    subtotal = sum(float(row["Price"]) for row in ticket_rows)
    total = float(order["TotalPrice"] or 0)
    taxes = round(total - subtotal, 2)
    payload = {
        "type": "TixlyTicket",
        "orderId": order["OrderID"],
        "ticketIds": ticket_ids,
        "event": order["Event"],
        "venue": order["Venue"],
        "location": order["Location"],
        "date": order["EventDate"],
        "guestCount": len(ticket_ids),
        "buyerUserId": order["UserID"],
        "paymentMethod": order["PaymentMethod"] or "Card",
        "subtotal": subtotal,
        "taxes": taxes,
        "total": total,
    }

    return {
        "ticket": {
            "ticketId": ticket_ids[0] if ticket_ids else order["OrderID"],
            "ticketIds": ticket_ids,
            "orderId": order["OrderID"],
            "eventName": order["Event"],
            "venue": order["Venue"],
            "location": order["Location"],
            "eventDate": order["EventDate"],
            "orderDate": order["OrderDate"],
            "guestCount": len(ticket_ids),
            "holder": order["Username"],
            "status": order["Status"],
            "subtotal": subtotal,
            "taxes": taxes,
            "total": total,
            "paymentMethod": order["PaymentMethod"] or "Card",
            "qrPayload": payload,
            "qrDataUrl": make_qr_data_url(payload),
        }
    }


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


def organizer_event_analytics(
    connection: sqlite3.Connection, organizer_id: int, event_id: int
) -> dict | None:
    event = connection.execute(
        """
        SELECT
            e.EventID,
            e.Name,
            e.Capacity,
            e.Category,
            e.Date,
            e.StartTime,
            v.Name AS Venue,
            v.Location
        FROM EVENT e
        JOIN VENUE v ON v.VenueID = e.VenueID
        WHERE e.EventID = ? AND e.OrganizerID = ?
        """,
        (event_id, organizer_id),
    ).fetchone()

    if not event:
        return None

    totals = connection.execute(
        """
        WITH event_orders AS (
            SELECT
                ord.OrderID,
                ord.TotalPrice,
                COUNT(t.TicketID) AS TicketsSold,
                SUM(t.Price) AS TicketRevenue
            FROM "ORDER" ord
            JOIN TICKET t ON t.OrderID = ord.OrderID
            WHERE t.EventID = ?
            GROUP BY ord.OrderID
        )
        SELECT
            COALESCE(SUM(TicketsSold), 0) AS TicketsSold,
            COUNT(OrderID) AS Orders,
            COALESCE(SUM(TicketRevenue), 0) AS TicketRevenue,
            COALESCE(SUM(TotalPrice), 0) AS PaymentRevenue
        FROM event_orders
        """,
        (event_id,),
    ).fetchone()

    date_rows = connection.execute(
        """
        SELECT
            ord.EventDate,
            COUNT(t.TicketID) AS TicketsSold,
            COUNT(DISTINCT ord.OrderID) AS Orders,
            COALESCE(SUM(t.Price), 0) AS Revenue
        FROM TICKET t
        JOIN "ORDER" ord ON ord.OrderID = t.OrderID
        WHERE t.EventID = ?
        GROUP BY ord.EventDate
        ORDER BY ord.EventDate
        """,
        (event_id,),
    ).fetchall()

    recent_rows = connection.execute(
        """
        SELECT
            ord.OrderID,
            ord.EventDate,
            ord.TotalPrice,
            ord.Status,
            u.Username,
            COUNT(t.TicketID) AS Tickets
        FROM "ORDER" ord
        LEFT JOIN USER u ON u.UserID = ord.UserID
        JOIN TICKET t ON t.OrderID = ord.OrderID
        WHERE t.EventID = ?
        GROUP BY ord.OrderID
        ORDER BY ord.OrderID DESC
        LIMIT 8
        """,
        (event_id,),
    ).fetchall()

    tickets_sold = totals["TicketsSold"] or 0
    orders = totals["Orders"] or 0
    capacity = event["Capacity"] or 0
    return {
        "event": {
            "id": event["EventID"],
            "name": event["Name"],
            "category": event["Category"],
            "venue": event["Venue"],
            "location": event["Location"],
            "date": event["Date"],
            "startTime": event["StartTime"],
            "capacity": capacity,
        },
        "summary": {
            "ticketsSold": tickets_sold,
            "orders": orders,
            "remaining": max(capacity - tickets_sold, 0),
            "sellThrough": round((tickets_sold / capacity) * 100, 1) if capacity else 0,
            "ticketRevenue": float(totals["TicketRevenue"] or 0),
            "paymentRevenue": float(totals["PaymentRevenue"] or 0),
            "averageOrder": round(float(totals["PaymentRevenue"] or 0) / orders, 2) if orders else 0,
        },
        "byDate": [
            {
                "date": row["EventDate"] or "Unassigned",
                "ticketsSold": row["TicketsSold"],
                "orders": row["Orders"],
                "revenue": float(row["Revenue"] or 0),
            }
            for row in date_rows
        ],
        "recentOrders": [
            {
                "id": row["OrderID"],
                "buyer": row["Username"] or "Guest account",
                "eventDate": row["EventDate"],
                "tickets": row["Tickets"],
                "total": float(row["TotalPrice"] or 0),
                "status": row["Status"],
            }
            for row in recent_rows
        ],
    }


def make_qr_data_url(payload: dict) -> str | None:
    qr_payload = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    try:
        cache_path = ROOT / "data" / "swift-module-cache"
        cache_path.mkdir(parents=True, exist_ok=True)
        environment = os.environ.copy()
        environment["CLANG_MODULE_CACHE_PATH"] = str(cache_path)
        result = subprocess.run(
            ["swift", str(QR_SCRIPT_PATH), qr_payload],
            check=True,
            capture_output=True,
            text=True,
            timeout=12,
            env=environment,
        )
        encoded = result.stdout.strip()
        if encoded:
            return f"data:image/png;base64,{encoded}"
    except Exception:
        pass

    svg = make_svg_qr(qr_payload) or make_svg_qr(qr_compact_payload(payload))
    if svg:
        encoded_svg = base64.b64encode(svg.encode("utf-8")).decode("ascii")
        return f"data:image/svg+xml;base64,{encoded_svg}"
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

                if len(parts) == 6 and parts[3] == "events" and parts[5] == "analytics":
                    try:
                        event_id = int(parts[4])
                    except ValueError:
                        self.send_json({"error": "Invalid event id."}, HTTPStatus.BAD_REQUEST)
                        return

                    analytics = organizer_event_analytics(connection, organizer_id, event_id)
                    if not analytics:
                        self.send_json({"error": "Event not found for this organizer."}, HTTPStatus.NOT_FOUND)
                        return
                    self.send_json({"analytics": analytics})
                    return

            self.send_json({"organizer": public_organizer(organizer)})
            return

        if parsed.path.startswith("/api/users/"):
            parts = parsed.path.strip("/").split("/")
            try:
                user_id = int(parts[2])
            except ValueError:
                self.send_json({"error": "Invalid user id."}, HTTPStatus.BAD_REQUEST)
                return

            with connect_db() as connection:
                user = connection.execute("SELECT * FROM USER WHERE UserID = ?", (user_id,)).fetchone()

                if not user:
                    self.send_json({"error": "User session is no longer valid."}, HTTPStatus.NOT_FOUND)
                    return

                if len(parts) == 5 and parts[3] == "reservations":
                    try:
                        order_id = int(parts[4])
                    except ValueError:
                        self.send_json({"error": "Invalid reservation id."}, HTTPStatus.BAD_REQUEST)
                        return

                    details = ticket_details_for_order(connection, user_id, order_id)
                    if not details:
                        self.send_json({"error": "Reservation not found."}, HTTPStatus.NOT_FOUND)
                        return
                    self.send_json(details)
                    return

                self.send_json({"user": public_user(user), "reservations": user_reservations(connection, user_id)})
            return
        
        # if parsed.path.startswith

        super().do_GET()

    def do_POST(self) -> None:
        routes = {
            "/api/signup": self.handle_signup,
            "/api/login": self.handle_login,
            "/api/users/update": self.handle_user_update,
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

    def handle_user_update(self, payload: dict) -> None:
        user_id = int(payload.get("userId") or 0)
        username = str(payload.get("username") or "").strip()
        password = str(payload.get("password") or "")

        if user_id <= 0:
            raise ValueError("Please log in again before editing your profile.")
        if not username:
            raise ValueError("Enter your name.")
        if password and len(password) < 4:
            raise ValueError("Password must be at least 4 characters.")

        with connect_db() as connection:
            user = connection.execute("SELECT * FROM USER WHERE UserID = ?", (user_id,)).fetchone()
            if not user:
                self.send_json({"error": "User session is no longer valid."}, HTTPStatus.UNAUTHORIZED)
                return

            if password:
                salt, digest = hash_password(password)
                connection.execute(
                    """
                    UPDATE USER
                    SET Username = ?,
                        PasswordSalt = ?,
                        PasswordHash = ?
                    WHERE UserID = ?
                    """,
                    (username, salt, digest, user_id),
                )
            else:
                connection.execute(
                    """
                    UPDATE USER
                    SET Username = ?
                    WHERE UserID = ?
                    """,
                    (username, user_id),
                )

            updated_user = connection.execute("SELECT * FROM USER WHERE UserID = ?", (user_id,)).fetchone()
            self.send_json(
                {
                    "user": public_user(updated_user),
                    "reservations": user_reservations(connection, user_id),
                }
            )

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
