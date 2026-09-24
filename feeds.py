SOURCES = [
    {"name":"Ars Technica","kind":"rss","url":"https://feeds.arstechnica.com/arstechnica/index","category":"Tech","language":"en"},
    {"name":"PC Gamer","kind":"rss","url":"https://www.pcgamer.com/rss/","category":"Gaming","language":"en"},
    {"name":"PPE","kind":"html","url":"https://www.ppe.pl/news.html","base_url":"https://www.ppe.pl","link_pattern":r"^/news/\d+/.+\.html$","category":"Gaming","language":"pl"},
    {"name":"CD-Action","kind":"html","url":"https://cdaction.pl/newsy/","base_url":"https://cdaction.pl","link_pattern":r"^/newsy/[a-z0-9-]+/?$","category":"Gaming","language":"pl"},
    {"name":"Komputer Świat","kind":"html","url":"https://www.komputerswiat.pl/","base_url":"https://www.komputerswiat.pl","link_pattern":r"^/(?:programy-i-aplikacje|nauka-i-technika|sprzet|internet|inne|gry|dom)/.+/[a-z0-9]+/?$","category":"Tech","language":"pl"},
]
