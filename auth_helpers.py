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
