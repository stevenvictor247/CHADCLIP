"""Warden's rulebook: what every shirt and listing must pass before it goes anywhere near Etsy.

Plain code, no AI, so checking costs nothing. Each rule says where it comes from and when it was last checked, and
the Etsy panel shows that list so you can see how fresh it is. Problems block a design; warnings send it to you.
"""

import re

CHECKED = "2026-10-26"   # the day these rules were last read against Etsy's and Printify's own pages

RULES = [
    {"rule": "No trademarks, brands, teams, leagues, schools, characters, shows or famous people in the words, "
             "title or tags", "source": "Etsy Intellectual Property Policy", "checked": CHECKED},
    {"rule": "Say that AI helped make the design, in the description, when the picture was made by an image AI",
     "source": "Etsy Creativity Standards", "checked": CHECKED},
    {"rule": "List as \"Designed by\" you and name the production partner (Printify), never as handmade",
     "source": "Etsy Creativity Standards and production partner rules", "checked": CHECKED},
    {"rule": "At least one real, unedited photo per listing (a photo of your sample shirt). HQ reminds you before "
             "you publish; it can't add the photo for you", "source": "Etsy seller policy update, Oct 22 2026",
     "checked": CHECKED},
    {"rule": "No listings made and posted by a bot: every listing is published by you, by hand, in Printify or Etsy",
     "source": "Etsy seller policy update, Oct 22 2026", "checked": CHECKED},
    {"rule": "Title up to 140 characters; %, : and & at most once each", "source": "Etsy listing rules",
     "checked": CHECKED},
    {"rule": "Up to 13 tags, each up to 20 characters: letters, numbers, spaces, - and ' only",
     "source": "Etsy listing rules", "checked": CHECKED},
    {"rule": "No copying other shops' designs, and HQ never scrapes Etsy", "source": "Etsy Terms of Use",
     "checked": CHECKED},
    {"rule": "HQ never publishes a listing, never sends an order to production and never answers buyers",
     "source": "HQ's own safety rule", "checked": CHECKED},
]

# Hard stops. Word-boundary matches, any case. Kept to names that are almost never innocent on a shirt.
BLOCKED = [
    # brands
    "nike", "adidas", "jordan", "under armour", "disney", "pixar", "marvel", "dc comics", "star wars", "harry potter",
    "hogwarts", "pokemon", "pokémon", "pikachu", "nintendo", "mario", "zelda", "minecraft", "fortnite", "roblox",
    "barbie", "hello kitty", "sanrio", "bluey", "peppa", "paw patrol", "sesame street", "snoopy", "peanuts", "grinch",
    "dr seuss", "dr. seuss", "mickey", "minnie", "winnie the pooh", "looney tunes", "scooby", "spongebob", "simpsons",
    "stranger things", "yellowstone", "friends tv", "gilmore", "the office", "game of thrones", "lord of the rings",
    "taylor swift", "swiftie", "eras tour", "beyonce", "beyoncé", "starbucks", "dunkin", "coca cola", "coca-cola",
    "pepsi", "budweiser", "bud light", "coors", "jack daniels", "jameson", "stanley cup", "stanley tumbler", "yeti",
    "jeep", "harley", "harley davidson", "john deere", "ford", "chevy", "chevrolet", "tesla", "apple inc", "iphone",
    "crocs", "lululemon", "supreme", "gucci", "louis vuitton", "chanel", "prada", "versace", "playboy", "carhartt",
    "trader joe", "target run", "walmart", "costco", "amazon", "etsy", "printify",
    # leagues, events, schools
    "nfl", "nba", "mlb", "nhl", "ncaa", "mls", "wnba", "wwe", "ufc", "fifa", "pga", "nascar", "olympic", "olympics",
    "super bowl", "world series", "march madness", "final four", "kentucky derby", "stanley cup",
    "wayne state", "wsu", "gliac", "big ten", "sec football", "acc", "big 12",
    # unique team names
    "packers", "steelers", "buccaneers", "seahawks", "49ers", "niners", "dodgers", "yankees", "red sox", "cubs",
    "lakers", "celtics", "knicks", "pistons", "red wings", "tigers baseball", "detroit lions", "chiefs kingdom",
    "dallas cowboys", "green bay", "crimson tide", "buckeyes", "wolverines", "spartans football", "fighting irish",
    # famous people
    "trump", "biden", "kamala", "obama", "elon", "musk", "kanye", "drake", "travis kelce", "kelce", "lebron",
    "brady", "mahomes", "messi", "ronaldo", "dolly parton", "bob ross", "betty white",
]

# Warnings: often fine, sometimes a team or a claim. Anything here goes to you instead of straight through.
WARN = {
    "team words": ["lions", "bears", "eagles", "giants", "jets", "chiefs", "bills", "browns", "bengals", "ravens",
                   "titans", "colts", "texans", "jaguars", "broncos", "raiders", "chargers", "cowboys", "commanders",
                   "saints", "falcons", "panthers", "vikings", "rams", "cardinals", "dolphins", "patriots", "warriors",
                   "tigers", "wildcats", "bulldogs", "game day", "gameday"],
    "misleading for print on demand": ["handmade", "hand made", "hand painted", "hand-painted", "made by me",
                                       "official", "licensed", "authentic", "vintage original"],
    "health or money claims": ["cure", "cures", "heals", "treats", "fda", "guaranteed", "get rich"],
    "strong language": ["fuck", "f*ck", "shit", "bitch", "cunt", "dick"],
}

TAG_OK = re.compile(r"^[A-Za-z0-9 '\-]+$")
TITLE_OK = re.compile(r"^[\w\s.,!?'\"()\-/%:&+#*@$™©®]+$")

PARTNER_LINE = ("Designed by us and printed and shipped by our production partner, Printify. Each shirt is made "
                "to order just for you.")
AI_LINE = "The artwork on this design was made with help from an AI image tool, then finished by us."
CARE_LINE = "Care: machine wash cold inside out, tumble dry low. Do not iron the print."


def _find(words: list[str], text: str) -> list[str]:
    low = text.lower()
    return [w for w in words if re.search(r"(?<![a-z0-9])" + re.escape(w) + r"(?![a-z0-9])", low)]


def clean_tags(tags: list) -> list[str]:
    """Etsy's tag rules applied: trimmed, allowed characters only, 20 characters max, no repeats, 13 at most."""
    out, seen = [], set()
    for t in tags or []:
        t = re.sub(r"[^A-Za-z0-9 '\-]", "", str(t)).strip()
        t = re.sub(r"\s+", " ", t)[:20].strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            out.append(t)
    return out[:13]


def finish_description(description: str, used_ai_art: bool) -> str:
    """Adds the lines Etsy needs (production partner, AI note when used) and care tips, once each."""
    text = (description or "").strip()
    for line in ([PARTNER_LINE] + ([AI_LINE] if used_ai_art else []) + [CARE_LINE]):
        if line not in text:
            text += ("\n\n" if text else "") + line
    return text


def check(design: dict) -> dict:
    """{"problems": [...], "warnings": [...]}. Any problem holds the design; warnings send it to you to look at."""
    problems, warnings = [], []
    words = " ".join(str(design.get(k) or "") for k in ("slogan", "subline", "title", "art_prompt", "theme"))
    tags = design.get("tags") or []
    words_and_tags = words + " " + " ".join(tags)
    hits = _find(BLOCKED, words_and_tags)
    if hits:
        problems.append("Names a brand, team, league, school, character or famous person: " + ", ".join(sorted(set(hits))))
    for why, ws in WARN.items():
        found = _find(ws, words_and_tags)
        if found:
            warnings.append(f"Check the wording ({why}): " + ", ".join(sorted(set(found))))
    title = design.get("title") or ""
    if not title.strip():
        problems.append("No listing title")
    elif len(title) > 140:
        problems.append(f"Title is {len(title)} characters; Etsy allows 140")
    if title and not TITLE_OK.match(title):
        problems.append("Title has characters Etsy doesn't allow")
    for ch in "%:&":
        if title.count(ch) > 1:
            problems.append(f"Title uses {ch} more than once")
    if len(tags) > 13:
        problems.append(f"{len(tags)} tags; Etsy allows 13")
    bad = [t for t in tags if len(t) > 20 or not TAG_OK.match(t)]
    if bad:
        problems.append("Tags Etsy won't take: " + ", ".join(bad[:5]))
    if len(tags) < 10:
        warnings.append(f"Only {len(tags)} tags; use all 13 to be found")
    slogan = (design.get("slogan") or "").strip()
    if not slogan:
        problems.append("No words for the shirt")
    elif len(slogan) > 60:
        warnings.append("Long slogan: shirts with fewer words read better from across a room")
    desc = design.get("description") or ""
    if PARTNER_LINE not in desc:
        problems.append("Description doesn't name the production partner")
    if design.get("used_ai_art") and AI_LINE not in desc:
        problems.append("Description doesn't say AI helped with the art")
    price = int(design.get("price_cents") or 0)
    if price < 1500:
        warnings.append(f"Price ${price / 100:.2f} is low: after Etsy fees and the shirt there's little left")
    return {"problems": problems, "warnings": warnings}
