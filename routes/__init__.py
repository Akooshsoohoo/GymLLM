from .auth_routes import auth_bp
from .search_routes import search_bp
from .review_routes import review_bp
from .home_routes import home_bp
from .confirm_routes import confirm_bp

all_blueprints = [auth_bp, search_bp, review_bp, home_bp, confirm_bp]
