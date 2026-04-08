from flask import Blueprint, render_template
from app import db
from models import PlayerProfile, Tournament, Match, Participant

bp = Blueprint('rankings', __name__)


@bp.route('/rankings')
def rankings():
    profiles = PlayerProfile.query.all()

    # Batch-count tournament wins and match wins in 2 queries instead of 2N
    t_wins = dict(db.session.query(
        Tournament.champion_id, db.func.count()
    ).filter(Tournament.champion_id.isnot(None)).group_by(Tournament.champion_id).all())

    m_wins = dict(db.session.query(
        Match.winner_profile_id, db.func.count()
    ).filter(Match.winner_profile_id.isnot(None)).group_by(Match.winner_profile_id).all())

    t_entered = dict(db.session.query(
        Participant.profile_id, db.func.count()
    ).group_by(Participant.profile_id).all())

    ranked = sorted(
        profiles,
        key=lambda p: (t_wins.get(p.id, 0), m_wins.get(p.id, 0), t_entered.get(p.id, 0)),
        reverse=True,
    )

    # Attach counts so the template can use them without extra queries
    for p in ranked:
        p._cached_tournament_wins = t_wins.get(p.id, 0)
        p._cached_match_wins = m_wins.get(p.id, 0)
        p._cached_tournaments_entered = t_entered.get(p.id, 0)

    return render_template('rankings.html', players=ranked)
