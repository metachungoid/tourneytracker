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
    from models import TeamMembership, User
    team = Team.query.get_or_404(tid)
    if not team.can_manage_roster(current_user):
        abort(403)
    m = TeamMembership.query.get_or_404(mid)
    if m.team_id != tid:
        abort(404)
    role = request.form.get('role', '')
    if role == 'sub':
        m.is_sub = not m.is_sub
        db.session.commit()
        return redirect(url_for('teams.team_dashboard', tid=tid))
    if role not in ('captain', 'co_captain'):
        abort(400)

    flag_attr = 'is_captain' if role == 'captain' else 'is_co_captain'
    setting_to = not getattr(m, flag_attr)
    if not setting_to:
        # Demoting — never needs an account.
        setattr(m, flag_attr, False)
        db.session.commit()
        return redirect(url_for('teams.team_dashboard', tid=tid))

    # Promoting. Need a user account on the profile.
    if m.profile.user_id is None:
        if request.form.get('create_account') != '1':
            return render_template('inline_account_create.html',
                                   team=team, membership=m, role=role,
                                   target_endpoint='teams.roster_role',
                                   error=None)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or len(password) < 6:
            return render_template('inline_account_create.html',
                                   team=team, membership=m, role=role,
                                   target_endpoint='teams.roster_role',
                                   error='Username and 6+ char password required.')
        if User.query.filter_by(username=username).first():
            return render_template('inline_account_create.html',
                                   team=team, membership=m, role=role,
                                   target_endpoint='teams.roster_role',
                                   error=f'Username "{username}" is already taken.')
        new_user = User(username=username, is_admin=False, is_league_operator=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()
        m.profile.user_id = new_user.id

    setattr(m, flag_attr, True)
    db.session.commit()
    flash(f'{m.profile.full_name} promoted to {role.replace("_", " ").title()}.', 'success')
    return redirect(url_for('teams.team_dashboard', tid=tid))


@bp.route('/team/<int:tid>/roster/<int:mid>/scorekeeper', methods=['POST'])
@login_required
def roster_scorekeeper(tid, mid):
    from models import TeamMembership, User
    team = Team.query.get_or_404(tid)
    if not team.can_assign_scorekeeper(current_user):
        abort(403)
    m = TeamMembership.query.get_or_404(mid)
    if m.team_id != tid:
        abort(404)

    setting_to = not m.is_scorekeeper
    if not setting_to:
        m.is_scorekeeper = False
        db.session.commit()
        return redirect(url_for('teams.team_dashboard', tid=tid))

    # Promoting to scorekeeper. Need a user account.
    if m.profile.user_id is None:
        if request.form.get('create_account') != '1':
            return render_template('inline_account_create.html',
                                   team=team, membership=m, role='scorekeeper',
                                   target_endpoint='teams.roster_scorekeeper',
                                   error=None)
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        if not username or len(password) < 6:
            return render_template('inline_account_create.html',
                                   team=team, membership=m, role='scorekeeper',
                                   target_endpoint='teams.roster_scorekeeper',
                                   error='Username and 6+ char password required.')
        if User.query.filter_by(username=username).first():
            return render_template('inline_account_create.html',
                                   team=team, membership=m, role='scorekeeper',
                                   target_endpoint='teams.roster_scorekeeper',
                                   error=f'Username "{username}" is already taken.')
        new_user = User(username=username, is_admin=False, is_league_operator=False)
        new_user.set_password(password)
        db.session.add(new_user)
        db.session.flush()
        m.profile.user_id = new_user.id

    m.is_scorekeeper = True
    db.session.commit()
    flash(f'{m.profile.full_name} can now keep score.', 'success')
    return redirect(url_for('teams.team_dashboard', tid=tid))


@bp.route('/my-teams')
@login_required
def my_teams():
    from models import PlayerProfile, TeamMembership
    profiles = PlayerProfile.query.filter_by(user_id=current_user.id).all()
    profile_ids = [p.id for p in profiles]
    if profile_ids:
        memberships = TeamMembership.query.filter(
            TeamMembership.profile_id.in_(profile_ids)
        ).all()
    else:
        memberships = []
    return render_template('my_teams.html', memberships=memberships)
