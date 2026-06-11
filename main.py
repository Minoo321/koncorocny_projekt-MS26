"""MS 2026 Tipovacka - hlavna Flask aplikacia.

Koncorocny projekt: tipovanie zapasov Majstrovstiev sveta vo futbale 2026.
Zive data o zapasoch dodava football-data.org (api_client.py), pouzivatelia
tipuju vysledky cez tiket, zbieraju body podla kurzov a sutazia v rebricku
aj v sukromnych ligach.

Struktura projektu:
    main.py       - routy, prihlasovanie, statistiky hracov (tento subor)
    models.py     - databazove modely (SQLAlchemy)
    api_client.py - stahovanie zapasov/tabuliek z API + vyhodnocovanie tipov
    forms.py      - registracny a prihlasovaci formular (Flask-WTF)
    seed.py       - naplnenie databazy demo pouzivatelmi
    teams_sk.py   - slovenske nazvy narodnych timov
"""
import os
import secrets
import string
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from flask import Flask, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import LoginManager, current_user, login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from api_client import LEAGUES, sync_matches
from forms import LoginForm, RegisterForm
from models import db, Match, Message, PrivateLeague, Standing, Tip, User, utcnow

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-tajny-kluc-zmen-ma")
app.config["SQLALCHEMY_DATABASE_URI"] = "sqlite:///databaza.db"

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = "login"
login_manager.login_message = "Najprv sa prihlas."

with app.app_context():
    db.create_all()


@login_manager.user_loader
def load_user(user_id):
    """Flask-Login: nacita prihlaseneho pouzivatela zo session cookie."""
    return db.session.get(User, int(user_id))


# ----------------------------------------------------------------------
# Lokalny cas (DB drzi UTC, zobrazujeme slovensky cas)
# ----------------------------------------------------------------------

TZ = ZoneInfo("Europe/Bratislava")
DNI = ["Pondelok", "Utorok", "Streda", "Štvrtok", "Piatok", "Sobota", "Nedeľa"]


def to_local(dt):
    """Prevedie nativny UTC cas z databazy na slovensky lokalny cas."""
    return dt.replace(tzinfo=timezone.utc).astimezone(TZ)


def local_day_to_utc(day):
    """Zaciatok daneho lokalneho dna prevedeny na nativny UTC."""
    start = datetime.combine(day, time.min, tzinfo=TZ)
    return start.astimezone(timezone.utc).replace(tzinfo=None)


@app.template_filter("lokalny")
def filter_lokalny(dt, fmt="%H:%M"):
    """Jinja filter: '{{ zapas.utc_date | lokalny }}' -> '21:00' v SK case."""
    return to_local(dt).strftime(fmt)


@app.template_filter("den_nazov")
def filter_den_nazov(day):
    """Jinja filter: datum -> 'Stvrtok 11.06.2026' (hlavicky dni v ponuke)."""
    return f"{DNI[day.weekday()]} {day.strftime('%d.%m.%Y')}"


@app.template_filter("skupina")
def filter_skupina(group_name):
    """Jinja filter: 'GROUP_A' z API -> 'Skupina A'."""
    return group_name.replace("GROUP_", "Skupina ").replace("_", " ").title()


STAGES = {
    "GROUP_STAGE": "Skupinová fáza",
    "LAST_32": "Šestnásťfinále",
    "LAST_16": "Osemfinále",
    "QUARTER_FINALS": "Štvrťfinále",
    "SEMI_FINALS": "Semifinále",
    "THIRD_PLACE": "O 3. miesto",
    "FINAL": "Finále",
}
KNOCKOUT_ORDER = ["LAST_32", "LAST_16", "QUARTER_FINALS", "SEMI_FINALS", "THIRD_PLACE", "FINAL"]


@app.template_filter("faza")
def filter_faza(stage):
    """Jinja filter: 'QUARTER_FINALS' z API -> 'Stvrtfinale'."""
    return STAGES.get(stage, (stage or "").replace("_", " ").title())


@app.template_filter("avatar_farba")
def filter_avatar_farba(username):
    """Stabilna farba avatara odvodena z mena."""
    hue = sum(ord(c) * 17 for c in username) % 360
    return f"hsl({hue}, 55%, 38%)"


# ----------------------------------------------------------------------
# Statistiky hraca: serie, uspesnost, ocenenia
# ----------------------------------------------------------------------

def compute_streaks(tips):
    """(najdlhsia seria, aktualna seria) zo zoznamu vyhodnotenych tipov."""
    evaluated = sorted((t for t in tips if t.evaluated), key=lambda t: t.match.utc_date)
    longest = current = run = 0
    for tip in evaluated:
        if tip.points_awarded > 0:
            run += 1
            longest = max(longest, run)
        else:
            run = 0
    current = run  # seria na konci = stale aktivna
    return longest, current


def user_stats(user):
    """Suhrnne statistiky hraca pre rebricek a profil (uspesnost, serie...)."""
    evaluated = [t for t in user.tips if t.evaluated]
    correct = sum(1 for t in evaluated if t.points_awarded > 0)
    longest, current = compute_streaks(user.tips)

    best_day = 0
    per_day = {}
    for tip in evaluated:
        if tip.points_awarded > 0:
            day = tip.match.utc_date.date()
            per_day[day] = per_day.get(day, 0) + tip.points_awarded
    if per_day:
        best_day = max(per_day.values())

    return {
        "tips": len(user.tips),
        "evaluated": len(evaluated),
        "correct": correct,
        "wrong": len(evaluated) - correct,
        "success": round(100 * correct / len(evaluated)) if evaluated else 0,
        "longest_streak": longest,
        "current_streak": current,
        "best_day": best_day,
    }


def compute_achievements(user, stats, rank):
    """Zoznam odznakov - (emoji, nazov, popis, ziskany?)."""
    exact_hit = any(
        t.evaluated and t.points_awarded > 0 and t.score_home is not None
        and t.score_home == t.match.score_home and t.score_away == t.match.score_away
        for t in user.tips)
    big_odds_win = any(
        t.evaluated and t.points_awarded > 0 and t.match.odds[t.vyber] > 3.0
        for t in user.tips)

    return [
        ("🎯", "Prvý tip", "Podaj svoj prvý tip", stats["tips"] >= 1),
        ("✅", "10 správnych", "Traf 10 tipov", stats["correct"] >= 10),
        ("🔥", "Séria 3", "3 správne tipy v rade", stats["longest_streak"] >= 3),
        ("🌋", "Séria 5", "5 správnych tipov v rade", stats["longest_streak"] >= 5),
        ("🎰", "Presný zásah", "Traf presné skóre", exact_hit),
        ("💎", "Lovec kurzov", "Vyhraj tip s kurzom nad 3.0", big_odds_win),
        ("👑", "Top 3", "Dostaň sa do top 3 rebríčka", rank is not None and rank <= 3),
    ]


def team_crest(team_name):
    """Najde logo timu podla mena (z ulozenych zapasov)."""
    if not team_name:
        return None
    match = Match.query.filter(Match.home_team == team_name).first()
    if match:
        return match.crest_home
    match = Match.query.filter(Match.away_team == team_name).first()
    return match.crest_away if match else None


# ----------------------------------------------------------------------
# Zakladne stranky
# ----------------------------------------------------------------------

@app.route("/")
def index():
    """Domovska stranka - MS hero, najblizsie zapasy, live skore, top hraci."""
    top_users = User.query.order_by(User.points.desc()).limit(3).all()
    stats = {
        "users": User.query.count(),
        "tips": Tip.query.count(),
        "matches": Match.query.filter(Match.league == "WC").count(),
    }
    next_wc = (Match.query
               .filter(Match.league == "WC", Match.status != "FINISHED",
                       Match.utc_date >= utcnow())
               .order_by(Match.utc_date).limit(5).all())
    live_wc = (Match.query
               .filter(Match.league == "WC", Match.status.in_(LIVE_STATUSY))
               .order_by(Match.utc_date).all())
    return render_template("index.html", top_users=top_users, stats=stats,
                           next_wc=next_wc, live_wc=live_wc)


# ----------------------------------------------------------------------
# Registracia / prihlasenie
# ----------------------------------------------------------------------

@app.route("/registracia", methods=["GET", "POST"])
def register():
    """Registracia - meno a email musia byt unikatne (bez ohladu na velkost pismen)."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = RegisterForm()
    if form.validate_on_submit():
        if User.query.filter(db.func.lower(User.username)
                             == form.username.data.strip().lower()).first():
            flash("Toto meno je uz obsadene.", "danger")
        elif User.query.filter(db.func.lower(User.email)
                               == form.email.data.strip().lower()).first():
            flash("Tento email je uz registrovany.", "danger")
        else:
            user = User(
                username=form.username.data,
                email=form.email.data,
                password_hash=generate_password_hash(form.password.data),
                last_login_at=utcnow(),
            )
            db.session.add(user)
            db.session.commit()
            login_user(user)
            flash("Registracia prebehla uspesne, vitaj!", "success")
            return redirect(url_for("matches"))
    return render_template("register.html", form=form)


@app.route("/prihlasenie", methods=["GET", "POST"])
def login():
    """Prihlasenie menom alebo emailom + banner 'odkedy si tu nebol'."""
    if current_user.is_authenticated:
        return redirect(url_for("index"))
    form = LoginForm()
    if form.validate_on_submit():
        # prihlasenie menom alebo emailom, bez ohladu na velke/male pismena
        login_id = form.username.data.strip()
        user = User.query.filter(db.or_(
            db.func.lower(User.username) == login_id.lower(),
            db.func.lower(User.email) == login_id.lower())).first()
        if user and check_password_hash(user.password_hash, form.password.data):
            login_user(user)
            flash("Prihlasenie uspesne.", "success")

            # "odkedy si tu nebol" - zhrnutie vyhodnotenych tipov
            prev_login = user.last_login_at
            user.last_login_at = utcnow()
            db.session.commit()
            if prev_login:
                fresh = [t for t in user.tips
                         if t.evaluated and t.evaluated_at and t.evaluated_at > prev_login]
                if fresh:
                    points = sum(t.points_awarded for t in fresh)
                    correct = sum(1 for t in fresh if t.points_awarded > 0)
                    flash(f"Odkedy si tu nebol, vyhodnotili sme {len(fresh)} tvojich tipov: "
                          f"{correct} správnych, spolu +{points} bodov 🎉", "info")

            return redirect(url_for("matches"))
        flash("Nespravne meno alebo heslo.", "danger")
    return render_template("login.html", form=form)


@app.route("/odhlasenie")
@login_required
def logout():
    logout_user()
    flash("Bol si odhlaseny.", "info")
    return redirect(url_for("index"))


# ----------------------------------------------------------------------
# Zapasy a tipovanie
# ----------------------------------------------------------------------

LIVE_STATUSY = ("IN_PLAY", "PAUSED", "LIVE")


@app.route("/zapasy")
def matches():
    """Ponuka zapasov - filter podla sutaze a dna, live sekcia, tiket panel.

    Parametre v URL: ?liga=WC|PL|... &den=dnes|zajtra|tyzden|vsetko &datum=RRRR-MM-DD
    """
    sync_matches()

    default_league = next(iter(LEAGUES))
    league = request.args.get("liga", default_league)
    if league not in LEAGUES:
        league = default_league

    # filter dna: dnes / zajtra / tyzden / vsetko, alebo konkretny datum
    den = request.args.get("den", "vsetko")
    datum_str = request.args.get("datum", "")
    now = utcnow()
    local_today = to_local(now).date()

    date_from, date_to = now, None
    if datum_str:
        try:
            day = datetime.strptime(datum_str, "%Y-%m-%d").date()
            date_from = max(local_day_to_utc(day), now)
            date_to = local_day_to_utc(day + timedelta(days=1))
            den = "datum"
        except ValueError:
            datum_str = ""
    elif den == "dnes":
        date_to = local_day_to_utc(local_today + timedelta(days=1))
    elif den == "zajtra":
        date_from = local_day_to_utc(local_today + timedelta(days=1))
        date_to = local_day_to_utc(local_today + timedelta(days=2))
    elif den == "tyzden":
        date_to = now + timedelta(days=7)
    else:
        den = "vsetko"

    query = Match.query.filter(Match.league == league,
                               Match.status != "FINISHED",
                               Match.status.notin_(LIVE_STATUSY),
                               Match.utc_date >= date_from)
    if date_to:
        query = query.filter(Match.utc_date < date_to)
    upcoming = query.order_by(Match.utc_date).all()

    # zoskupenie podla lokalneho dna -> [(datum, [zapasy]), ...]
    days = []
    for match in upcoming:
        day = to_local(match.utc_date).date()
        if not days or days[-1][0] != day:
            days.append((day, []))
        days[-1][1].append(match)

    live = (Match.query
            .filter(Match.league == league, Match.status.in_(LIVE_STATUSY))
            .order_by(Match.utc_date).all())
    finished = (Match.query
                .filter(Match.league == league, Match.status == "FINISHED")
                .order_by(Match.utc_date.desc()).limit(10).all())

    my_tips = {}
    if current_user.is_authenticated:
        tips = Tip.query.filter_by(user_id=current_user.id).all()
        my_tips = {t.match_id: t for t in tips}

    return render_template("matches.html", leagues=LEAGUES, league=league,
                           den=den, datum=datum_str, days=days, live=live,
                           finished=finished, my_tips=my_tips)


@app.route("/tipnut/<int:match_id>", methods=["POST"])
@login_required
def tip(match_id):
    """Jednotlivy tip cez formular (zalozna cesta - hlavna je /api/tiket)."""
    match = db.session.get(Match, match_id)
    if match is None:
        abort(404)

    vyber = request.form.get("vyber")
    if vyber not in ("1", "X", "2"):
        flash("Vyber najprv tip 1, X alebo 2.", "warning")
        return redirect(request.referrer or url_for("matches", liga=match.league))

    if (not match.has_teams or match.status == "FINISHED" or match.is_live
            or match.utc_date <= utcnow()):
        flash("Tento zápas sa už nedá tipovať.", "warning")
        return redirect(request.referrer or url_for("matches", liga=match.league))

    # nepovinne presne skore (musia byt vyplnene obe polia)
    def _parse_score(name):
        raw = (request.form.get(name) or "").strip()
        if raw == "":
            return None
        try:
            value = int(raw)
        except ValueError:
            return None
        return value if 0 <= value <= 20 else None

    skore_domaci = _parse_score("skore_domaci")
    skore_hostia = _parse_score("skore_hostia")
    if skore_domaci is None or skore_hostia is None:
        skore_domaci = skore_hostia = None

    existing = Tip.query.filter_by(user_id=current_user.id, match_id=match.id).first()
    if existing:
        existing.vyber = vyber
        existing.score_home = skore_domaci
        existing.score_away = skore_hostia
    else:
        db.session.add(Tip(user_id=current_user.id, match_id=match.id, vyber=vyber,
                           score_home=skore_domaci, score_away=skore_hostia))
    db.session.commit()

    detail = f" ({skore_domaci}:{skore_hostia})" if skore_domaci is not None else ""
    flash(f"Tip '{vyber}'{detail} na {match.home_team} – {match.away_team} uložený. "
          f"Kurz {match.odds[vyber]}.", "success")
    return redirect(request.referrer or url_for("matches", liga=match.league))


@app.route("/api/tiket", methods=["POST"])
@login_required
def podaj_tiket():
    """Podanie celeho tiketu naraz - zoznam tipov z lokalneho 'kosika'."""
    data = request.get_json(silent=True) or {}
    items = data.get("tipy") or []
    if not isinstance(items, list) or not items:
        return jsonify({"error": "Tiket je prázdny."}), 400

    def _score(value):
        if value in (None, ""):
            return None
        try:
            value = int(value)
        except (TypeError, ValueError):
            return None
        return value if 0 <= value <= 20 else None

    saved, skipped = 0, 0
    now = utcnow()
    for item in items[:50]:
        match = db.session.get(Match, item.get("match_id"))
        vyber = item.get("vyber")
        if (match is None or vyber not in ("1", "X", "2")
                or not match.has_teams
                or match.status == "FINISHED" or match.is_live
                or match.utc_date <= now):
            skipped += 1
            continue

        skore_domaci = _score(item.get("skore_domaci"))
        skore_hostia = _score(item.get("skore_hostia"))
        if skore_domaci is None or skore_hostia is None:
            skore_domaci = skore_hostia = None

        existing = Tip.query.filter_by(user_id=current_user.id, match_id=match.id).first()
        if existing:
            existing.vyber = vyber
            existing.score_home = skore_domaci
            existing.score_away = skore_hostia
        else:
            db.session.add(Tip(user_id=current_user.id, match_id=match.id, vyber=vyber,
                               score_home=skore_domaci, score_away=skore_hostia))
        saved += 1

    db.session.commit()
    if saved:
        text = f"Tiket podaný — {saved} tipov uložených."
        if skipped:
            text += f" ({skipped} preskočených — zápas sa už hrá alebo neexistuje.)"
        flash(text, "success")
    return jsonify({"saved": saved, "skipped": skipped})


# ----------------------------------------------------------------------
# Detail zapasu, skupiny, pavuk, moje tipy
# ----------------------------------------------------------------------

@app.route("/zapas/<int:match_id>")
def match_detail(match_id):
    """Detail zapasu - skore/cas, rozlozenie tipov, H2H, diskusia, tipovanie."""
    match = db.session.get(Match, match_id)
    if match is None:
        abort(404)

    my_tip = None
    if current_user.is_authenticated:
        my_tip = Tip.query.filter_by(user_id=current_user.id, match_id=match.id).first()

    # rozlozenie tipov vsetkych hracov (kolko % veri 1/X/2)
    all_tips = Tip.query.filter_by(match_id=match.id).all()
    distribution = {"1": 0, "X": 0, "2": 0}
    for t in all_tips:
        distribution[t.vyber] += 1
    total_tips = len(all_tips)
    percent = {k: round(100 * v / total_tips) if total_tips else 0
               for k, v in distribution.items()}

    # vzajomne zapasy z nasej DB
    h2h = []
    if match.has_teams:
        h2h = (Match.query
               .filter(Match.id != match.id, Match.status == "FINISHED",
                       db.or_(
                           db.and_(Match.home_team == match.home_team,
                                   Match.away_team == match.away_team),
                           db.and_(Match.home_team == match.away_team,
                                   Match.away_team == match.home_team)))
               .order_by(Match.utc_date.desc()).limit(5).all())

    can_tip = (match.has_teams and match.status != "FINISHED"
               and not match.is_live and match.utc_date > utcnow())

    return render_template("zapas.html", match=match, my_tip=my_tip,
                           percent=percent, total_tips=total_tips,
                           h2h=h2h, can_tip=can_tip)


@app.route("/skupiny")
def groups():
    """Tabulky 12 skupin MS (data z API /standings)."""
    sync_matches()
    rows = (Standing.query.filter_by(league="WC")
            .order_by(Standing.group_name, Standing.position).all())
    skupiny = []
    for row in rows:
        if not skupiny or skupiny[-1][0] != row.group_name:
            skupiny.append((row.group_name, []))
        skupiny[-1][1].append(row)
    return render_template("skupiny.html", skupiny=skupiny)


@app.route("/pavuk")
def bracket():
    """Vyradovaci pavuk - kola zoradene zlava doprava az po finale."""
    sync_matches()
    matches = (Match.query
               .filter(Match.league == "WC", Match.stage.in_(KNOCKOUT_ORDER))
               .order_by(Match.utc_date).all())
    stages = [(stage, [m for m in matches if m.stage == stage])
              for stage in KNOCKOUT_ORDER]
    stages = [(s, ms) for s, ms in stages if ms]
    return render_template("pavuk.html", stages=stages)


@app.route("/moje-tipy")
@login_required
def my_tips_page():
    """Historia vlastnych tipov so suhrnnymi statistikami."""
    tips = (Tip.query.join(Match)
            .filter(Tip.user_id == current_user.id)
            .order_by(Match.utc_date.desc()).all())
    evaluated = [t for t in tips if t.evaluated]
    correct = sum(1 for t in evaluated if t.points_awarded > 0)
    summary = {
        "total": len(tips),
        "pending": len(tips) - len(evaluated),
        "correct": correct,
        "wrong": len(evaluated) - correct,
        "success": round(100 * correct / len(evaluated)) if evaluated else 0,
    }
    return render_template("moje_tipy.html", tips=tips, summary=summary)


# ----------------------------------------------------------------------
# Sukromne ligy - vlastny rebricek pre triedu/partiu, vstup cez kod
# ----------------------------------------------------------------------

def _generate_league_code():
    """Vygeneruje unikatny 6-znakovy vstupny kod (bez 0/O/1/I, aby sa neplietli)."""
    alphabet = "".join(c for c in string.ascii_uppercase + string.digits
                       if c not in "0O1I")
    while True:
        code = "".join(secrets.choice(alphabet) for _ in range(6))
        if not PrivateLeague.query.filter_by(code=code).first():
            return code


@app.route("/ligy")
@login_required
def private_leagues():
    """Prehlad mojich sukromnych lig + formulare na vytvorenie/vstup."""
    return render_template("ligy.html", moje_ligy=current_user.leagues)


@app.route("/ligy/vytvorit", methods=["POST"])
@login_required
def create_league():
    """Zalozenie ligy - zakladatel je automaticky clenom, dostane vstupny kod."""
    name = request.form.get("nazov", "").strip()
    if not 3 <= len(name) <= 50:
        flash("Názov ligy musí mať 3 až 50 znakov.", "warning")
        return redirect(url_for("private_leagues"))
    if len(current_user.owned_leagues) >= 5:
        flash("Môžeš vlastniť najviac 5 líg.", "warning")
        return redirect(url_for("private_leagues"))

    league = PrivateLeague(name=name, code=_generate_league_code(),
                           owner_id=current_user.id)
    league.members.append(current_user)
    db.session.add(league)
    db.session.commit()
    flash(f"Liga '{name}' vytvorená! Zdieľaj kód {league.code} so spoluhráčmi.", "success")
    return redirect(url_for("league_detail", league_id=league.id))


@app.route("/ligy/pridat", methods=["POST"])
@login_required
def join_league():
    """Vstup do ligy cez 6-znakovy kod."""
    code = request.form.get("kod", "").strip().upper()
    league = PrivateLeague.query.filter_by(code=code).first()
    if league is None:
        flash("Liga s týmto kódom neexistuje.", "warning")
        return redirect(url_for("private_leagues"))
    if current_user in league.members:
        flash("V tejto lige už si.", "info")
    else:
        league.members.append(current_user)
        db.session.commit()
        flash(f"Vitaj v lige '{league.name}'!", "success")
    return redirect(url_for("league_detail", league_id=league.id))


@app.route("/liga/<int:league_id>")
@login_required
def league_detail(league_id):
    """Rebricek konkretnej ligy - len pre jej clenov."""
    league = db.session.get(PrivateLeague, league_id)
    if league is None:
        abort(404)
    if current_user not in league.members:
        flash("Do tejto ligy najprv vstúp pomocou kódu.", "warning")
        return redirect(url_for("private_leagues"))

    members = sorted(league.members, key=lambda u: (-u.points, u.username))
    rows = [{"rank": i, "user": u, "stats": user_stats(u)}
            for i, u in enumerate(members, start=1)]
    return render_template("liga.html", league=league, rows=rows)


@app.route("/liga/<int:league_id>/odist", methods=["POST"])
@login_required
def leave_league(league_id):
    """Odchod z ligy (vlastnik odist nemoze - musi ligu zmazat)."""
    league = db.session.get(PrivateLeague, league_id)
    if league is None or current_user not in league.members:
        abort(404)
    if league.owner_id == current_user.id:
        flash("Vlastník ligu nemôže opustiť — môže ju len zmazať.", "warning")
        return redirect(url_for("league_detail", league_id=league.id))
    league.members.remove(current_user)
    db.session.commit()
    flash(f"Opustil si ligu '{league.name}'.", "info")
    return redirect(url_for("private_leagues"))


@app.route("/liga/<int:league_id>/zmazat", methods=["POST"])
@login_required
def delete_league(league_id):
    """Zmazanie ligy - moze len vlastnik."""
    league = db.session.get(PrivateLeague, league_id)
    if league is None:
        abort(404)
    if league.owner_id != current_user.id:
        abort(403)
    name = league.name
    db.session.delete(league)
    db.session.commit()
    flash(f"Liga '{name}' zmazaná.", "info")
    return redirect(url_for("private_leagues"))


# ----------------------------------------------------------------------
# JSON API pre live skore a graf rebricka
# ----------------------------------------------------------------------

@app.route("/api/live")
def api_live():
    """JSON so zapasmi, ktore sa prave hraju (pouziva live.js na auto-refresh)."""
    sync_matches()
    league = request.args.get("liga", "WC")
    if league not in LEAGUES:
        league = "WC"
    matches = (Match.query
               .filter(Match.league == league, Match.status.in_(LIVE_STATUSY))
               .order_by(Match.utc_date).all())
    return jsonify([
        {
            "id": m.id,
            "home": m.home_team,
            "away": m.away_team,
            "crest_home": m.crest_home,
            "crest_away": m.crest_away,
            "score_home": m.score_home if m.score_home is not None else 0,
            "score_away": m.score_away if m.score_away is not None else 0,
            "group": filter_skupina(m.group_name) if m.group_name else
                     (filter_faza(m.stage) if m.stage and m.stage != "GROUP_STAGE" else ""),
        }
        for m in matches
    ])


@app.route("/zrusit-tip/<int:match_id>", methods=["POST"])
@login_required
def cancel_tip(match_id):
    """Zrusenie vlastneho tipu - len kym sa zapas nezacal."""
    tip = Tip.query.filter_by(user_id=current_user.id, match_id=match_id).first()
    if tip is None:
        abort(404)
    match = tip.match
    if match.status == "FINISHED" or match.is_live or match.utc_date <= utcnow():
        flash("Zápas sa už hrá — tip sa nedá zrušiť.", "warning")
    else:
        db.session.delete(tip)
        db.session.commit()
        flash(f"Tip na {match.home_team} – {match.away_team} zrušený.", "info")
    return redirect(request.referrer or url_for("matches", liga=match.league))


# ----------------------------------------------------------------------
# Profily
# ----------------------------------------------------------------------

@app.route("/hrac/<username>")
def player_profile(username):
    """Verejny profil hraca - statistiky, ocenenia, posledne tipy."""
    user = User.query.filter_by(username=username).first()
    if user is None:
        abort(404)

    rank = (User.query.filter(db.or_(User.points > user.points,
                                     db.and_(User.points == user.points,
                                             User.username < user.username)))
            .count()) + 1
    stats = user_stats(user)
    achievements = compute_achievements(user, stats, rank)

    # najcastejsie tipovany tim ("komu veri")
    counts = {}
    for tip in user.tips:
        team = tip.match.home_team if tip.vyber == "1" else (
            tip.match.away_team if tip.vyber == "2" else None)
        if team:
            counts[team] = counts.get(team, 0) + 1
    most_tipped = max(counts, key=counts.get) if counts else None

    recent = (Tip.query.join(Match)
              .filter(Tip.user_id == user.id)
              .order_by(Match.utc_date.desc()).limit(10).all())

    return render_template("hrac.html", player=user, rank=rank, stats=stats,
                           achievements=achievements,
                           favorite_crest=team_crest(user.favorite_team),
                           champion_crest=team_crest(user.champion_pick),
                           most_tipped=most_tipped,
                           most_tipped_crest=team_crest(most_tipped),
                           recent=recent)


def tournament_started():
    """True, ak sa uz odohral vykop prveho zapasu MS (zamyka tip na majstra)."""
    first = (db.session.query(db.func.min(Match.utc_date))
             .filter(Match.league == "WC").scalar())
    return first is not None and first <= utcnow()


@app.route("/profil", methods=["GET", "POST"])
@login_required
def profile_settings():
    """Nastavenia profilu - oblubeny tim, tip na majstra, zmena hesla.

    Jedna stranka, tri formulare - rozlisene hidden polom 'akcia'.
    """
    if request.method == "POST":
        action = request.form.get("akcia")

        if action == "tim":
            team = request.form.get("favorite_team", "").strip()
            if team and not Match.query.filter(db.or_(Match.home_team == team,
                                                      Match.away_team == team)).first():
                flash("Tento tím nepoznáme.", "warning")
            else:
                current_user.favorite_team = team or None
                db.session.commit()
                flash("Obľúbený tím uložený." if team else "Obľúbený tím odstránený.", "success")

        elif action == "majster":
            if tournament_started():
                flash("MS už začali — tip na majstra sa už nedá zmeniť.", "warning")
            else:
                team = request.form.get("champion_pick", "").strip()
                if team and not Match.query.filter(Match.league == "WC",
                                                   db.or_(Match.home_team == team,
                                                          Match.away_team == team)).first():
                    flash("Tento tím nehrá na MS.", "warning")
                else:
                    current_user.champion_pick = team or None
                    db.session.commit()
                    flash(f"Tip na majstra uložený: {team} (+25 b ak vyhrá)." if team
                          else "Tip na majstra odstránený.", "success")

        elif action == "heslo":
            old = request.form.get("stare_heslo", "")
            new = request.form.get("nove_heslo", "")
            confirm = request.form.get("nove_heslo2", "")
            if not check_password_hash(current_user.password_hash, old):
                flash("Staré heslo nie je správne.", "danger")
            elif len(new) < 6:
                flash("Nové heslo musí mať aspoň 6 znakov.", "danger")
            elif new != confirm:
                flash("Nové heslá sa nezhodujú.", "danger")
            else:
                current_user.password_hash = generate_password_hash(new)
                db.session.commit()
                flash("Heslo zmenené.", "success")

        return redirect(url_for("profile_settings"))

    # vyber timov MS pre select (zname timy zo zapasov WC)
    wc_matches = Match.query.filter(Match.league == "WC",
                                    Match.home_team.isnot(None)).all()
    teams = sorted({m.home_team for m in wc_matches} | {m.away_team for m in wc_matches if m.away_team})

    return render_template("profil.html", teams=teams,
                           favorite_crest=team_crest(current_user.favorite_team),
                           champion_crest=team_crest(current_user.champion_pick),
                           started=tournament_started())


# ----------------------------------------------------------------------
# Rebricek
# ----------------------------------------------------------------------

@app.route("/rebricek")
def leaderboard():
    """Celkovy rebricek + highlight karty (najdlhsia seria, najlepsi den...)."""
    users = User.query.order_by(User.points.desc(), User.username).all()

    crest_cache = {}

    def cached_crest(team):
        if team not in crest_cache:
            crest_cache[team] = team_crest(team)
        return crest_cache[team]

    rows = []
    for rank, user in enumerate(users, start=1):
        stats = user_stats(user)
        rows.append({"rank": rank, "user": user, "stats": stats,
                     "crest": cached_crest(user.favorite_team)})

    highlights = {}
    with_tips = [r for r in rows if r["stats"]["evaluated"] > 0]
    if with_tips:
        highlights["streak"] = max(with_tips, key=lambda r: r["stats"]["longest_streak"])
        highlights["best_day"] = max(with_tips, key=lambda r: r["stats"]["best_day"])
        experienced = [r for r in with_tips if r["stats"]["evaluated"] >= 10]
        if experienced:
            highlights["success"] = max(experienced, key=lambda r: r["stats"]["success"])

    return render_template("leaderboard.html", rows=rows, highlights=highlights)


# ----------------------------------------------------------------------
# Chat
# ----------------------------------------------------------------------

@app.route("/chat")
@login_required
def chat():
    """Globalny chat (spravy nacitava a posiela chat.js cez /api/chat)."""
    return render_template("chat.html")


@app.route("/api/chat", methods=["GET"])
@login_required
def chat_messages():
    """JSON poslednych 50 sprav - globalnych alebo k zapasu (?zapas=id)."""
    match_id = request.args.get("zapas", type=int)
    query = Message.query.filter(Message.match_id == match_id)  # None = globalny chat
    messages = query.order_by(Message.created_at.desc()).limit(50).all()
    messages.reverse()

    crest_cache = {}

    def fav_crest(user):
        if user.favorite_team not in crest_cache:
            crest_cache[user.favorite_team] = team_crest(user.favorite_team)
        return crest_cache[user.favorite_team]

    return jsonify([
        {
            "id": m.id,
            "user": m.user.username,
            "mine": m.user_id == current_user.id,
            "text": m.text,
            "time": m.created_at.strftime("%H:%M"),
            "crest": fav_crest(m.user),
        }
        for m in messages
    ])


@app.route("/api/chat", methods=["POST"])
@login_required
def chat_send():
    """Odoslanie spravy do globalneho chatu alebo k zapasu (match_id v JSON)."""
    data = request.get_json(silent=True) or {}
    text = (data.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Prazdna sprava."}), 400
    if len(text) > 500:
        return jsonify({"error": "Sprava je prilis dlha (max 500 znakov)."}), 400

    match_id = data.get("match_id")
    if match_id is not None and db.session.get(Match, match_id) is None:
        return jsonify({"error": "Zapas neexistuje."}), 400

    db.session.add(Message(user_id=current_user.id, text=text, match_id=match_id))
    db.session.commit()
    return jsonify({"ok": True})


if __name__ == "__main__":
    app.run(debug=True)
