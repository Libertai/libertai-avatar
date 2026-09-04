"""The demo MCP servers back the showcase scenarios, so their rules have to hold.

A stdio server is spawned per tool call, which is why state lives in a file rather than in
module globals: an avatar that books an appointment must still find it a sentence later.
"""

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path("apps/api/mcp_servers").resolve()))

import _state  # noqa: E402
import clinic  # noqa: E402
import flights  # noqa: E402


@pytest.fixture(autouse=True)
def demo_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(_state, "STATE_DIR", tmp_path)


def next_weekday(offset_from: int = 1) -> int:
    """Day offset of the next weekday, so a test never lands on a closed Saturday."""
    offset = offset_from
    while (date.today() + timedelta(days=offset)).weekday() >= 5:
        offset += 1
    return offset


def test_a_booking_survives_the_process_that_made_it() -> None:
    day = next_weekday()
    booked = clinic.book_appointment("dr-moreau", day, 14, "Camille", "0600000000")
    reference = booked.rsplit("Reference ", 1)[1].rstrip(".")

    # A fresh read is what the next tool call sees: a new process, no module state.
    assert "Camille" in clinic.check_appointment(reference)


def test_two_doctors_at_the_same_hour_get_different_references() -> None:
    day = next_weekday()
    first = clinic.book_appointment("dr-moreau", day, 14, "Camille", "0600000000")
    second = clinic.book_appointment("dr-haddad", day, 14, "Yusuf", "0600000001")

    assert first.rsplit("Reference ", 1)[1] != second.rsplit("Reference ", 1)[1]
    assert "Camille" in clinic.check_appointment(first.rsplit("Reference ", 1)[1].rstrip("."))


def test_booking_refuses_a_day_the_clinic_is_closed() -> None:
    saturday = 1
    while (date.today() + timedelta(days=saturday)).weekday() != 5:
        saturday += 1

    assert "closed" in clinic.book_appointment("dr-moreau", saturday, 14, "Camille", "0600000000")


def test_booking_refuses_a_date_beyond_the_horizon() -> None:
    assert "within the next" in clinic.book_appointment("dr-moreau", 400, 14, "Camille", "0600000000")


def test_booking_refuses_a_slot_that_is_already_taken() -> None:
    # 10:00 with Dr Moreau is one of the fixed unavailable slots.
    assert "not available" in clinic.book_appointment("dr-moreau", next_weekday(), 10, "Camille", "0600000000")


def test_the_same_slot_cannot_be_booked_twice() -> None:
    day = next_weekday()
    clinic.book_appointment("dr-moreau", day, 14, "Camille", "0600000000")

    assert "already taken" in clinic.book_appointment("dr-moreau", day, 14, "Yusuf", "0600000001")


def test_an_unknown_reference_is_reported_not_raised() -> None:
    assert "No appointment found" in clinic.check_appointment("RDV-9999-99-XXX")


def test_a_flight_booking_survives_too() -> None:
    booked = flights.book_flight("AV220", "Ada Lovelace")
    reference = booked.rsplit("Reference ", 1)[1].rstrip(".")

    assert "Ada Lovelace" in flights.check_booking(reference)


def test_unknown_flights_and_airports_are_reported() -> None:
    assert "Unknown flight" in flights.book_flight("ZZ999", "Ada Lovelace")
    assert "Unknown airport" in flights.search_flights("XXX", "JFK")


def test_state_survives_a_reload_and_is_isolated_per_server() -> None:
    _state.save("clinic", {"a": 1})
    _state.save("flights", {"b": 2})

    assert _state.load("clinic") == {"a": 1}
    assert _state.load("flights") == {"b": 2}


def test_missing_state_reads_as_empty() -> None:
    assert _state.load("never-written") == {}
