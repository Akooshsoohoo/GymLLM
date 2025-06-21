from .search_routes import search_bp
from .review_routes import review_bp
from .confirm_routes import confirm_bp
from .home_routes import home_bp
from .auth_routes import auth_bp

def register_blueprints(app):
    app.register_blueprint(search_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(confirm_bp)
    app.register_blueprint(home_bp)
    app.register_blueprint(auth_bp)
