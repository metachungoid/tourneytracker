from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from models import PlayerProfile, Participant, Tournament, Match, League
from routes.admin import admin_required

bp = Blueprint('players', __name__)


def _check_league_access(league):
    if not league.can_manage(current_user):
        abort(403)


@bp.route('/league/<int:lid>/players')
@login_required
def players(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    all_players = PlayerProfile.query.filter_by(league_id=lid).order_by(
        PlayerProfile.first_name, PlayerProfile.last_name).all()
    return render_template('players.html', players=all_players, league=league)


@bp.route('/league/<int:lid>/players/add', methods=['GET', 'POST'])
@login_required
def add_player_profile(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    if request.method == 'POST':
        first = request.form.get('first_name', '').strip()
        last = request.form.get('last_name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip() or None
        if not first:
            flash('First name is required.', 'danger')
            return redirect(url_for('players.add_player_profile', lid=lid))
        fargo_str = request.form.get('fargo_rating', '').strip()
        fargo = int(fargo_str) if fargo_str.isdigit() else None
        p = PlayerProfile(first_name=first, last_name=last or '',
                          phone=phone, email=email, fargo_rating=fargo,
                          league_id=lid)
        db.session.add(p)
        db.session.commit()
        flash(f'{p.full_name} added to the player registry.', 'success')
        return redirect(url_for('players.players', lid=lid))
    return render_template('player_form.html', player=None, league=league)


@bp.route('/league/<int:lid>/players/<int:pid>/edit', methods=['GET', 'POST'])
@login_required
def edit_player_profile(lid, pid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    p = PlayerProfile.query.get_or_404(pid)
    if p.league_id != lid:
        abort(404)
    if request.method == 'POST':
        first = request.form.get('first_name', '').strip()
        last = request.form.get('last_name', '').strip()
        if first:
            p.first_name = first
        p.last_name = last or ''
        p.phone = request.form.get('phone', '').strip() or None
        p.email = request.form.get('email', '').strip() or None
        fargo_str = request.form.get('fargo_rating', '').strip()
        p.fargo_rating = int(fargo_str) if fargo_str.isdigit() else None
        db.session.commit()
        flash('Player updated.', 'success')
        return redirect(url_for('players.players', lid=lid))
    return render_template('player_form.html', player=p, league=league)


@bp.route('/league/<int:lid>/players/<int:pid>/delete', methods=['POST'])
@admin_required
def delete_player_profile(lid, pid):
    league = League.query.get_or_404(lid)
    p = PlayerProfile.query.get_or_404(pid)
    if p.league_id != lid:
        abort(404)
    name = p.full_name

    # Get participant IDs for this player
    part_ids = {pt.id for pt in Participant.query.filter_by(profile_id=pid).all()}

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
    Tournament.query.filter(Tournament.champion_id == pid).update({'champion_id': None})
    Tournament.query.filter(Tournament.runner_up_id == pid).update({'runner_up_id': None})

    # Clear winner_profile_id references on matches
    Match.query.filter_by(winner_profile_id=pid).update({'winner_profile_id': None})

    # Bulk delete participants and the profile
    Participant.query.filter_by(profile_id=pid).delete()
    db.session.delete(p)
    db.session.commit()
    flash(f'{name} removed from the registry.', 'info')
    return redirect(url_for('players.players', lid=lid))
