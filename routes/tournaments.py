import json
import math
from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from app import db
from models import Tournament, Match, PlayerProfile, Participant, League, ManagerShare
from bracket.helpers import _set_winner, advance_winner, _clear_forward
from bracket.generators import generate_bracket

bp = Blueprint('tournaments', __name__)


def _check_access(t):
    """Abort 403 if current_user cannot manage this tournament."""
    if not t.can_manage(current_user):
        abort(403)


@bp.route('/')
def index():
    upcoming = Tournament.query.filter(
        Tournament.status != 'complete'
    ).order_by(Tournament.tournament_date.asc().nullslast(), Tournament.id.desc()).all()

    past = Tournament.query.filter_by(status='complete').order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()

    # Precompute manageable tournament IDs to avoid N+1 ManagerShare queries
    manageable_ids = set()
    if current_user.is_authenticated:
        all_tournaments = upcoming + past
        if current_user.is_admin:
            manageable_ids = {t.id for t in all_tournaments}
        else:
            # Leagues the user owns
            owned_league_ids = {lg.id for lg in League.query.filter_by(owner_id=current_user.id).all()}
            # Leagues delegated to the user
            delegate_league_ids = {s.league_id for s in ManagerShare.query.filter_by(
                delegate_id=current_user.id).all() if s.league_id}
            all_league_ids = owned_league_ids | delegate_league_ids
            manageable_ids = {t.id for t in all_tournaments
                             if t.league_id in all_league_ids}

    return render_template('index.html', upcoming=upcoming, past=past,
                           manageable_ids=manageable_ids)


@bp.route('/league/<int:lid>/tournament/new', methods=['GET', 'POST'])
@login_required
def new_tournament(lid):
    league = League.query.get_or_404(lid)
    if not league.can_manage(current_user):
        abort(403)
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
            try:
                t_date = datetime.strptime(t_date_str, '%Y-%m-%d').date()
            except ValueError:
                pass
        if not name:
            flash('Tournament name is required.', 'danger')
            return redirect(url_for('tournaments.new_tournament', lid=lid))

        # Parse dynamic prize splits: split_type_N, split_val_N
        ORDINALS = ['1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th']
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
            return redirect(url_for('tournaments.new_tournament', lid=lid))

        t = Tournament(
            name=name, buyin=buyin, table_fee=table_fee,
            format=fmt, seeding=seeding,
            race_to=race_to, fargo_rated=fargo_rated,
            bracket_type=bracket_type,
            lb_format=lb_fmt, lb_race_to=lb_race_to,
            prize_splits=json.dumps(splits),
            tournament_date=t_date,
            owner_id=current_user.id,
            league_id=lid,
        )
        db.session.add(t)
        db.session.commit()
        return redirect(url_for('tournaments.tournament', tid=t.id))
    return render_template('new_tournament.html', league=league)


@bp.route('/tournament/<int:tid>')
@login_required
def tournament(tid):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    all_profiles = PlayerProfile.query.filter_by(league_id=t.league_id).order_by(
        PlayerProfile.first_name, PlayerProfile.last_name).all()
    enrolled_ids = {p.profile_id for p in t.participants}
    return render_template('tournament.html', t=t, all_profiles=all_profiles,
                           enrolled_ids=enrolled_ids)


@bp.route('/tournament/<int:tid>/add_player', methods=['POST'])
@login_required
def add_player(tid):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    if t.status != 'open':
        flash('Cannot add players after bracket is generated.', 'warning')
        return redirect(url_for('tournaments.tournament', tid=tid))
    profile_id = request.form.get('profile_id', type=int)
    if profile_id:
        if not Participant.query.filter_by(tournament_id=tid, profile_id=profile_id).first():
            db.session.add(Participant(tournament_id=tid, profile_id=profile_id))
            db.session.commit()
    return redirect(url_for('tournaments.tournament', tid=tid))


@bp.route('/tournament/<int:tid>/quick_add_player', methods=['POST'])
@login_required
def quick_add_player(tid):
    """Create a new player profile and immediately add them to the tournament."""
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    if t.status != 'open':
        flash('Cannot add players after bracket is generated.', 'warning')
        return redirect(url_for('tournaments.tournament', tid=tid))
    first = request.form.get('first_name', '').strip()
    last = request.form.get('last_name', '').strip()
    if not first:
        flash('First name is required.', 'danger')
        return redirect(url_for('tournaments.tournament', tid=tid))
    profile = PlayerProfile(first_name=first, last_name=last or '', league_id=t.league_id)
    db.session.add(profile)
    db.session.flush()
    db.session.add(Participant(tournament_id=tid, profile_id=profile.id))
    db.session.commit()
    flash(f'{profile.full_name} created and added to the tournament.', 'success')
    return redirect(url_for('tournaments.tournament', tid=tid))


@bp.route('/tournament/<int:tid>/remove_player/<int:part_id>', methods=['POST'])
@login_required
def remove_player(tid, part_id):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    if t.status != 'open':
        flash('Cannot remove players after bracket is generated.', 'warning')
        return redirect(url_for('tournaments.tournament', tid=tid))
    p = Participant.query.get_or_404(part_id)
    name = p.profile.full_name
    db.session.delete(p)
    db.session.commit()
    flash(f'{name} removed from tournament.', 'info')
    return redirect(url_for('tournaments.tournament', tid=tid))


@bp.route('/tournament/<int:tid>/generate', methods=['POST'])
@login_required
def generate(tid):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    if t.num_players < 2:
        flash('Need at least 2 players to generate a bracket.', 'danger')
        return redirect(url_for('tournaments.tournament', tid=tid))
    generate_bracket(t)
    return redirect(url_for('tournaments.bracket', tid=tid))


def _load_bracket_context(t):
    """Load WB rounds, LB rounds, and GF match for a tournament bracket."""
    tid = t.id
    all_matches = Match.query.filter_by(tournament_id=tid).order_by(Match.position).all()

    num_wr_rounds = t.rounds
    wr_rounds = {}
    for r in range(1, num_wr_rounds + 1):
        wr_rounds[r] = [m for m in all_matches if m.bracket == 'W' and m.round_num == r]

    lb_rounds = {}
    gf_match = None
    num_lb_rounds = 0
    if t.is_double:
        lb_matches = [m for m in all_matches if m.bracket == 'L']
        num_lb_rounds = max((m.round_num for m in lb_matches), default=0)
        for r in range(1, num_lb_rounds + 1):
            lb_rounds[r] = [m for m in lb_matches if m.round_num == r]
        gf_match = next((m for m in all_matches if m.bracket == 'GF'), None)

    can_manage = t.can_manage(current_user)

    return dict(
        t=t, wr_rounds=wr_rounds, num_wr_rounds=num_wr_rounds,
        lb_rounds=lb_rounds, num_lb_rounds=num_lb_rounds,
        gf_match=gf_match, can_manage=can_manage,
    )


@bp.route('/tournament/<int:tid>/bracket')
def bracket(tid):
    t = Tournament.query.get_or_404(tid)
    if t.status == 'open':
        if current_user.is_authenticated and t.can_manage(current_user):
            return redirect(url_for('tournaments.tournament', tid=tid))
        flash('Bracket not generated yet.', 'info')
        return redirect(url_for('tournaments.index'))
    return render_template('bracket.html', **_load_bracket_context(t))


@bp.route('/tournament/<int:tid>/bracket/print')
def bracket_print(tid):
    t = Tournament.query.get_or_404(tid)
    if t.status == 'open':
        flash('Bracket not generated yet.', 'info')
        return redirect(url_for('tournaments.index'))
    return render_template('bracket_print.html', **_load_bracket_context(t))


@bp.route('/tournament/<int:tid>/bracket/status')
def bracket_status(tid):
    """Lightweight JSON endpoint for auto-refresh polling."""
    t = Tournament.query.get_or_404(tid)
    decided = Match.query.filter(
        Match.tournament_id == tid,
        Match.winner_id != None   # noqa: E711
    ).count()
    return jsonify(status=t.status, decided=decided)


@bp.route('/tournament/<int:tid>/set_winner/<int:mid>/<int:part_id>', methods=['POST'])
@login_required
def set_winner(tid, mid, part_id):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    match = Match.query.get_or_404(mid)
    part = Participant.query.get_or_404(part_id)
    _set_winner(match, part)
    advance_winner(match, t)
    db.session.commit()
    return redirect(url_for('tournaments.bracket', tid=tid))


@bp.route('/tournament/<int:tid>/add_score/<int:mid>/<int:player_num>', methods=['POST'])
@login_required
def add_score(tid, mid, player_num):
    """Increment score for race-to matches."""
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    match = Match.query.get_or_404(mid)
    if match.winner_id:
        return redirect(url_for('tournaments.bracket', tid=tid))

    if t.is_double and match.bracket == 'L':
        race_to = t.lb_race_to or t.race_to or 3
    else:
        race_to = t.race_to or 3
    score_attr = 'score1' if player_num == 1 else 'score2'
    player_attr = 'player1_id' if player_num == 1 else 'player2_id'
    new_score = (getattr(match, score_attr) or 0) + 1
    setattr(match, score_attr, new_score)
    if new_score >= race_to:
        part = db.session.get(Participant, getattr(match, player_attr))
        _set_winner(match, part)
        advance_winner(match, t)

    db.session.commit()
    return redirect(url_for('tournaments.bracket', tid=tid))


@bp.route('/tournament/<int:tid>/clear_winner/<int:mid>', methods=['POST'])
@login_required
def clear_winner(tid, mid):
    """Undo a winner decision and all downstream effects."""
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    match = Match.query.get_or_404(mid)
    _clear_forward(match)
    db.session.commit()
    flash('Winner cleared — match is back to undecided.', 'info')
    return redirect(url_for('tournaments.bracket', tid=tid))


@bp.route('/tournament/<int:tid>/reset', methods=['POST'])
@login_required
def reset_tournament(tid):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    Match.query.filter_by(tournament_id=tid).delete()
    t.status = 'open'
    t.champion_id = None
    t.runner_up_id = None
    db.session.commit()
    return redirect(url_for('tournaments.tournament', tid=tid))


@bp.route('/tournament/<int:tid>/delete', methods=['POST'])
@login_required
def delete_tournament(tid):
    t = Tournament.query.get_or_404(tid)
    _check_access(t)
    db.session.delete(t)
    db.session.commit()
    return redirect(url_for('tournaments.index'))
