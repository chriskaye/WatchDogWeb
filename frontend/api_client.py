import os
import requests

API_BASE_URL = os.getenv("API_BASE_URL", "http://api:80")


class ApiError(Exception):
    def __init__(self, detail: str, status_code: int):
        super().__init__(detail)
        self.detail = detail
        self.status_code = status_code

    @property
    def is_support_session_expired(self) -> bool:
        """A support_token whose grant/session has ended returns 401 with a distinct
        message. Recovery is different from a normal expired login: send the admin
        back to the grants list, not to the login page."""
        return self.status_code == 401 and "Support Access session" in self.detail


def _handle(resp: requests.Response) -> dict:
    if resp.status_code >= 400:
        try:
            detail = resp.json().get("detail", resp.text)
        except ValueError:
            detail = resp.text
        raise ApiError(detail, resp.status_code)
    return resp.json()


def register(email: str, password: str) -> dict:
    resp = requests.post(
        f"{API_BASE_URL}/users/register",
        json={"email": email, "password": password},
        timeout=10,
    )
    return _handle(resp)


def login(email: str, password: str) -> dict:
    resp = requests.post(
        f"{API_BASE_URL}/token",
        data={"username": email, "password": password},  # form-encoded, per OAuth2PasswordRequestForm
        timeout=10,
    )
    return _handle(resp)


def get_me(access_token: str) -> dict:
    resp = requests.get(
        f"{API_BASE_URL}/users/me",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=10,
    )
    return _handle(resp)


def verify_email(token: str) -> dict:
    resp = requests.get(
        f"{API_BASE_URL}/verify",
        params={"token": token},
        timeout=10,
    )
    return _handle(resp)