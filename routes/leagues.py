from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from models import League, Tournament, PlayerProfile, ManagerShare, LeagueSponsorship

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
    from auth_helpers import can_create_league
    if not can_create_league(current_user):
        abort(403)
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
    sponsorships = LeagueSponsorship.query.filter_by(league_id=lid).all()
    sponsored_bar_ids = [s.bar_id for s in sponsorships]
    from models import Bar
    invitable_bars = Bar.query.filter(~Bar.id.in_(sponsored_bar_ids)).order_by(Bar.name).all() \
        if sponsored_bar_ids else Bar.query.order_by(Bar.name).all()
    return render_template('league_dashboard.html', league=league,
                           tournaments=tournaments, player_count=player_count,
                           sponsorships=sponsorships,
                           invitable_bars=invitable_bars)


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


@bp.route('/league/<int:lid>/sponsor/onboard', methods=['POST'])
@login_required
def onboard_sponsor(lid):
    from datetime import datetime
    from models import Admin, Bar, BarMembership
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    bar_name = request.form.get('bar_name', '').strip()
    username = request.form.get('sponsor_username', '').strip()
    password = request.form.get('sponsor_password', '')
    if not bar_name or not username or len(password) < 6:
        flash('Bar name, username, and a 6+ character password are required.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))

    bar = Bar(name=bar_name, created_by_id=current_user.id,
              created_at=datetime.utcnow())
    db.session.add(bar)
    db.session.flush()

    user = Admin(username=username, is_admin=False, is_league_operator=False)
    user.set_password(password)
    db.session.add(user)
    db.session.flush()

    db.session.add(BarMembership(user_id=user.id, bar_id=bar.id, is_primary=True))
    db.session.add(LeagueSponsorship(league_id=lid, bar_id=bar.id,
                                     invited_by_id=current_user.id,
                                     invited_at=datetime.utcnow()))
    db.session.commit()
    flash(f'Sponsor "{bar_name}" onboarded with primary login "{username}".', 'success')
    return redirect(url_for('leagues.league_dashboard', lid=lid))


@bp.route('/league/<int:lid>/sponsor/invite', methods=['POST'])
@login_required
def invite_sponsor(lid):
    from datetime import datetime
    from models import Bar
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    bar_id = request.form.get('bar_id', type=int)
    if not bar_id:
        flash('Pick a bar to invite.', 'danger')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    bar = Bar.query.get_or_404(bar_id)
    existing = LeagueSponsorship.query.filter_by(
        league_id=lid, bar_id=bar.id
    ).first()
    if existing:
        flash(f'{bar.name} already sponsors this league.', 'warning')
        return redirect(url_for('leagues.league_dashboard', lid=lid))
    db.session.add(LeagueSponsorship(
        league_id=lid, bar_id=bar.id,
        invited_by_id=current_user.id, invited_at=datetime.utcnow(),
    ))
    db.session.commit()
    flash(f'{bar.name} added as a sponsor.', 'success')
    return redirect(url_for('leagues.league_dashboard', lid=lid))


@bp.route('/league/<int:lid>/sponsor/<int:sid>/remove', methods=['POST'])
@login_required
def remove_sponsor(lid, sid):
    league = League.query.get_or_404(lid)
    _check_league_access(league)
    ls = LeagueSponsorship.query.get_or_404(sid)
    if ls.league_id != lid:
        abort(404)
    db.session.delete(ls)
    db.session.commit()
    flash('Sponsor removed from league.', 'info')
    return redirect(url_for('leagues.league_dashboard', lid=lid))
