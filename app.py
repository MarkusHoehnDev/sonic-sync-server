import json
import time
from os import environ as env
from urllib.parse import quote_plus, urlencode

from authlib.integrations.flask_client import OAuth
from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, render_template, session, url_for, request, make_response
from flask_socketio import SocketIO

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")

socketio = SocketIO(app, cors_allowed_origins="*")

oauth = OAuth(app)

# Register Auth0
oauth.register(
    "auth0",
    client_id=env.get("AUTH0_CLIENT_ID"),
    client_secret=env.get("AUTH0_CLIENT_SECRET"),
    client_kwargs={
        "scope": "openid profile email",
    },
    server_metadata_url=f'https://{env.get("AUTH0_DOMAIN")}/.well-known/openid-configuration',
)

# Register Spotify
oauth.register(
    "spotify",
    client_id=env.get("SPOTIFY_CLIENT_ID"),
    client_secret=env.get("SPOTIFY_CLIENT_SECRET"),
    access_token_url="https://accounts.spotify.com/api/token",
    access_token_params=None,
    authorize_url="https://accounts.spotify.com/authorize",
    authorize_params=None,
    api_base_url="https://api.spotify.com/v1/",
    client_kwargs={
        "scope": "user-read-email user-read-private",  # Adjust scopes as needed
    },
)

user_gps_data = {}

@app.route("/")
def home():
    user = session.get("user")
    spotify_token = session.get("spotify_token")

    spotify_profile = None

    if spotify_token:
        response = oauth.spotify.get("me", token=spotify_token)
        if response.ok:
            spotify_profile = response.json()

    return render_template(
        "home.html",
        session=user,
        pretty=json.dumps(user, indent=4) if user else None,
        spotify_token=spotify_token,
        spotify_profile=spotify_profile
    )

# Auth0 Callback
@app.route("/callback", methods=["GET", "POST"])
def callback():
    token = oauth.auth0.authorize_access_token()
    session["user"] = token
    return redirect(url_for("spotify_login"))

# Initiate Auth0 Login
@app.route("/login")
def login():
    return oauth.auth0.authorize_redirect(
        redirect_uri=url_for("callback", _external=True)
    )

# Logout from Auth0
@app.route("/logout")
def logout():
    session.clear()
    return redirect(
        "https://"
        + env.get("AUTH0_DOMAIN")
        + "/v2/logout?"
        + urlencode(
            {
                "returnTo": url_for("home", _external=True),
                "client_id": env.get("AUTH0_CLIENT_ID"),
            },
            quote_via=quote_plus,
        )
    )

# Initiate Spotify Login
@app.route("/spotify-login")
def spotify_login():
    if "user" not in session:
        return redirect(url_for("login"))
    return oauth.spotify.authorize_redirect(
        redirect_uri=env.get("SPOTIFY_REDIRECT_URI")
    )

# Spotify Callback
@app.route("/spotify-callback")
def spotify_callback():
    token = oauth.spotify.authorize_access_token()
    session["spotify_token"] = token
    return redirect(url_for("home"))

@socketio.on('gps_data')
def handle_gps_data(data):
    """
    Handle incoming GPS data from clients.
    Expected data format (JSON):
    {
        "user_id": "<string>", # should be the "sub" vlaue
        "latitude": <float>,
        "longitude": <float>,
        "timestamp": <string or int>
    }
    """
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    timestamp = data.get('timestamp')
    received_user_id = data.get('user_id')
    
    # Ensure latitude, longitude, and timestamp are present
    if latitude is None or longitude is None or timestamp is None:
        return

    # Initialize GPS data storage if it does not exist
    if received_user_id not in user_gps_data:
        user_gps_data[received_user_id] = []

    # Append GPS data
    user_gps_data[received_user_id].append({
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp
    })


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(env.get("PORT", 3000)))
