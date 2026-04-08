"""Tests for round-gating and bye randomization in both WB and LB."""
import pytest
from app import db
from models import Match, Participant
from bracket.helpers import advance_winner, _set_winner, _should_gate_lb_round
from tests.conftest import make_tournament, play_all, lb_bye_matches


# ---------------------------------------------------------------------------
# _should_gate_lb_round unit tests
# ---------------------------------------------------------------------------

def test_should_gate_lb_round_consolidation_odd(app):
    """LB match feeding into consolidation with odd prior count → True."""
    with app.app_context():
        # n=13: LB R2 has 3 matches (odd), LB R3 is consolidation → should gate
        t = make_tournament(13, bracket_type='double')
        lb_r2_match = Match.query.filter_by(
            tournament_id=t.id, bracket='L', round_num=2
        ).first()
        assert lb_r2_match is not None
        assert _should_gate_lb_round(lb_r2_match, t) is True


def test_should_gate_lb_round_consolidation_even(app):
    """LB match feeding into consolidation with even prior count → False."""
    with app.app_context():
        # n=8: LB R1 has 2 matches (even), LB R2 is consolidation → no gate
        t = make_tournament(8, bracket_type='double')
        # Check LB R1 round type
        lb_r1_match = Match.query.filter_by(
            tournament_id=t.id, bracket='L', round_num=1
        ).first()
        # For n=8, LB R1 has 4 matches (even) → no gate
        r1_count = Match.query.filter_by(
            tournament_id=t.id, bracket='L', round_num=1
        ).count()
        if r1_count % 2 == 0:
            assert _should_gate_lb_round(lb_r1_match, t) is False


def test_should_gate_lb_round_not_lb(app):
    """WB match → False."""
    with app.app_context():
        t = make_tournament(8, bracket_type='double')
        wb_match = Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=1
        ).first()
        assert _should_gate_lb_round(wb_match, t) is False


def test_should_gate_lb_round_no_next(app):
    """LB match with no next_match_id (LB final) → False."""
    with app.app_context():
        t = make_tournament(4, bracket_type='double')
        from app import db as _db
        max_lb = _db.session.query(
            db.func.max(Match.round_num)
        ).filter_by(tournament_id=t.id, bracket='L').scalar()
        lb_final = Match.query.filter_by(
            tournament_id=t.id, bracket='L', round_num=max_lb
        ).first()
        # LB final links to GF, not another LB round
        assert _should_gate_lb_round(lb_final, t) is False


# ---------------------------------------------------------------------------
# LB gating hold: gate doesn't fire until all round matches complete
# ---------------------------------------------------------------------------

def test_lb_gate_holds_until_round_complete(app):
    """n=13: LB R2 (3 matches) feeds consolidation LB R3.
    Play 2 of 3 LB R2 matches — LB R3 should remain empty.
    Play the 3rd — LB R3 should now be populated.
    """
    with app.app_context():
        t = make_tournament(13, bracket_type='double')

        # First play all WB R1 so LB R1 gets populated
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=1
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # Play all LB R1 matches
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='L', round_num=1
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # Play all WB R2 (to populate LB R2 dropdown slots)
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=2
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # Now LB R2 should have playable matches. Play 2 of 3.
        lb_r2 = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 2,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
            Match.winner_id == None,  # noqa: E711
        ).all()
        assert len(lb_r2) == 3, f"Expected 3 LB R2 matches, got {len(lb_r2)}"

        # Play 2 of 3
        for m in lb_r2[:2]:
            _set_winner(m, db.session.get(Participant, m.player1_id))
            advance_winner(m, m.tournament)
            db.session.commit()

        # LB R3 should still be empty (gate not fired)
        lb_r3_players = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 3,
            (Match.player1_id != None) | (Match.player2_id != None),  # noqa: E711
        ).count()
        assert lb_r3_players == 0, "LB R3 should be empty before gate fires"

        # Play the 3rd LB R2 match — gate fires
        _set_winner(lb_r2[2], db.session.get(Participant, lb_r2[2].player1_id))
        advance_winner(lb_r2[2], lb_r2[2].tournament)
        db.session.commit()

        # LB R3 should now have players
        lb_r3_populated = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'L',
            Match.round_num == 3,
            (Match.player1_id != None) | (Match.player2_id != None),  # noqa: E711
        ).count()
        assert lb_r3_populated > 0, "LB R3 should be populated after gate fires"


# ---------------------------------------------------------------------------
# LB bye randomization (statistical)
# ---------------------------------------------------------------------------

def test_lb_bye_randomization_statistical(app):
    """n=13: LB R3 bye is assigned randomly, not to a deterministic player.
    Run 20 trials, each always picking player1 as winner. Without gating,
    the same player always gets the bye. With gating, distribution spreads.
    """
    bye_recipients = set()
    TRIALS = 20

    for _ in range(TRIALS):
        with app.app_context():
            t = make_tournament(13, bracket_type='double')
            play_all(t)

            r3_byes = lb_bye_matches(t.id, round_num=3)
            for m in r3_byes:
                bye_recipients.add(m.winner_id)

    assert len(bye_recipients) >= 3, (
        f"Expected LB R3 bye to go to ≥3 distinct players over {TRIALS} trials, "
        f"got {len(bye_recipients)}. Gating may not be randomizing correctly."
    )


# ---------------------------------------------------------------------------
# WB gating hold: semi-finals don't populate until prior round completes
# ---------------------------------------------------------------------------

def test_wb_gate_holds_final(app):
    """n=8 (3 WB rounds, gated_from=2): WB R3 (final) should not populate
    until ALL WB R2 (semis) matches are decided.
    n=8: R1=4 matches, R2=2 semis (gated), R3=1 final (gated).
    """
    with app.app_context():
        t = make_tournament(8, bracket_type='single')
        # Play all R1
        for m in Match.query.filter_by(
            tournament_id=t.id, bracket='W', round_num=1
        ).all():
            if m.player1_id and m.player2_id and not m.winner_id:
                _set_winner(m, db.session.get(Participant, m.player1_id))
                advance_winner(m, m.tournament)
                db.session.commit()

        # Play 1 of 2 R2 (semi) matches
        r2 = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 2,
            Match.player1_id != None,  # noqa: E711
            Match.player2_id != None,  # noqa: E711
            Match.winner_id == None,  # noqa: E711
        ).all()
        assert len(r2) == 2, f"n=8 should have 2 R2 semis, got {len(r2)}"

        _set_winner(r2[0], db.session.get(Participant, r2[0].player1_id))
        advance_winner(r2[0], r2[0].tournament)
        db.session.commit()

        # R3 (final) should still be empty
        r3_players = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 3,
            (Match.player1_id != None) | (Match.player2_id != None),  # noqa: E711
        ).count()
        assert r3_players == 0, "WB R3 final should be empty before all R2 semis done"

        # Play the 2nd R2 match — gate fires, final populates
        _set_winner(r2[1], db.session.get(Participant, r2[1].player1_id))
        advance_winner(r2[1], r2[1].tournament)
        db.session.commit()

        r3_populated = Match.query.filter(
            Match.tournament_id == t.id,
            Match.bracket == 'W',
            Match.round_num == 3,
            (Match.player1_id != None) | (Match.player2_id != None),  # noqa: E711
        ).count()
        assert r3_populated > 0, "WB R3 final should populate after all R2 semis done"


# ---------------------------------------------------------------------------
# WB bye randomization
# ---------------------------------------------------------------------------

def test_wb_bye_randomization_statistical(app):
    """n=11 single (5 R1 matches, odd → bye in semi-finals):
    The semi-finals bye should go to different players across trials.
    """
    bye_recipients = set()
    TRIALS = 20

    for _ in range(TRIALS):
        with app.app_context():
            t = make_tournament(11, bracket_type='single')
            play_all(t)

            num_rounds = t.rounds
            gated_from = num_rounds - 1

            # Find bye matches in the gated rounds (semis+)
            for r in range(gated_from, num_rounds + 1):
                bye_m = Match.query.filter(
                    Match.tournament_id == t.id,
                    Match.bracket == 'W',
                    Match.round_num == r,
                    Match.winner_id != None,  # noqa: E711
                    (Match.player1_id == None) | (Match.player2_id == None),  # noqa: E711
                ).first()
                if bye_m:
                    bye_recipients.add(bye_m.winner_id)

    assert len(bye_recipients) >= 3, (
        f"Expected WB bye to go to ≥3 distinct players over {TRIALS} trials, "
        f"got {len(bye_recipients)}."
    )


# ---------------------------------------------------------------------------
# No double-bye via gating
# ---------------------------------------------------------------------------

@pytest.mark.parametrize('n', [9, 11, 13])
def test_no_double_bye_after_gating(app, n):
    """After LB gating fires and assigns byes, no player should have received
    byes in two consecutive LB rounds in the same tournament run.
    """
    with app.app_context():
        t = make_tournament(n, bracket_type='double')
        play_all(t)

        from app import db as _db
        max_lb = _db.session.query(
            db.func.max(Match.round_num)
        ).filter_by(tournament_id=t.id, bracket='L').scalar() or 0

        bye_per_round = {}
        for r in range(1, max_lb + 1):
            bye_m = Match.query.filter(
                Match.tournament_id == t.id,
                Match.bracket == 'L',
                Match.round_num == r,
                Match.winner_id != None,  # noqa: E711
                (Match.player1_id == None) | (Match.player2_id == None),  # noqa: E711
            ).first()
            if bye_m:
                bye_per_round[r] = bye_m.winner_id

        for r in sorted(bye_per_round):
            if r + 1 in bye_per_round:
                assert bye_per_round[r] != bye_per_round[r + 1], (
                    f"n={n}: same player got byes in LB R{r} and LB R{r+1}"
                )
