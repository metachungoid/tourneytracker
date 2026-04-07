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


@app.template_filter('money')
def money_filter(value):
    """Format a number as currency: $1, $1.25, $0.50"""
    if value is None:
        return '$0'
    v = float(value)
    if v == int(v):
        return f'${int(v)}'
    return f'${v:.2f}'


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
    format = db.Column(db.String(20), default='bestof')  # bestof | raceto
    race_to = db.Column(db.Integer, default=1)
    table_fee = db.Column(db.Float, default=1.0)           # $ per game played
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
    def total_matches(self):
        """Number of matches in a single-elim bracket."""
        return max(self.num_players - 1, 0)

    @property
    def est_games_per_match(self):
        """Average games per match based on format.
        Race to X: min X (sweep), max 2X-1 (full distance). Average ≈ 1.5X.
        Race to 1 (single game): exactly 1."""
        race = self.race_to or 1
        if race == 1:
            return 1.0
        return round(1.5 * race, 1)

    @property
    def est_total_games(self):
        """Estimated total games across the tournament."""
        return round(self.total_matches * self.est_games_per_match)

    @property
    def est_table_cost(self):
        """Estimated table fees: est_total_games * table_fee."""
        return round(self.est_total_games * (self.table_fee or 0), 2)

    @property
    def prize_pool(self):
        """Gross buy-ins minus table fees.
        During bracket play: uses estimated cost.
        Once complete: uses actual cost (real games played)."""
        if self.status == 'complete':
            return max(self.gross_pool - self.actual_table_cost, 0)
        if self.status == 'bracket':
            return max(self.gross_pool - self.est_table_cost, 0)
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
        """Return list of dicts: [{place, label, pct, amount}].
        Flat-dollar places are paid first; percentage places split the remainder."""
        pool = self.prize_pool
        splits = self.splits

        # Deduct flat amounts first
        flat_total = sum(s.get('flat', 0) for s in splits if s.get('type') == 'flat')
        remaining = max(pool - flat_total, 0)

        payouts = []
        for s in splits:
            if s.get('type') == 'flat':
                amt = s.get('flat', 0)
            else:
                amt = round(remaining * s.get('pct', 0) / 100)
            payouts.append({**s, 'amount': amt})
        return payouts

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
        """Number of rounds in the bracket (variable-size rounds, not power-of-2)."""
        if self.status in ('bracket', 'complete'):
            r = db.session.query(db.func.max(Match.round_num)).filter_by(
                tournament_id=self.id
            ).scalar()
            return r or 0
        n = self.num_players
        if n < 2:
            return 0
        count = 0
        remaining = n
        while remaining > 1:
            count += 1
            remaining = (remaining + 1) // 2
        return count

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
        race = self.race_to or 1
        if (self.format or 'bestof') == 'raceto':
            return f'Race to {race}'
        else:
            best_of = 2 * race - 1
            return f'Best of {best_of}'

    @property
    def actual_games_played(self):
        """Count actual games played (excludes bye matches)."""
        games = 0
        for m in self.matches:
            if not m.winner_id:
                continue
            # Skip byes — matches where one side had no player
            if not m.player1_id or not m.player2_id:
                continue
            if (self.race_to or 1) > 1:
                games += (m.score1 or 0) + (m.score2 or 0)
            else:
                games += 1
        return games

    @property
    def actual_table_cost(self):
        """Actual table fees: real games played * table_fee."""
        return round(self.actual_games_played * (self.table_fee or 0), 2)


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
    """Return ordered list of Participants for the bracket.

    Rankings seeding sorts by past performance (championships then wins).
    Random seeding shuffles.  No None padding — the bracket generator
    handles byes based on odd player counts.
    """
    parts = list(tournament.participants)

    if (tournament.seeding or 'random') == 'rankings':
        champ_counts = dict(db.session.query(
            Tournament.champion_id, db.func.count()
        ).filter(
            Tournament.id != tournament.id,
            Tournament.champion_id.isnot(None),
        ).group_by(Tournament.champion_id).all())
        win_counts = dict(db.session.query(
            Match.winner_profile_id, db.func.count()
        ).filter(
            Match.tournament_id != tournament.id,
            Match.winner_profile_id.isnot(None),
        ).group_by(Match.winner_profile_id).all())
        return sorted(parts, key=lambda p: (
            -champ_counts.get(p.profile_id, 0),
            -win_counts.get(p.profile_id, 0),
        ))

    ordered = parts[:]
    random.shuffle(ordered)
    return ordered


def _finalize_tournament(tournament, winner_id, loser_id):
    """Set champion, runner-up, and mark tournament complete."""
    winner = db.session.get(Participant, winner_id)
    if winner:
        tournament.champion_id = winner.profile_id
    loser = db.session.get(Participant, loser_id) if loser_id else None
    if loser:
        tournament.runner_up_id = loser.profile_id
    tournament.status = 'complete'


def _gate_advance(tournament, completed_round_num):
    """Round-gating for semi-finals and finals.

    Populates the next round only when ALL matches in the current round
    are decided.  Auto-resolves any byes in the populated round, then
    cascades if that round is also fully decided.
    """
    round_matches = Match.query.filter_by(
        tournament_id=tournament.id, bracket='W',
        round_num=completed_round_num,
    ).all()
    for m in round_matches:
        if (m.player1_id or m.player2_id) and not m.winner_id:
            return  # round not yet complete

    # Place ALL winners into next round
    for m in round_matches:
        if m.winner_id and m.next_match_id:
            winner_part = db.session.get(Participant, m.winner_id)
            next_m = db.session.get(Match, m.next_match_id)
            if next_m and winner_part:
                if m.next_slot == 1:
                    next_m.player1_id = winner_part.id
                elif m.next_slot == 2:
                    next_m.player2_id = winner_part.id
    db.session.flush()

    # Resolve byes in the populated round
    next_round = completed_round_num + 1
    next_matches = Match.query.filter_by(
        tournament_id=tournament.id, bracket='W',
        round_num=next_round,
    ).all()
    if not next_matches:
        return

    for nm in next_matches:
        if nm.winner_id:
            continue
        p1, p2 = nm.player1_id, nm.player2_id
        if p1 and not p2:
            _set_winner(nm, db.session.get(Participant, p1))
        elif p2 and not p1:
            _set_winner(nm, db.session.get(Participant, p2))

    # Check for tournament completion (finals decided)
    for nm in next_matches:
        if nm.winner_id and not nm.next_match_id:
            loser_id = nm.player2_id if nm.winner_id == nm.player1_id else nm.player1_id
            _finalize_tournament(tournament, nm.winner_id, loser_id)
            return

    # If ALL populated matches are already decided (all byes), cascade
    has_pending = any(
        (nm.player1_id or nm.player2_id) and not nm.winner_id
        for nm in next_matches
    )
    if not has_pending:
        _gate_advance(tournament, next_round)


def advance_winner(match, tournament):
    """Advance the match winner to the next match.

    Early rounds: per-match advancement (immediate, no waiting).
    Semi-finals and finals (last 2 rounds): round-gated (waits for
    entire previous round to complete before populating).
    """
    if not match.next_match_id:
        if match.winner_id:
            loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
            _finalize_tournament(tournament, match.winner_id, loser_id)
        return

    next_m = db.session.get(Match, match.next_match_id)
    if not next_m:
        return

    num_rounds = tournament.rounds
    gated_from = num_rounds - 1 if num_rounds >= 3 else num_rounds + 99

    # Semi-finals and finals: round-gated
    if next_m.round_num >= gated_from:
        _gate_advance(tournament, match.round_num)
        return

    # Per-match advancement for earlier rounds
    winner_part = db.session.get(Participant, match.winner_id)
    if match.next_slot == 1:
        next_m.player1_id = winner_part.id
    else:
        next_m.player2_id = winner_part.id
    db.session.flush()

    # Auto-advance bye (one player, no pending feeders for the empty slot)
    if next_m.winner_id:
        return
    p1, p2 = next_m.player1_id, next_m.player2_id
    if p1 and p2:
        return  # real match — wait for it to be played
    if not p1 and not p2:
        return

    empty_slot = 2 if p1 else 1
    pending = Match.query.filter(
        Match.next_match_id == next_m.id,
        Match.next_slot == empty_slot,
        Match.winner_id == None,  # noqa: E711
    ).count()
    if pending == 0:
        filled_part = db.session.get(Participant, p1 or p2)
        _set_winner(next_m, filled_part)
        advance_winner(next_m, tournament)


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

    # Cascade: remove winner from next match
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


# ---------------------------------------------------------------------------
# Bracket generators
# ---------------------------------------------------------------------------

def _generate_single_bracket(tournament):
    """Generate a single-elimination bracket with minimal byes.

    At most 1 bye per round (when odd player count).  The bye player is
    pre-placed into the next round's first match so play can start
    immediately when that match's opponent is decided.

    Early rounds: per-match advancement (immediate).
    Semi-finals and finals (last 2 rounds): round-gated — players are
    NOT pre-seeded; the round populates only when the prior round
    completes.  Byes in gated rounds become extra matches instead of
    skip-ahead links.
    """
    players = _get_slots(tournament)
    n = len(players)
    if n < 2:
        tournament.status = 'bracket'
        db.session.commit()
        return

    # ── Compute round structure ────────────────────────────────────────
    # Each round: (num_matches, has_bye)
    round_info = []
    remaining = n
    while remaining > 1:
        num_matches = remaining // 2
        has_bye = remaining % 2 == 1
        round_info.append((num_matches, has_bye))
        remaining = num_matches + (1 if has_bye else 0)
    num_rounds = len(round_info)

    # Gated rounds: semi-finals and finals (last 2 rounds, if >= 3 rounds)
    gated_from = num_rounds - 1 if num_rounds >= 3 else num_rounds + 99

    # ── Adjust byes that would skip into gated rounds ────────────────
    # A round's bye causes a skip-ahead to round r+2 (1-indexed).
    # If that target is gated (semi-finals or finals), convert the bye
    # into an extra match in the SAME round — a bye match with one player
    # that auto-resolves.  Output count stays the same (m+1 either way).
    for r_idx in range(num_rounds):
        if not round_info[r_idx][1]:
            continue
        skip_target = r_idx + 2  # 1-indexed round the skip would land in
        if skip_target >= gated_from:
            m_count, _ = round_info[r_idx]
            round_info[r_idx] = (m_count + 1, False)

    # ── Create all matches ─────────────────────────────────────────────
    all_rounds = []
    for r_idx, (num_matches, _) in enumerate(round_info):
        round_matches = []
        for i in range(num_matches):
            kwargs = dict(
                tournament_id=tournament.id, bracket='W',
                round_num=r_idx + 1, position=i,
                score1=0, score2=0,
            )
            if r_idx == 0:
                p1_idx = i * 2
                p2_idx = i * 2 + 1
                if p1_idx < len(players):
                    kwargs['player1_id'] = players[p1_idx].id
                if p2_idx < len(players):
                    kwargs['player2_id'] = players[p2_idx].id
            m = Match(**kwargs)
            db.session.add(m)
            round_matches.append(m)
        all_rounds.append(round_matches)
    db.session.flush()

    # ── Pre-fill R1 bye player into R2M0 slot 1 (non-gated only) ──────
    if round_info[0][1] and num_rounds > 1 and 2 < gated_from:
        all_rounds[1][0].player1_id = players[-1].id

    # ── Auto-resolve R1 bye matches (player with no opponent) ──────────
    for m in all_rounds[0]:
        if m.player1_id and not m.player2_id:
            _set_winner(m, db.session.get(Participant, m.player1_id))
        elif m.player2_id and not m.player1_id:
            _set_winner(m, db.session.get(Participant, m.player2_id))

    # ── Link matches across rounds ─────────────────────────────────────
    for r_idx in range(num_rounds - 1):
        curr = all_rounds[r_idx]
        has_bye = round_info[r_idx][1]
        next_round = all_rounds[r_idx + 1]
        next_has_bye = round_info[r_idx + 1][1]

        # Build feeder list: None = bye placeholder, else = match object
        feeders = []
        if has_bye:
            feeders.append(None)  # bye already pre-filled or will arrive via gate
        for m in curr:
            feeders.append(m)

        # If next round has a bye, pull the last feeder out — it skips ahead
        skip_feeder = None
        if next_has_bye:
            skip_target = r_idx + 2
            # Only skip if target is NOT gated
            if skip_target < gated_from or skip_target >= num_rounds:
                skip_feeder = feeders.pop()

        # Randomize bye position for gated rounds (so the same player
        # doesn't always get the bye in semi-finals)
        next_round_num = r_idx + 2  # 1-indexed
        if len(feeders) % 2 == 1 and next_round_num >= gated_from:
            bye_idx = random.randrange(len(feeders))
            # Move the bye feeder to the end
            feeders.append(feeders.pop(bye_idx))

        # Pair remaining feeders into next round matches
        for i in range(0, len(feeders), 2):
            dest_idx = i // 2
            if dest_idx >= len(next_round):
                break
            dest = next_round[dest_idx]
            f1 = feeders[i]
            f2 = feeders[i + 1] if i + 1 < len(feeders) else None
            if f1 is not None:
                f1.next_match_id = dest.id
                f1.next_slot = 1
            if f2 is not None:
                f2.next_match_id = dest.id
                f2.next_slot = 2

        # Skip feeder links to the round after next (slot 1 of first match)
        if skip_feeder is not None:
            if r_idx + 2 < num_rounds:
                target = all_rounds[r_idx + 2][0]
                skip_feeder.next_match_id = target.id
                skip_feeder.next_slot = 1

    tournament.status = 'bracket'
    db.session.commit()


def generate_bracket(tournament):
    Match.query.filter_by(tournament_id=tournament.id).delete()
    db.session.flush()
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
    name = p.name

    # Remove participant entries (tournament rosters)
    participants = Participant.query.filter_by(profile_id=pid).all()
    part_ids = {pt.id for pt in participants}

    # Clear match references to these participants
    if part_ids:
        for m in Match.query.filter(
            db.or_(Match.player1_id.in_(part_ids),
                   Match.player2_id.in_(part_ids),
                   Match.winner_id.in_(part_ids))
        ).all():
            if m.player1_id in part_ids:
                m.player1_id = None
            if m.player2_id in part_ids:
                m.player2_id = None
            if m.winner_id in part_ids:
                m.winner_id = None
                m.winner_profile_id = None

    # Clear champion/runner-up references
    for t in Tournament.query.filter(
        db.or_(Tournament.champion_id == pid, Tournament.runner_up_id == pid)
    ).all():
        if t.champion_id == pid:
            t.champion_id = None
        if t.runner_up_id == pid:
            t.runner_up_id = None

    # Clear winner_profile_id references on matches
    Match.query.filter_by(winner_profile_id=pid).update({'winner_profile_id': None})

    for pt in participants:
        db.session.delete(pt)

    db.session.delete(p)
    db.session.commit()
    flash(f'{name} removed from the registry.', 'info')
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
        table_fee = float(request.form.get('table_fee', 1) or 0)
        fmt = request.form.get('format', 'bestof')
        format_value = int(request.form.get('format_value', 1) or 1)
        if fmt == 'bestof':
            race_to = math.ceil(format_value / 2)
        else:
            race_to = format_value
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

        # Parse dynamic prize splits: split_type_N, split_val_N
        ORDINALS = ['1st','2nd','3rd','4th','5th','6th','7th','8th']
        splits = []
        i = 1
        while True:
            val_str = request.form.get(f'split_val_{i}', '').strip()
            if not val_str:
                break
            split_type = request.form.get(f'split_type_{i}', 'pct').strip()
            try:
                val = float(val_str)
            except ValueError:
                val = 0
            if val > 0:
                label = ORDINALS[i - 1] if i <= len(ORDINALS) else f'{i}th'
                if split_type == 'flat':
                    splits.append({'place': i, 'label': label, 'type': 'flat', 'flat': val, 'pct': 0})
                else:
                    splits.append({'place': i, 'label': label, 'type': 'pct', 'pct': val, 'flat': 0})
            i += 1

        if not splits:
            splits = [{'place': 1, 'label': '1st', 'type': 'pct', 'pct': 70, 'flat': 0},
                      {'place': 2, 'label': '2nd', 'type': 'pct', 'pct': 30, 'flat': 0}]

        total_pct = sum(s['pct'] for s in splits if s.get('type') == 'pct')
        if total_pct > 100:
            flash(f'Percentage split total is {total_pct}% — cannot exceed 100%.', 'danger')
            return redirect(url_for('new_tournament'))

        t = Tournament(
            name=name, buyin=buyin, table_fee=table_fee,
            format=fmt, seeding=seeding,
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
