"""The shirt-selling calendar, and the evergreen themes that sell all year. Free: no AI, no web.

Shoppers buy holiday shirts weeks ahead, and a new listing takes a while to be found, so each holiday has a
"start by" date about 7 weeks before it. Radar puts the next ones in every weekly brief; with no Claude key this
calendar plus the evergreen list is the whole brief.
"""

from datetime import date, timedelta

LEAD_WEEKS = 7


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    d = date(year, month, 1)
    d += timedelta(days=(weekday - d.weekday()) % 7)
    return d + timedelta(weeks=n - 1)


def _easter(year: int) -> date:
    a, b, c = year % 19, year // 100, year % 100
    d, e = b // 4, b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = c // 4, c % 4
    l = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * l) // 451
    month = (h + l - 7 * m + 114) // 31
    return date(year, month, (h + l - 7 * m + 114) % 31 + 1)


def _holidays(year: int) -> list[tuple[str, date, list[str]]]:
    return [
        ("New Year", date(year, 1, 1), ["new year new me", "resolution humor", "fresh start"]),
        ("Valentine's Day", date(year, 2, 14), ["couples", "galentine's", "anti-valentine humor", "teacher valentines"]),
        ("St. Patrick's Day", date(year, 3, 17), ["lucky", "shamrock", "irish-ish humor"]),
        ("Easter", _easter(year), ["easter bunny", "spring", "kids easter"]),
        ("Teacher Appreciation Week", _nth_weekday(year, 5, 0, 1), ["teacher life", "teacher squad"]),
        ("Mother's Day", _nth_weekday(year, 5, 6, 2), ["mama", "mom life", "dog mom", "new mom"]),
        ("Graduation", date(year, 5, 25), ["class of " + str(year), "senior", "nurse graduate", "teacher graduate"]),
        ("Father's Day", _nth_weekday(year, 6, 6, 3), ["dad jokes", "girl dad", "fishing dad", "grill dad"]),
        ("Fourth of July", date(year, 7, 4), ["usa", "america", "fourth of july party", "fireworks"]),
        ("Back to School", date(year, 8, 15), ["teacher first day", "school staff", "kindergarten"]),
        ("Fall and Football Season", date(year, 9, 15), ["fall vibes", "pumpkin spice", "football mom (no teams)"]),
        ("Halloween", date(year, 10, 31), ["spooky season", "witchy", "halloween teacher", "ghost"]),
        ("Thanksgiving", _nth_weekday(year, 11, 3, 4), ["thankful", "friendsgiving", "turkey day", "family matching"]),
        ("Christmas", date(year, 12, 25), ["christmas family matching", "ugly sweater style", "christmas teacher",
                                           "cozy season", "holiday dog"]),
    ]


def upcoming(today: date | None = None, weeks: int = 12) -> list[dict]:
    """Holidays in the next `weeks` weeks, soonest first, with when to have designs up by."""
    today = today or date.today()
    out = []
    for y in (today.year, today.year + 1):
        for name, day, angles in _holidays(y):
            if today <= day <= today + timedelta(weeks=weeks):
                start = day - timedelta(weeks=LEAD_WEEKS)
                out.append({"name": name, "date": day.isoformat(), "start_by": start.isoformat(),
                            "late": start < today, "angles": angles})
    return sorted(out, key=lambda h: h["date"])


# Themes that sell all year on Etsy shirts. General interests and jobs: no brands, teams or people.
EVERGREEN = [
    ("Coffee lovers", "people who joke about needing coffee", ["coffee first", "powered by coffee", "but first coffee"]),
    ("Dog moms and dads", "dog owners, often women 25-45", ["dog mom", "my dog is my valentine", "dog hair don't care"]),
    ("Cat people", "cat owners who like dry humor", ["cat mom", "introverted cat lover", "sassy cat"]),
    ("Teachers", "teachers and school staff, big gift market", ["teacher life", "teach love inspire", "recess humor"]),
    ("Nurses and healthcare", "nurses, techs and students", ["nurse life", "night shift", "nursing school"]),
    ("Camping and outdoors", "campers, hikers and RV people", ["camp hair", "happy camper", "mountains are calling"]),
    ("Fishing", "anglers and fishing dads", ["reel cool dad", "fishing humor", "lake life"]),
    ("Gardening and plants", "gardeners and plant collectors", ["plant lady", "garden therapy", "grow your own"]),
    ("Book lovers", "readers, book clubs and librarians", ["bookish", "one more chapter", "book club"]),
    ("Mental health and kindness", "people who like gentle, positive words", ["be kind", "you matter",
                                                                             "mental health matters"]),
    ("Mama and family", "moms, grandmas and family matching sets", ["mama", "grandma era", "matching family"]),
    ("Dad humor", "dads and gift-buyers for dads", ["dad jokes", "girl dad", "grill master"]),
    ("Gym and fitness", "people who lift, run or do yoga", ["gym humor", "leg day", "running"]),
    ("Retro sunsets and beach", "people who like 70s looks and the beach", ["retro sunset", "beach vibes",
                                                                           "lake days"]),
    ("Introverts and sarcasm", "people who like dry jokes", ["introvert", "sarcasm", "socially exhausted"]),
    ("Birthdays and milestones", "gift buyers for big birthdays and retirements", ["birthday squad", "40th birthday",
                                                                                  "retired"]),
    ("Gaming", "gamers, without any game names", ["gamer dad", "level up", "respawn"]),
    ("Farm and country life", "rural, farm and chicken people", ["chicken lady", "farm life", "country roads"]),
]


def evergreen() -> list[dict]:
    return [{"theme": t, "audience": a, "angles": angles, "why": "Sells all year", "keywords": angles, "until": None}
            for t, a, angles in EVERGREEN]


def free_brief(today: date | None = None) -> list[dict]:
    """The brief without Claude: the next holidays you can still make it for, then evergreen themes."""
    themes = []
    for h in upcoming(today):
        if not h["late"] or date.fromisoformat(h["date"]) - (today or date.today()) > timedelta(weeks=3):
            themes.append({"theme": h["name"], "audience": "gift buyers and people celebrating",
                           "why": f"{h['name']} is {h['date']}; have designs up by {h['start_by']}",
                           "angles": h["angles"], "keywords": h["angles"], "until": h["date"]})
    return themes[:3] + evergreen()[:9]
