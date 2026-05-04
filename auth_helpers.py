"""Authorization predicates not naturally tied to a single model.

Model-attached predicates (League.can_manage, Tournament.can_manage,
Bar.can_manage) live on their respective models.  This module covers
global capabilities and cross-model checks (e.g., Sponsorship.can_act).
"""


def _is_real_user(user):
    """True only for an authenticated User row (not anonymous)."""
    return bool(user and getattr(user, 'is_authenticated', False))


def can_create_league(user):
    if not _is_real_user(user):
        return False
    return bool(user.is_admin or user.is_league_operator)


def can_create_bar(user):
    if not _is_real_user(user):
        return False
    return bool(user.is_admin or user.is_league_operator)


def can_promote_user(user):
    """Only admins can flip is_league_operator on another user."""
    if not _is_real_user(user):
        return False
    return bool(user.is_admin)


def can_act_as_sponsor(user, league, bar):
    """True if `user` is a member of `bar` AND `bar` sponsors `league`.

    Admins always pass. Used (in later projects) for any sponsor action
    scoped to a specific league context — creating teams, designating
    tournament officials, etc.
    """
    if not _is_real_user(user):
        return False
    if user.is_admin:
        return True
    if not bar.can_manage(user):
        return False
    from models import LeagueSponsorship
    return LeagueSponsorship.query.filter_by(
        league_id=league.id, bar_id=bar.id
    ).first() is not None
