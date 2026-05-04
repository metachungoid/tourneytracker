def test_user_is_importable_from_models():
    from models import User, Admin
    assert User is Admin
