from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required
from app import db
from models import PlayerProfile, Participant, Tournament, Match

bp = Blueprint('players', __name__)


@bp.route('/players')
@login_required
def players():
    all_players = PlayerProfile.query.order_by(PlayerProfile.name).all()
    return render_template('players.html', players=all_players)


@bp.route('/players/add', methods=['GET', 'POST'])
@login_required
def add_player_profile():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        phone = request.form.get('phone', '').strip() or None
        email = request.form.get('email', '').strip() or None
        if not name:
            flash('Name is required.', 'danger')
            return redirect(url_for('players.add_player_profile'))
        fargo_str = request.form.get('fargo_rating', '').strip()
        fargo = int(fargo_str) if fargo_str.isdigit() else None
        db.session.add(PlayerProfile(name=name, phone=phone, email=email, fargo_rating=fargo))
        db.session.commit()
        flash(f'{name} added to the player registry.', 'success')
        return redirect(url_for('players.players'))
    return render_template('player_form.html', player=None)


@bp.route('/players/<int:pid>/edit', methods=['GET', 'POST'])
@login_required
def edit_player_profile(pid):
    p = PlayerProfile.query.get_or_404(pid)
    if request.method == 'POST':
        p.name = request.form.get('name', '').strip() or p.name
        p.phone = request.form.get('phone', '').strip() or None
        p.email = request.form.get('email', '').strip() or None
        fargo_str = request.form.get('fargo_rating', '').strip()
        p.fargo_rating = int(fargo_str) if fargo_str.isdigit() else None
        db.session.commit()
        flash('Player updated.', 'success')
        return redirect(url_for('players.players'))
    return render_template('player_form.html', player=p)


@bp.route('/players/<int:pid>/delete', methods=['POST'])
@login_required
def delete_player_profile(pid):
    p = PlayerProfile.query.get_or_404(pid)
    name = p.name

    # Get participant IDs for this player
    part_ids = {pt.id for pt in Participant.query.filter_by(profile_id=pid).all()}

    # Clear match references to these participants (bulk updates)
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
    return redirect(url_for('players.players'))
