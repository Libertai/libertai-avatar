"""Demo MCP server for the doctor-appointment scenario.

Exposes the appointment book: what the avatar cannot know from a prompt because it changes
as people book. All data is fabricated — no real patients, no real practitioners.
"""

from __future__ import annotations

from datetime import date, timedelta

from mcp.server.fastmcp import FastMCP

import _state  # sibling module: stdio servers run as scripts, so their own directory is on sys.path

mcp = FastMCP("clinic")

DOCTORS = {
    "dr-moreau": {"name": "Dr Moreau", "specialty": "General medicine"},
    "dr-haddad": {"name": "Dr Haddad", "specialty": "Dermatology"},
}
SLOT_HOURS = [9, 10, 11, 14, 15, 16, 17]
# Deterministic "already booked" slots so the demo behaves identically on every run.
BOOKED = {("dr-moreau", 10), ("dr-moreau", 15), ("dr-haddad", 9), ("dr-haddad", 16)}

MAX_DAYS_AHEAD = 30


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
    if not 0 <= day_offset <= MAX_DAYS_AHEAD:
        return f"Only the next {MAX_DAYS_AHEAD} days can be checked."

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
    if not 0 <= day_offset <= MAX_DAYS_AHEAD:
        return f"Appointments can only be booked within the next {MAX_DAYS_AHEAD} days."

    when = date.today() + timedelta(days=day_offset)
    if when.weekday() >= 5:
        return f"The clinic is closed on {when.strftime('%A %d %B')}."
    if hour not in SLOT_HOURS or (doctor, hour) in BOOKED:
        return f"{hour}:00 is not available. Check list_availability first."

    # The doctor belongs in the reference: two practitioners share every slot hour.
    reference = f"RDV-{when.strftime('%m%d')}-{hour}-{doctor.removeprefix('dr-').upper()[:3]}"
    appointments = _state.load("clinic")
    if reference in appointments:
        return f"{hour}:00 with {DOCTORS[doctor]['name']} is already taken on that day."

    appointments[reference] = {
        "doctor": doctor,
        "when": f"{when.isoformat()} {hour}:00",
        "patient": patient_name,
        "phone": phone,
    }
    _state.save("clinic", appointments)
    return (
        f"Booked: {patient_name} with {DOCTORS[doctor]['name']} on "
        f"{when.strftime('%A %d %B')} at {hour}:00. Reference {reference}."
    )


@mcp.tool()
def check_appointment(reference: str) -> str:
    """Look up an existing appointment by its reference."""
    booking = _state.load("clinic").get(reference.strip().upper())
    if booking is None:
        return f"No appointment found for {reference}. References look like RDV-0312-14-MOR."
    doctor = DOCTORS[booking["doctor"]]["name"]
    return f"{reference}: {booking['patient']} with {doctor} at {booking['when']}."


if __name__ == "__main__":
    mcp.run()
