"""Tests for _clear_forward: undo cascading through WB, LB, and GF."""
import pytest
from app import db
from models import Match, Participant, Tournament
from bracket.helpers import advance_winner, _set_winner, _clear_forward
from tests.conftest import make_tournament, play_all, undecided_count


# ---------------------------------------------------------------------------
# Single elim: basic clear
# ---------------------------------------------------------------------------

def test_single_clear_r1_removes_winner_from_r2(app):
    """After clearing a decided R1 match, its winner is removed from R2."""
    with app.app_context():
        t = make_tournament(4, bracket_type='single')
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        winner_id = m.player1_id
        _set_winner(m, db.session.get(Participant, winner_id))
        advance_winner(m, m.tournament)
        db.session.commit()

        # Winner should be in R2
        r2 = db.session.get(Match, m.next_match_id)
        assert r2.player1_id == winner_id or r2.player2_id == winner_id

        # Clear R1
        _clear_forward(m)
        db.session.commit()

        r2 = db.session.get(Match, m.next_match_id)
        assert r2.player1_id != winner_id
        assert r2.player2_id != winner_id
        assert m.winner_id is None
        assert m.score1 == 0
        assert m.score2 == 0


def test_single_clear_resets_scores(app):
    """Clearing a match resets score1 and score2 to 0."""
    with app.app_context():
        t = make_tournament(4, bracket_type='single', race_to=3)
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        m.score1 = 3
        m.score2 = 2
        _set_winner(m, db.session.get(Participant, m.player1_id))
        advance_winner(m, m.tournament)
        db.session.commit()

        _clear_forward(m)
        db.session.commit()

        assert m.score1 == 0
        assert m.score2 == 0


# ---------------------------------------------------------------------------
# Single elim: clear the final
# ---------------------------------------------------------------------------

def test_single_clear_final_resets_tournament(app):
    """Clearing the final match resets tournament status and champion."""
    with app.app_context():
        t = make_tournament(4, bracket_type='single')
        t = play_all(t)
        assert t.status == 'complete'
        assert t.champion_id is not None

        # Find the final
        final = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=t.rounds
        ).first()
        _clear_forward(final)
        db.session.commit()

        t = db.session.get(Tournament, t.id)
        assert t.status == 'bracket'
        assert t.champion_id is None


# ---------------------------------------------------------------------------
# Double elim: WB clear cascades to LB
# ---------------------------------------------------------------------------

def test_double_clear_wb_removes_loser_from_lb(app):
    """Clearing a WB R1 match also removes the loser from the LB match."""
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        loser_id = m.player2_id
        lb_mid = m.loser_next_match_id

        _set_winner(m, db.session.get(Participant, m.player1_id))
        advance_winner(m, m.tournament)
        db.session.commit()

        lb_m = db.session.get(Match, lb_mid)
        assert lb_m.player1_id == loser_id or lb_m.player2_id == loser_id

        _clear_forward(m)
        db.session.commit()

        lb_m = db.session.get(Match, lb_mid)
        assert lb_m.player1_id != loser_id
        assert lb_m.player2_id != loser_id


def test_double_clear_wb_removes_winner_from_wb_next(app):
    """Clearing a WB R1 match also removes the winner from WB R2."""
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        winner_id = m.player1_id
        _set_winner(m, db.session.get(Participant, winner_id))
        advance_winner(m, m.tournament)
        db.session.commit()

        _clear_forward(m)
        db.session.commit()

        r2 = db.session.get(Match, m.next_match_id)
        assert r2.player1_id != winner_id
        assert r2.player2_id != winner_id


# ---------------------------------------------------------------------------
# Double elim: cascade through LB chain
# ---------------------------------------------------------------------------

def test_double_clear_lb_cascades(app):
    """Clearing an LB match removes the winner from the next LB match."""
    with app.app_context():
        t = make_tournament(8, bracket_type='double')

        # Play WB R1 to get losers into LB R1
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=1
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # Play all LB R1 matches
        lb_r1 = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
            Match.winner_id == None,  # noqa: E711
        ).all()
        for m in lb_r1:
            _set_winner(m, db.session.get(Participant, m.player1_id))
            advance_winner(m, m.tournament)
            db.session.commit()

        # Pick one decided LB R1 match and clear it
        decided = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 1,
            Match.winner_id != None,  # noqa: E711
        ).first()
        winner_id = decided.winner_id
        next_lb_mid = decided.next_match_id

        _clear_forward(decided)
        db.session.commit()

        assert decided.winner_id is None
        if next_lb_mid:
            next_lb = db.session.get(Match, next_lb_mid)
            assert next_lb.player1_id != winner_id
            assert next_lb.player2_id != winner_id


# ---------------------------------------------------------------------------
# Double elim: clear GF
# ---------------------------------------------------------------------------

def test_double_clear_gf_resets_tournament(app):
    """Clearing the GF resets tournament to bracket status."""
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        t = play_all(t)
        assert t.status == 'complete'

        gf = Match.query.filter_by(tournament_id=t.id, bracket='GF').first()
        _clear_forward(gf)
        db.session.commit()

        t = db.session.get(Tournament, t.id)
        assert t.status == 'bracket'
        assert t.champion_id is None
        assert t.runner_up_id is None


# ---------------------------------------------------------------------------
# Idempotent clear
# ---------------------------------------------------------------------------

def test_clear_undecided_match_no_crash(app):
    """Clearing a match with no winner should not raise or change state."""
    with app.app_context():
        t = make_tournament(4, bracket_type='single')
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        assert m.winner_id is None
        _clear_forward(m)  # should be a no-op
        db.session.commit()
        assert m.winner_id is None


# ---------------------------------------------------------------------------
# Re-play after clear produces correct new winner
# ---------------------------------------------------------------------------

def test_replay_after_clear_advances_new_winner(app):
    """After clearing, re-playing a match with a DIFFERENT winner correctly
    advances the new winner downstream.
    """
    with app.app_context():
        t = make_tournament(4, bracket_type='single')
        m = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
        ).first()
        p1_id = m.player1_id
        p2_id = m.player2_id
        original_next = m.next_match_id
        original_slot = m.next_slot

        # Play with player1 winning
        _set_winner(m, db.session.get(Participant, p1_id))
        advance_winner(m, m.tournament)
        db.session.commit()

        r2 = db.session.get(Match, original_next)
        assert r2.player1_id == p1_id or r2.player2_id == p1_id

        # Clear and re-play with player2 winning
        _clear_forward(m)
        db.session.commit()

        _set_winner(m, db.session.get(Participant, p2_id))
        advance_winner(m, m.tournament)
        db.session.commit()

        r2 = db.session.get(Match, original_next)
        # Now p2 should be in R2
        assert r2.player1_id == p2_id or r2.player2_id == p2_id
        # And p1 should NOT be in R2
        assert r2.player1_id != p1_id
        assert r2.player2_id != p1_id


# ---------------------------------------------------------------------------
# Full clear-and-replay: tournament can complete after mid-clear
# ---------------------------------------------------------------------------

def test_double_clear_mid_tournament_and_complete(app):
    """Play partway through, clear an LB match, continue — tournament still reaches complete."""
    with app.app_context():
        t = make_tournament(8, bracket_type='double')

        # Play WB R1 only
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=1
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # Play LB R1
        for m in Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 1,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
            Match.winner_id == None,  # noqa: E711
        ).all():
            _set_winner(m, db.session.get(Participant, m.player1_id))
            advance_winner(m, m.tournament)
            db.session.commit()

        # Clear one LB R1 match
        lb_r1_decided = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 1,
            Match.winner_id != None,  # noqa: E711
        ).first()
        _clear_forward(lb_r1_decided)
        db.session.commit()

        # Re-play cleared match then finish tournament
        _set_winner(lb_r1_decided, db.session.get(Participant, lb_r1_decided.player1_id))
        advance_winner(lb_r1_decided, lb_r1_decided.tournament)
        db.session.commit()

        t = play_all(t)
        assert t.status == 'complete'
        assert undecided_count(t.id) == 0
