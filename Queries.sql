-- 1) List all events at a venue with organizer info, ordered by date
SELECT
    e.Name      AS Event,
    e.Date,
    e.StartTime,
    v.Name      AS Venue,
    v.Location,
    o.Name      AS Organizer,
    o.Email     AS OrganizerEmail
FROM EVENT e
JOIN VENUE v     ON e.VenueID    = v.VenueID
JOIN ORGANIZER o ON e.OrganizerID = o.OrganizerID
ORDER BY e.Date;

-- 2) Shows all venues that have hosted more than one event 
SELECT 
    v.Name
FROM
    VENUE v
        JOIN
    EVENT e ON e.VenueID = v.VenueID
GROUP BY v.VenueID
HAVING COUNT(e.EventID) > 1;

-- 3) Find all events happening in Austin, TX ordered by date 
SELECT 
    e.Name, e.Date
FROM
    EVENT e
        JOIN
    VENUE v ON e.VenueID = v.VenueID
WHERE
    v.Location LIKE '%Austin, TX%'
ORDER BY e.Date;

-- 4) List all tickets that haven't been purchased yet (no OrderID), showing the event name, ticket type, and price 
SELECT e.Name, t.Type, t.Price
FROM TICKET t
JOIN EVENT e ON t.EventID = t.EventID
WHERE t.OrderID IS NULL;

-- 5) Total revenue per event / top-grossing events
SELECT
    e.Name          AS Event,
    COUNT(t.TicketID) AS TicketsSold,
    SUM(t.Price)    AS TotalRevenue
FROM EVENT e
JOIN TICKET t ON e.EventID = t.EventID
WHERE t.OrderID IS NOT NULL
GROUP BY e.EventID, e.Name
ORDER BY TotalRevenue DESC;

-- 6) Calculate the total revenue collected per payment method 
SELECT 
    Method, SUM(Amount) AS 'Total Revenue'
FROM
    Payment
GROUP BY Method;

-- 7) The average ticket price for each event type (Music, Sports, Conference)
SELECT 
    'Music' AS EventType, AVG(t.Price) AS `Average Ticket Price`
FROM
    TICKET t
        JOIN
    MUSIC_EVENT me ON t.EventID = me.EventID
    
UNION

SELECT 
    'Sports', AVG(t.Price)
FROM
    TICKET t
        JOIN
    SPORTS_EVENT se ON t.EventID = se.EventID

UNION

SELECT 
    'Conference', AVG(t.Price)
FROM
    TICKET t
        JOIN
    CONFERENCE c ON t.EventID = c.EventID;
    
-- 8) Showing number of orders users have placed, if they have more than one order
SELECT UserID as 'User', COUNT(OrderID) as 'Number of Orders'
FROM `ORDER`
GROUP BY UserID
HAVING COUNT(OrderID)> 1;

-- 9) Find users who purchased tickets to music events only
SELECT
    u.UserID,
    u.Username,
    u.Email
FROM USER u
WHERE u.UserID IN (
        SELECT o.UserID
        FROM `ORDER` o
        JOIN TICKET t ON t.OrderID = o.OrderID
        WHERE t.EventID IN (SELECT EventID FROM MUSIC_EVENT)
    )
  AND u.UserID NOT IN (
        SELECT o.UserID
        FROM `ORDER` o
        JOIN TICKET t ON t.OrderID = o.OrderID
        WHERE t.EventID NOT IN (SELECT EventID FROM MUSIC_EVENT)
    );
    
-- 10) all events where no tickets have been sold
SELECT 
    e.Name
FROM
    EVENT e
WHERE
    e.EventID NOT IN (SELECT DISTINCT
            t.EventID
        FROM
            TICKET t
        WHERE
            t.OrderID IS NOT NULL);
            
-- 11) Lists organizers who have never had a cancelled or refunded order on any of their events 
SELECT o.OrganizerID, o.Name
FROM ORGANIZER o
WHERE NOT EXISTS (
    SELECT 1
    FROM EVENT e
    JOIN TICKET t ON e.EventID = t.EventID
    JOIN `ORDER` ord ON t.OrderID = ord.OrderID
    WHERE e.OrganizerID = o.OrganizerID
    AND ord.Status IN ('Cancelled', 'Refunded')
);

-- 12) The most expensive ticket ever purchased, showing the buyer's username and email

SELECT u.Username, u.Email, t.Price
FROM TICKET t
JOIN `ORDER` ord ON ord.OrderID = t.OrderID
JOIN USER u ON u.UserID = ord.UserID
WHERE t.Price = (
    SELECT MAX(t2.Price) 
    FROM TICKET t2
    WHERE t2.OrderID IS NOT NULL);
    
-- 13) Events with ticket sales exceeding 80% capacity
SELECT
    e.Name AS Event,
    e.Capacity,
    COUNT(t.TicketID) AS TicketsSold,
    ROUND(COUNT(t.TicketID) / e.Capacity * 100, 1) AS PercentSold
FROM EVENT e
JOIN TICKET t ON e.EventID = t.EventID
WHERE t.OrderID IS NOT NULL
GROUP BY e.EventID, e.Name, e.Capacity
HAVING COUNT(t.TicketID) >= 1
ORDER BY PercentSold DESC;

-- 14) Show the full purchase trail: username → order → ticket → event → venue for all confirmed orders

SELECT 
    u.Username,
    o.OrderID,
    t.Type AS TicketType,
    t.Price,
    e.Name AS Event,
    v.Name AS Venue
FROM TICKET t
JOIN `ORDER` o ON o.OrderID = t.OrderID
JOIN EVENT e ON e.EventID = t.EventID
JOIN VENUE v ON v.VenueID = e.VenueID
JOIN USER u ON u.UserID = o.UserID
WHERE o.Status = 'Confirmed';

-- 15) All sports events with their sport team, home team, away team, venue name, and venue capacity
SELECT
	se.SportTeam,
    se.HomeTeam,
    se.AwayTeam,
    v.Name as Venue,
    v.Capacity 
FROM SPORTS_EVENT se
JOIN EVENT e ON e.EventID = se.EventID
JOIN VENUE v ON v.VenueID = e.VenueID;

-- 16) Trigger to auto-update order status on payment confirmation
DELIMITER $$
 
CREATE TRIGGER trg_confirm_order_on_payment
AFTER INSERT ON PAYMENT
FOR EACH ROW
BEGIN
    UPDATE `ORDER`
    SET Status = 'Confirmed'
    WHERE OrderID = NEW.OrderID
      AND Status  = 'Pending';
END$$
 
DELIMITER ;

-- 17) Trigger that prevents a ticket's OrderID from being updated if the associated order is already Cancelled or Refunded  
DELIMITER $$
CREATE TRIGGER trg_prevent_orderid_update
BEFORE UPDATE ON TICKET
FOR EACH ROW
BEGIN
    DECLARE order_status VARCHAR(50);
    
    IF NEW.OrderID != OLD.OrderID THEN
        SELECT Status INTO order_status
        FROM `ORDER`
        WHERE OrderID = NEW.OrderID;
        
        IF order_status IN ('Cancelled', 'Refunded') THEN
            SIGNAL SQLSTATE '45000'
                SET MESSAGE_TEXT = 'Cannot update ticket: associated order is either Cancelled or Refunded';
        END IF;
    END IF;
END$$
DELIMITER ;

-- 18) Trigger that automatically sets an order's Status to 'Cancelled' if its payment amount doesn't match the order's TotalPrice 
DELIMITER $$
CREATE TRIGGER trg_cancel_order_on_payment_mismatch
AFTER INSERT ON PAYMENT
FOR EACH ROW
BEGIN
    DECLARE order_total DECIMAL(10,2);
    
    SELECT TotalPrice INTO order_total
    FROM `ORDER`
    WHERE OrderID = NEW.OrderID;
    
    IF NEW.Amount != order_total THEN
        UPDATE `ORDER`
        SET Status = 'Cancelled'
        WHERE OrderID = NEW.OrderID;
    END IF;
END$$
DELIMITER ;

-- 19) Create Organizer view to see ticket sales summary per their events 
CREATE VIEW vw_OrganizerSalesSummary AS
SELECT
    o.Name AS Organizer,
    e.Name AS Event,
    e.Date,
    COUNT(t.TicketID) AS TotalTickets,
    SUM(CASE WHEN t.OrderID IS NOT NULL THEN 1      ELSE 0 END) AS TicketsSold,
    SUM(CASE WHEN t.OrderID IS NOT NULL THEN t.Price ELSE 0 END) AS Revenue
FROM ORGANIZER o
JOIN EVENT e  ON o.OrganizerID = e.OrganizerID
JOIN TICKET t ON e.EventID     = t.EventID
GROUP BY o.OrganizerID, o.Name, e.EventID, e.Name, e.Date;

-- 20) View showing each user's total spending across all their confirmed orders  
CREATE VIEW vw_UserTotalSpending AS
SELECT 
    u.UserID,
    u.Username,
    u.Email,
    SUM(o.TotalPrice) AS TotalSpending
FROM USER u
JOIN `ORDER` o ON u.UserID = o.UserID
WHERE o.Status = 'Confirmed'
GROUP BY u.UserID, u.Username, u.Email;

-- Query the view
SELECT * FROM vw_UserTotalSpending
ORDER BY TotalSpending DESC;

-- 21) View that flags events where tickets sold exceed 50% of capacity 
CREATE VIEW vw_HighDemandEvents AS
SELECT 
    e.EventID,
    e.Name AS Event,
    e.Capacity,
    COUNT(t.TicketID) AS TicketsSold,
    ROUND(COUNT(t.TicketID) / e.Capacity * 100, 1) AS PercentSold,
    CASE 
        WHEN COUNT(t.TicketID) / e.Capacity * 100 > 50 
        THEN 'High Demand'
        ELSE 'Normal'
    END AS DemandFlag
FROM EVENT e
JOIN TICKET t ON e.EventID = t.EventID
WHERE t.OrderID IS NOT NULL
GROUP BY e.EventID, e.Name, e.Capacity
HAVING COUNT(t.TicketID) / e.Capacity * 100 > 50;

-- Query the view
SELECT * FROM vw_HighDemandEvents
ORDER BY PercentSold DESC;

-- 22) Enforce ticket count ≤ venue seating capacity
DELIMITER $$
 
CREATE TRIGGER trg_enforce_venue_capacity
BEFORE INSERT ON TICKET
FOR EACH ROW
BEGIN
    DECLARE sold_count INT;
    DECLARE venue_cap  INT;
 
    SELECT COUNT(*)
    INTO sold_count
    FROM TICKET
    WHERE EventID = NEW.EventID;
 
    SELECT v.Capacity
    INTO venue_cap
    FROM EVENT e
    JOIN VENUE v ON e.VenueID = v.VenueID
    WHERE e.EventID = NEW.EventID;
 
    IF sold_count >= venue_cap THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Cannot add ticket: venue capacity reached.';
    END IF;
END$$
 
DELIMITER ;

-- 23) users who have purchased tickets to all three event types 
SELECT u.UserID, u.Username
FROM USER u
WHERE EXISTS (
    SELECT *
    FROM `ORDER` o
    JOIN TICKET t ON t.OrderID = o.OrderID
    WHERE o.UserID = u.UserID
    AND t.EventID IN (SELECT EventID FROM MUSIC_EVENT)
)
AND EXISTS (
    SELECT *
    FROM `ORDER` o
    JOIN TICKET t ON t.OrderID = o.OrderID
    WHERE o.UserID = u.UserID
    AND t.EventID IN (SELECT EventID FROM SPORTS_EVENT)
)
AND EXISTS (
    SELECT *
    FROM `ORDER` o
    JOIN TICKET t ON t.OrderID = o.OrderID
    WHERE o.UserID = u.UserID
    AND t.EventID IN (SELECT EventID FROM CONFERENCE)
);

-- 24) Organizers whose events have generated zero revenue across all their events
SELECT o.OrganizerID, o.Name
FROM ORGANIZER o
WHERE o.OrganizerID NOT IN (
    SELECT e.OrganizerID
    FROM EVENT e
    JOIN TICKET t ON t.EventID = e.EventID
    JOIN `ORDER` ord ON ord.OrderID = t.OrderID
    WHERE ord.Status = 'Confirmed'
);
