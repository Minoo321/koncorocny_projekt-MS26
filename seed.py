"""Naplni databazu 50 demo pouzivatelmi, tipmi a spravami v chate.

Spustenie:  python seed.py
Vsetci demo pouzivatelia maju heslo: heslo123
"""
import random

from werkzeug.security import generate_password_hash

from api_client import _evaluate_tips, sync_matches
from main import app
from models import db, Match, Message, Tip, User

MENA = [
    "Adam", "Boris", "Cyril", "Daniel", "Erik", "Filip", "Gabriel", "Henrich",
    "Igor", "Jakub", "Karol", "Lukas", "Marek", "Norbert", "Oliver", "Patrik",
    "Rastislav", "Samuel", "Tomas", "Viktor", "Zdeno", "Andrej", "Branislav",
    "Dominik", "Emanuel", "Frantisek", "Gregor", "Hugo", "Ivan", "Jan",
    "Kristian", "Ladislav", "Martin", "Nikolas", "Ondrej", "Peter", "Richard",
    "Stefan", "Tibor", "Urban", "Vladimir", "Maros", "Juraj", "Matus", "Simon",
    "Dusan", "Roman", "Milos", "Pavol", "Leo",
]

CHAT_SPRAVY = [
    "Ahojte, kto tipuje dnesny zapas?",
    "MS 2026 zacina, konecne!",
    "Ja tipujem domacich, jasna vyhra.",
    "Remiza tam smrdi na 100%...",
    "Kto je prvy v rebricku? :D",
    "Vcera mi nevysiel ani jeden tip :(",
    "3 body za spravny tip, ide sa na to!",
    "Tipnite si vsetci X, nech sa pobavime.",
    "Tento turnaj bude super.",
    "Kto vyhra celé MS? Ja vravim Brazilia.",
    "Anglicko to tento rok da!",
    "Nezabudnite tipovat pred zaciatkom zapasu.",
    "Som na 1. mieste, dobehnite ma :)",
    "Aky kurz by mal tento zapas v stavkovej?",
    "GG vsetkym tiperom!",
]


def seed():
    rng = random.Random(7)

    with app.app_context():
        sync_matches()  # stiahni realne zapasy (alebo demo data bez API kluca)

        finished = Match.query.filter(Match.status == "FINISHED",
                                      Match.home_team.isnot(None)).all()
        upcoming = Match.query.filter(Match.status != "FINISHED",
                                      Match.home_team.isnot(None)).all()
        print(f"Zapasy v DB: {len(finished)} dohranych, {len(upcoming)} nadchadzajucich")

        wc_teams = sorted({m.home_team for m in upcoming + finished
                           if m.league == "WC" and m.home_team})

        password = generate_password_hash("heslo123")
        created = 0
        for meno in MENA:
            username = meno.lower()
            if User.query.filter_by(username=username).first():
                continue
            user = User(username=username, email=f"{username}@demo.sk",
                        password_hash=password,
                        favorite_team=rng.choice(wc_teams) if wc_teams and rng.random() < 0.7 else None,
                        champion_pick=rng.choice(wc_teams) if wc_teams and rng.random() < 0.6 else None)
            db.session.add(user)
            db.session.flush()  # aby mal user.id
            created += 1

            # tipy na dohrane zapasy (vyhodnoti ich _evaluate_tips nizsie)
            for match in rng.sample(finished, min(len(finished), rng.randint(5, 15))):
                tip = Tip(user_id=user.id, match_id=match.id,
                          vyber=rng.choice(["1", "1", "X", "2"]))
                if rng.random() < 0.4:  # niektori tipuju aj presne skore
                    tip.score_home = rng.randint(0, 4)
                    tip.score_away = rng.randint(0, 3)
                db.session.add(tip)

            # par tipov aj na nadchadzajuce zapasy
            for match in rng.sample(upcoming, min(len(upcoming), rng.randint(2, 6))):
                tip = Tip(user_id=user.id, match_id=match.id,
                          vyber=rng.choice(["1", "X", "2"]))
                if rng.random() < 0.4:
                    tip.score_home = rng.randint(0, 4)
                    tip.score_away = rng.randint(0, 3)
                db.session.add(tip)

        # spravy do chatu
        if Message.query.count() == 0:
            users = User.query.all()
            for text in CHAT_SPRAVY:
                db.session.add(Message(user_id=rng.choice(users).id, text=text))

        db.session.commit()
        _evaluate_tips()  # prideli body podla kurzov + bonusy za presne skore
        print(f"Vytvorenych {created} pouzivatelov (heslo: heslo123), "
              f"{Tip.query.count()} tipov, {Message.query.count()} sprav v chate.")


if __name__ == "__main__":
    seed()
