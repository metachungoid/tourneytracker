from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from models import Admin, Tournament, PlayerProfile, Match

bp = Blueprint('admin', __name__)


@bp.route('/admin')
@login_required
def admin_panel():
    admins = Admin.query.order_by(Admin.username).all()
    stats = {
        'tournaments': Tournament.query.count(),
        'players': PlayerProfile.query.count(),
        'matches': Match.query.count(),
        'complete': Tournament.query.filter_by(status='complete').count(),
        'open': Tournament.query.filter_by(status='open').count(),
        'in_progress': Tournament.query.filter_by(status='bracket').count(),
    }
    tournaments = Tournament.query.order_by(Tournament.id.desc()).all()
    players = PlayerProfile.query.order_by(PlayerProfile.name).all()
    return render_template('admin.html', admins=admins, stats=stats,
                           tournaments=tournaments, players=players)


@bp.route('/admin/change_password', methods=['POST'])
@login_required
def admin_change_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')
    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if len(new_pw) < 6:
        flash('New password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    current_user.set_password(new_pw)
    db.session.commit()
    flash('Password changed successfully.', 'success')
    return redirect(url_for('admin.admin_panel'))


@bp.route('/admin/add_admin', methods=['POST'])
@login_required
def admin_add_admin():
    username = request.form.get('username', '').strip()
    password = request.form.get('password', '')
    if not username or not password:
        flash('Username and password are required.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if len(password) < 6:
        flash('Password must be at least 6 characters.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    if Admin.query.filter_by(username=username).first():
        flash(f'Username "{username}" is already taken.', 'danger')
        return redirect(url_for('admin.admin_panel'))
    a = Admin(username=username)
    a.set_password(password)
    db.session.add(a)
    db.session.commit()
    flash(f'Admin "{username}" created.', 'success')
    return redirect(url_for('admin.admin_panel'))


@bp.route('/admin/delete_admin/<int:aid>', methods=['POST'])
@login_required
def admin_delete_admin(aid):
    if aid == current_user.id:
        flash("You can't delete your own account.", 'danger')
        return redirect(url_for('admin.admin_panel'))
    a = Admin.query.get_or_404(aid)
    db.session.delete(a)
    db.session.commit()
    flash(f'Admin "{a.username}" removed.', 'info')
    return redirect(url_for('admin.admin_panel'))
