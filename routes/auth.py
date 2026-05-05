from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_user, logout_user, login_required, current_user
from models import Admin

bp = Blueprint('auth', __name__)


@bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(_post_login_target(current_user))
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        admin = Admin.query.filter_by(username=username).first()
        if admin and admin.check_password(password):
            login_user(admin, remember=request.form.get('remember') == 'on')
            return redirect(request.args.get('next') or _post_login_target(admin))
        flash('Invalid username or password.', 'danger')
    return render_template('login.html')


def _post_login_target(user):
    """Return the URL to send `user` to after login.

    Priority:
      1. League-management context (admin/operator/delegate) -> /leagues
      2. Otherwise, any bar membership -> first bar's dashboard
      3. Otherwise -> public landing
    """
    from models import get_user_leagues, BarMembership
    if user.is_admin or user.is_league_operator or get_user_leagues(user):
        return url_for('leagues.league_list')
    bm = BarMembership.query.filter_by(user_id=user.id).first()
    if bm:
        return url_for('bars.bar_dashboard', bid=bm.bar_id)
    return url_for('tournaments.index')


@bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('tournaments.index'))
