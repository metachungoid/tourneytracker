import json
import math
import os
import random
from datetime import date as date_type
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import (
    LoginManager, UserMixin, login_user, logout_user,
    login_required, current_user,
)
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URI', 'sqlite:///tourneytracker.db')
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'tourney-super-secret-2025')

db = SQLAlchemy(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message_category = 'warning'


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

class Admin(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Admin, int(user_id))


class PlayerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    fargo_rating = db.Column(db.Integer, nullable=True)
    participations = db.relationship('Participant', backref='profile', lazy=True)

    @property
    def tournaments_entered(self):
        return len(self.participations)

    @property
    def match_wins(self):
        return Match.query.filter_by(winner_profile_id=self.id).count()

    @property
    def tournament_wins(self):
        return Tournament.query.filter_by(champion_id=self.id).count()

    @property
    def ranking_score(self):
        return self.tournament_wins * 1000 + self.match_wins


class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    buyin = db.Column(db.Integer, nullable=False, default=10)
    status = db.Column(db.String(20), default='open')   # open | bracket | complete
    tournament_date = db.Column(db.Date, nullable=True)
    format = db.Column(db.String(20), default='single')  # single | double | race3
    race_to = db.Column(db.Integer, default=3)            # for race3 format
    fargo_rated = db.Column(db.Integer, default=0)        # 0=no, 1=yes
    prize_splits = db.Column(db.Text, default='[{"place":1,"label":"1st","pct":70},{"place":2,"label":"2nd","pct":30}]')
    seeding = db.Column(db.String(20), default='random')  # random | rankings
    champion_id = db.Column(db.Integer, db.ForeignKey('player_profile.id'), nullable=True)
    runner_up_id = db.Column(db.Integer, db.ForeignKey('player_profile.id'), nullable=True)
    champion = db.relationship('PlayerProfile', foreign_keys=[champion_id])
    runner_up = db.relationship('PlayerProfile', foreign_keys=[runner_up_id])
    participants = db.relationship(
        'Participant', backref='tournament', lazy=True, cascade='all, delete-orphan'
    )
    matches = db.relationship(
        'Match', backref='tournament', lazy=True, cascade='all, delete-orphan'
    )

    @property
    def num_players(self):
        return len(self.participants)

    @property
    def gross_pool(self):
        return self.num_players * self.buyin

    @property
    def total_games(self):
        return max(self.num_players - 1, 0)

    @property
    def prize_pool(self):
        """Gross buy-ins while registration is open; deduct $1/game once bracket is locked."""
        if self.status in ('bracket', 'complete'):
            return max(self.gross_pool - self.total_games, 0)
        return self.gross_pool

    @property
    def splits(self):
        """Return list of dicts: [{place, label, pct}] sorted by place."""
        try:
            data = json.loads(self.prize_splits or '[]')
            return sorted(data, key=lambda x: x.get('place', 99))
        except Exception:
            return [{'place': 1, 'label': '1st', 'pct': 70},
                    {'place': 2, 'label': '2nd', 'pct': 30}]

    @property
    def prize_payouts(self):
        """Return list of dicts: [{place, label, pct, amount}]"""
        pool = self.prize_pool
        return [{**s, 'amount': round(pool * s['pct'] / 100)} for s in self.splits]

    @property
    def split_1st(self):
        s = self.splits
        return s[0]['pct'] if s else 70

    @property
    def split_2nd(self):
        s = self.splits
        return s[1]['pct'] if len(s) > 1 else 30

    @property
    def prize_1st(self):
        return round(self.prize_pool * self.split_1st / 100)

    @property
    def prize_2nd(self):
        return round(self.prize_pool * self.split_2nd / 100)

    @property
    def rounds(self):
        n = self.num_players
        return math.ceil(math.log2(n)) if n >= 2 else 0

    @property
    def is_upcoming(self):
        if self.status == 'complete':
            return False
        if self.tournament_date is None:
            return True
        return self.tournament_date >= date_type.today()

    @property
    def is_past(self):
        return self.status == 'complete'

    @property
    def format_label(self):
        return {'single': 'Single Elim', 'double': 'Double Elim', 'race3': 'Race to 3'}.get(
            self.format or 'single', self.format
        )


class Participant(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    profile_id = db.Column(db.Integer, db.ForeignKey('player_profile.id'), nullable=False)


class Match(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tournament_id = db.Column(db.Integer, db.ForeignKey('tournament.id'), nullable=False)
    bracket = db.Column(db.String(2), default='W')   # W=Winners  L=Losers  GF=Grand Final
    round_num = db.Column(db.Integer, nullable=False)
    position = db.Column(db.Integer, nullable=False)
    player1_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=True)
    player2_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=True)
    winner_id = db.Column(db.Integer, db.ForeignKey('participant.id'), nullable=True)
    winner_profile_id = db.Column(db.Integer, db.ForeignKey('player_profile.id'), nullable=True)
    next_match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=True)
    next_slot = db.Column(db.Integer, nullable=True)          # explicit slot (1/2) in next match
    loser_next_match_id = db.Column(db.Integer, db.ForeignKey('match.id'), nullable=True)
    loser_slot = db.Column(db.Integer, nullable=True)         # slot (1/2) loser fills in LB match
    score1 = db.Column(db.Integer, default=0)
    score2 = db.Column(db.Integer, default=0)

    player1 = db.relationship('Participant', foreign_keys=[player1_id])
    player2 = db.relationship('Participant', foreign_keys=[player2_id])
    winner = db.relationship('Participant', foreign_keys=[winner_id])


# ---------------------------------------------------------------------------
# Bracket helpers
# ---------------------------------------------------------------------------

def _set_winner(match, participant):
    match.winner_id = participant.id if participant else None
    match.winner_profile_id = participant.profile_id if participant else None


def _seeded_bracket_order(n):
    """Return seed numbers in bracket-slot order for a power-of-2 bracket of size n.
    Result: [1,8,4,5,2,7,3,6] for n=8 → matches (1v8),(4v5),(2v7),(3v6)."""
    positions = [1, 2]
    while len(positions) < n:
        size = len(positions)
        nxt = []
        for p in positions:
            nxt.extend([p, 2 * size + 1 - p])
        positions = nxt
    return positions


def _get_slots(tournament):
    """Return ordered Participant/None list for bracket slots."""
    parts = list(tournament.participants)
    n = len(parts)
    num_rounds = math.ceil(math.log2(n)) if n >= 2 else 1
    bracket_size = 2 ** num_rounds

    if (tournament.seeding or 'random') == 'rankings':
        ranked = sorted(parts, key=lambda p: (
            -Tournament.query.filter(
                Tournament.champion_id == p.profile_id,
                Tournament.id != tournament.id
            ).count(),
            -Match.query.filter(
                Match.winner_profile_id == p.profile_id,
                Match.tournament_id != tournament.id
            ).count()
        ))
        seed_order = _seeded_bracket_order(bracket_size)
        seeds_with_byes = ranked + [None] * (bracket_size - len(ranked))
        slots = [None] * bracket_size
        for i, seed_num in enumerate(seed_order):
            idx = seed_num - 1
            slots[i] = seeds_with_byes[idx] if idx < len(seeds_with_byes) else None
        return slots
    else:
        random.shuffle(parts)
        return parts + [None] * (bracket_size - len(parts))


def _maybe_auto_advance(match, tournament):
    """For LB/GF matches: if one slot is filled and the other has no pending feeders,
    auto-advance the filled player."""
    if match.winner_id or match.bracket == 'W':
        return
    p1 = match.player1_id
    p2 = match.player2_id
    if (p1 and p2) or (not p1 and not p2):
        return

    empty_slot = 2 if p1 else 1
    filled_id = p1 if p1 else p2

    loser_pending = Match.query.filter(
        Match.loser_next_match_id == match.id,
        Match.loser_slot == empty_slot,
        Match.winner_id == None   # noqa: E711
    ).count()
    winner_pending = Match.query.filter(
        Match.next_match_id == match.id,
        Match.next_slot == empty_slot,
        Match.winner_id == None   # noqa: E711
    ).count()

    if loser_pending + winner_pending == 0:
        filled_part = db.session.get(Participant, filled_id)
        if filled_part:
            _set_winner(match, filled_part)
            advance_winner(match, tournament)


def advance_winner(match, tournament):
    """Core advancement logic: push winner to next match, route loser to LB (double),
    mark champion when final is decided."""
    winner_part = db.session.get(Participant, match.winner_id) if match.winner_id else None

    # ── Double-elim: route loser to LB ───────────────────────────────────────
    if (tournament.format or 'single') == 'double' and match.bracket == 'W' and match.loser_next_match_id:
        loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
        loser_part = db.session.get(Participant, loser_id) if loser_id else None
        lb_m = db.session.get(Match, match.loser_next_match_id)
        if lb_m:
            if loser_part:
                if match.loser_slot == 1:
                    lb_m.player1_id = loser_part.id
                else:
                    lb_m.player2_id = loser_part.id
            _maybe_auto_advance(lb_m, tournament)

    # ── Grand Final ───────────────────────────────────────────────────────────
    if match.bracket == 'GF':
        if winner_part:
            match.tournament.champion_id = winner_part.profile_id
            loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
            loser_part = db.session.get(Participant, loser_id) if loser_id else None
            if loser_part:
                match.tournament.runner_up_id = loser_part.profile_id
        match.tournament.status = 'complete'
        return

    # ── No next match → terminal (single/race3 final) ────────────────────────
    if not match.next_match_id:
        if match.bracket != 'L':
            if winner_part:
                match.tournament.champion_id = winner_part.profile_id
                loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
                loser_part = db.session.get(Participant, loser_id) if loser_id else None
                if loser_part:
                    match.tournament.runner_up_id = loser_part.profile_id
            match.tournament.status = 'complete'
        return

    next_m = db.session.get(Match, match.next_match_id)
    if not next_m:
        return

    # ── Place winner in the next match ───────────────────────────────────────
    if match.next_slot == 1:
        next_m.player1_id = winner_part.id if winner_part else None
    elif match.next_slot == 2:
        next_m.player2_id = winner_part.id if winner_part else None
    else:
        # Position-based routing (WB → WB only)
        feeders = Match.query.filter_by(
            next_match_id=next_m.id, next_slot=None
        ).order_by(Match.position).all()
        if feeders and feeders[0].id == match.id:
            next_m.player1_id = winner_part.id if winner_part else None
        else:
            next_m.player2_id = winner_part.id if winner_part else None

    # ── Auto-advance byes / empty slots ──────────────────────────────────────
    if next_m.bracket == 'W':
        p1, p2 = next_m.player1_id, next_m.player2_id
        if (p1 and not p2) or (p2 and not p1):
            # Only a true bye if no other undecided match feeds into this one
            pending = Match.query.filter(
                Match.next_match_id == next_m.id,
                Match.winner_id == None  # noqa: E711
            ).count()
            if pending == 0:
                filled = db.session.get(Participant, p1 or p2)
                if filled:
                    _set_winner(next_m, filled)
                    advance_winner(next_m, tournament)
    else:
        _maybe_auto_advance(next_m, tournament)


# ---------------------------------------------------------------------------
# Winner correction
# ---------------------------------------------------------------------------

def _clear_forward(match):
    """Recursively remove a match's winner and all downstream effects."""
    if not match.winner_id:
        return

    winner_part_id = match.winner_id
    loser_part_id = (
        match.player2_id if match.winner_id == match.player1_id else match.player1_id
    )

    # Clear this match result
    match.winner_id = None
    match.winner_profile_id = None
    match.score1 = 0
    match.score2 = 0

    # Clear tournament status if it was decided by this match
    t = match.tournament
    if t.status == 'complete':
        t.status = 'bracket'
    t.champion_id = None
    t.runner_up_id = None

    # Cascade: remove winner from next WB/LB/GF match
    if match.next_match_id:
        next_m = db.session.get(Match, match.next_match_id)
        if next_m:
            removed = False
            if next_m.player1_id == winner_part_id:
                next_m.player1_id = None
                removed = True
            elif next_m.player2_id == winner_part_id:
                next_m.player2_id = None
                removed = True
            if removed:
                _clear_forward(next_m)

    # Cascade: remove loser from LB match (double elim only)
    if match.loser_next_match_id and loser_part_id:
        lb_m = db.session.get(Match, match.loser_next_match_id)
        if lb_m:
            removed = False
            if lb_m.player1_id == loser_part_id:
                lb_m.player1_id = None
                removed = True
            elif lb_m.player2_id == loser_part_id:
                lb_m.player2_id = None
                removed = True
            if removed:
                _clear_forward(lb_m)


# ---------------------------------------------------------------------------
# Bracket generators
# ---------------------------------------------------------------------------

def _generate_single_bracket(tournament):
    slots = _get_slots(tournament)
    bracket_size = len(slots)
    num_rounds = int(math.log2(bracket_size))

    round1 = []
    for i in range(0, bracket_size, 2):
        p1, p2 = slots[i], slots[i + 1]
        m = Match(
            tournament_id=tournament.id, bracket='W',
            round_num=1, position=i // 2,
            player1_id=p1.id if p1 else None,
            player2_id=p2.id if p2 else None,
            score1=0, score2=0,
        )
        if p1 and not p2:
            _set_winner(m, p1)
        elif p2 and not p1:
            _set_winner(m, p2)
        db.session.add(m)
        round1.append(m)
    db.session.flush()

    prev = round1
    for r in range(2, num_rounds + 1):
        curr = []
        for i in range(0, len(prev), 2):
            m = Match(
                tournament_id=tournament.id, bracket='W',
                round_num=r, position=i // 2,
                score1=0, score2=0,
            )
            db.session.add(m)
            db.session.flush()
            prev[i].next_match_id = m.id
            if i + 1 < len(prev):
                prev[i + 1].next_match_id = m.id
            p1 = db.session.get(Participant, prev[i].winner_id) if prev[i].winner_id else None
            p2 = db.session.get(Participant, prev[i + 1].winner_id) if (
                i + 1 < len(prev) and prev[i + 1].winner_id
            ) else None
            m.player1_id = p1.id if p1 else None
            m.player2_id = p2.id if p2 else None
            # Only auto-advance if both feeder matches are resolved
            # (have a winner or have no players at all). Otherwise the
            # empty slot belongs to a real match that hasn't been played.
            f1 = prev[i]
            f2 = prev[i + 1] if i + 1 < len(prev) else None
            f1_done = f1.winner_id is not None or (f1.player1_id is None and f1.player2_id is None)
            f2_done = f2 is None or f2.winner_id is not None or (f2.player1_id is None and f2.player2_id is None)
            if f1_done and f2_done:
                if p1 and not p2:
                    _set_winner(m, p1)
                elif p2 and not p1:
                    _set_winner(m, p2)
            curr.append(m)
        prev = curr

    tournament.status = 'bracket'
    db.session.commit()


def _generate_double_bracket(tournament):
    slots = _get_slots(tournament)
    bracket_size = len(slots)
    num_rounds = int(math.log2(bracket_size))

    # ── Winners Bracket ───────────────────────────────────────────────────────
    wr_rounds = {}

    wr1 = []
    for i in range(0, bracket_size, 2):
        p1, p2 = slots[i], slots[i + 1]
        m = Match(
            tournament_id=tournament.id, bracket='W',
            round_num=1, position=i // 2,
            player1_id=p1.id if p1 else None,
            player2_id=p2.id if p2 else None,
            score1=0, score2=0,
        )
        if p1 and not p2:
            _set_winner(m, p1)
        elif p2 and not p1:
            _set_winner(m, p2)
        db.session.add(m)
        wr1.append(m)
    db.session.flush()
    wr_rounds[1] = wr1

    prev = wr1
    for r in range(2, num_rounds + 1):
        curr = []
        for i in range(0, len(prev), 2):
            m = Match(
                tournament_id=tournament.id, bracket='W',
                round_num=r, position=i // 2,
                score1=0, score2=0,
            )
            db.session.add(m)
            db.session.flush()
            prev[i].next_match_id = m.id
            if i + 1 < len(prev):
                prev[i + 1].next_match_id = m.id
            p1 = db.session.get(Participant, prev[i].winner_id) if prev[i].winner_id else None
            p2 = db.session.get(Participant, prev[i + 1].winner_id) if (
                i + 1 < len(prev) and prev[i + 1].winner_id
            ) else None
            m.player1_id = p1.id if p1 else None
            m.player2_id = p2.id if p2 else None
            f1 = prev[i]
            f2 = prev[i + 1] if i + 1 < len(prev) else None
            f1_done = f1.winner_id is not None or (f1.player1_id is None and f1.player2_id is None)
            f2_done = f2 is None or f2.winner_id is not None or (f2.player1_id is None and f2.player2_id is None)
            if f1_done and f2_done:
                if p1 and not p2:
                    _set_winner(m, p1)
                elif p2 and not p1:
                    _set_winner(m, p2)
            curr.append(m)
        wr_rounds[r] = curr
        prev = curr

    # ── Losers Bracket ────────────────────────────────────────────────────────
    lb_round = 1

    # LB R1: pair WR1 losers among themselves
    lb_current = []
    for i in range(0, len(wr_rounds[1]), 2):
        m1 = wr_rounds[1][i]
        m2 = wr_rounds[1][i + 1] if i + 1 < len(wr_rounds[1]) else None
        m1_real = m1.player1_id is not None and m1.player2_id is not None
        m2_real = m2 is not None and m2.player1_id is not None and m2.player2_id is not None
        if not m1_real and not m2_real:
            continue
        lb_m = Match(
            tournament_id=tournament.id, bracket='L',
            round_num=lb_round, position=len(lb_current),
            score1=0, score2=0,
        )
        db.session.add(lb_m)
        db.session.flush()
        if m1_real:
            m1.loser_next_match_id = lb_m.id
            m1.loser_slot = 1
        if m2_real:
            m2.loser_next_match_id = lb_m.id
            m2.loser_slot = 2
        lb_current.append(lb_m)
    lb_round += 1

    # Subsequent LB rounds: alternating combination + pure
    for wr_r in range(2, num_rounds + 1):
        # Combination round: lb winners (slot 1) + WR losers (slot 2)
        wr_r_matches = wr_rounds[wr_r]
        new_lb = []
        for i in range(max(len(lb_current), len(wr_r_matches))):
            lb_prev = lb_current[i] if i < len(lb_current) else None
            wr_m = wr_r_matches[i] if i < len(wr_r_matches) else None
            wr_real = wr_m is not None and wr_m.player1_id is not None and wr_m.player2_id is not None
            if lb_prev is None and not wr_real:
                continue
            new_m = Match(
                tournament_id=tournament.id, bracket='L',
                round_num=lb_round, position=len(new_lb),
                score1=0, score2=0,
            )
            db.session.add(new_m)
            db.session.flush()
            if lb_prev:
                lb_prev.next_match_id = new_m.id
                lb_prev.next_slot = 1
            if wr_real:
                wr_m.loser_next_match_id = new_m.id
                wr_m.loser_slot = 2
            new_lb.append(new_m)
        lb_current = new_lb
        lb_round += 1

        # Pure round: pair lb_current down to half
        if len(lb_current) > 1:
            pure_lb = []
            for i in range(0, len(lb_current), 2):
                if i + 1 < len(lb_current):
                    new_m = Match(
                        tournament_id=tournament.id, bracket='L',
                        round_num=lb_round, position=len(pure_lb),
                        score1=0, score2=0,
                    )
                    db.session.add(new_m)
                    db.session.flush()
                    lb_current[i].next_match_id = new_m.id
                    lb_current[i].next_slot = 1
                    lb_current[i + 1].next_match_id = new_m.id
                    lb_current[i + 1].next_slot = 2
                    pure_lb.append(new_m)
                else:
                    pure_lb.append(lb_current[i])   # odd pass-through
            lb_current = pure_lb
            lb_round += 1

    # ── Grand Final ───────────────────────────────────────────────────────────
    gf = Match(
        tournament_id=tournament.id, bracket='GF',
        round_num=1, position=0,
        score1=0, score2=0,
    )
    db.session.add(gf)
    db.session.flush()

    wr_final = wr_rounds[num_rounds][0]
    wr_final.next_match_id = gf.id
    wr_final.next_slot = 1

    if lb_current:
        lb_final = lb_current[0]
        lb_final.next_match_id = gf.id
        lb_final.next_slot = 2

    tournament.status = 'bracket'
    db.session.commit()


def generate_bracket(tournament):
    Match.query.filter_by(tournament_id=tournament.id).delete()
    db.session.flush()
    if (tournament.format or 'single') == 'double':
        _generate_double_bracket(tournament)
    else:
        _generate_single_bracket(tournament)


# ---------------------------------------------------------------------------
# Auth routes
# ---------------------------------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin, remember=request.form.get('remember') == 'on')
            return redirect(request.args.get('next') or url_for('index'))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Player registry routes
# ---------------------------------------------------------------------------

@app.route('/players')
@login_required
def players():
    all_players = PlayerProfile.query.order_by(PlayerProfile.name).all()
    return render_template('players.html', players=all_players)


@app.route('/players/add', methods=['GET', 'POST'])
@login_required
def add_player_profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip() or None
        if not name:
            flash('Name is required.', 'danger')
            return redirect(url_for('add_player_profile'))
        fargo_str = request.form.get('fargo_rating', '').strip()
        fargo = int(fargo_str) if fargo_str.isdigit() else None
        db.session.add(PlayerProfile(name=name, phone=phone, email=email, fargo_rating=fargo))
        db.session.commit()
        flash(f'{name} added to the player registry.', 'success')
        return redirect(url_for('players'))
    return render_template('player_form.html', player=None)


@app.route('/players/<int:pid>/edit', methods=['GET', 'POST'])
@login_required
def edit_player_profile(pid):
    p = PlayerProfile.query.get_or_404(pid)
    if request.method == 'POST':
        p.name = request.form.get('name', '').strip() or p.name
        p.phone = request.form.get('phone', '').strip() or None
        p.email = request.form.get('email', '').strip() or None
        fargo_str = request.form.get('fargo_rating', '').strip()
        p.fargo_rating = int(fargo_str) if fargo_str.isdigit() else None
        db.session.commit()
        flash('Player updated.', 'success')
        return redirect(url_for('players'))
    return render_template('player_form.html', player=p)


@app.route('/players/<int:pid>/delete', methods=['POST'])
@login_required
def delete_player_profile(pid):
    p = PlayerProfile.query.get_or_404(pid)
    db.session.delete(p)
    db.session.commit()
    flash(f'{p.name} removed from the registry.', 'info')
    return redirect(url_for('players'))


# ---------------------------------------------------------------------------
# Rankings route
# ---------------------------------------------------------------------------

@app.route('/rankings')
def rankings():
    profiles = PlayerProfile.query.all()
    ranked = sorted(
        profiles,
        key=lambda p: (p.tournament_wins, p.match_wins, p.tournaments_entered),
        reverse=True,
    )
    return render_template('rankings.html', players=ranked)


# ---------------------------------------------------------------------------
# Tournament routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    upcoming = Tournament.query.filter(
        Tournament.status != 'complete'
    ).order_by(Tournament.tournament_date.asc().nullslast(), Tournament.id.desc()).all()

    past = Tournament.query.filter_by(status='complete').order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()

    return render_template('index.html', upcoming=upcoming, past=past)


@app.route('/tournament/new', methods=['GET', 'POST'])
@login_required
def new_tournament():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        buyin = int(request.form.get('buyin', 10))
        fmt = request.form.get('format', 'single')
        race_to = int(request.form.get('race_to', 3) or 3)
        fargo_rated = 1 if request.form.get('fargo_rated') else 0
        seeding = request.form.get('seeding', 'random')
        t_date_str = request.form.get('tournament_date', '').strip()
        t_date = None
        if t_date_str:
            from datetime import datetime
            try:
                t_date = datetime.strptime(t_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if not name:
            flash('Tournament name is required.', 'danger')
            return redirect(url_for('new_tournament'))

        # Parse dynamic prize splits: split_pct_1, split_pct_2, ...
        ORDINALS = ['1st','2nd','3rd','4th','5th','6th','7th','8th']
        splits = []
        i = 1
        while True:
            pct_str = request.form.get(f'split_pct_{i}', '').strip()
            if not pct_str:
                break
            try:
                pct = int(pct_str)
            except ValueError:
                pct = 0
            if pct > 0:
                label = ORDINALS[i - 1] if i <= len(ORDINALS) else f'{i}th'
                splits.append({'place': i, 'label': label, 'pct': pct})
            i += 1

        if not splits:
            splits = [{'place': 1, 'label': '1st', 'pct': 70},
                      {'place': 2, 'label': '2nd', 'pct': 30}]

        total_pct = sum(s['pct'] for s in splits)
        if total_pct > 100:
            flash(f'Prize split total is {total_pct}% — cannot exceed 100%.', 'danger')
            return redirect(url_for('new_tournament'))

        t = Tournament(
            name=name, buyin=buyin, format=fmt, seeding=seeding,
            race_to=race_to, fargo_rated=fargo_rated,
            prize_splits=json.dumps(splits),
            tournament_date=t_date,
        )
        db.session.add(t)
        db.session.commit()
        return redirect(url_for('tournament', tid=t.id))
    return render_template('new_tournament.html')


@app.route('/tournament/<int:tid>')
@login_required
def tournament(tid):
    t = Tournament.query.get_or_404(tid)
    all_profiles = PlayerProfile.query.order_by(PlayerProfile.name).all()
    enrolled_ids = {p.profile_id for p in t.participants}
    return render_template('tournament.html', t=t, all_profiles=all_profiles,
                           enrolled_ids=enrolled_ids)


@app.route('/tournament/<int:tid>/add_player', methods=['POST'])
@login_required
def add_player(tid):
    t = Tournament.query.get_or_404(tid)
    if t.status != 'open':
        flash('Cannot add players after bracket is generated.', 'warning')
        return redirect(url_for('tournament', tid=tid))
    profile_id = request.form.get('profile_id', type=int)
    if profile_id:
        if not Participant.query.filter_by(tournament_id=tid, profile_id=profile_id).first():
            db.session.add(Participant(tournament_id=tid, profile_id=profile_id))
            db.session.commit()
    return redirect(url_for('tournament', tid=tid))


@app.route('/tournament/<int:tid>/quick_add_player', methods=['POST'])
@login_required
def quick_add_player(tid):
    """Create a new player profile and immediately add them to the tournament."""
    t = Tournament.query.get_or_404(tid)
    if t.status != 'open':
        flash('Cannot add players after bracket is generated.', 'warning')
        return redirect(url_for('tournament', tid=tid))
    name = request.form.get('new_player_name', '').strip()
    if not name:
        flash('Player name is required.', 'danger')
        return redirect(url_for('tournament', tid=tid))
    profile = PlayerProfile(name=name)
    db.session.add(profile)
    db.session.flush()
    db.session.add(Participant(tournament_id=tid, profile_id=profile.id))
    db.session.commit()
    flash(f'{name} created and added to the tournament.', 'success')
    return redirect(url_for('tournament', tid=tid))


@app.route('/tournament/<int:tid>/remove_player/<int:part_id>', methods=['POST'])
@login_required
def remove_player(tid, part_id):
    t = Tournament.query.get_or_404(tid)
    if t.status != 'open':
        flash('Cannot remove players after bracket is generated.', 'warning')
        return redirect(url_for('tournament', tid=tid))
    p = Participant.query.get_or_404(part_id)
    db.session.delete(p)
    db.session.commit()
    return redirect(url_for('tournament', tid=tid))


@app.route('/tournament/<int:tid>/generate', methods=['POST'])
@login_required
def generate(tid):
    t = Tournament.query.get_or_404(tid)
    if t.num_players < 2:
        flash('Need at least 2 players to generate a bracket.', 'danger')
        return redirect(url_for('tournament', tid=tid))
    if t.format == 'double' and t.num_players < 4:
        flash('Double elimination requires at least 4 players.', 'danger')
        return redirect(url_for('tournament', tid=tid))
    generate_bracket(t)
    return redirect(url_for('bracket', tid=tid))


@app.route('/tournament/<int:tid>/bracket')
def bracket(tid):
    t = Tournament.query.get_or_404(tid)
    if t.status == 'open':
        if current_user.is_authenticated:
            return redirect(url_for('tournament', tid=tid))
        flash('Bracket not generated yet.', 'info')
        return redirect(url_for('index'))

    num_wr_rounds = t.rounds
    wr_rounds = {}
    for r in range(1, num_wr_rounds + 1):
        wr_rounds[r] = Match.query.filter_by(
            tournament_id=tid, round_num=r, bracket='W'
        ).order_by(Match.position).all()

    lb_rounds = {}
    gf_match = None
    num_lb_rounds = 0
    if (t.format or 'single') == 'double':
        max_lb = db.session.query(db.func.max(Match.round_num)).filter_by(
            tournament_id=tid, bracket='L'
        ).scalar() or 0
        num_lb_rounds = max_lb
        for r in range(1, max_lb + 1):
            lb_rounds[r] = Match.query.filter_by(
                tournament_id=tid, round_num=r, bracket='L'
            ).order_by(Match.position).all()
        gf_match = Match.query.filter_by(tournament_id=tid, bracket='GF').first()

    return render_template(
        'bracket.html', t=t,
        wr_rounds=wr_rounds, num_wr_rounds=num_wr_rounds,
        lb_rounds=lb_rounds, num_lb_rounds=num_lb_rounds,
        gf_match=gf_match,
    )


@app.route('/tournament/<int:tid>/bracket/print')
def bracket_print(tid):
    t = Tournament.query.get_or_404(tid)
    if t.status == 'open':
        flash('Bracket not generated yet.', 'info')
        return redirect(url_for('index'))

    num_wr_rounds = t.rounds
    wr_rounds = {}
    for r in range(1, num_wr_rounds + 1):
        wr_rounds[r] = Match.query.filter_by(
            tournament_id=tid, round_num=r, bracket='W'
        ).order_by(Match.position).all()

    lb_rounds = {}
    gf_match = None
    num_lb_rounds = 0
    if (t.format or 'single') == 'double':
        max_lb = db.session.query(db.func.max(Match.round_num)).filter_by(
            tournament_id=tid, bracket='L'
        ).scalar() or 0
        num_lb_rounds = max_lb
        for r in range(1, max_lb + 1):
            lb_rounds[r] = Match.query.filter_by(
                tournament_id=tid, round_num=r, bracket='L'
            ).order_by(Match.position).all()
        gf_match = Match.query.filter_by(tournament_id=tid, bracket='GF').first()

    return render_template(
        'bracket_print.html', t=t,
        wr_rounds=wr_rounds, num_wr_rounds=num_wr_rounds,
        lb_rounds=lb_rounds, num_lb_rounds=num_lb_rounds,
        gf_match=gf_match,
    )


@app.route('/tournament/<int:tid>/bracket/status')
def bracket_status(tid):
    """Lightweight JSON endpoint for auto-refresh polling."""
    t = Tournament.query.get_or_404(tid)
    decided = Match.query.filter(
        Match.tournament_id == tid,
        Match.winner_id != None   # noqa: E711
    ).count()
    return jsonify(status=t.status, decided=decided)


@app.route('/tournament/<int:tid>/set_winner/<int:mid>/<int:part_id>', methods=['POST'])
@login_required
def set_winner(tid, mid, part_id):
    match = Match.query.get_or_404(mid)
    part = Participant.query.get_or_404(part_id)
    t = Tournament.query.get_or_404(tid)
    _set_winner(match, part)
    advance_winner(match, t)
    db.session.commit()
    return redirect(url_for('bracket', tid=tid))


@app.route('/tournament/<int:tid>/add_score/<int:mid>/<int:player_num>', methods=['POST'])
@login_required
def add_score(tid, mid, player_num):
    """Increment score for race-to-3 matches."""
    match = Match.query.get_or_404(mid)
    t = Tournament.query.get_or_404(tid)
    if match.winner_id:
        return redirect(url_for('bracket', tid=tid))

    race_to = t.race_to or 3
    if player_num == 1:
        match.score1 = (match.score1 or 0) + 1
        if match.score1 >= race_to:
            part = db.session.get(Participant, match.player1_id)
            _set_winner(match, part)
            advance_winner(match, t)
    else:
        match.score2 = (match.score2 or 0) + 1
        if match.score2 >= race_to:
            part = db.session.get(Participant, match.player2_id)
            _set_winner(match, part)
            advance_winner(match, t)

    db.session.commit()
    return redirect(url_for('bracket', tid=tid))


@app.route('/tournament/<int:tid>/clear_winner/<int:mid>', methods=['POST'])
@login_required
def clear_winner(tid, mid):
    """Undo a winner decision and all downstream effects."""
    match = Match.query.get_or_404(mid)
    _clear_forward(match)
    db.session.commit()
    flash('Winner cleared — match is back to undecided.', 'info')
    return redirect(url_for('bracket', tid=tid))


@app.route('/tournament/<int:tid>/reset', methods=['POST'])
@login_required
def reset_tournament(tid):
    t = Tournament.query.get_or_404(tid)
    Match.query.filter_by(tournament_id=tid).delete()
    t.status = 'open'
    t.champion_id = None
    t.runner_up_id = None
    db.session.commit()
    return redirect(url_for('tournament', tid=tid))


@app.route('/tournament/<int:tid>/delete', methods=['POST'])
@login_required
def delete_tournament(tid):
    t = Tournament.query.get_or_404(tid)
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for('index'))


# ---------------------------------------------------------------------------
# Admin panel
# ---------------------------------------------------------------------------

@app.route('/admin')
@login_required
def admin_panel():
    admins = Admin.query.order_by(Admin.username).all()
    stats = {
        'tournaments': Tournament.query.count(),
        'players': PlayerProfile.query.count(),
        'matches': Match.query.count(),
        'complete': Tournament.query.filter_by(status='complete').count(),
        'open': Tournament.query.filter_by(status='open').count(),
        'in_progress': Tournament.query.filter_by(status='bracket').count(),
    }
    tournaments = Tournament.query.order_by(Tournament.id.desc()).all()
    players = PlayerProfile.query.order_by(PlayerProfile.name).all()
    return render_template('admin.html', admins=admins, stats=stats,
                           tournaments=tournaments, players=players)


@app.route('/admin/change_password', methods=['POST'])
@login_required
def admin_change_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')
    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('admin_panel'))
    if len(new_pw) < 6:
        flash('New password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin_panel'))
    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('admin_panel'))
    current_user.set_password(new_pw)
    db.session.commit()
    flash('Password changed successfully.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/add_admin', methods=['POST'])
@login_required
def admin_add_admin():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin_panel'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin_panel'))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('admin_panel'))
    a = Admin(username=username)
    a.set_password(password)
    db.session.add(a)
    db.session.commit()
    flash(f'Admin "{username}" created.', 'success')
    return redirect(url_for('admin_panel'))


@app.route('/admin/delete_admin/<int:aid>', methods=['POST'])
@login_required
def admin_delete_admin(aid):
    if aid == current_user.id:
        flash("You can't delete your own account.", 'danger')
        return redirect(url_for('admin_panel'))
    a = Admin.query.get_or_404(aid)
    db.session.delete(a)
    db.session.commit()
    flash(f'Admin "{a.username}" removed.', 'info')
    return redirect(url_for('admin_panel'))


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def create_default_admin():
    if not Admin.query.filter_by(username='admin').first():
        a = Admin(username='admin')
        a.set_password('admin123')
        db.session.add(a)
        db.session.commit()
        print('Default admin created  →  username: admin  /  password: admin123')


with app.app_context():
    db.create_all()
    create_default_admin()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=5050)
