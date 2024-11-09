import json
from os import environ as env
from urllib.parse import quote_plus, urlencode

from authlib.integrations.flask_client import OAuth
from dotenv import find_dotenv, load_dotenv
from flask import Flask, redirect, render_template, session, url_for
from flask_socketio import SocketIO

ENV_FILE = find_dotenv()
if ENV_FILE:
    load_dotenv(ENV_FILE)

app = Flask(__name__)
app.secret_key = env.get("APP_SECRET_KEY")

socketio = SocketIO(app, cors_allowed_origins="*")

oauth = OAuth(app)

oauth.register(
    "auth0",
    client_id=env.get("AUTH0_CLIENT_ID"),
    client_secret=env.get("AUTH0_CLIENT_SECRET"),
    client_kwargs={
        "scope": "openid profile email",
    },
    server_metadata_url=f'https://{env.get("AUTH0_DOMAIN")}/.well-known/openid-configuration',
)

user_gps_data = {}

@app.route("/")
def home():
    user = session.get("user")
    return render_template(
        "home.html",
        session=user,
        pretty=json.dumps(user, indent=4) if user else None,
    )

@app.route("/callback", methods=["GET", "POST"])
def callback():
    token = oauth.auth0.authorize_access_token()
    session["user"] = token
    return redirect("/")

@app.route("/login")
def login():
    return oauth.auth0.authorize_redirect(
        redirect_uri=url_for("callback", _external=True)
    )

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


@socketio.on('gps_data')
def handle_gps_data(data):
    """
    Handle incoming GPS data from clients.
    Expected data format (JSON):
    {
        "user_id": "<string>",
        "latitude": <float>,
        "longitude": <float>,
        "timestamp": <string or int>
    }
    """
    received_user_id = data.get('user_id')
    authenticated_user = session.get("user")
    
    if not authenticated_user:
        return
    
    session_user_id = authenticated_user.get('sub')
    
    if received_user_id != session_user_id:
        return
    
    latitude = data.get('latitude')
    longitude = data.get('longitude')
    timestamp = data.get('timestamp')

    if latitude is None or longitude is None or timestamp is None:
        return
    
    if session_user_id not in user_gps_data:
        user_gps_data[session_user_id] = []
    
    user_gps_data[session_user_id].append({
        "latitude": latitude,
        "longitude": longitude,
        "timestamp": timestamp
    })

    # do some logic with the dictionary of GPS data

if __name__ == "__main__":
    socketio.run(app, host="0.0.0.0", port=int(env.get("PORT", 3000)))
