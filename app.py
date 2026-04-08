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
    bracket_type = db.Column(db.String(10), default='single')  # single | double
    lb_format = db.Column(db.String(20), default='bestof')      # bestof | raceto (losers bracket)
    lb_race_to = db.Column(db.Integer, default=1)               # race_to for losers bracket
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
        """Number of matches in the bracket."""
        n = self.num_players
        if n < 2:
            return 0
        if (self.bracket_type or 'single') == 'double':
            return 2 * n - 2  # WB(n-1) + LB(n-2) + GF(1) = 2n-2
        return n - 1

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
    def lb_est_games_per_match(self):
        """Average games per LB match."""
        race = self.lb_race_to or 1
        if race == 1:
            return 1.0
        return round(1.5 * race, 1)

    @property
    def est_total_games(self):
        """Estimated total games across the tournament."""
        n = self.num_players
        if (self.bracket_type or 'single') == 'double' and n >= 2:
            wb_matches = n - 1
            lb_matches = max(n - 2, 0)
            gf_matches = 1
            return round(wb_matches * self.est_games_per_match
                         + lb_matches * self.lb_est_games_per_match
                         + gf_matches * self.est_games_per_match)
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
        """Number of WB rounds in the bracket (variable-size rounds, not power-of-2)."""
        if self.status in ('bracket', 'complete'):
            r = db.session.query(db.func.max(Match.round_num)).filter_by(
                tournament_id=self.id, bracket='W'
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
    def lb_format_label(self):
        race = self.lb_race_to or 1
        if (self.lb_format or 'bestof') == 'raceto':
            return f'Race to {race}'
        best_of = 2 * race - 1
        return f'Best of {best_of}'

    @property
    def actual_games_played(self):
        """Count actual games played (excludes bye matches)."""
        games = 0
        is_double = (self.bracket_type or 'single') == 'double'
        for m in self.matches:
            if not m.winner_id:
                continue
            if not m.player1_id or not m.player2_id:
                continue
            if is_double and m.bracket == 'L':
                race = self.lb_race_to or 1
            else:
                race = self.race_to or 1
            if race > 1:
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

    When matches in the round have different destination rounds (a
    skip-feeder sending one winner past the semis), the winner→destination
    assignments are randomized so no bracket position gets an inherent
    advantage (bye to finals).
    """
    round_matches = Match.query.filter_by(
        tournament_id=tournament.id, bracket='W',
        round_num=completed_round_num,
    ).all()
    for m in round_matches:
        if (m.player1_id or m.player2_id) and not m.winner_id:
            return  # round not yet complete

    # Collect advances and check if randomization is needed
    advances = [(m, m.next_match_id, m.next_slot)
                for m in round_matches if m.winner_id and m.next_match_id]
    if advances:
        # Randomize when: destinations span multiple rounds (skip-feeder)
        # OR odd number of advances (guarantees a bye in the next round).
        # This prevents any bracket position from having a deterministic
        # advantage (skipping to finals or getting a bye through semis).
        dest_rounds = set()
        for _, nmid, _ in advances:
            nm = db.session.get(Match, nmid)
            if nm:
                dest_rounds.add(nm.round_num)

        needs_shuffle = len(dest_rounds) > 1 or len(advances) % 2 == 1
        if needs_shuffle and len(advances) >= 2:
            dests = [(nmid, ns) for _, nmid, ns in advances]
            random.shuffle(dests)
            for i, (m, _, _) in enumerate(advances):
                m.next_match_id = dests[i][0]
                m.next_slot = dests[i][1]
            db.session.flush()

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


def _try_auto_advance(next_m, tournament):
    """If next_m has one player and no pending feeders for the empty slot,
    auto-resolve it as a bye and recurse."""
    if next_m.winner_id:
        return
    p1, p2 = next_m.player1_id, next_m.player2_id
    if p1 and p2:
        return  # real match
    if not p1 and not p2:
        return

    empty_slot = 2 if p1 else 1
    # Check both winner feeders and loser feeders
    pending = Match.query.filter(
        Match.next_match_id == next_m.id,
        Match.next_slot == empty_slot,
        Match.winner_id == None,  # noqa: E711
    ).count()
    if pending > 0:
        return
    # Also check loser feeders (WB losers dropping into LB)
    pending_loser = Match.query.filter(
        Match.loser_next_match_id == next_m.id,
        Match.loser_slot == empty_slot,
        Match.winner_id == None,  # noqa: E711
    ).count()
    if pending_loser > 0:
        return

    filled_part = db.session.get(Participant, p1 or p2)
    _set_winner(next_m, filled_part)
    advance_winner(next_m, tournament)


def advance_winner(match, tournament):
    """Advance the match winner to the next match.

    Both single and double elim gate the last 2 WB rounds (semis/finals)
    so that bye recipients are randomized instead of positionally determined.
    Double elim: losers always drop to LB immediately (before gating check).
    """
    is_double = (tournament.bracket_type or 'single') == 'double'

    if not match.next_match_id:
        if match.winner_id:
            loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
            _finalize_tournament(tournament, match.winner_id, loser_id)
        return

    next_m = db.session.get(Match, match.next_match_id)
    if not next_m:
        return

    # Drop loser to LB FIRST so LB stays active even when WB is gated
    if is_double and match.bracket == 'W' and match.loser_next_match_id:
        loser_id = match.player2_id if match.winner_id == match.player1_id else match.player1_id
        if loser_id:
            lb_match = db.session.get(Match, match.loser_next_match_id)
            if lb_match:
                loser_part = db.session.get(Participant, loser_id)
                if match.loser_slot == 1:
                    lb_match.player1_id = loser_part.id
                else:
                    lb_match.player2_id = loser_part.id
                db.session.flush()
                _try_auto_advance(lb_match, tournament)

    num_rounds = tournament.rounds
    gated_from = num_rounds - 1 if num_rounds >= 3 else num_rounds + 99

    # Semi-finals and finals: round-gated (randomizes bye assignment)
    if next_m.round_num >= gated_from and match.bracket == 'W':
        _gate_advance(tournament, match.round_num)
        return

    # Per-match advancement: place winner into next match
    winner_part = db.session.get(Participant, match.winner_id)
    if match.next_slot == 1:
        next_m.player1_id = winner_part.id
    else:
        next_m.player2_id = winner_part.id
    db.session.flush()

    # Auto-advance bye in the winner's next match
    _try_auto_advance(next_m, tournament)


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

    # Cascade: remove loser from LB match (double elim)
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


def _generate_double_bracket(tournament):
    """Generate a double-elimination bracket (WB + LB + Grand Final).

    WB uses per-match advancement (no gating).
    LB alternates dropdown rounds (WB losers enter) and consolidation
    rounds (LB-only).  Grand Final is a single match.
    """
    players = _get_slots(tournament)
    n = len(players)
    if n < 4:
        tournament.status = 'bracket'
        db.session.commit()
        return

    # ══════════════════════════════════════════════════════════════════
    # Phase 1: Winners Bracket (same structure as single elim, no gating)
    # ══════════════════════════════════════════════════════════════════
    wb_round_info = []
    remaining = n
    while remaining > 1:
        num_matches = remaining // 2
        has_bye = remaining % 2 == 1
        wb_round_info.append((num_matches, has_bye))
        remaining = num_matches + (1 if has_bye else 0)
    num_wb_rounds = len(wb_round_info)

    # Create WB matches
    wb_rounds = []
    for r_idx, (num_matches, _) in enumerate(wb_round_info):
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
        wb_rounds.append(round_matches)
    db.session.flush()

    # Pre-fill WB R1 bye player into R2M0 slot 1
    if wb_round_info[0][1] and num_wb_rounds > 1:
        wb_rounds[1][0].player1_id = players[-1].id

    # Auto-resolve WB R1 bye matches
    for m in wb_rounds[0]:
        if m.player1_id and not m.player2_id:
            _set_winner(m, db.session.get(Participant, m.player1_id))
        elif m.player2_id and not m.player1_id:
            _set_winner(m, db.session.get(Participant, m.player2_id))

    # Link WB matches (no gating, no skip-ahead adjustment)
    for r_idx in range(num_wb_rounds - 1):
        curr = wb_rounds[r_idx]
        has_bye = wb_round_info[r_idx][1]
        next_round = wb_rounds[r_idx + 1]
        next_has_bye = wb_round_info[r_idx + 1][1]

        feeders = []
        if has_bye:
            feeders.append(None)
        for m in curr:
            feeders.append(m)

        skip_feeder = None
        if next_has_bye:
            skip_feeder = feeders.pop()

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

        if skip_feeder is not None and r_idx + 2 < num_wb_rounds:
            target = wb_rounds[r_idx + 2][0]
            skip_feeder.next_match_id = target.id
            skip_feeder.next_slot = 1

    # ══════════════════════════════════════════════════════════════════
    # Phase 2: Losers Bracket
    # ══════════════════════════════════════════════════════════════════
    # LB R1:  WB R1 losers pair up
    # LB R2 (dropdown): LB R1 survivors vs WB R2 losers
    # LB R3 (consolidation): LB R2 survivors play each other
    # LB R4 (dropdown): LB R3 survivors vs WB R3 losers
    # ...alternating...

    # Count real losers per WB round (bye matches don't produce a real loser)
    wb_losers_per_round = []
    for r_idx, (num_matches, has_bye) in enumerate(wb_round_info):
        real_losers = num_matches
        # Bye matches in R1 auto-resolve — no real loser
        if r_idx == 0:
            for m in wb_rounds[0]:
                if not m.player1_id or not m.player2_id:
                    real_losers -= 1
        wb_losers_per_round.append(real_losers)

    lb_rounds = []       # list of lists of Match objects
    lb_round_bye = []    # True if round has a bye at last position
    lb_round_num = 0
    lb_survivors = 0

    for wb_r in range(num_wb_rounds):
        wb_losers = wb_losers_per_round[wb_r]

        if wb_r == 0:
            # LB R1: WB R1 losers pair up
            total = wb_losers
            lb_matches = total // 2
            lb_bye = total % 2 == 1
            if lb_matches == 0 and not lb_bye:
                continue  # No losers from R1 (all byes — shouldn't happen with >= 4)

            lb_round_num += 1
            round_matches = []
            for i in range(lb_matches + (1 if lb_bye else 0)):
                m = Match(
                    tournament_id=tournament.id, bracket='L',
                    round_num=lb_round_num, position=i,
                    score1=0, score2=0,
                )
                db.session.add(m)
                round_matches.append(m)
            lb_rounds.append(round_matches)
            lb_round_bye.append(lb_bye)
            lb_survivors = lb_matches + (1 if lb_bye else 0)

        else:
            # Dropdown round: LB survivors + WB losers
            total = lb_survivors + wb_losers
            if total <= 0:
                continue
            dd_matches = total // 2
            dd_bye = total % 2 == 1
            lb_round_num += 1
            round_matches = []
            for i in range(dd_matches + (1 if dd_bye else 0)):
                m = Match(
                    tournament_id=tournament.id, bracket='L',
                    round_num=lb_round_num, position=i,
                    score1=0, score2=0,
                )
                db.session.add(m)
                round_matches.append(m)
            lb_rounds.append(round_matches)
            lb_round_bye.append(dd_bye)
            lb_survivors = dd_matches + (1 if dd_bye else 0)

            # Consolidation round (skip for last WB round — no more dropdowns after)
            if wb_r < num_wb_rounds - 1 and lb_survivors > 1:
                c_matches = lb_survivors // 2
                c_bye = lb_survivors % 2 == 1
                lb_round_num += 1
                round_matches = []
                for i in range(c_matches + (1 if c_bye else 0)):
                    m = Match(
                        tournament_id=tournament.id, bracket='L',
                        round_num=lb_round_num, position=i,
                        score1=0, score2=0,
                    )
                    db.session.add(m)
                    round_matches.append(m)
                lb_rounds.append(round_matches)
                lb_round_bye.append(c_bye)
                lb_survivors = c_matches + (1 if c_bye else 0)

    db.session.flush()

    # ── Track LB round types for correct linking ──
    # LB round types: 'init' (R1, WB R1 losers pair up),
    #   'dropdown' (LB survivors + WB losers), 'consolidation' (LB-only)
    # Pattern: [init, dropdown, consolidation, dropdown, consolidation, ...]
    # For linking:
    #   Before a consolidation round: 2:1 pairing (two matches → one)
    #   Before a dropdown round: 1:1 (each LB match → slot 1 of dropdown match)
    #     WB losers fill slot 2 of dropdown matches via loser_next_match_id
    lb_round_types = []
    for lb_r_idx_t in range(len(lb_rounds)):
        if lb_r_idx_t == 0:
            lb_round_types.append('init')
        elif (lb_r_idx_t - 1) % 2 == 0:
            lb_round_types.append('dropdown')
        else:
            lb_round_types.append('consolidation')

    # Link LB matches internally (next_match_id / next_slot)
    # When two consecutive rounds both have byes, reorder linking so the
    # bye winner from round N goes to a real match in round N+1 (not
    # another bye).  This prevents any player getting 2 byes in a row.
    for lb_r_idx in range(len(lb_rounds) - 1):
        curr = lb_rounds[lb_r_idx]
        nxt = lb_rounds[lb_r_idx + 1]
        next_type = lb_round_types[lb_r_idx + 1]
        consecutive_byes = (lb_round_bye[lb_r_idx] and lb_round_bye[lb_r_idx + 1]
                            and len(curr) >= 2)

        if next_type == 'consolidation':
            # 2:1 pairing: matches [0,1] → dest 0, [2,3] → dest 1
            link_order = list(range(len(curr)))
            if consecutive_byes:
                # Swap last two so bye (last, even pos) moves to odd pos
                # (slot 2 of a real match) instead of slot 1 of the bye dest
                link_order[-1], link_order[-2] = link_order[-2], link_order[-1]
            for link_i, src_idx in enumerate(link_order):
                dest_idx = link_i // 2
                if dest_idx < len(nxt):
                    curr[src_idx].next_match_id = nxt[dest_idx].id
                    curr[src_idx].next_slot = 1 if link_i % 2 == 0 else 2
        else:
            # 1:1: each match → slot 1 of the corresponding dropdown match
            link_order = list(range(len(curr)))
            if consecutive_byes:
                # Move bye (last) to position 0 so it feeds a dropdown match
                # that has a WB loser opponent, not the unfed bye match
                bye_idx = len(curr) - 1
                link_order = [bye_idx] + list(range(bye_idx))
            for link_i, src_idx in enumerate(link_order):
                if link_i < len(nxt):
                    curr[src_idx].next_match_id = nxt[link_i].id
                    curr[src_idx].next_slot = 1

    # ══════════════════════════════════════════════════════════════════
    # Phase 3: Link WB losers → LB (loser_next_match_id / loser_slot)
    # ══════════════════════════════════════════════════════════════════

    # WB R1 losers → LB R1 (first LB round)
    # Pair WB R1 matches to LB R1 matches: WB M0 loser + WB M1 loser → LB M0
    if lb_rounds:
        lb_r_idx = 0  # LB round index for WB R1 losers
        real_wb_r1 = [m for m in wb_rounds[0] if m.player1_id and m.player2_id]
        for i, wb_m in enumerate(real_wb_r1):
            dest_idx = i // 2
            if dest_idx < len(lb_rounds[lb_r_idx]):
                wb_m.loser_next_match_id = lb_rounds[lb_r_idx][dest_idx].id
                wb_m.loser_slot = 1 if i % 2 == 0 else 2

    # WB R2+ losers → corresponding dropdown LB round
    # The dropdown rounds are: LB round index 1 (for WB R2), 3 (for WB R3), 5 (for WB R4), etc.
    lb_dd_idx = 1  # LB round index for the first dropdown (WB R2 losers)
    for wb_r in range(1, num_wb_rounds):
        if lb_dd_idx >= len(lb_rounds):
            break
        dd_round = lb_rounds[lb_dd_idx]
        # WB losers go to slot 2 of dropdown matches; LB survivors get slot 1
        for i, wb_m in enumerate(wb_rounds[wb_r]):
            if i < len(dd_round):
                wb_m.loser_next_match_id = dd_round[i].id
                wb_m.loser_slot = 2
        lb_dd_idx += 2  # skip consolidation round

    # ══════════════════════════════════════════════════════════════════
    # Phase 4: Grand Final
    # ══════════════════════════════════════════════════════════════════
    gf = Match(
        tournament_id=tournament.id, bracket='GF',
        round_num=1, position=0,
        score1=0, score2=0,
    )
    db.session.add(gf)
    db.session.flush()

    # WB Final winner → GF slot 1
    wb_final = wb_rounds[-1][-1]
    wb_final.next_match_id = gf.id
    wb_final.next_slot = 1

    # LB Final winner → GF slot 2
    if lb_rounds:
        lb_final = lb_rounds[-1][-1]
        lb_final.next_match_id = gf.id
        lb_final.next_slot = 2

    tournament.status = 'bracket'
    db.session.commit()


def generate_bracket(tournament):
    Match.query.filter_by(tournament_id=tournament.id).delete()
    db.session.flush()
    if (tournament.bracket_type or 'single') == 'double':
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
        bracket_type = request.form.get('bracket_type', 'single')
        lb_fmt = request.form.get('lb_format', 'bestof')
        lb_format_value = int(request.form.get('lb_format_value', 1) or 1)
        if lb_fmt == 'bestof':
            lb_race_to = math.ceil(lb_format_value / 2)
        else:
            lb_race_to = lb_format_value
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
            bracket_type=bracket_type,
            lb_format=lb_fmt, lb_race_to=lb_race_to,
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
    name = p.profile.name
    db.session.delete(p)
    db.session.commit()
    flash(f'{name} removed from tournament.', 'info')
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
    if (t.bracket_type or 'single') == 'double':
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
    if (t.bracket_type or 'single') == 'double':
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

    if (t.bracket_type or 'single') == 'double' and match.bracket == 'L':
        race_to = t.lb_race_to or t.race_to or 3
    else:
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
    # Migration: add new columns for double elimination support
    for col_sql in [
        "ALTER TABLE tournament ADD COLUMN bracket_type VARCHAR(10) DEFAULT 'single'",
        "ALTER TABLE tournament ADD COLUMN lb_format VARCHAR(20) DEFAULT 'bestof'",
        "ALTER TABLE tournament ADD COLUMN lb_race_to INTEGER DEFAULT 1",
    ]:
        try:
            db.session.execute(db.text(col_sql))
            db.session.commit()
        except Exception:
            db.session.rollback()
    create_default_admin()

if __name__ == '__main__':
    app.run(debug=os.environ.get('FLASK_DEBUG', '0') == '1', host='0.0.0.0', port=5050)
