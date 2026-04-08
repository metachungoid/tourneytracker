import pytest
from app import app as flask_app, db as _db
from models import Tournament, PlayerProfile, Participant, Match, Admin, League


@pytest.fixture(scope='session')
def app():
    flask_app.config['TESTING'] = True
    flask_app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///:memory:'
    with flask_app.app_context():
        _db.create_all()
        yield flask_app


@pytest.fixture(autouse=True)
def clean_db(app):
    yield
    with app.app_context():
        for table in reversed(_db.metadata.sorted_tables):
            _db.session.execute(table.delete())
        _db.session.commit()


# ---------------------------------------------------------------------------
# Helpers (plain functions — call with app context managed externally,
# or use the `app` fixture to enter context before calling)
# ---------------------------------------------------------------------------

def _get_or_create_test_league():
    """Return a test league, creating it (with a test admin) if needed."""
    league = League.query.first()
    if league:
        return league
    admin = Admin.query.filter_by(username='testadmin').first()
    if not admin:
        admin = Admin(username='testadmin', role='admin')
        admin.set_password('test123')
        _db.session.add(admin)
        _db.session.flush()
    league = League(name='Test League', owner_id=admin.id)
    _db.session.add(league)
    _db.session.flush()
    return league


def make_tournament(n, bracket_type='single', seeding='random', race_to=1):
    """Create a tournament with n players and generate the bracket.
    Must be called inside an app context.  Returns the Tournament object
    (refreshed from the DB so all relationships are loaded).
    """
    from bracket.generators import generate_bracket
    league = _get_or_create_test_league()
    t = Tournament(
        name='Test', buyin=10, bracket_type=bracket_type,
        seeding=seeding, race_to=race_to, lb_race_to=race_to,
        owner_id=league.owner_id, league_id=league.id,
    )
    _db.session.add(t)
    _db.session.flush()
    for i in range(n):
        p = PlayerProfile(first_name='Player', last_name=f'{i + 1}',
                          league_id=league.id)
        _db.session.add(p)
        _db.session.flush()
        _db.session.add(Participant(tournament_id=t.id, profile_id=p.id))
    _db.session.commit()
    generate_bracket(t)
    return _db.session.get(Tournament, t.id)


def play_match(match, pick_player=1):
    """Play a single match. pick_player=1 picks player1, 2 picks player2.
    Must be called inside an app context.
    """
    from bracket.helpers import advance_winner, _set_winner
    pid = match.player1_id if pick_player == 1 else match.player2_id
    part = _db.session.get(Participant, pid)
    _set_winner(match, part)
    advance_winner(match, match.tournament)
    _db.session.commit()


def play_all(tournament, pick=1):
    """Play every decidable match to completion.
    Must be called inside an app context.  Returns the refreshed Tournament.
    """
    from bracket.helpers import advance_winner, _set_winner
    for _ in range(500):
        m = Match.query.filter(
            Match.tournament_id == tournament.id,
            Match.winner_id == None,  # noqa: E711
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        if not m:
            break
        pid = m.player1_id if pick == 1 else m.player2_id
        part = _db.session.get(Participant, pid)
        _set_winner(m, part)
        advance_winner(m, m.tournament)
        _db.session.commit()
    return _db.session.get(Tournament, tournament.id)


def undecided_count(tournament_id):
    """Count matches that have players but no winner yet."""
    return Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.winner_id == None,  # noqa: E711
        Match.player1_id != None,  # noqa: E711
        Match.player2_id != None,  # noqa: E711
    ).count()


def lb_bye_matches(tournament_id, round_num=None):
    """Return LB matches that were decided as byes (one slot empty)."""
    q = Match.query.filter(
        Match.tournament_id == tournament_id,
        Match.bracket == 'L',
        Match.winner_id != None,  # noqa: E711
        (Match.player1_id == None) | (Match.player2_id == None),  # noqa: E711
    )
    if round_num is not None:
        q = q.filter(Match.round_num == round_num)
    return q.all()
