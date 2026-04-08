import json
from datetime import date as date_type
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
from app import app, db, login_manager


@app.template_filter('money')
def money_filter(value):
    """Format a number as currency: $1, $1.25, $0.50"""
    if value is None:
        return '$0'
    v = float(value)
    if v == int(v):
        return f'${int(v)}'
    return f'${v:.2f}'


class Admin(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='admin')

    @property
    def is_admin(self):
        return self.role == 'admin'

    @property
    def is_manager(self):
        return self.role == 'manager'

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)


class League(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    owner = db.relationship('Admin', backref='leagues')
    tournaments = db.relationship('Tournament', backref='league', lazy=True)
    players = db.relationship('PlayerProfile', backref='league', lazy=True)

    def can_manage(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        if self.owner_id == user.id:
            return True
        return ManagerShare.query.filter_by(
            league_id=self.id, delegate_id=user.id
        ).first() is not None


class ManagerShare(db.Model):
    """Grants delegate_id access to all tournaments in a league."""
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)  # legacy, kept for migration
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    delegate_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=False)
    __table_args__ = (db.UniqueConstraint('league_id', 'delegate_id'),)

    league = db.relationship('League', backref='shares')
    delegate = db.relationship('Admin', foreign_keys=[delegate_id], backref='shares_received')


@login_manager.user_loader
def load_user(user_id):
    return db.session.get(Admin, int(user_id))


def get_user_leagues(user):
    """All leagues a user can access (owns or delegated)."""
    if user.is_admin:
        return League.query.order_by(League.name).all()
    owned = League.query.filter_by(owner_id=user.id)
    shared_ids = [s.league_id for s in ManagerShare.query.filter_by(delegate_id=user.id).all()]
    if shared_ids:
        return owned.union(League.query.filter(League.id.in_(shared_ids))).order_by(League.name).all()
    return owned.order_by(League.name).all()


class PlayerProfile(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False, default='')  # legacy, kept for migration
    first_name = db.Column(db.String(50), nullable=True)
    last_name = db.Column(db.String(50), nullable=True)
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
    phone = db.Column(db.String(30), nullable=True)
    email = db.Column(db.String(120), nullable=True)
    fargo_rating = db.Column(db.Integer, nullable=True)
    participations = db.relationship('Participant', backref='profile', lazy=True)

    @property
    def full_name(self):
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name}'
        return self.first_name or self.last_name or self.name or ''

    @property
    def display_name(self):
        """First name + last initial for bracket display."""
        if self.first_name and self.last_name:
            return f'{self.first_name} {self.last_name[0]}.'
        return self.full_name

    @property
    def search_label(self):
        return f'{self.display_name} #{self.id}'

    @property
    def tournaments_entered(self):
        if hasattr(self, '_cached_tournaments_entered'):
            return self._cached_tournaments_entered
        return len(self.participations)

    @property
    def match_wins(self):
        if hasattr(self, '_cached_match_wins'):
            return self._cached_match_wins
        return Match.query.filter_by(winner_profile_id=self.id).count()

    @property
    def tournament_wins(self):
        if hasattr(self, '_cached_tournament_wins'):
            return self._cached_tournament_wins
        return Tournament.query.filter_by(champion_id=self.id).count()

    @property
    def ranking_score(self):
        return self.tournament_wins * 1000 + self.match_wins


class Tournament(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    owner_id = db.Column(db.Integer, db.ForeignKey('admin.id'), nullable=True)
    owner = db.relationship('Admin', backref='tournaments')
    league_id = db.Column(db.Integer, db.ForeignKey('league.id'), nullable=True)
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
    def is_double(self):
        return self.bracket_type == 'double'

    def can_manage(self, user):
        if not user or not getattr(user, 'is_authenticated', False):
            return False
        if user.is_admin:
            return True
        if self.league:
            return self.league.can_manage(user)
        return self.owner_id == user.id

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
        if self.is_double:
            return 2 * n - 2  # WB(n-1) + LB(n-2) + GF(1) = 2n-2
        return n - 1

    @property
    def est_games_per_match(self):
        """Average games per match based on format.
        Race to X: min X (sweep), max 2X-1 (full distance). Average ~ 1.5X.
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
        if self.is_double and n >= 2:
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
        is_double = self.is_double
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
