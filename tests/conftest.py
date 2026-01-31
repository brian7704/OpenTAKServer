import pytest
import sqlalchemy
from flask_security import hash_password

from opentakserver.app import create_app
from opentakserver.extensions import db, logger


class AuthActions:
    def __init__(self, app, client, username="TestUser", password="TestPass"):
        self.app = app
        self.client = client
        self.username = username
        self.password = password
        self.headers = {}
        self.create()
        self.login()

    def create(self):
        try:
            with self.client.application.app_context():
                self.app.security.datastore.create_user(
                    username=self.username,
                    password=hash_password(self.password),
                    roles=["administrator"],
                )
                db.session.commit()
        except sqlalchemy.exc.IntegrityError:
            logger.warning("{} already exists".format(self.username))

    def login(self):
        response = self.get("/api/login")
        csrf_token = response.json["response"]["csrf_token"]
        self.headers["X-CSRFToken"] = csrf_token
        response = self.client.post(
            "/api/login", json={"username": self.username, "password": self.password}
        )

        return response

    def logout(self):
        return self.client.get("/api/logout")

    def get(self, path, headers=None, json=None):
        if json is None:
            json = {}

        if headers is None:
            headers = self.headers
        return self.client.get(path, headers=headers, json=json)

    def post(self, path, headers=None):
        if headers is None:
            headers = self.headers
        return self.client.post(path, headers=headers)


@pytest.fixture
def app():
    app = create_app()
    app.config["TESTING"] = True
    app.config["PRESERVE_CONTEXT_ON_EXCEPTION"] = False
    return app


@pytest.fixture()
def client(app):
    with app.test_client() as client:
        with client.session_transaction() as session:
            session["Authorization"] = "redacted"
        print(session)  # will be populated SecureCookieSession
        yield client


@pytest.fixture
def auth(app, client):
    return AuthActions(app, client)
