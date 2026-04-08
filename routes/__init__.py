from routes.auth import bp as auth_bp
from routes.players import bp as players_bp
from routes.rankings import bp as rankings_bp
from routes.tournaments import bp as tournaments_bp
from routes.admin import bp as admin_bp


def register_routes(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(rankings_bp)
    app.register_blueprint(tournaments_bp)
    app.register_blueprint(admin_bp)
