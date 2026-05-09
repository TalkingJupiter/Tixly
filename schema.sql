PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS USER (
  UserID INTEGER PRIMARY KEY AUTOINCREMENT,
  Username TEXT NOT NULL,
  Email TEXT NOT NULL UNIQUE,
  PasswordSalt TEXT NOT NULL,
  PasswordHash TEXT NOT NULL,
  CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS ORGANIZER (
  OrganizerID INTEGER PRIMARY KEY,
  Name TEXT NOT NULL,
  Email TEXT NOT NULL UNIQUE,
  PasswordSalt TEXT,
  PasswordHash TEXT,
  CreatedAt TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS VENUE (
  VenueID INTEGER PRIMARY KEY,
  Name TEXT NOT NULL,
  Location TEXT NOT NULL,
  Capacity INTEGER NOT NULL,
  OrganizerID INTEGER,
  FOREIGN KEY (OrganizerID) REFERENCES ORGANIZER (OrganizerID)
);

CREATE TABLE IF NOT EXISTS EVENT (
  EventID INTEGER PRIMARY KEY,
  Name TEXT NOT NULL,
  Date TEXT NOT NULL,
  StartTime TEXT NOT NULL,
  VenueID INTEGER NOT NULL,
  OrganizerID INTEGER NOT NULL,
  Capacity INTEGER NOT NULL,
  Category TEXT NOT NULL,
  ImageUrl TEXT NOT NULL,
  ImagePosition TEXT NOT NULL DEFAULT '50% 50%',
  Rating REAL NOT NULL DEFAULT 4.8,
  FOREIGN KEY (VenueID) REFERENCES VENUE (VenueID),
  FOREIGN KEY (OrganizerID) REFERENCES ORGANIZER (OrganizerID)
);

CREATE TABLE IF NOT EXISTS EVENT_DATE (
  EventDateID INTEGER PRIMARY KEY AUTOINCREMENT,
  EventID INTEGER NOT NULL,
  Date TEXT NOT NULL,
  FOREIGN KEY (EventID) REFERENCES EVENT (EventID) ON DELETE CASCADE,
  UNIQUE (EventID, Date)
);

CREATE TABLE IF NOT EXISTS MUSIC_EVENT (
  EventID INTEGER PRIMARY KEY,
  Artist TEXT NOT NULL,
  Genre TEXT NOT NULL,
  FOREIGN KEY (EventID) REFERENCES EVENT (EventID)
);

CREATE TABLE IF NOT EXISTS SPORTS_EVENT (
  EventID INTEGER PRIMARY KEY,
  SportTeam TEXT NOT NULL,
  HomeTeam TEXT NOT NULL,
  AwayTeam TEXT NOT NULL,
  FOREIGN KEY (EventID) REFERENCES EVENT (EventID)
);

CREATE TABLE IF NOT EXISTS CONFERENCE (
  EventID INTEGER PRIMARY KEY,
  Topic TEXT NOT NULL,
  Speaker TEXT NOT NULL,
  FOREIGN KEY (EventID) REFERENCES EVENT (EventID)
);

CREATE TABLE IF NOT EXISTS "ORDER" (
  OrderID INTEGER PRIMARY KEY AUTOINCREMENT,
  UserID INTEGER NOT NULL,
  OrderDate TEXT NOT NULL,
  EventDate TEXT,
  TotalPrice REAL NOT NULL,
  Status TEXT NOT NULL,
  FOREIGN KEY (UserID) REFERENCES USER (UserID)
);

CREATE TABLE IF NOT EXISTS TICKET (
  TicketID INTEGER PRIMARY KEY AUTOINCREMENT,
  EventID INTEGER NOT NULL,
  OrderID INTEGER,
  Type TEXT NOT NULL,
  Price REAL NOT NULL,
  FOREIGN KEY (EventID) REFERENCES EVENT (EventID),
  FOREIGN KEY (OrderID) REFERENCES "ORDER" (OrderID)
);

CREATE TABLE IF NOT EXISTS PAYMENT (
  PaymentID INTEGER PRIMARY KEY AUTOINCREMENT,
  OrderID INTEGER NOT NULL,
  Method TEXT NOT NULL,
  Amount REAL NOT NULL,
  PaymentDate TEXT NOT NULL,
  FOREIGN KEY (OrderID) REFERENCES "ORDER" (OrderID)
);

INSERT OR IGNORE INTO ORGANIZER (OrganizerID, Name, Email) VALUES
  (1, 'Pulse Productions', 'hello@pulse.example'),
  (2, 'Lone Star Sports', 'tickets@lonestarsports.example'),
  (3, 'BrightStage', 'events@brightstage.example'),
  (4, 'Night Owl Events', 'crew@nightowl.example'),
  (5, 'Encore Arts', 'boxoffice@encore.example');

INSERT OR IGNORE INTO VENUE (VenueID, Name, Location, Capacity) VALUES
  (1, 'The Ballroom', 'Austin, TX', 1100),
  (2, 'Metro Field', 'Austin, TX', 20500),
  (3, 'Civic Forum', 'Dallas, TX', 1000),
  (4, 'Laugh Hall', 'Houston, TX', 400),
  (5, 'Southtown Stage', 'San Antonio, TX', 700),
  (6, 'Innovation House', 'Austin, TX', 850),
  (7, 'Crescent Theater', 'Fort Worth, TX', 900),
  (8, 'Downtown Arena', 'Dallas, TX', 14500);

INSERT OR IGNORE INTO EVENT
  (EventID, Name, Date, StartTime, VenueID, OrganizerID, Capacity, Category, ImageUrl, ImagePosition, Rating)
VALUES
  (1, 'Neon Skyline Live', '2026-05-24', '20:00', 1, 1, 1100, 'Music', 'https://images.unsplash.com/photo-1501386761578-eac5c94b800a?auto=format&fit=crop&w=1100&q=80', '38% 62%', 4.97),
  (2, 'Austin FC Rival Night', '2026-06-02', '19:30', 2, 2, 20500, 'Sports', 'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1100&q=80', '72% 58%', 4.88),
  (3, 'Founders Summit', '2026-06-11', '09:00', 3, 3, 1000, 'Conference', 'https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=1100&q=80', '50% 38%', 4.93),
  (4, 'Moonlight Comedy Club', '2026-06-14', '21:00', 4, 4, 400, 'Comedy', 'https://images.unsplash.com/photo-1527224857830-43a7acc85260?auto=format&fit=crop&w=1100&q=80', '24% 62%', 4.84),
  (5, 'Indie Strings Showcase', '2026-06-18', '20:30', 5, 1, 700, 'Music', 'https://images.unsplash.com/photo-1501386761578-eac5c94b800a?auto=format&fit=crop&w=1100&q=80', '62% 70%', 4.91),
  (6, 'Modern Product Forum', '2026-07-03', '10:00', 6, 3, 850, 'Conference', 'https://images.unsplash.com/photo-1511578314322-379afb476865?auto=format&fit=crop&w=1100&q=80', '46% 28%', 4.79),
  (7, 'Classic Theater Night', '2026-07-08', '19:00', 7, 5, 900, 'Theater', 'https://images.unsplash.com/photo-1503095396549-807759245b35?auto=format&fit=crop&w=1100&q=80', '18% 40%', 4.86),
  (8, 'City Hoops Final', '2026-07-21', '19:00', 8, 2, 14500, 'Sports', 'https://images.unsplash.com/photo-1461896836934-ffe607ba8211?auto=format&fit=crop&w=1100&q=80', '86% 54%', 4.95);

INSERT OR IGNORE INTO MUSIC_EVENT (EventID, Artist, Genre) VALUES
  (1, 'Neon Skyline', 'Electronic'),
  (5, 'Indie Strings Collective', 'Indie');

INSERT OR IGNORE INTO SPORTS_EVENT (EventID, SportTeam, HomeTeam, AwayTeam) VALUES
  (2, 'Austin FC', 'Austin FC', 'Dallas SC'),
  (8, 'City Hoops', 'Dallas City', 'Houston North');

INSERT OR IGNORE INTO CONFERENCE (EventID, Topic, Speaker) VALUES
  (3, 'Startup Leadership', 'Maya Chen'),
  (6, 'Product Strategy', 'Jordan Ellis');

INSERT OR IGNORE INTO TICKET (TicketID, EventID, OrderID, Type, Price) VALUES
  (1, 1, NULL, 'General Admission', 84),
  (2, 2, NULL, 'General Admission', 62),
  (3, 3, NULL, 'General Admission', 145),
  (4, 4, NULL, 'General Admission', 38),
  (5, 5, NULL, 'General Admission', 56),
  (6, 6, NULL, 'General Admission', 118),
  (7, 7, NULL, 'General Admission', 72),
  (8, 8, NULL, 'General Admission', 96);

INSERT OR IGNORE INTO EVENT_DATE (EventID, Date)
SELECT EventID, Date FROM EVENT;
