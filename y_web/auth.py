"""
Authentication and user management routes.

Handles user login and logout functionality for administrative users,
researchers, and experiment participants. Manages session creation
and validation for the YSocial platform.
"""

import secrets
from urllib.parse import urlencode

import requests
from flask import (
    Blueprint,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_login import login_required, login_user, logout_user
from werkzeug.security import check_password_hash, generate_password_hash

from . import db
from .models import Admin_users, Exps, User_Experiment, User_mgmt

auth = Blueprint("auth", __name__)


def _build_unique_username(raw_name, prefix):
    """Create a unique username that fits the Admin_users length constraint."""
    base = "".join(ch for ch in (raw_name or "") if ch.isalnum()).lower()[:15]
    if not base:
        base = f"{prefix}{secrets.token_hex(2)}"[:15]
    candidate = base
    suffix = 1
    while Admin_users.query.filter_by(username=candidate).first():
        suffix_str = str(suffix)
        candidate = f"{base[: max(1, 15 - len(suffix_str))]}{suffix_str}"
        suffix += 1
    return candidate


def _social_config():
    """Read social provider settings from environment variables."""
    provider = current_app.config.get(
        "SOCIAL_PROVIDER", "google"
    ).lower() or "google"
    client_id = current_app.config.get("SOCIAL_CLIENT_ID") or current_app.config.get(
        "GOOGLE_CLIENT_ID"
    )
    client_secret = current_app.config.get(
        "SOCIAL_CLIENT_SECRET"
    ) or current_app.config.get("GOOGLE_CLIENT_SECRET")
    return {
        "provider": provider,
        "client_id": client_id,
        "client_secret": client_secret,
        "auth_url": current_app.config.get(
            "SOCIAL_AUTH_URL", "https://accounts.google.com/o/oauth2/v2/auth"
        ),
        "token_url": current_app.config.get(
            "SOCIAL_TOKEN_URL", "https://oauth2.googleapis.com/token"
        ),
        "userinfo_url": current_app.config.get(
            "SOCIAL_USERINFO_URL", "https://openidconnect.googleapis.com/v1/userinfo"
        ),
    }


def _orcid_config():
    """Read ORCID OAuth settings from environment variables."""
    base_url = (current_app.config.get("ORCID_BASE_URL") or "https://orcid.org").rstrip(
        "/"
    )
    return {
        "client_id": current_app.config.get("ORCID_CLIENT_ID"),
        "client_secret": current_app.config.get("ORCID_CLIENT_SECRET"),
        "auth_url": f"{base_url}/oauth/authorize",
        "token_url": f"{base_url}/oauth/token",
    }


def _upsert_oauth_user(email, display_name, username_prefix):
    """
    Get or create an admin user account for OAuth sign-in.
    New users default to researcher role.
    """
    user = Admin_users.query.filter_by(email=email).first()
    if user:
        return user

    user = Admin_users(
        username=_build_unique_username(display_name, username_prefix),
        email=email,
        password=generate_password_hash(secrets.token_urlsafe(24)),
        last_seen="",
        role="researcher",
        llm="",
        llm_url="",
        profile_pic="",
    )
    db.session.add(user)
    db.session.commit()
    return user


def _login_admin_or_user(user, remember=False):
    """Preserve existing role-based login behavior."""
    if user.role == "user":
        user_experiments = User_Experiment.query.filter_by(user_id=user.id).all()

        if not user_experiments:
            flash(
                "You are not assigned to any experiments. Please contact an administrator."
            )
            return redirect(url_for("auth.login"))

        exp_ids = [ue.exp_id for ue in user_experiments]
        active_exps = Exps.query.filter(Exps.idexp.in_(exp_ids), Exps.status == 1).all()

        if not active_exps:
            flash("No active experiments available. Please contact an administrator.")
            return redirect(url_for("auth.login"))

        auth_token = secrets.token_urlsafe(32)
        session["exp_select_token"] = auth_token
        session["exp_select_user_id"] = user.id
        session["exp_select_remember"] = remember
        session["exp_select_experiments"] = [
            {
                "idexp": exp.idexp,
                "exp_name": exp.exp_name,
                "platform_type": exp.platform_type,
            }
            for exp in active_exps
        ]

        return render_template(
            "login.html",
            show_exp_selection=True,
            experiments=active_exps,
            auth_token=auth_token,
        )

    if user.role in {"admin", "researcher"}:
        login_user(user, remember=remember)
        return redirect(url_for("admin.dashboard"))

    flash("Invalid user role. Please contact an administrator.")
    return redirect(url_for("auth.login"))


@auth.route("/login")
def login():
    """
    Display login page.

    Returns:
        Rendered login template
    """
    return render_template("login.html")


@auth.route("/login", methods=["POST"])
def login_post():
    """
    Process login form submission and authenticate user.

    Validates credentials and redirects based on role:
    - admin/researcher: admin dashboard
    - user: experiment selection page (if multiple) or direct to feed

    Returns:
        Redirect to appropriate page based on role, or back to login on failure
    """
    if request.method == "GET":
        return render_template("login.html")

    email = request.form.get("email")
    password = request.form.get("password")
    remember = True if request.form.get("remember") else False

    user = Admin_users.query.filter_by(email=email).first()

    # check if the user actually exists
    # take the user-supplied password, hash it, and compare it to the hashed password in the database
    if not user or not check_password_hash(user.password, password):
        flash("Please check your login details and try again.")
        return redirect(url_for("auth.login"))

    return _login_admin_or_user(user, remember=remember)


@auth.route("/login/social")
def social_login():
    """Start OAuth login flow for social provider (default: Google)."""
    cfg = _social_config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        flash("Social login is not configured.")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(24)
    session["social_oauth_state"] = state

    params = {
        "client_id": cfg["client_id"],
        "redirect_uri": url_for("auth.social_callback", _external=True),
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "access_type": "online",
        "prompt": "select_account",
    }
    return redirect(f"{cfg['auth_url']}?{urlencode(params)}")


@auth.route("/login/social/callback")
def social_callback():
    """Handle social provider callback, then sign up/login user."""
    cfg = _social_config()
    state = request.args.get("state")
    code = request.args.get("code")
    expected_state = session.pop("social_oauth_state", None)

    if not code or not state or state != expected_state:
        flash("Invalid social login response.")
        return redirect(url_for("auth.login"))

    try:
        token_resp = requests.post(
            cfg["token_url"],
            data={
                "code": code,
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "redirect_uri": url_for("auth.social_callback", _external=True),
                "grant_type": "authorization_code",
            },
            timeout=15,
        )
        token_resp.raise_for_status()
        access_token = token_resp.json().get("access_token")
        if not access_token:
            flash("Social login failed: missing access token.")
            return redirect(url_for("auth.login"))

        userinfo_resp = requests.get(
            cfg["userinfo_url"],
            headers={"Authorization": f"Bearer {access_token}"},
            timeout=15,
        )
        userinfo_resp.raise_for_status()
        payload = userinfo_resp.json()
        email = payload.get("email")
        name = payload.get("name") or payload.get("given_name") or cfg["provider"]

        if not email:
            flash("Social login failed: provider did not return an email.")
            return redirect(url_for("auth.login"))

        user = _upsert_oauth_user(
            email=email,
            display_name=name,
            username_prefix=cfg["provider"][:4] or "soc",
        )
        return _login_admin_or_user(user, remember=True)
    except requests.RequestException:
        flash("Could not complete social login. Please try again.")
        return redirect(url_for("auth.login"))


@auth.route("/login/orcid")
def orcid_login():
    """Start ORCID OAuth login/signup flow."""
    cfg = _orcid_config()
    if not cfg["client_id"] or not cfg["client_secret"]:
        flash("ORCID login is not configured.")
        return redirect(url_for("auth.login"))

    state = secrets.token_urlsafe(24)
    session["orcid_oauth_state"] = state
    params = {
        "client_id": cfg["client_id"],
        "response_type": "code",
        "scope": "/authenticate",
        "redirect_uri": url_for("auth.orcid_callback", _external=True),
        "state": state,
    }
    return redirect(f"{cfg['auth_url']}?{urlencode(params)}")


@auth.route("/login/orcid/callback")
def orcid_callback():
    """Handle ORCID callback, then sign up/login user."""
    cfg = _orcid_config()
    state = request.args.get("state")
    code = request.args.get("code")
    expected_state = session.pop("orcid_oauth_state", None)

    if not code or not state or state != expected_state:
        flash("Invalid ORCID login response.")
        return redirect(url_for("auth.login"))

    try:
        token_resp = requests.post(
            cfg["token_url"],
            data={
                "client_id": cfg["client_id"],
                "client_secret": cfg["client_secret"],
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": url_for("auth.orcid_callback", _external=True),
            },
            headers={"Accept": "application/json"},
            timeout=15,
        )
        token_resp.raise_for_status()
        payload = token_resp.json()
        orcid_id = payload.get("orcid")
        display_name = payload.get("name") or "orcid_user"

        if not orcid_id:
            flash("ORCID login failed: missing ORCID identifier.")
            return redirect(url_for("auth.login"))

        pseudo_email = f"orcid+{orcid_id}@orcid.local"
        user = _upsert_oauth_user(
            email=pseudo_email,
            display_name=display_name,
            username_prefix="orc",
        )
        return _login_admin_or_user(user, remember=True)
    except requests.RequestException:
        flash("Could not complete ORCID login. Please try again.")
        return redirect(url_for("auth.login"))


@auth.route("/select_experiment", methods=["POST"])
def select_experiment():
    """
    Handle experiment selection for users with multiple active experiments.

    Returns:
        Redirect to the selected experiment's feed
    """
    from flask import session

    exp_id = request.form.get("experiment_id")
    auth_token = request.form.get("auth_token")

    if not exp_id or not auth_token:
        flash("Invalid request.")
        return redirect(url_for("auth.login"))

    # Verify session token
    if "exp_select_token" not in session or session["exp_select_token"] != auth_token:
        flash("Invalid or expired session. Please log in again.")
        return redirect(url_for("auth.login"))

    user_id = session.get("exp_select_user_id")
    remember = session.get("exp_select_remember", False)

    # Clear session data
    session.pop("exp_select_token", None)
    session.pop("exp_select_user_id", None)
    session.pop("exp_select_remember", None)

    # Get user
    user = Admin_users.query.filter_by(id=user_id).first()
    if not user:
        flash("User not found.")
        return redirect(url_for("auth.login"))

    # Verify user has access to this experiment
    user_exp = User_Experiment.query.filter_by(
        user_id=user.id, exp_id=int(exp_id)
    ).first()
    if not user_exp:
        flash("You do not have access to this experiment.")
        return redirect(url_for("auth.login"))

    # Get experiment
    exp = Exps.query.filter_by(idexp=int(exp_id), status=1).first()
    if not exp:
        flash("Experiment not found or not active.")
        return redirect(url_for("auth.login"))

    try:
        # Use the proper experiment context registration
        from flask import current_app

        from y_web.experiment_context import (
            get_db_bind_key_for_exp,
            register_experiment_database,
        )

        # Register the experiment database if not already registered
        bind_key = get_db_bind_key_for_exp(int(exp_id))
        if bind_key not in current_app.config["SQLALCHEMY_BINDS"]:
            register_experiment_database(current_app, int(exp_id), exp.db_name)

        # Temporarily switch to experiment database to get user
        old_bind = current_app.config["SQLALCHEMY_BINDS"].get("db_exp")
        current_app.config["SQLALCHEMY_BINDS"]["db_exp"] = current_app.config[
            "SQLALCHEMY_BINDS"
        ][bind_key]

        try:
            user_agent = User_mgmt.query.filter_by(username=user.username).first()
            if not user_agent:
                flash("User not found in experiment database.")
                return redirect(url_for("auth.login"))

            login_user(user_agent, remember=remember)

            # Redirect to appropriate feed
            if exp.platform_type == "microblogging":
                return redirect(f"/{exp.idexp}/feed/{user_agent.id}/feed/rf/1")
            elif exp.platform_type == "forum":
                return redirect(f"/{exp.idexp}/rfeed/{user_agent.id}/rfeed/rf/1")
            else:
                flash("Unknown platform type.")
                return redirect(url_for("auth.login"))
        finally:
            # Restore original db_exp binding
            if old_bind:
                current_app.config["SQLALCHEMY_BINDS"]["db_exp"] = old_bind

    except Exception as e:
        flash(f"Error accessing experiment: {str(e)}")
        return redirect(url_for("auth.login"))


@auth.route("/logout")
@login_required
def logout():
    """
    Log out the current user and return to login page.

    Returns:
        Rendered login template after logout
    """

    logout_user()

    return render_template("login.html")
