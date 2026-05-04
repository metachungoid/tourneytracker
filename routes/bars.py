from flask import Blueprint, render_template, abort, request, redirect, url_for, flash
from flask_login import login_required, current_user
from models import Admin, Bar, BarMembership, LeagueSponsorship, Tournament
from app import db

bp = Blueprint('bars', __name__)


@bp.route('/bar/<int:bid>')
@login_required
def bar_dashboard(bid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage(current_user):
        abort(403)
    membership = BarMembership.query.filter_by(
        bar_id=bid, user_id=current_user.id
    ).first()
    is_primary = bool(membership and membership.is_primary) or current_user.is_admin
    sponsorships = LeagueSponsorship.query.filter_by(bar_id=bid).all()
    staff = BarMembership.query.filter_by(bar_id=bid).all()
    tournaments = Tournament.query.filter_by(bar_id=bid).order_by(
        Tournament.tournament_date.desc().nullslast(), Tournament.id.desc()
    ).all()
    return render_template('bar_dashboard.html', bar=bar,
                           is_primary=is_primary, sponsorships=sponsorships,
                           staff=staff, tournaments=tournaments)


@bp.route('/bar/<int:bid>/staff/invite', methods=['POST'])
@login_required
def invite_staff(bid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage_staff(current_user):
        abort(403)
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or len(password) < 6:
        flash('Username and a 6+ character password required.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    u = Admin(username=username, is_admin=False, is_league_operator=False)
    u.set_password(password)
    db.session.add(u)
    db.session.flush()
    db.session.add(BarMembership(user_id=u.id, bar_id=bid, is_primary=False))
    db.session.commit()
    flash(f'{username} added as bar staff.', 'success')
    return redirect(url_for('bars.bar_dashboard', bid=bid))


@bp.route('/bar/<int:bid>/staff/<int:mid>/remove', methods=['POST'])
@login_required
def remove_staff(bid, mid):
    bar = Bar.query.get_or_404(bid)
    if not bar.can_manage_staff(current_user):
        abort(403)
    m = BarMembership.query.get_or_404(mid)
    if m.bar_id != bid:
        abort(404)
    if m.is_primary:
        flash('Cannot remove the primary membership. Transfer primary first.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    db.session.delete(m)
    db.session.commit()
    flash('Staff removed.', 'info')
    return redirect(url_for('bars.bar_dashboard', bid=bid))


@bp.route('/bar/<int:bid>/tournament/new', methods=['POST'])
@login_required
def new_bar_tournament(bid):
    abort(404)
