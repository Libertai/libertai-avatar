"""Demo MCP server for the pizzeria scenario.

Exposes the data an avatar cannot know from its prompt: what the kitchen is doing right
now. Everything here is fabricated for the showcase — no real orders, no real customers.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from mcp.server.fastmcp import FastMCP

import _serve

mcp = FastMCP("pizzeria")

# Delivery zones keyed by postcode prefix, with the minutes each adds to the base time.
ZONES = {
    "75001": 10,
    "75002": 15,
    "75011": 20,
    "75020": 30,
}
BASE_MINUTES = 25
KITCHEN_LOAD = {"quiet": 0, "busy": 15}


@mcp.tool()
def check_delivery(postcode: str) -> str:
    """Estimate delivery time to a postcode, accounting for current kitchen load.

    Args:
        postcode: The customer's postcode, e.g. "75011".
    """
    postcode = postcode.strip()
    if postcode not in ZONES:
        served = ", ".join(sorted(ZONES))
        return f"We do not deliver to {postcode}. We serve: {served}."

    load = "busy" if datetime.now().hour in (12, 13, 19, 20) else "quiet"
    minutes = BASE_MINUTES + ZONES[postcode] + KITCHEN_LOAD[load]
    arrival = (datetime.now() + timedelta(minutes=minutes)).strftime("%H:%M")
    return f"Delivery to {postcode} takes about {minutes} minutes ({load} kitchen), arriving around {arrival}."


@mcp.tool()
def check_order(order_number: str) -> str:
    """Look up the status of an existing order.

    Args:
        order_number: The order reference given to the customer, e.g. "A417".
    """
    order_number = order_number.strip().upper()
    if not order_number.startswith("A") or not order_number[1:].isdigit():
        return f"Order {order_number} does not exist. Order numbers look like A417."

    # Deterministic demo statuses so the showcase behaves the same on every run.
    statuses = ["in the oven", "out for delivery", "delivered"]
    return f"Order {order_number} is {statuses[int(order_number[1:]) % len(statuses)]}."


if __name__ == "__main__":
    _serve.serve(mcp)
