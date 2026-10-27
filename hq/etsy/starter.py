"""Twelve hand-written shirts to open the shop with, so Print Street has designs on day one without spending on
Claude. Quill adds these first (in order, a few a day like its own), then writes new ones from Radar's briefs.

Four are for the holidays coming up in late 2026 (Thanksgiving, Christmas and gift season), eight sell all year.
All original words, no brands, teams, schools or famous names; Warden still checks every one.
"""

STARTER = [
    {"theme": "Thanksgiving", "slogan": "Here for / the Pie", "subline": "Thanksgiving Crew", "style": "retro",
     "title": "Here for the Pie Shirt, Funny Thanksgiving Tee, Family Thanksgiving Shirts, Pie Lover Gift, "
              "Fall Dinner Shirt",
     "tags": ["thanksgiving shirt", "pie lover gift", "funny thanksgiving", "family dinner tee", "fall shirt",
              "turkey day shirt", "pie shirt", "matching family", "holiday dinner", "november shirt",
              "foodie gift", "thankful shirt", "fall gift for her"],
     "description": "For the person who skips the turkey and heads straight for dessert. A fun pick for "
                    "Thanksgiving dinner, family photos or the cousin who always brings the pie.\n\n"
                    "Order one for everyone at the table and make it the family shirt of the year."},
    {"theme": "Thanksgiving", "slogan": "Thankful / and Full", "subline": None, "style": "script",
     "title": "Thankful and Full Shirt, Cute Thanksgiving Tee, Fall Shirt for Women, Grateful Shirt, "
              "Thanksgiving Gift",
     "tags": ["thankful shirt", "thanksgiving tee", "cute fall shirt", "grateful shirt", "thanksgiving gift",
              "fall shirt women", "turkey day", "family dinner", "holiday shirt", "cozy fall tee",
              "friends dinner", "autumn shirt", "november tee"],
     "description": "Grateful heart, full plate. A soft, simple shirt for Thanksgiving dinner, fall "
                    "get-togethers and every cozy day after.\n\n"
                    "A sweet gift for a mom, sister or best friend who hosts the big meal."},
    {"theme": "Christmas", "slogan": "Most Likely to / Eat All the / Cookies", "subline": "Christmas Crew",
     "style": "bold",
     "title": "Most Likely to Eat All the Cookies Shirt, Funny Family Christmas Shirts, Matching Christmas Tee, "
              "Cookie Lover Gift",
     "tags": ["most likely to", "family christmas", "matching christmas", "christmas shirt", "cookie lover",
              "funny christmas tee", "christmas pajama", "holiday party tee", "christmas gift",
              "group christmas", "xmas family shirt", "cookie baker gift", "secret santa gift"],
     "description": "Every family has one, and now they get a shirt. Made for matching family photos, "
                    "Christmas morning and the holiday party.\n\n"
                    "Pair it with the other Most Likely To shirts in the shop so everyone gets their own."},
    {"theme": "Christmas", "slogan": "Most Likely to / Wrap Gifts / at Midnight", "subline": "Christmas Crew",
     "style": "bold",
     "title": "Most Likely to Wrap Gifts at Midnight Shirt, Funny Family Christmas Shirts, Matching Christmas Tee, "
              "Procrastinator Gift",
     "tags": ["most likely to", "family christmas", "matching christmas", "christmas shirt", "last minute gift",
              "funny christmas tee", "christmas morning", "holiday party tee", "christmas gift",
              "group christmas", "xmas family shirt", "procrastinator", "secret santa gift"],
     "description": "For the one still wrapping at 11:59 on Christmas Eve. A funny shirt for matching family "
                    "photos, Christmas morning and holiday parties.\n\n"
                    "Mix and match with the other Most Likely To shirts so the whole family is covered."},
    {"theme": "Winter and cozy season", "slogan": "Cozy Season / Certified", "subline": "Blankets, Cocoa, Repeat",
     "style": "badge",
     "title": "Cozy Season Certified Shirt, Cute Winter Tee, Hot Cocoa Shirt, Homebody Gift, Christmas Gift for Her",
     "tags": ["cozy season", "winter shirt", "hot cocoa shirt", "homebody gift", "christmas gift her",
              "cozy vibes tee", "blanket lover", "introvert gift", "cute winter tee", "fall winter shirt",
              "stay home shirt", "gift for sister", "stocking stuffer"],
     "description": "Fuzzy socks on, cocoa in hand, plans cancelled. For the homebody who has waited all year "
                    "for blanket weather.\n\n"
                    "An easy gift for a best friend, sister or anyone who loves a quiet night in."},
    {"theme": "Dog moms and dads", "slogan": "Dog Hair / Is My Glitter", "subline": None, "style": "marker",
     "title": "Dog Hair Is My Glitter Shirt, Funny Dog Mom Shirt, Dog Lover Gift, Dog Owner Tee, Gift for Dog Mom",
     "tags": ["dog mom shirt", "dog lover gift", "dog hair shirt", "funny dog shirt", "dog owner gift",
              "fur mama", "rescue dog mom", "dog mom gift", "pet lover tee", "dog people",
              "gift for her", "dog mama shirt", "puppy lover"],
     "description": "If it's on the couch, the car and every black pair of pants, it might as well be glitter. "
                    "For proud dog moms who stopped fighting the fur.\n\n"
                    "A fun gift for birthdays, Mother's Day or a new rescue adoption day."},
    {"theme": "Teachers", "slogan": "Running on / Coffee and / Recess", "subline": None, "style": "retro",
     "title": "Running on Coffee and Recess Shirt, Funny Teacher Shirt, Teacher Appreciation Gift, "
              "Coffee Teacher Tee",
     "tags": ["teacher shirt", "funny teacher tee", "teacher gift", "coffee teacher", "teacher appreciation",
              "teacher life", "elementary teacher", "back to school", "recess shirt", "coffee lover gift",
              "school staff shirt", "teacher christmas", "end of year gift"],
     "description": "Fueled by caffeine and the twenty minutes of quiet at recess. Made for the teachers who "
                    "keep the whole building running.\n\n"
                    "A great gift for teacher appreciation week, the holidays or the end of the school year."},
    {"theme": "Cat people", "slogan": "Socially / Exhausted / Cat Person", "subline": None, "style": "marker",
     "title": "Socially Exhausted Cat Person Shirt, Funny Cat Lover Tee, Introvert Shirt, Cat Mom Gift, "
              "Sarcastic Cat Shirt",
     "tags": ["cat lover shirt", "introvert shirt", "cat mom gift", "funny cat shirt", "sarcastic shirt",
              "cat person", "homebody gift", "cat owner gift", "antisocial shirt", "cat dad gift",
              "gift for her", "cat lady shirt", "funny gift"],
     "description": "Talked to people today. Need to go home and sit with the cat now. For cat lovers who "
                    "recharge best with a purring friend.\n\n"
                    "A funny birthday or holiday gift for the introvert in your life."},
    {"theme": "Book lovers", "slogan": "Booked for / the Weekend", "subline": None, "style": "script",
     "title": "Booked for the Weekend Shirt, Book Lover Gift, Reading Shirt, Bookish Tee, Book Club Shirt for Women",
     "tags": ["book lover gift", "reading shirt", "bookish shirt", "book club shirt", "librarian gift",
              "bookworm tee", "reader gift", "teacher reading", "gift for reader", "introvert reader",
              "weekend shirt", "book nerd", "gift for her"],
     "description": "No plans, just pages. For the reader who has cleared the calendar for one more chapter, "
                    "and then another.\n\n"
                    "A cute gift for book club friends, librarians or anyone with a stack on the nightstand."},
    {"theme": "Retro sunsets and beach", "slogan": "Lake Days / Are the / Best Days", "subline": None,
     "style": "retro",
     "title": "Lake Days Are the Best Days Shirt, Retro Lake Life Tee, Summer Lake Shirt, Lake House Gift, "
              "Boating Shirt",
     "tags": ["lake life shirt", "lake days", "retro sunset tee", "lake house gift", "summer shirt",
              "boating shirt", "lake vacation", "family lake trip", "retro summer", "cabin shirt",
              "lake lover gift", "vacation tee", "70s sunset shirt"],
     "description": "Sun on the dock, feet in the water, nowhere to be. A retro sunset shirt for lake people "
                    "and lake house weekends.\n\n"
                    "Great for family lake trips, cabin weekends or a gift for whoever owns the boat."},
    {"theme": "Fishing", "slogan": "Professional / Fish Whisperer", "subline": None, "style": "bold",
     "title": "Professional Fish Whisperer Shirt, Funny Fishing Shirt for Men, Fishing Dad Gift, Fisherman Tee, "
              "Angler Gift",
     "tags": ["fishing shirt", "funny fishing tee", "fishing dad gift", "fisherman gift", "angler shirt",
              "fishing grandpa", "bass fishing", "lake fishing", "gift for dad", "outdoors shirt",
              "fishing lover", "fathers day gift", "retirement gift"],
     "description": "He talks, they bite. Or at least that's the story. For the dad, grandpa or buddy who "
                    "swears he has a gift.\n\n"
                    "A fun pick for Father's Day, birthdays, retirement or the next fishing trip."},
    {"theme": "Gardening and plants", "slogan": "Plant Mom / Club", "subline": "Est. In the Garden",
     "style": "badge",
     "title": "Plant Mom Club Shirt, Plant Lover Gift, Gardening Shirt for Women, Houseplant Tee, Gardener Gift",
     "tags": ["plant mom shirt", "plant lover gift", "gardening shirt", "houseplant tee", "gardener gift",
              "plant lady", "garden lover", "crazy plant lady", "gift for mom", "mothers day gift",
              "green thumb", "botanical shirt", "plant mama"],
     "description": "Members only: people who name their plants and talk to them every morning. For plant moms "
                    "with a sunny windowsill and one more pot than they need.\n\n"
                    "A sweet gift for Mother's Day, birthdays or a fellow plant swapper."},
]
