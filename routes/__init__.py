from routes.auth import bp as auth_bp
from routes.players import bp as players_bp
from routes.rankings import bp as rankings_bp
from routes.tournaments import bp as tournaments_bp
from routes.admin import bp as admin_bp
from routes.settings import bp as settings_bp
from routes.leagues import bp as leagues_bp


def register_routes(app):
    app.register_blueprint(auth_bp)
    app.register_blueprint(players_bp)
    app.register_blueprint(rankings_bp)
    app.register_blueprint(tournaments_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(leagues_bp)
