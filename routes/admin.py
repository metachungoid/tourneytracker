from functools import wraps
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from models import Admin, Tournament, PlayerProfile, Match, League

bp = Blueprint('admin', __name__)


def admin_required(f):
    @wraps(f)
    @login_required
    def decorated(*args, **kwargs):
        if not current_user.is_admin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@bp.route('/admin')
@admin_required
def admin_panel():
    from models import Bar
    admins = Admin.query.order_by(Admin.username).all()
    stats = {
        'tournaments': Tournament.query.count(),
        'players': PlayerProfile.query.count(),
        'matches': Match.query.count(),
        'complete': Tournament.query.filter_by(status='complete').count(),
        'open': Tournament.query.filter_by(status='open').count(),
        'in_progress': Tournament.query.filter_by(status='bracket').count(),
        'leagues': League.query.count(),
        'bars': Bar.query.count(),
    }
    tournaments = Tournament.query.order_by(Tournament.id.desc()).all()
    players = PlayerProfile.query.order_by(PlayerProfile.first_name, PlayerProfile.last_name).all()
    leagues = League.query.order_by(League.name).all()
    bars = Bar.query.order_by(Bar.name).all()
    return render_template('admin.html', admins=admins, stats=stats,
                           tournaments=tournaments, players=players,
                           leagues=leagues, bars=bars)


@bp.route('/admin/add_user', methods=['POST'])
@admin_required
def admin_add_user():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    is_admin_flag = request.form.get('is_admin') == '1'
    is_op_flag = request.form.get('is_league_operator') == '1'
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    a = Admin(username=username, is_admin=is_admin_flag,
              is_league_operator=is_op_flag)
    a.set_password(password)
    db.session.add(a)
    db.session.commit()
    label = 'Admin' if is_admin_flag else ('League Operator' if is_op_flag else 'User')
    flash(f'{label} "{username}" created.', 'success')
    return redirect(url_for('admin.admin_panel'))


@bp.route('/admin/delete_admin/<int:aid>', methods=['POST'])
@admin_required
def admin_delete_admin(aid):
    if aid == current_user.id:
        flash("You can't delete your own account.", 'danger')
        return redirect(url_for('admin.admin_panel'))
    a = Admin.query.get_or_404(aid)
    db.session.delete(a)
    db.session.commit()
    flash(f'User "{a.username}" removed.', 'info')
    return redirect(url_for('admin.admin_panel'))
