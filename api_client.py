"""Klient pre football-data.org (top 5 lig) + demo data ako zaloha bez API kluca."""
import os
import random
from datetime import datetime, timedelta

import requests

from models import db, Match, Standing, Tip, User, utcnow
from teams_sk import po_slovensky

API_KEY = os.environ.get("FOOTBALL_DATA_API_KEY", "")
BASE_URL = "https://api.football-data.org/v4"

LEAGUES = {
    "WC":  "MS 2026",
    "PL":  "Premier League",
    "PD":  "La Liga",
    "BL1": "Bundesliga",
    "SA":  "Serie A",
    "FL1": "Ligue 1",
}

SYNC_INTERVAL = timedelta(minutes=5)
_last_sync = None


def sync_matches():
    """Stiahne/obnovi zapasy (max raz za 10 min kvoli rate limitu) a vyhodnoti tipy."""
    global _last_sync
    now = utcnow()
    if _last_sync is None or now - _last_sync >= SYNC_INTERVAL:
        if API_KEY:
            _fetch_from_api()
            _fetch_standings("WC")
        else:
            _ensure_demo_data()
        _last_sync = now
    _evaluate_tips()


def _fetch_from_api():
    """Stiahne celu aktualnu sezonu kazdej sutaze (1 request na ligu = 6 requestov,
    bezpecne pod limitom 10/min). Mimo sezony by uzsie datumove okno nevratilo nic."""
    headers = {"X-Auth-Token": API_KEY}
    oldest = utcnow() - timedelta(days=30)

    for code in LEAGUES:
        try:
            resp = requests.get(
                f"{BASE_URL}/competitions/{code}/matches",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
        except requests.RequestException as e:
            print(f"[API] Chyba pri lige {code}: {e}")
            continue

        for m in resp.json().get("matches", []):
            utc_date = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).replace(tzinfo=None)
            if utc_date < oldest:
                continue  # stare zapasy nepotrebujeme, drzime DB malu
            _upsert_match(m, code)

    db.session.commit()


def _upsert_match(m, league_code):
    match = Match.query.filter_by(api_id=m["id"]).first()
    if match is None:
        match = Match(api_id=m["id"], league=league_code)
        db.session.add(match)

    # vyradovacie zapasy MS este nemusia mat zname timy (None = "postupujuci")
    match.home_team = po_slovensky(m["homeTeam"].get("name"))
    match.away_team = po_slovensky(m["awayTeam"].get("name"))
    match.venue = m.get("venue")
    match.crest_home = m["homeTeam"].get("crest")
    match.crest_away = m["awayTeam"].get("crest")
    match.utc_date = datetime.fromisoformat(m["utcDate"].replace("Z", "+00:00")).replace(tzinfo=None)
    match.status = m["status"]
    match.matchday = m.get("matchday")
    match.stage = m.get("stage")
    match.group_name = m.get("group")

    score = m.get("score", {})
    full_time = score.get("fullTime", {})
    match.score_home = full_time.get("home")
    match.score_away = full_time.get("away")
    match.winner_side = score.get("winner")


def _fetch_standings(league_code):
    """Stiahne tabulky skupin a nahradi nimi ulozene poradie."""
    try:
        resp = requests.get(f"{BASE_URL}/competitions/{league_code}/standings",
                            headers={"X-Auth-Token": API_KEY}, timeout=15)
        resp.raise_for_status()
    except requests.RequestException as e:
        print(f"[API] Chyba pri tabulkach {league_code}: {e}")
        return

    rows = []
    for standing in resp.json().get("standings", []):
        if standing.get("type") != "TOTAL":
            continue
        for row in standing.get("table", []):
            rows.append(Standing(
                league=league_code,
                group_name=standing.get("group"),
                position=row["position"],
                team_name=po_slovensky(row["team"]["name"]),
                crest=row["team"].get("crest"),
                played=row.get("playedGames", 0),
                won=row.get("won", 0),
                draw=row.get("draw", 0),
                lost=row.get("lost", 0),
                goals_for=row.get("goalsFor", 0),
                goals_against=row.get("goalsAgainst", 0),
                goal_diff=row.get("goalDifference", 0),
                points=row.get("points", 0),
            ))

    if rows:  # stare poradie nahradime az ked mame nove
        Standing.query.filter_by(league=league_code).delete()
        db.session.add_all(rows)
        db.session.commit()


def _evaluate_tips():
    """Prideli body za tipy na dohrane zapasy.

    Spravny vysledok (1/X/2) = kurz x 2 zaokruhlene, presne skore = bonus +5 b.
    """
    now = utcnow()
    tips = (Tip.query.join(Match)
            .filter(Tip.evaluated.is_(False), Match.status == "FINISHED")
            .all())
    for tip in tips:
        match = tip.match
        outcome = match.outcome
        if outcome is None:
            continue
        tip.evaluated = True
        tip.evaluated_at = now
        if tip.vyber == outcome:
            points = round(match.odds[tip.vyber] * 2)
            if (tip.score_home is not None
                    and tip.score_home == match.score_home
                    and tip.score_away == match.score_away):
                points += 5
            tip.points_awarded = points
            tip.user.points += points
    if tips:
        db.session.commit()
    _award_champions()


CHAMPION_POINTS = 25


def _award_champions():
    """Po finale MS prideli +25 b vsetkym, co tipli majstra sveta."""
    final = Match.query.filter_by(league="WC", stage="FINAL", status="FINISHED").first()
    if final is None or not final.winner_name:
        return
    winners = User.query.filter(User.champion_pick == final.winner_name,
                                User.champion_awarded.is_(False)).all()
    for user in winners:
        user.points += CHAMPION_POINTS
        user.champion_awarded = True
    if winners:
        db.session.commit()
        print(f"[MAJSTER] {len(winners)} hracov dostalo +{CHAMPION_POINTS} b za tip na majstra.")


# ----------------------------------------------------------------------
# Demo data - aby aplikacia fungovala aj bez API kluca
# ----------------------------------------------------------------------

DEMO_TEAMS = {
    "PL":  ["Arsenal", "Liverpool", "Man City", "Chelsea", "Tottenham", "Man United"],
    "PD":  ["Real Madrid", "Barcelona", "Atletico Madrid", "Sevilla", "Valencia", "Villarreal"],
    "BL1": ["Bayern", "Dortmund", "Leverkusen", "Leipzig", "Frankfurt", "Stuttgart"],
    "SA":  ["Inter", "AC Milan", "Juventus", "Napoli", "Roma", "Lazio"],
    "FL1": ["PSG", "Marseille", "Lyon", "Monaco", "Lille", "Nice"],
}


def _ensure_demo_data():
    if Match.query.first() is not None:
        _finish_old_demo_matches()
        return

    rng = random.Random(42)
    now = utcnow()
    for code, teams in DEMO_TEAMS.items():
        pairs = [(teams[0], teams[1]), (teams[2], teams[3]), (teams[4], teams[5]),
                 (teams[1], teams[2]), (teams[3], teams[0]), (teams[5], teams[4])]
        for i, (home, away) in enumerate(pairs):
            finished = i < 2  # prve dva zapasy kazdej ligy su uz dohrane
            match = Match(
                league=code,
                home_team=home,
                away_team=away,
                utc_date=now - timedelta(days=2 - i) if finished else now + timedelta(days=i),
                status="FINISHED" if finished else "SCHEDULED",
                score_home=rng.randint(0, 4) if finished else None,
                score_away=rng.randint(0, 3) if finished else None,
            )
            db.session.add(match)
    db.session.commit()
    print("[DEMO] Vytvorene demo zapasy (bez API kluca).")


def _finish_old_demo_matches():
    """V demo rezime 'dohra' zapasy, ktorych cas uz presiel."""
    rng = random.Random()
    stale = Match.query.filter(Match.status != "FINISHED",
                               Match.utc_date < utcnow() - timedelta(hours=2)).all()
    for match in stale:
        match.status = "FINISHED"
        match.score_home = rng.randint(0, 4)
        match.score_away = rng.randint(0, 3)
    if stale:
        db.session.commit()
