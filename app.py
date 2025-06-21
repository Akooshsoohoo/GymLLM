import os
from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from flask_sqlalchemy import SQLAlchemy

# Import database and blueprints
from models.models import db
from routes import register_blueprints  # This should import/register all your blueprints
from routes.auth_google import create_google_bp  # Your Google auth blueprint factory

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "supersekrit")
app.config['SQLALCHEMY_DATABASE_URI'] = os.getenv('DATABASE_URL')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Bind db to app
db.init_app(app)

# Register app blueprints (all routes)
register_blueprints(app)

# Register Google OAuth blueprint
google_bp = create_google_bp()
app.register_blueprint(google_bp, url_prefix="/login")

# Main entrypoint
if __name__ == "__main__":
    with app.app_context():
        db.create_all()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
