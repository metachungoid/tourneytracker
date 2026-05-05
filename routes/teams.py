from datetime import datetime
from flask import Blueprint, render_template, request, redirect, url_for, flash, abort
from flask_login import login_required, current_user
from app import db
from models import Bar, League, LeagueSponsorship, Team
from auth_helpers import can_create_team

bp = Blueprint('teams', __name__)


@bp.route('/bar/<int:bid>/team/new', methods=['POST'])
@login_required
def new_team(bid):
    bar = Bar.query.get_or_404(bid)
    league_id = request.form.get('league_id', type=int)
    if not league_id:
        flash('Pick a league.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    league = League.query.get_or_404(league_id)
    if not can_create_team(current_user, bar, league):
        abort(403)
    name = request.form.get('name', '').strip()
    if not name:
        flash('Team name required.', 'danger')
        return redirect(url_for('bars.bar_dashboard', bid=bid))
    t = Team(name=name, bar_id=bid, league_id=league_id,
             created_by_id=current_user.id, created_at=datetime.utcnow())
    db.session.add(t)
    db.session.commit()
    return redirect(url_for('teams.team_dashboard', tid=t.id))


@bp.route('/team/<int:tid>')
@login_required
def team_dashboard(tid):
    team = Team.query.get_or_404(tid)
    if not (team.can_manage_roster(current_user) or team.is_member(current_user)):
        abort(403)
    return render_template('team_dashboard.html', team=team)
