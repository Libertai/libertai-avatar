"""Demo MCP server for the doctor-appointment scenario.

Exposes the appointment book: what the avatar cannot know from a prompt because it changes
as people book. All data is fabricated — no real patients, no real practitioners.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from mcp.server.fastmcp import FastMCP

mcp = FastMCP("clinic")

DOCTORS = {
    "dr-moreau": {"name": "Dr Moreau", "specialty": "General medicine"},
    "dr-haddad": {"name": "Dr Haddad", "specialty": "Dermatology"},
}
SLOT_HOURS = [9, 10, 11, 14, 15, 16, 17]
# Deterministic "already booked" slots so the demo behaves identically on every run.
BOOKED = {("dr-moreau", 10), ("dr-moreau", 15), ("dr-haddad", 9), ("dr-haddad", 16)}

_appointments: dict[str, dict] = {}


@mcp.tool()
def list_doctors() -> str:
    """List the practitioners at the clinic and their specialties."""
    return "\n".join(f"{key}: {value['name']}, {value['specialty']}" for key, value in DOCTORS.items())


@mcp.tool()
def list_availability(doctor: str, day_offset: int = 1) -> str:
    """Free appointment slots for a practitioner.

    Args:
        doctor: Practitioner key, e.g. "dr-moreau". Use list_doctors to find one.
        day_offset: Days from today; 1 is tomorrow.
    """
    if doctor not in DOCTORS:
        return f"Unknown practitioner '{doctor}'. Known: {', '.join(DOCTORS)}."
    if not 0 <= day_offset <= 30:
        return "Only the next 30 days can be checked."

    when = date.today() + timedelta(days=day_offset)
    if when.weekday() >= 5:
        return f"The clinic is closed on {when.strftime('%A %d %B')}."

    free = [f"{hour}:00" for hour in SLOT_HOURS if (doctor, hour) not in BOOKED]
    if not free:
        return f"{DOCTORS[doctor]['name']} is fully booked on {when.strftime('%A %d %B')}."
    return f"{DOCTORS[doctor]['name']} on {when.strftime('%A %d %B')}: {', '.join(free)}."


@mcp.tool()
def book_appointment(doctor: str, day_offset: int, hour: int, patient_name: str, phone: str) -> str:
    """Book a slot and return the confirmation reference.

    Args:
        doctor: Practitioner key.
        day_offset: Days from today; 1 is tomorrow.
        hour: Slot hour in 24h form, e.g. 14.
        patient_name: Name the appointment is under.
        phone: Callback number.
    """
    if doctor not in DOCTORS:
        return f"Unknown practitioner '{doctor}'."
    if hour not in SLOT_HOURS or (doctor, hour) in BOOKED:
        return f"{hour}:00 is not available. Check list_availability first."

    when = date.today() + timedelta(days=day_offset)
    reference = f"RDV-{when.strftime('%m%d')}-{hour}"
    _appointments[reference] = {
        "doctor": doctor,
        "when": f"{when.isoformat()} {hour}:00",
        "patient": patient_name,
        "phone": phone,
    }
    return (
        f"Booked: {patient_name} with {DOCTORS[doctor]['name']} on "
        f"{when.strftime('%A %d %B')} at {hour}:00. Reference {reference}."
    )


@mcp.tool()
def check_appointment(reference: str) -> str:
    """Look up an existing appointment by its reference."""
    booking = _appointments.get(reference.strip().upper())
    if booking is None:
        return f"No appointment found for {reference}. References look like RDV-0312-14."
    doctor = DOCTORS[booking["doctor"]]["name"]
    return f"{reference}: {booking['patient']} with {doctor} at {booking['when']}."


if __name__ == "__main__":
    mcp.run()
