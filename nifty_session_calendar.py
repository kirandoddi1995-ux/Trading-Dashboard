"""Reviewable NSE cash-session calendar, bounded to the downloaded study period.

Annual circulars plus explicit amendments; never inferred from returned candles.
The caller must review this calendar before declaring research inputs ready.
"""
from datetime import date

ANNUAL = {
    2022: ("CMTR50560", "01-26 03-01 03-18 04-14 04-15 05-03 08-09 08-15 08-31 10-05 10-24 10-26 11-08"),
    2023: ("CMTR54757", "01-26 03-07 03-30 04-04 04-07 04-14 05-01 06-29 08-15 09-19 10-02 10-24 11-14 11-27 12-25"),
    2024: ("CMTR59722", "01-22 01-26 03-08 03-25 03-29 04-11 04-17 05-01 05-20 06-17 07-17 08-15 10-02 11-01 11-15 11-20 12-25"),
    2025: ("CMTR65587", "02-26 03-14 03-31 04-10 04-14 04-18 05-01 08-15 08-27 10-02 10-21 10-22 11-05 12-25"),
    2026: ("CMTR71775", "01-15 01-26 03-03 03-26 03-31 04-03 04-14 05-01 05-28 06-26 09-14 10-02 10-20 11-10 11-24 12-25"),
}


def circular(name):
    return f"https://nsearchives.nseindia.com/content/circulars/{name}.pdf"


AMENDMENTS = {
    "2023-06-28": "https://www.niftyindices.com/Press_Release/ind_prs27062023.pdf",
    "2023-06-29": "https://www.niftyindices.com/Press_Release/ind_prs27062023.pdf",
    "2024-01-22": circular("CMPT60343"),
    "2024-05-20": circular("CMTR61518"),
    "2024-11-20": circular("CMTR64960"),
    "2026-01-15": circular("CMTR72260"),
}
# Unknown timing is explicit, not guessed. These days remain excluded from replay.
SPECIAL = {
    "2022-10-24": (None, circular("CMTR50560")),
    "2023-11-12": ([("18:15", "19:15")], circular("CMTR59124")),
    "2024-01-20": ([("09:15", "15:30")], circular("CMPT60343")),
    "2024-03-02": ([("09:15", "10:00"), ("11:30", "12:30")], circular("MSD60677")),
    "2024-05-18": ([("09:15", "10:00"), ("11:30", "12:30")], circular("MSD61893")),
    "2024-11-01": ([("18:00", "19:00")], circular("CMTR64628")),
    "2025-02-01": (None, circular("CMTR65587")),
    "2025-10-21": ([("13:45", "14:45")], circular("CMTR70319")),
    "2026-02-01": ([("09:15", "15:30")], circular("CMTR72349")),
}


def session(day):
    if not date(2022, 1, 1) <= day <= date(2026, 9, 30):
        raise ValueError("CALENDAR_OUTSIDE_REVIEWED_STUDY_RANGE")
    code, holidays = ANNUAL[day.year]
    source = AMENDMENTS.get(str(day), circular(code))
    if str(day) in SPECIAL:
        windows, source = SPECIAL[str(day)]
        return {"kind": "SPECIAL", "windows": windows, "source": source}
    closed = day.weekday() >= 5 or day.strftime("%m-%d") in holidays.split()
    return {"kind": "CLOSED" if closed else "REGULAR",
            "windows": [] if closed else [("09:15", "15:30")], "source": source}
