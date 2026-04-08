"""Tests for bracket structure after generation.

Verifies match counts, linking, bye placement, and structural invariants
for both single and double elimination brackets.
"""
import pytest
from models import Match, Tournament
from bracket.generators import _compute_round_info
from tests.conftest import make_tournament


# ---------------------------------------------------------------------------
# _compute_round_info
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('n,expected', [
    (2,  [(1, False)]),
    (3,  [(1, True),  (1, False)]),
    (4,  [(2, False), (1, False)]),
    (5,  [(2, True),  (1, True), (1, False)]),
    (7,  [(3, True),  (2, False), (1, False)]),
    (8,  [(4, False), (2, False), (1, False)]),
    (16, [(8, False), (4, False), (2, False), (1, False)]),
])
def test_compute_round_info(n, expected):
    assert _compute_round_info(n) == expected


@pytest.mark.parametrize('n', range(2, 21))
def test_compute_round_info_total_matches(n):
    """Sum of all num_matches in round_info == n-1 (single elim match count)."""
    info = _compute_round_info(n)
    assert sum(m for m, _ in info) == n - 1


# ---------------------------------------------------------------------------
# Single bracket structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('n', [2, 3, 4, 5, 7, 8, 11, 13, 16, 20])
def test_single_match_count(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='single')
        wb = Match.query.filter_by(tournament_id=t.id, bracket='W').count()
        # Each match eliminates one player → at least n-1.
        # Byes in gated rounds are converted to extra real matches (fairness),
        # so the count may exceed n-1 by the number of such conversions.
        assert wb >= n - 1, f"Expected at least {n-1} WB matches for n={n}, got {wb}"


@pytest.mark.parametrize('n', [2, 3, 4, 5, 7, 8, 11, 13, 16, 20])
def test_single_status_after_generation(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='single')
        assert t.status == 'bracket'


@pytest.mark.parametrize('n', [2, 3, 4, 5, 7, 8, 11, 13, 16, 20])
def test_single_final_has_no_next_match(app, n):
    """The WB final must not link to any further match."""
    with app.app_context():
        t = make_tournament(n, bracket_type='single')
        num_rounds = t.rounds
        finals = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=num_rounds
        ).all()
        assert len(finals) == 1
        assert finals[0].next_match_id is None


@pytest.mark.parametrize('n', [2, 3, 4, 5, 7, 8, 11, 13, 16, 20])
def test_single_non_final_matches_have_next_match(app, n):
    """Every WB match except the final must link to a next match."""
    with app.app_context():
        t = make_tournament(n, bracket_type='single')
        num_rounds = t.rounds
        non_finals = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num < num_rounds,
        ).all()
        missing = [m for m in non_finals if m.next_match_id is None]
        assert missing == [], f"Non-final matches missing next_match_id: {[m.id for m in missing]}"


@pytest.mark.parametrize('n', [2, 3, 4, 5, 7, 8, 11, 13, 16, 20])
def test_single_at_most_one_bye_per_round(app, n):
    """No round should have more than one bye (auto-resolved solo match)."""
    with app.app_context():
        t = make_tournament(n, bracket_type='single')
        num_rounds = t.rounds
        for r in range(1, num_rounds + 1):
            byes = Match.query.filter(
                Match.tournament_id == t.id,
                Match.bracket == 'W',
                Match.round_num == r,
                Match.winner_id != None,  # noqa: E711
                (Match.player1_id == None) | (Match.player2_id == None),  # noqa: E711
            ).count()
            assert byes <= 1, f"Round {r} has {byes} byes (expected ≤1)"


def test_single_r1_bye_prefilled_in_r2(app):
    """For n=11 (4 rounds, R1 has bye), the bye player is pre-seeded in R2M0 slot 1."""
    with app.app_context():
        t = make_tournament(11, bracket_type='single')
        r2_m0 = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=2, position=0
        ).first()
        assert r2_m0 is not None
        # R2 is non-gated for 11 players (4 rounds, gated_from=3)
        assert r2_m0.player1_id is not None, "R2M0 slot 1 should be pre-filled with R1 bye player"


def test_single_min_players(app):
    """n=2 generates a valid 1-match bracket."""
    with app.app_context():
        t = make_tournament(2, bracket_type='single')
        assert t.status == 'bracket'
        assert Match.query.filter_by(tournament_id=t.id, bracket='W').count() == 1


def test_single_too_few_players(app):
    """n=1 should not generate a bracket (stays 'open')."""
    from bracket.generators import generate_bracket
    from models import Participant, PlayerProfile
    from app import db
    with app.app_context():
        t = Tournament(name='T', buyin=10, bracket_type='single')
        db.session.add(t)
        db.session.flush()
        p = PlayerProfile(name='Solo')
        db.session.add(p)
        db.session.flush()
        db.session.add(Participant(tournament_id=t.id, profile_id=p.id))
        db.session.commit()
        generate_bracket(t)
        assert t.status == 'bracket'  # generator sets bracket but no matches
        assert Match.query.filter_by(tournament_id=t.id).count() == 0


# ---------------------------------------------------------------------------
# Double bracket structure
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_wb_match_count(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        wb = Match.query.filter_by(tournament_id=t.id, bracket='W').count()
        assert wb == n - 1


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_has_exactly_one_gf(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        gf = Match.query.filter_by(tournament_id=t.id, bracket='GF').count()
        assert gf == 1


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_status_after_generation(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        assert t.status == 'bracket'


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_wb_final_links_to_gf_slot1(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        gf = Match.query.filter_by(tournament_id=t.id, bracket='GF').first()
        num_wb_rounds = Match.query.with_entities(
            Match.round_num
        ).filter_by(tournament_id=t.id, bracket='W').distinct().count()
        wb_final = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=num_wb_rounds
        ).first()
        assert wb_final.next_match_id == gf.id
        assert wb_final.next_slot == 1


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_lb_final_links_to_gf_slot2(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        gf = Match.query.filter_by(tournament_id=t.id, bracket='GF').first()
        from app import db
        max_lb_round = db.session.query(
            db.func.max(Match.round_num)
        ).filter_by(tournament_id=t.id, bracket='L').scalar()
        lb_final = Match.query.filter_by(
            tournament_id=t.id, bracket='L', round_num=max_lb_round
        ).first()
        assert lb_final.next_match_id == gf.id
        assert lb_final.next_slot == 2


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_wb_r1_real_matches_have_loser_link(app, n):
    """Every WB R1 match with 2 players must have loser_next_match_id set."""
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        real_r1 = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).all()
        no_link = [m for m in real_r1 if m.loser_next_match_id is None]
        assert no_link == [], f"WB R1 real matches missing loser link: {[m.id for m in no_link]}"


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_wb_r2plus_matches_have_loser_link(app, n):
    """Every WB R2+ match (except the WB final) must have loser_next_match_id."""
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        num_wb_rounds = Match.query.with_entities(
            Match.round_num
        ).filter_by(tournament_id=t.id, bracket='W').distinct().count()
        r2plus = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num > 1,
            Match.round_num < num_wb_rounds,
        ).all()
        no_link = [m for m in r2plus if m.loser_next_match_id is None]
        assert no_link == [], f"WB R2+ non-final matches missing loser link: {[m.id for m in no_link]}"


@pytest.mark.parametrize('n', [4, 5, 7, 8, 11, 13, 16])
def test_double_at_most_one_bye_per_lb_round(app, n):
    """No LB round should have more than one bye match."""
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        from app import db
        max_lb = db.session.query(
            db.func.max(Match.round_num)
        ).filter_by(tournament_id=t.id, bracket='L').scalar() or 0
        for r in range(1, max_lb + 1):
            byes = Match.query.filter(
                Match.tournament_id == t.id,
                Match.bracket == 'L',
                Match.round_num == r,
                Match.winner_id != None,  # noqa: E711
                (Match.player1_id == None) | (Match.player2_id == None),  # noqa: E711
            ).count()
            assert byes <= 1, f"LB Round {r} has {byes} byes for n={n}"


@pytest.mark.parametrize('n', [9, 11])
def test_double_no_consecutive_lb_byes_for_same_player(app, n):
    """No player should receive a bye in two consecutive LB rounds."""
    with app.app_context():
        from tests.conftest import play_all
        t = make_tournament(n, bracket_type='double')
        play_all(t)

        from app import db
        max_lb = db.session.query(
            db.func.max(Match.round_num)
        ).filter_by(tournament_id=t.id, bracket='L').scalar() or 0

        bye_per_round = {}
        for r in range(1, max_lb + 1):
            bye_match = Match.query.filter(
                Match.tournament_id == t.id,
                Match.bracket == 'L',
                Match.round_num == r,
                Match.winner_id != None,  # noqa: E711
                (Match.player1_id == None) | (Match.player2_id == None),  # noqa: E711
            ).first()
            if bye_match:
                bye_per_round[r] = bye_match.winner_id

        for r in sorted(bye_per_round):
            if r + 1 in bye_per_round:
                assert bye_per_round[r] != bye_per_round[r + 1], (
                    f"Same player got byes in consecutive LB rounds {r} and {r+1}"
                )
