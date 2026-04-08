import random
from app import db
from models import Match, Participant
from bracket.helpers import _set_winner, _get_slots


def _compute_round_info(n):
    """Compute round structure: list of (num_matches, has_bye) per round."""
    info = []
    remaining = n
    while remaining > 1:
        info.append((remaining // 2, remaining % 2 == 1))
        remaining = remaining // 2 + remaining % 2
    return info


def _create_wb_matches(tournament, players, round_info):
    """Create WB match objects for all rounds, seed R1 players. Returns list of round lists."""
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
    return all_rounds


def _resolve_r1_byes(round_matches):
    """Auto-resolve R1 matches where one player has no opponent."""
    for m in round_matches:
        if m.player1_id and not m.player2_id:
            _set_winner(m, db.session.get(Participant, m.player1_id))
        elif m.player2_id and not m.player1_id:
            _set_winner(m, db.session.get(Participant, m.player2_id))


def _generate_single_bracket(tournament):
    """Generate a single-elimination bracket with minimal byes.

    At most 1 bye per round (when odd player count).  The bye player is
    pre-placed into the next round's first match so play can start
    immediately when that match's opponent is decided.

    Early rounds: per-match advancement (immediate).
    Semi-finals and finals (last 2 rounds): round-gated -- players are
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

    round_info = _compute_round_info(n)
    num_rounds = len(round_info)

    # Gated rounds: semi-finals and finals (last 2 rounds, if >= 3 rounds)
    gated_from = num_rounds - 1 if num_rounds >= 3 else num_rounds + 99

    # Adjust byes that would skip into gated rounds: convert to extra match
    for r_idx in range(num_rounds):
        if not round_info[r_idx][1]:
            continue
        skip_target = r_idx + 2
        if skip_target >= gated_from:
            m_count, _ = round_info[r_idx]
            round_info[r_idx] = (m_count + 1, False)

    all_rounds = _create_wb_matches(tournament, players, round_info)

    # Pre-fill R1 bye player into R2M0 slot 1 (non-gated only)
    if round_info[0][1] and num_rounds > 1 and 2 < gated_from:
        all_rounds[1][0].player1_id = players[-1].id

    _resolve_r1_byes(all_rounds[0])

    # -- Link matches across rounds --
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

        # If next round has a bye, pull the last feeder out -- it skips ahead
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

    # ==================================================================
    # Phase 1: Winners Bracket (same structure as single elim, no gating)
    # ==================================================================
    wb_round_info = _compute_round_info(n)
    num_wb_rounds = len(wb_round_info)

    wb_rounds = _create_wb_matches(tournament, players, wb_round_info)

    # Pre-fill WB R1 bye player into R2M0 slot 1
    if wb_round_info[0][1] and num_wb_rounds > 1:
        wb_rounds[1][0].player1_id = players[-1].id

    _resolve_r1_byes(wb_rounds[0])

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

    # ==================================================================
    # Phase 2: Losers Bracket
    # ==================================================================
    # LB R1:  WB R1 losers pair up
    # LB R2 (dropdown): LB R1 survivors vs WB R2 losers
    # LB R3 (consolidation): LB R2 survivors play each other
    # LB R4 (dropdown): LB R3 survivors vs WB R3 losers
    # ...alternating...

    # Count real losers per WB round (bye matches don't produce a real loser)
    wb_losers_per_round = []
    for r_idx, (num_matches, has_bye) in enumerate(wb_round_info):
        real_losers = num_matches
        # Bye matches in R1 auto-resolve -- no real loser
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
                continue  # No losers from R1 (all byes -- shouldn't happen with >= 4)

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

            # Consolidation round (skip for last WB round -- no more dropdowns after)
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

    # -- Track LB round types for correct linking --
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
            # 2:1 pairing: matches [0,1] -> dest 0, [2,3] -> dest 1
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
            # 1:1: each match -> slot 1 of the corresponding dropdown match
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

    # ==================================================================
    # Phase 3: Link WB losers -> LB (loser_next_match_id / loser_slot)
    # ==================================================================

    # WB R1 losers -> LB R1 (first LB round)
    # Pair WB R1 matches to LB R1 matches: WB M0 loser + WB M1 loser -> LB M0
    if lb_rounds:
        lb_r_idx = 0  # LB round index for WB R1 losers
        real_wb_r1 = [m for m in wb_rounds[0] if m.player1_id and m.player2_id]
        for i, wb_m in enumerate(real_wb_r1):
            dest_idx = i // 2
            if dest_idx < len(lb_rounds[lb_r_idx]):
                wb_m.loser_next_match_id = lb_rounds[lb_r_idx][dest_idx].id
                wb_m.loser_slot = 1 if i % 2 == 0 else 2

    # WB R2+ losers -> corresponding dropdown LB round
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

    # ==================================================================
    # Phase 4: Grand Final
    # ==================================================================
    gf = Match(
        tournament_id=tournament.id, bracket='GF',
        round_num=1, position=0,
        score1=0, score2=0,
    )
    db.session.add(gf)
    db.session.flush()

    # WB Final winner -> GF slot 1
    wb_final = wb_rounds[-1][-1]
    wb_final.next_match_id = gf.id
    wb_final.next_slot = 1

    # LB Final winner -> GF slot 2
    if lb_rounds:
        lb_final = lb_rounds[-1][-1]
        lb_final.next_match_id = gf.id
        lb_final.next_slot = 2

    tournament.status = 'bracket'
    db.session.commit()


def generate_bracket(tournament):
    Match.query.filter_by(tournament_id=tournament.id).delete()
    db.session.flush()
    if tournament.is_double:
        _generate_double_bracket(tournament)
    else:
        _generate_single_bracket(tournament)
