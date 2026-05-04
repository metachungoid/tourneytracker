from flask import Blueprint, render_template, abort, request
from flask_login import login_required, current_user
from models import Bar, BarMembership, LeagueSponsorship, Tournament
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
    abort(404)


@bp.route('/bar/<int:bid>/staff/<int:mid>/remove', methods=['POST'])
@login_required
def remove_staff(bid, mid):
    abort(404)


@bp.route('/bar/<int:bid>/tournament/new', methods=['POST'])
@login_required
def new_bar_tournament(bid):
    abort(404)
