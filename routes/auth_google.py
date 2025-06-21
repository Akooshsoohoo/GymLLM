# auth_google.py
import os
from flask_dance.contrib.google import make_google_blueprint

def create_google_bp():
    return make_google_blueprint(
        client_id=os.getenv("GOOGLE_CLIENT_ID"),
        client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
        scope=[
            "https://www.googleapis.com/auth/userinfo.email",
            "https://www.googleapis.com/auth/userinfo.profile",
            "openid",
        ],
        redirect_to="oauth_success",
    )
