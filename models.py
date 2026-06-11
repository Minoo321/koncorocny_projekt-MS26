"""Databazove modely aplikacie (SQLAlchemy / SQLite).

User          - hrac: prihlasenie, body, oblubeny tim, tip na majstra
Match         - zapas z API (alebo demo): timy, cas, skore, faza/skupina
Tip           - tip hraca na zapas: 1/X/2 + volitelne presne skore
Message       - sprava v chate (globalna alebo k zapasu)
PrivateLeague - sukromna liga s vlastnym rebrickom (vstup cez kod)
Standing      - riadok tabulky skupiny MS

Vsetky casy sa ukladaju ako nativny UTC (bez tzinfo) - na slovensky cas
ich prevadza az zobrazovacia vrstva (filter 'lokalny' v main.py).
"""
import random
from datetime import datetime, timezone

from flask_login import UserMixin
from flask_sqlalchemy import SQLAlchemy

db = SQLAlchemy()


def utcnow():
    """Nativny (naive) UTC cas - v celej DB pracujeme s UTC bez tzinfo."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(25), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    points = db.Column(db.Integer, default=0, nullable=False)
    favorite_team = db.Column(db.String(80), nullable=True)    # oblubeny narodny tim
    last_login_at = db.Column(db.DateTime, nullable=True)      # pre "odkedy si tu nebol"
    champion_pick = db.Column(db.String(80), nullable=True)    # tip na majstra sveta
    champion_awarded = db.Column(db.Boolean, default=False, nullable=False)

    tips = db.relationship("Tip", backref="user", lazy=True)
    messages = db.relationship("Message", backref="user", lazy=True)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    api_id = db.Column(db.Integer, unique=True, nullable=True)  # id z football-data.org
    league = db.Column(db.String(5), nullable=False)            # WC, PL, PD, BL1, SA, FL1
    home_team = db.Column(db.String(80), nullable=True)         # None = postupujuci este nie je znamy
    away_team = db.Column(db.String(80), nullable=True)
    venue = db.Column(db.String(120), nullable=True)            # stadion
    utc_date = db.Column(db.DateTime, nullable=False)           # nativny UTC cas
    status = db.Column(db.String(20), default="SCHEDULED")      # SCHEDULED / TIMED / IN_PLAY / FINISHED ...
    score_home = db.Column(db.Integer, nullable=True)
    score_away = db.Column(db.Integer, nullable=True)
    winner_side = db.Column(db.String(12), nullable=True)       # HOME_TEAM / AWAY_TEAM / DRAW (z API, riesi penalty)
    matchday = db.Column(db.Integer, nullable=True)             # kolo
    stage = db.Column(db.String(40), nullable=True)             # napr. GROUP_STAGE
    group_name = db.Column(db.String(40), nullable=True)        # napr. Group A (MS)
    crest_home = db.Column(db.String(255), nullable=True)       # URL loga timu
    crest_away = db.Column(db.String(255), nullable=True)

    tips = db.relationship("Tip", backref="match", lazy=True)

    @property
    def odds(self):
        """Ilustracne kurzy 1/X/2 - stabilne (odvodene z ID zapasu)."""
        rng = random.Random((self.api_id or self.id or 0) * 7919)
        return {
            "1": round(rng.uniform(1.3, 3.4), 2),
            "X": round(rng.uniform(2.8, 4.2), 2),
            "2": round(rng.uniform(1.4, 4.6), 2),
        }

    @property
    def is_live(self):
        return self.status in ("IN_PLAY", "PAUSED", "LIVE")

    @property
    def has_teams(self):
        return bool(self.home_team and self.away_team)

    @property
    def ko_outcome(self):
        """Vitaz vyradovacieho zapasu ('1'/'2') - zohladnuje aj penalty."""
        if self.winner_side == "HOME_TEAM":
            return "1"
        if self.winner_side == "AWAY_TEAM":
            return "2"
        return self.outcome

    @property
    def winner_name(self):
        if self.ko_outcome == "1":
            return self.home_team
        if self.ko_outcome == "2":
            return self.away_team
        return None

    @property
    def outcome(self):
        """Vysledok zapasu ako '1', 'X' alebo '2' (None ak nie je dohrany)."""
        if self.score_home is None or self.score_away is None:
            return None
        if self.score_home > self.score_away:
            return "1"
        if self.score_home < self.score_away:
            return "2"
        return "X"


class Tip(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=False)
    vyber = db.Column(db.String(1), nullable=False)             # '1', 'X', '2'
    score_home = db.Column(db.Integer, nullable=True)           # nepovinny tip na presne skore
    score_away = db.Column(db.Integer, nullable=True)
    evaluated = db.Column(db.Boolean, default=False, nullable=False)
    evaluated_at = db.Column(db.DateTime, nullable=True)
    points_awarded = db.Column(db.Integer, default=0, nullable=False)

    __table_args__ = (db.UniqueConstraint("user_id", "match_id", name="uq_user_match"),)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    match_id = db.Column(db.Integer, db.ForeignKey("match.id"), nullable=True)  # None = globalny chat
    text = db.Column(db.String(500), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)


# clenstvo v sukromnych ligach (M:N medzi User a PrivateLeague)
league_members = db.Table(
    "league_members",
    db.Column("user_id", db.Integer, db.ForeignKey("user.id"), primary_key=True),
    db.Column("league_id", db.Integer, db.ForeignKey("private_league.id"), primary_key=True),
)


class PrivateLeague(db.Model):
    """Sukromna liga - vlastny rebricek pre partiu/triedu, vstup cez kod."""
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(50), nullable=False)
    code = db.Column(db.String(8), unique=True, nullable=False)  # zdielatelny vstupny kod
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    owner = db.relationship("User", backref="owned_leagues", foreign_keys=[owner_id])
    members = db.relationship("User", secondary=league_members, backref="leagues")


class Standing(db.Model):
    """Riadok tabulky skupiny (z API /standings)."""
    id = db.Column(db.Integer, primary_key=True)
    league = db.Column(db.String(5), nullable=False)
    group_name = db.Column(db.String(40), nullable=True)
    position = db.Column(db.Integer, nullable=False)
    team_name = db.Column(db.String(80), nullable=False)
    crest = db.Column(db.String(255), nullable=True)
    played = db.Column(db.Integer, default=0)
    won = db.Column(db.Integer, default=0)
    draw = db.Column(db.Integer, default=0)
    lost = db.Column(db.Integer, default=0)
    goals_for = db.Column(db.Integer, default=0)
    goals_against = db.Column(db.Integer, default=0)
    goal_diff = db.Column(db.Integer, default=0)
    points = db.Column(db.Integer, default=0)
