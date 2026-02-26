import os
from argparse import ArgumentParser

from y_web import create_app, db


def start_app(
    db_type="sqlite",
    debug=False,
    host="localhost",
    port=8080,
    notebook=False,
    desktop_mode=False,
):
    import sys

    import nltk

    # Download NLTK data only when not running from PyInstaller bundle
    # In PyInstaller mode, NLTK data is bundled and the runtime hook sets up the path
    if not getattr(sys, "frozen", False):
        nltk.download("vader_lexicon")

    # LLM integrations are disabled in this build.
    os.environ.pop("LLM_BACKEND", None)
    os.environ.pop("LLM_URL", None)

    app = create_app(db_type=db_type, desktop_mode=desktop_mode)

    with app.app_context():
        from y_web.models import Exps

        exps = Exps.query.filter_by(status=1).all()
        for exp in exps:
            exp.status = 0
        db.session.commit()

    if notebook:
        print("Jupyter Notebook integration is disabled in this build.")
    app.config["ENABLE_NOTEBOOK"] = False

    if db_type.lower() == "sqlite":
        app.run(debug=debug, host=host, port=port, threaded=False)
    else:
        app.run(debug=debug, host=host, port=port)


if __name__ == "__main__":
    parser = ArgumentParser()

    parser.add_argument(
        "-x", "--host", default="localhost", help="host address to run the app on"
    )
    parser.add_argument("-y", "--port", default="8080", help="port to run the app on")
    parser.add_argument(
        "-d", "--debug", default=False, action="store_true", help="debug mode"
    )
    parser.add_argument(
        "-D",
        "--db",
        choices=["sqlite", "postgresql"],
        default="sqlite",
        help="Database type",
    )
    parser.add_argument(
        "-n",
        "--no_notebook",
        action="store_false",
        help="Enable Jupyter Notebook server launch for experiments",
    )

    args = parser.parse_args()

    try:
        from y_web.pyinstaller_utils.installation_id import (
            get_or_create_installation_id,
        )

        # This will create the ID on first run or load existing one
        installation_info = get_or_create_installation_id()
    except Exception as e:
        print(f"Warning: Could not initialize installation ID: {e}")

    start_app(
        db_type=args.db,
        debug=args.debug,
        host=args.host,
        port=args.port,
        notebook=args.no_notebook,
    )
