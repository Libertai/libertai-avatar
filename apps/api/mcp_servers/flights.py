"""Demo MCP server for the flight-booking scenario.

Availability and fares change per query, which is exactly what a prompt cannot hold. All
flights here are fabricated.
"""

from __future__ import annotations

from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("flights")

AIRPORTS = {
    "CDG": "Paris Charles de Gaulle",
    "LHR": "London Heathrow",
    "JFK": "New York JFK",
    "DXB": "Dubai",
    "CMN": "Casablanca",
}

ROUTES = {
    ("CDG", "LHR"): [("AV110", "07:20", "07:35", 89.0), ("AV118", "18:45", "19:00", 132.0)],
    ("CDG", "JFK"): [("AV220", "10:05", "12:40", 415.0), ("AV228", "16:30", "19:05", 508.0)],
    ("CDG", "DXB"): [("AV330", "22:15", "07:45", 372.0)],
    ("CDG", "CMN"): [("AV440", "08:40", "10:25", 143.0), ("AV448", "19:10", "20:55", 121.0)],
}

_bookings: dict[str, dict] = {}


@mcp.tool()
def list_airports() -> str:
    """List the airports served, with their codes."""
    return "\n".join(f"{code}: {name}" for code, name in AIRPORTS.items())


@mcp.tool()
def search_flights(origin: str, destination: str, day_offset: int = 7) -> str:
    """Find flights on a route.

    Args:
        origin: Departure airport code, e.g. "CDG".
        destination: Arrival airport code, e.g. "JFK".
        day_offset: Days from today for the departure date.
    """
    origin, destination = origin.strip().upper(), destination.strip().upper()
    for code in (origin, destination):
        if code not in AIRPORTS:
            return f"Unknown airport '{code}'. Use list_airports for the codes served."

    flights = ROUTES.get((origin, destination))
    if not flights:
        return f"No direct flights from {origin} to {destination}."

    when = date.today() + timedelta(days=max(0, day_offset))
    lines = [f"{number} departs {dep}, arrives {arr}, {price} EUR" for number, dep, arr, price in flights]
    return f"{origin} to {destination} on {when.strftime('%A %d %B')}:\n" + "\n".join(lines)


@mcp.tool()
def book_flight(flight_number: str, passenger_name: str, day_offset: int = 7) -> str:
    """Reserve a seat and return the booking reference.

    Args:
        flight_number: Flight to book, e.g. "AV220".
        passenger_name: Name exactly as on the travel document.
        day_offset: Days from today for the departure date.
    """
    flight_number = flight_number.strip().upper()
    for (origin, destination), flights in ROUTES.items():
        for number, departure, _, price in flights:
            if number != flight_number:
                continue

            when = date.today() + timedelta(days=max(0, day_offset))
            reference = f"{flight_number}-{when.strftime('%m%d')}"
            _bookings[reference] = {
                "passenger": passenger_name,
                "route": f"{origin}-{destination}",
                "when": f"{when.isoformat()} {departure}",
                "price": price,
            }
            return (
                f"Booked {passenger_name} on {flight_number}, {origin} to {destination}, "
                f"{when.strftime('%A %d %B')} at {departure}, {price} EUR. Reference {reference}."
            )

    return f"Unknown flight '{flight_number}'. Search first."


@mcp.tool()
def check_booking(reference: str) -> str:
    """Look up a booking by its reference."""
    booking = _bookings.get(reference.strip().upper())
    if booking is None:
        return f"No booking found for {reference}."
    return (
        f"{reference}: {booking['passenger']}, {booking['route']}, "
        f"{booking['when']}, {booking['price']} EUR."
    )


if __name__ == "__main__":
    mcp.run()
