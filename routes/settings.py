from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app import db
from models import Admin, League, ManagerShare

bp = Blueprint('settings', __name__)


@bp.route('/settings')
@login_required
def settings():
    leagues = []
    shared_with_me = []
    other_managers = []
    if current_user.is_manager:
        leagues = League.query.filter_by(owner_id=current_user.id).order_by(League.name).all()
        shared_with_me = ManagerShare.query.filter_by(delegate_id=current_user.id).all()
        # Build set of all current delegate IDs across all leagues
        all_delegate_ids = set()
        for lg in leagues:
            for s in lg.shares:
                all_delegate_ids.add(s.delegate_id)
        other_managers = Admin.query.filter(
            Admin.role == 'manager',
            Admin.id != current_user.id,
        ).order_by(Admin.username).all()
    return render_template('settings.html',
                           leagues=leagues,
                           shared_with_me=shared_with_me,
                           other_managers=other_managers)


@bp.route('/settings/change_password', methods=['POST'])
@login_required
def change_password():
    current_pw = request.form.get('current_password', '')
    new_pw = request.form.get('new_password', '')
    confirm_pw = request.form.get('confirm_password', '')
    if not current_user.check_password(current_pw):
        flash('Current password is incorrect.', 'danger')
        return redirect(url_for('settings.settings'))
    if len(new_pw) < 6:
        flash('New password must be at least 6 characters.', 'danger')
        return redirect(url_for('settings.settings'))
    if new_pw != confirm_pw:
        flash('New passwords do not match.', 'danger')
        return redirect(url_for('settings.settings'))
    current_user.set_password(new_pw)
    db.session.commit()
    flash('Password changed successfully.', 'success')
    return redirect(url_for('settings.settings'))


@bp.route('/settings/add_delegate', methods=['POST'])
@login_required
def add_delegate():
    if not current_user.is_manager:
        flash('Only managers can share access.', 'danger')
        return redirect(url_for('settings.settings'))
    league_id = request.form.get('league_id', type=int)
    delegate_id = request.form.get('delegate_id', type=int)
    if not league_id or not delegate_id or delegate_id == current_user.id:
        flash('Invalid selection.', 'danger')
        return redirect(url_for('settings.settings'))
    league = League.query.get(league_id)
    if not league or league.owner_id != current_user.id:
        flash('You can only share your own leagues.', 'danger')
        return redirect(url_for('settings.settings'))
    delegate = Admin.query.get(delegate_id)
    if not delegate or delegate.role != 'manager':
        flash('Can only share with other manager accounts.', 'danger')
        return redirect(url_for('settings.settings'))
    if ManagerShare.query.filter_by(league_id=league_id, delegate_id=delegate_id).first():
        flash(f'{delegate.username} already has access to {league.name}.', 'warning')
        return redirect(url_for('settings.settings'))
    db.session.add(ManagerShare(league_id=league_id, delegate_id=delegate_id))
    db.session.commit()
    flash(f'{delegate.username} can now manage "{league.name}".', 'success')
    return redirect(url_for('settings.settings'))


@bp.route('/settings/remove_delegate/<int:share_id>', methods=['POST'])
@login_required
def remove_delegate(share_id):
    share = ManagerShare.query.get_or_404(share_id)
    league = League.query.get(share.league_id)
    if not league or league.owner_id != current_user.id:
        flash('You can only remove delegates from your own leagues.', 'danger')
        return redirect(url_for('settings.settings'))
    name = share.delegate.username
    league_name = league.name
    db.session.delete(share)
    db.session.commit()
    flash(f'{name} no longer has access to "{league_name}".', 'info')
    return redirect(url_for('settings.settings'))
