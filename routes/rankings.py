from flask import Blueprint, render_template
from app import db
from models import PlayerProfile, Tournament, Match, Participant, League

bp = Blueprint('rankings', __name__)


def _build_rankings(profiles, league_id=None):
    """Compute rankings for a set of profiles, optionally scoped to a league."""
    profile_ids = [p.id for p in profiles]
    if not profile_ids:
        return []

    # Scope queries to league's tournaments if league_id provided
    t_wins_q = db.session.query(
        Tournament.champion_id, db.func.count()
    ).filter(Tournament.champion_id.isnot(None))

    m_wins_q = db.session.query(
        Match.winner_profile_id, db.func.count()
    ).filter(Match.winner_profile_id.isnot(None))

    t_entered_q = db.session.query(
        Participant.profile_id, db.func.count()
    )

    if league_id:
        league_t_ids = db.session.query(Tournament.id).filter_by(league_id=league_id).subquery()
        t_wins_q = t_wins_q.filter(Tournament.league_id == league_id)
        m_wins_q = m_wins_q.join(Tournament, Match.tournament_id == Tournament.id).filter(
            Tournament.league_id == league_id)
        t_entered_q = t_entered_q.filter(Participant.tournament_id.in_(
            db.session.query(Tournament.id).filter_by(league_id=league_id)))

    t_wins = dict(t_wins_q.group_by(Tournament.champion_id).all())
    m_wins = dict(m_wins_q.group_by(Match.winner_profile_id).all())
    t_entered = dict(t_entered_q.group_by(Participant.profile_id).all())

    ranked = sorted(
        profiles,
        key=lambda p: (t_wins.get(p.id, 0), m_wins.get(p.id, 0), t_entered.get(p.id, 0)),
        reverse=True,
    )

    for p in ranked:
        p._cached_tournament_wins = t_wins.get(p.id, 0)
        p._cached_match_wins = m_wins.get(p.id, 0)
        p._cached_tournaments_entered = t_entered.get(p.id, 0)

    return ranked


@bp.route('/rankings')
def rankings():
    profiles = PlayerProfile.query.all()
    ranked = _build_rankings(profiles)
    return render_template('rankings.html', players=ranked, league=None)


@bp.route('/league/<int:lid>/rankings')
def league_rankings(lid):
    league = League.query.get_or_404(lid)
    profiles = PlayerProfile.query.filter_by(league_id=lid).all()
    ranked = _build_rankings(profiles, league_id=lid)
    return render_template('rankings.html', players=ranked, league=league)
