"""Slovenske nazvy narodnych timov MS 2026.

API football-data.org vracia anglicke nazvy - prekladame ich hned pri ukladani
do databazy, aby boli vsade konzistentne (zapasy, tabulky, tikety, profily).
Klubove nazvy (Premier League a pod.) sa neprekladaju - dict ich nepozna
a preklad ich vrati bez zmeny.
"""

TEAM_SK = {
    "Algeria": "Alžírsko",
    "Argentina": "Argentína",
    "Australia": "Austrália",
    "Austria": "Rakúsko",
    "Belgium": "Belgicko",
    "Bosnia-Herzegovina": "Bosna a Hercegovina",
    "Brazil": "Brazília",
    "Canada": "Kanada",
    "Cape Verde Islands": "Kapverdy",
    "Colombia": "Kolumbia",
    "Congo DR": "DR Kongo",
    "Croatia": "Chorvátsko",
    "Czechia": "Česko",
    "Ecuador": "Ekvádor",
    "Egypt": "Egypt",
    "England": "Anglicko",
    "France": "Francúzsko",
    "Germany": "Nemecko",
    "Iran": "Irán",
    "Iraq": "Irak",
    "Ivory Coast": "Pobrežie Slonoviny",
    "Japan": "Japonsko",
    "Jordan": "Jordánsko",
    "Mexico": "Mexiko",
    "Morocco": "Maroko",
    "Netherlands": "Holandsko",
    "New Zealand": "Nový Zéland",
    "Norway": "Nórsko",
    "Paraguay": "Paraguaj",
    "Portugal": "Portugalsko",
    "Qatar": "Katar",
    "Saudi Arabia": "Saudská Arábia",
    "Scotland": "Škótsko",
    "South Africa": "Južná Afrika",
    "South Korea": "Južná Kórea",
    "Spain": "Španielsko",
    "Sweden": "Švédsko",
    "Switzerland": "Švajčiarsko",
    "Tunisia": "Tunisko",
    "Turkey": "Turecko",
    "United States": "USA",
    "Uruguay": "Uruguaj",
    # Ghana, Haiti, Panama, Senegal, Uzbekistan, Curacao - rovnake v slovencine
}


def po_slovensky(name):
    """Prelozi nazov timu do slovenciny; nezname nazvy vrati bez zmeny."""
    if name is None:
        return None
    return TEAM_SK.get(name, name)
