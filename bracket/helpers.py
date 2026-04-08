import random
from app import db
from models import Match, Participant, Tournament


def _set_winner(match, participant):
    match.winner_id = participant.id if participant else None
    match.winner_profile_id = participant.profile_id if participant else None


def _seeded_bracket_order(n):
    """Return seed numbers in bracket-slot order for a power-of-2 bracket of size n.
    Result: [1,8,4,5,2,7,3,6] for n=8 -> matches (1v8),(4v5),(2v7),(3v6)."""
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
    Random seeding shuffles.  No None padding -- the bracket generator
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


def _should_gate_lb_round(match, tournament):
    """Check whether this LB match's round should be gated.

    Only gate rounds feeding into a CONSOLIDATION round with a bye.
    Consolidation rounds have no WB loser-feeders — all inputs come
    from a single preceding LB round, so the bye is fully determined
    by the current round's match count.  Dropdown rounds (which mix
    LB survivors with WB losers) are left ungated to avoid deadlocks.
    """
    if match.bracket != 'L' or not match.next_match_id:
        return False
    next_m = db.session.get(Match, match.next_match_id)
    if not next_m or next_m.bracket != 'L':
        return False  # feeds GF, not another LB round

    # Check if next round is consolidation (no WB loser feeders)
    next_round_matches = Match.query.filter_by(
        tournament_id=tournament.id, bracket='L',
        round_num=next_m.round_num,
    ).all()
    next_match_ids = {nm.id for nm in next_round_matches}
    has_wb_feeders = Match.query.filter(
        Match.loser_next_match_id.in_(next_match_ids),
    ).count() > 0
    if has_wb_feeders:
        return False  # dropdown round — don't gate

    # Consolidation: gate when current round has odd match count (= bye)
    current_count = Match.query.filter_by(
        tournament_id=tournament.id, bracket='L',
        round_num=match.round_num,
    ).count()
    return current_count % 2 == 1


def _gate_advance_lb(tournament, completed_lb_round_num):
    """LB round-gating: randomize bye assignment in the next consolidation round.

    Waits for ALL matches in the completed LB round to be decided,
    then shuffles winner-to-destination assignments so the bye
    recipient is random, not determined by match completion order.
    """
    round_matches = Match.query.filter_by(
        tournament_id=tournament.id, bracket='L',
        round_num=completed_lb_round_num,
    ).all()

    # Check all matches in the round are decided
    for m in round_matches:
        if (m.player1_id or m.player2_id) and not m.winner_id:
            return  # round not yet complete

    # Collect advances
    advances = [(m, m.next_match_id, m.next_slot)
                for m in round_matches if m.winner_id and m.next_match_id]
    if not advances:
        return

    # Randomize destinations (bye assignment)
    if len(advances) % 2 == 1 and len(advances) >= 2:
        dests = [(nmid, ns) for _, nmid, ns in advances]
        random.shuffle(dests)
        for i, (m, _, _) in enumerate(advances):
            m.next_match_id = dests[i][0]
            m.next_slot = dests[i][1]
        db.session.flush()

    # Place ALL winners into next round
    for m in round_matches:
        if m.winner_id and m.next_match_id:
            next_m = db.session.get(Match, m.next_match_id)
            if next_m:
                if m.next_slot == 1:
                    next_m.player1_id = m.winner_id
                elif m.next_slot == 2:
                    next_m.player2_id = m.winner_id
    db.session.flush()

    # Resolve byes in the populated consolidation round
    next_round_num = completed_lb_round_num + 1
    next_round_matches = Match.query.filter_by(
        tournament_id=tournament.id, bracket='L',
        round_num=next_round_num,
    ).all()
    for nm in next_round_matches:
        if nm.winner_id:
            continue
        _try_auto_advance(nm, tournament)


def _gate_advance(tournament, completed_round_num):
    """Round-gating for semi-finals and finals.

    Populates the next round only when ALL matches in the current round
    are decided.  Auto-resolves any byes in the populated round, then
    cascades if that round is also fully decided.

    When matches in the round have different destination rounds (a
    skip-feeder sending one winner past the semis), the winner->destination
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
        # Pre-fetch destination matches in one query
        dest_ids = {nmid for _, nmid, _ in advances}
        dest_matches = {m.id: m for m in Match.query.filter(Match.id.in_(dest_ids)).all()}

        dest_rounds = {dest_matches[nmid].round_num for _, nmid, _ in advances if nmid in dest_matches}

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
            next_m = db.session.get(Match, m.next_match_id)
            if next_m:
                if m.next_slot == 1:
                    next_m.player1_id = m.winner_id
                elif m.next_slot == 2:
                    next_m.player2_id = m.winner_id
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
    is_double = tournament.is_double

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
                if match.loser_slot == 1:
                    lb_match.player1_id = loser_id
                else:
                    lb_match.player2_id = loser_id
                db.session.flush()
                _try_auto_advance(lb_match, tournament)

    num_rounds = tournament.rounds
    gated_from = num_rounds - 1 if num_rounds >= 3 else num_rounds + 99

    # Semi-finals and finals: round-gated (randomizes bye assignment)
    if next_m.round_num >= gated_from and match.bracket == 'W':
        _gate_advance(tournament, match.round_num)
        return

    # LB rounds feeding into a round with a bye: round-gated
    if match.bracket == 'L' and _should_gate_lb_round(match, tournament):
        _gate_advance_lb(tournament, match.round_num)
        return

    # Per-match advancement: place winner into next match
    if match.next_slot == 1:
        next_m.player1_id = match.winner_id
    else:
        next_m.player2_id = match.winner_id
    db.session.flush()

    # Auto-advance bye in the winner's next match
    _try_auto_advance(next_m, tournament)


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
