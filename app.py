import json
import time
from os import environ as env
from urllib.parse import quote_plus, urlencode

from authlib.integrations.flask_client import OAuth
from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, render_template, session, url_for, request, make_response, jsonify
from flask_socketio import SocketIO, emit

from collections import defaultdict, deque
from threading import Lock

RATE_LIMIT = 60  # Maximum number of requests
TIME_WINDOW = 60  # Time window in seconds

request_timestamps = defaultdict(deque)  # Keeps track of request times per user
request_timestamps_lock = Lock()  # Ensures thread safety


# Load environment variables
ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")

# Initialize SocketIO and OAuth
socketio = SocketIO(app, cors_allowed_origins="*", async_mode="eventlet", transports=["websocket"])
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
    authorize_url="https://accounts.spotify.com/authorize",
    api_base_url="https://api.spotify.com/v1/",
    client_kwargs={
        "scope": "user-read-email user-read-private user-read-playback-state",  # Adjust scopes as needed
    },
)

user_gps_data = {}
active_spotify_users = {}  

@app.route("/")
def home():
    user = session.get("user")
    spotify_token = session.get("spotify_token")

    spotify_profile = None

    if spotify_token:
        response = oauth.spotify.get("me", token=spotify_token)
        if response.ok:
            spotify_profile = response.json()
            user_id = spotify_profile.get("id")
            if user_id:
                active_spotify_users[user_id] = {
                    "sub":  user['userinfo']['sub'],
                    "user_id": user_id,
                    "display_name": spotify_profile.get("display_name"),
                    "email": spotify_profile.get("email"),
                    "image_url": spotify_profile.get("images")[0]["url"] if spotify_profile.get("images") else None,
                    "last_active": time.time(),
                    "spotify_token": spotify_token
                }
                socketio.emit("update_active_users", get_active_user_list())

    return render_template(
        "blueprint.html",
        session=user,
        pretty=json.dumps(user, indent=4) if user else None,
        spotify_token=spotify_token,
        spotify_profile=spotify_profile,
        sub=user['userinfo']['sub'] if user else None
    )

@socketio.on('connect')
def handle_connect():
    emit("update_active_users", get_active_user_list(), broadcast=True)

@socketio.on('disconnect')
def handle_disconnect():
    user_id = session.get("user", {}).get("sub")
    if user_id and user_id in active_spotify_users:
        del active_spotify_users[user_id]
        emit("update_active_users", get_active_user_list(), broadcast=True)

# Helper function to retrieve the list of active Spotify profiles
def get_active_user_list():
    return [
        {
            "user_id": uid,
            "display_name": profile["display_name"],
            "email": profile["email"],
            "image_url": profile["image_url"],
            "sub": profile["sub"]
        }
        for uid, profile in active_spotify_users.items()
    ]

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
    spotify_token = session.get("spotify_token")
    if spotify_token:
        response = oauth.spotify.get("me", token=spotify_token)
        if response.ok:
            spotify_profile = response.json()
            user_id = spotify_profile.get("id")
            if user_id and user_id in active_spotify_users:
                del active_spotify_users[user_id]
                socketio.emit("update_active_users", get_active_user_list())

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

@socketio.on('find_tracks')
def handle_find_tracks(data):
    user_id = data.get('user_id')
    user_data = active_spotify_users.get(user_id)
    if user_data and "spotify_token" in user_data:
        
        # Rate limiting logic
        now = time.time()
        with request_timestamps_lock:
            timestamps = request_timestamps[user_id]
            # Remove timestamps outside the time window
            while timestamps and timestamps[0] <= now - TIME_WINDOW:
                timestamps.popleft()
            if len(timestamps) >= RATE_LIMIT:
                # Reject the request
                return
            else:
                timestamps.append(now)

        # Proceed with the Spotify API request
        spotify_token = user_data["spotify_token"]
        response = oauth.spotify.get("me/player/currently-playing", token=spotify_token)
        print(response)
        
        if response.ok:
            try:
                track_data = response.json()
                if track_data and track_data.get("item"):
                    track_info = track_data["item"]
                    song_name = track_info.get("name")
                    artist_name = ", ".join([artist["name"] for artist in track_info.get("artists", [])])
                    album_image = track_info["album"]["images"][0]["url"] if track_info["album"].get("images") else None
                    emit("track_info", {
                        "user_id": user_id,
                        "song_name": song_name,
                        "artist_name": artist_name,
                        "album_image": album_image
                    }, broadcast=True)  # Add broadcast=True here
            except Exception as e:
                print(f"Error processing track info: {e}")



@socketio.on('send_gps')
def handle_send_gps():
    emit("update_gps", user_gps_data, broadcast=True)


@socketio.on('gps_data')
def handle_gps_data(data):
    """
    Handle incoming GPS data from clients.
    Expected data format (JSON):
    {
        "user_id": "<string>", # should be the "sub" value
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

    # Update GPS data with the most recent entry for the user
    gps_data_entry = {
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp,
        "received_user_id": received_user_id
    }
    
    # Store the most recent GPS data entry for the user
    user_gps_data[received_user_id] = gps_data_entry
    # print("Received GPS data:", gps_data_entry) # this works for sure but the gps display on front end not working


if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(env.get("PORT", 3000)))
