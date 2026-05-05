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
    from models import PlayerProfile, TeamMembership
    team = Team.query.get_or_404(tid)
    if not (team.can_manage_roster(current_user) or team.is_member(current_user)):
        abort(403)
    roster = TeamMembership.query.filter_by(team_id=tid).all()
    rostered_profile_ids = [m.profile_id for m in roster]
    if rostered_profile_ids:
        invitable = PlayerProfile.query.filter(
            PlayerProfile.league_id == team.league_id,
            ~PlayerProfile.id.in_(rostered_profile_ids),
        ).order_by(PlayerProfile.first_name, PlayerProfile.last_name).all()
    else:
        invitable = PlayerProfile.query.filter_by(league_id=team.league_id).order_by(
            PlayerProfile.first_name, PlayerProfile.last_name
        ).all()
    return render_template('team_dashboard.html', team=team,
                           roster=roster, invitable=invitable,
                           can_manage=team.can_manage_roster(current_user),
                           can_assign_sk=team.can_assign_scorekeeper(current_user))


@bp.route('/team/<int:tid>/roster/add', methods=['POST'])
@login_required
def roster_add(tid):
    from models import PlayerProfile, TeamMembership
    team = Team.query.get_or_404(tid)
    if not team.can_manage_roster(current_user):
        abort(403)
    profile_id = request.form.get('profile_id', type=int)
    if not profile_id:
        flash('Pick a player.', 'danger')
        return redirect(url_for('teams.team_dashboard', tid=tid))
    profile = PlayerProfile.query.get_or_404(profile_id)
    if profile.league_id != team.league_id:
        flash('Player is not in this league.', 'danger')
        return redirect(url_for('teams.team_dashboard', tid=tid))
    if TeamMembership.query.filter_by(team_id=tid, profile_id=profile_id).first():
        flash(f'{profile.full_name} is already on this team.', 'warning')
        return redirect(url_for('teams.team_dashboard', tid=tid))
    db.session.add(TeamMembership(team_id=tid, profile_id=profile_id))
    db.session.commit()
    flash(f'{profile.full_name} added to roster.', 'success')
    return redirect(url_for('teams.team_dashboard', tid=tid))


@bp.route('/team/<int:tid>/roster/<int:mid>/remove', methods=['POST'])
@login_required
def roster_remove(tid, mid):
    from models import TeamMembership
    team = Team.query.get_or_404(tid)
    if not team.can_manage_roster(current_user):
        abort(403)
    m = TeamMembership.query.get_or_404(mid)
    if m.team_id != tid:
        abort(404)
    db.session.delete(m)
    db.session.commit()
    flash('Removed from roster.', 'info')
    return redirect(url_for('teams.team_dashboard', tid=tid))


@bp.route('/team/<int:tid>/roster/<int:mid>/role', methods=['POST'])
@login_required
def roster_role(tid, mid):
    abort(404)


@bp.route('/team/<int:tid>/roster/<int:mid>/scorekeeper', methods=['POST'])
@login_required
def roster_scorekeeper(tid, mid):
    abort(404)
