"""Demo MCP server for the telecom-support scenario.

Account lookups are the case a prompt cannot cover: the answer is per-customer. All
accounts here are fabricated.
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

import _serve

mcp = FastMCP("telecom")

ACCOUNTS = {
    "40012345": {
        "holder": "Camille Duval",
        "plan": "Fibre 500",
        "monthly": 29.99,
        "balance": 0.0,
        "status": "active",
        "last_invoice": "2026-08-02, 29.99 EUR, paid",
    },
    "40067890": {
        "holder": "Yusuf Karim",
        "plan": "Mobile 50GB",
        "monthly": 14.99,
        "balance": 29.98,
        "status": "suspended for non-payment",
        "last_invoice": "2026-08-02, 14.99 EUR, unpaid",
    },
}

OUTAGES = {"75011": "Fibre maintenance in your area until 18:00 today.", "69003": "No known incident."}

PLANS = [
    {"plan": "Mobile 50GB", "monthly": 14.99},
    {"plan": "Mobile 200GB", "monthly": 22.99},
    {"plan": "Fibre 500", "monthly": 29.99},
    {"plan": "Fibre 2000", "monthly": 42.99},
]


@mcp.tool()
def check_account(account_number: str) -> str:
    """Look up an account: holder, plan, balance and status.

    Args:
        account_number: The 8-digit account number, e.g. "40012345".
    """
    account = ACCOUNTS.get(account_number.strip())
    if account is None:
        return f"No account {account_number}. Account numbers are 8 digits, e.g. 40012345."
    return (
        f"Account {account_number}: {account['holder']}, plan {account['plan']} at "
        f"{account['monthly']} EUR/month, status {account['status']}, "
        f"balance {account['balance']} EUR. Last invoice: {account['last_invoice']}."
    )


@mcp.tool()
def check_network(postcode: str) -> str:
    """Check for a known network incident at a postcode."""
    return OUTAGES.get(postcode.strip(), f"No known incident for {postcode}.")


@mcp.tool()
def list_upgrades(account_number: str) -> str:
    """List plans the account can move up to, with the monthly difference."""
    account = ACCOUNTS.get(account_number.strip())
    if account is None:
        return f"No account {account_number}."

    current = account["monthly"]
    better = [plan for plan in PLANS if plan["monthly"] > current]
    if not better:
        return f"{account['plan']} is already the top plan."
    return "\n".join(f"{p['plan']}: {p['monthly']} EUR/month (+{round(p['monthly'] - current, 2)})" for p in better)


if __name__ == "__main__":
    _serve.serve(mcp)
