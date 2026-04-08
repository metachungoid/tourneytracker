from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from models import League, Tournament, PlayerProfile, ManagerShare

bp = Blueprint('leagues', __name__)


def _check_league_access(league):
    """Abort 403 if current_user cannot manage this league."""
    if not league.can_manage(current_user):
        abort(403)


@bp.route('/leagues')
@login_required
def league_list():
    from models import get_user_leagues
    leagues = get_user_leagues(current_user)
    return render_template('leagues.html', leagues=leagues)


@bp.route('/league/new', methods=['GET', 'POST'])
@login_required
def new_league():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('League name is required.', 'danger')
            return redirect(url_for('leagues.new_league'))
        league = League(name=name, owner_id=current_user.id)
        db.session.add(league)
        db.session.commit()
        flash(f'League "{name}" created.', 'success')
        return redirect(url_for('leagues.league_dashboard', lid=league.id))
    return render_template('league_form.html', league=None)


@bp.route('/league/<int:lid>')
@login_required
def league_dashboard(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    tournaments = Tournament.query.filter_by(league_id=lid).order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()
    player_count = PlayerProfile.query.filter_by(league_id=lid).count()
    return render_template('league_dashboard.html', league=league,
                           tournaments=tournaments, player_count=player_count)


@bp.route('/league/<int:lid>/edit', methods=['GET', 'POST'])
@login_required
def edit_league(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('League name is required.', 'danger')
            return redirect(url_for('leagues.edit_league', lid=lid))
        league.name = name
        db.session.commit()
        flash('League updated.', 'success')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    return render_template('league_form.html', league=league)


@bp.route('/league/<int:lid>/delete', methods=['POST'])
@login_required
def delete_league(lid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    t_count = Tournament.query.filter_by(league_id=lid).count()
    p_count = PlayerProfile.query.filter_by(league_id=lid).count()
    if t_count > 0 or p_count > 0:
        flash('Cannot delete a league that has tournaments or players. Remove them first.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    # Remove any shares for this league
    ManagerShare.query.filter_by(league_id=lid).delete()
    db.session.delete(league)
    db.session.commit()
    flash(f'League "{league.name}" deleted.', 'info')
    return redirect(url_for('leagues.league_list'))
