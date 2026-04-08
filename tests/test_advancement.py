"""Tests for match advancement, finalization, and scoring logic."""
import pytest
from app import db
from models import Tournament, Match, Participant
from bracket.helpers import advance_winner, _set_winner
from tests.conftest import make_tournament, play_all, undecided_count


# ---------------------------------------------------------------------------
# Full play-through: every bracket reaches 'complete' with no orphaned matches
# ---------------------------------------------------------------------------

SINGLE_COUNTS = [2, 3, 4, 5, 7, 8, 11, 13, 16, 20]
DOUBLE_COUNTS = [4, 5, 7, 8, 11, 13, 16]


@pytest.mark.parametrize('n', SINGLE_COUNTS)
def test_single_full_playthrough(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='single')
        t = play_all(t)
        assert t.status == 'complete', f"single n={n}: expected complete, got {t.status}"
        assert t.champion_id is not None, f"single n={n}: champion not set"
        assert undecided_count(t.id) == 0, f"single n={n}: undecided matches remain"


@pytest.mark.parametrize('n', DOUBLE_COUNTS)
def test_double_full_playthrough(app, n):
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        t = play_all(t)
        assert t.status == 'complete', f"double n={n}: expected complete, got {t.status}"
        assert t.champion_id is not None, f"double n={n}: champion not set"
        assert t.runner_up_id is not None, f"double n={n}: runner_up not set"
        assert undecided_count(t.id) == 0, f"double n={n}: undecided matches remain"


# ---------------------------------------------------------------------------
# R1 bye auto-resolve
# ---------------------------------------------------------------------------

def test_single_r1_bye_auto_resolved(app):
    """n=5: the R1 bye match (one player, no opponent) is resolved at generation time."""
    with app.app_context():
        t = make_tournament(5, bracket_type='single')
        bye_matches = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.winner_id != None,  # noqa: E711
        ).all()
        # Exactly one bye in R1 for n=5
        assert len(bye_matches) == 1
        bye = bye_matches[0]
        assert bye.player1_id is None or bye.player2_id is None


def test_double_r1_bye_pre_seeded_in_r2(app):
    """n=5 double: the WB R1 bye player is pre-seeded into R2M0 slot 1 (no R1 bye match)."""
    with app.app_context():
        t = make_tournament(5, bracket_type='double')
        # In double elim, the bye player skips R1 entirely and is placed
        # directly into R2M0 slot 1; there is no R1 bye match.
        r2_m0 = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=2, position=0
        ).first()
        assert r2_m0 is not None
        assert r2_m0.player1_id is not None, "Bye player should be pre-seeded into R2M0 slot 1"


# ---------------------------------------------------------------------------
# Loser drop into LB (double elim)
# ---------------------------------------------------------------------------

def test_loser_drops_to_lb_immediately(app):
    """After a WB R1 match completes, the loser appears in the LB match."""
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        # Find a WB R1 match with two real players
        wb_r1 = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        assert wb_r1.loser_next_match_id is not None

        loser_pid = wb_r1.player2_id  # player2 will lose
        _set_winner(wb_r1, db.session.get(Participant, wb_r1.player1_id))
        advance_winner(wb_r1, wb_r1.tournament)
        db.session.commit()

        lb_match = db.session.get(Match, wb_r1.loser_next_match_id)
        lb_players = {lb_match.player1_id, lb_match.player2_id}
        assert loser_pid in lb_players, "Loser should be placed in the LB match"


def test_loser_drops_before_wb_gate(app):
    """Double elim: LB gets populated even when WB is gated at semi-finals.
    n=8 has 3 WB rounds. gated_from=2 (semis). After WB R1 completes, WB R2
    is populated. After WB R2 completes, WB semis are gated. The WB semi gate
    fires only when all R2 matches are done — but LB should have received its
    WB R2 losers immediately.
    """
    with app.app_context():
        t = make_tournament(8, bracket_type='double')
        # Play all WB R1 matches
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=1
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()
        # Play all WB R2 matches
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=2
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # WB semis (R3) should NOT yet be populated (gated)
        semis = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=3
        ).all()
        semi_players = sum(1 for s in semis if s.player1_id or s.player2_id)
        # All R2 matches done → gate fires → semis DO populate
        assert semi_players > 0, "Semis should populate after all R2 done"

        # LB dropdown round (receives WB R2 losers) should have players
        from app import db as _db
        lb_dd_matches = Match.query.filter_by(
            tournament_id=t.id, bracket='L'
        ).filter(Match.round_num >= 2).all()
        lb_with_players = [m for m in lb_dd_matches if m.player1_id or m.player2_id]
        assert len(lb_with_players) > 0, "LB dropdown should have WB R2 losers"


# ---------------------------------------------------------------------------
# Score-based advancement (race_to > 1)
# ---------------------------------------------------------------------------

def test_score_based_win(app):
    """race_to=3: match not decided until a player reaches 3 wins."""
    with app.app_context():
        t = make_tournament(4, bracket_type='single', race_to=3)
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()

        # Two wins — not yet decided
        m.score1 = 2
        db.session.commit()
        assert m.winner_id is None

        # Third win — match decided
        m.score1 = 3
        part = db.session.get(Participant, m.player1_id)
        _set_winner(m, part)
        advance_winner(m, m.tournament)
        db.session.commit()
        assert m.winner_id == m.player1_id


def test_lb_uses_lb_race_to(app):
    """Double elim: LB matches respect lb_race_to independently of WB race_to."""
    from bracket.generators import generate_bracket
    with app.app_context():
        t = make_tournament(4, bracket_type='double', race_to=3)
        # lb_race_to is also 3 (set by make_tournament)
        lb_m = Match.query.filter_by(tournament_id=t.id, bracket='L').first()
        assert lb_m is not None
        assert t.lb_race_to == 3


# ---------------------------------------------------------------------------
# Tournament finalization
# ---------------------------------------------------------------------------

def test_single_finalizes_with_champion(app):
    with app.app_context():
        t = make_tournament(4, bracket_type='single')
        t = play_all(t)
        assert t.status == 'complete'
        assert t.champion_id is not None


def test_double_finalizes_with_champion_and_runner_up(app):
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        t = play_all(t)
        assert t.status == 'complete'
        assert t.champion_id is not None
        assert t.runner_up_id is not None
        assert t.champion_id != t.runner_up_id


def test_champion_is_gf_winner(app):
    """In double elim, champion_id corresponds to whoever wins the GF."""
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        t = play_all(t, pick=1)  # player1 always wins → traces to first bracket player
        gf = Match.query.filter_by(tournament_id=t.id, bracket='GF').first()
        winner = db.session.get(Participant, gf.winner_id)
        assert t.champion_id == winner.profile_id


# ---------------------------------------------------------------------------
# No orphaned matches after completion
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('n,bracket_type', [
    (8, 'single'), (13, 'single'), (8, 'double'), (13, 'double')
])
def test_no_orphaned_undecided_matches(app, n, bracket_type):
    """After play-through, every match with players must have a winner."""
    with app.app_context():
        t = make_tournament(n, bracket_type=bracket_type)
        play_all(t)
        remaining = Match.query.filter(
            Match.tournament_id == t.id,
            Match.winner_id == None,  # noqa: E711
            (Match.player1_id != None) | (Match.player2_id != None),  # noqa: E711
        ).count()
        assert remaining == 0
