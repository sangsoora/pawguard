import pytest
from django.core.management import call_command
from django.core.management.base import CommandError

from apps.accounts.management.commands.seed_users import SEED_USERS
from apps.accounts.models import User


def test_seed_users_is_idempotent(db, settings):
    settings.DEBUG = True
    call_command("seed_users")
    call_command("seed_users")
    assert User.objects.count() == len(SEED_USERS)
    assert User.objects.get(username="olivia").check_password("pawguard-dev")


def test_seed_users_refuses_without_debug(db, settings):
    settings.DEBUG = False
    with pytest.raises(CommandError):
        call_command("seed_users")


def test_seed_agents_get_group_and_admin_is_superuser(db, settings):
    settings.DEBUG = True
    call_command("seed_users")
    assert User.objects.get(username="admin").is_superuser
    agent = User.objects.get(username="agent1")
    assert agent.groups.filter(name="T&S Agents").exists()
    assert agent.has_perm("accounts.change_user")
    assert not agent.has_perm("accounts.delete_user")


def test_admin_login_page_is_branded(client):
    response = client.get("/admin/login/")
    assert response.status_code == 200
    assert b"PawGuard" in response.content
    assert b"admin/pawguard.css" in response.content


# --- end-user (owner/sitter) auth ---

ACCOUNT = "/api/account"
CONSOLE = "/api/console"


def _csrf_client():
    from rest_framework.test import APIClient

    client = APIClient(enforce_csrf_checks=True)
    token = client.get(f"{ACCOUNT}/auth/csrf/").json()["csrfToken"]
    return client, token


def _login(client, token, base, username, password):
    return client.post(
        f"{base}/auth/login/",
        {"username": username, "password": password},
        HTTP_X_CSRFTOKEN=token,
    )


@pytest.fixture
def people(db):
    users = {
        "owner": User.objects.create_user("olivia", "o@x.com", "pw-owner-1", role=User.Role.OWNER),
        "sitter": User.objects.create_user("emma", "e@x.com", "pw-sitter-1", role=User.Role.SITTER),
        "agent": User.objects.create_user("agent", "a@x.com", "pw-agent-1", role=User.Role.AGENT),
    }
    return users


def test_owner_and_sitter_can_log_in_and_see_themselves(people):
    client, token = _csrf_client()
    assert client.get(f"{ACCOUNT}/auth/me/").status_code in (401, 403)
    r = _login(client, token, ACCOUNT, "olivia", "pw-owner-1")
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert client.get(f"{ACCOUNT}/auth/me/").json()["username"] == "olivia"
    token = client.cookies["pawguard-csrftoken"].value
    assert client.post(f"{ACCOUNT}/auth/logout/", HTTP_X_CSRFTOKEN=token).status_code == 204
    assert client.get(f"{ACCOUNT}/auth/me/").status_code in (401, 403)


def test_roles_are_kept_apart_between_console_and_account(people):
    client, token = _csrf_client()
    # an agent cannot use the end-user login, and a user cannot use the console login
    assert _login(client, token, ACCOUNT, "agent", "pw-agent-1").status_code == 401
    assert _login(client, token, CONSOLE, "olivia", "pw-owner-1").status_code == 401
    # the right door works for each
    assert _login(client, token, CONSOLE, "agent", "pw-agent-1").status_code == 200


def test_a_user_session_cannot_reach_agent_endpoints(people):
    client, token = _csrf_client()
    assert _login(client, token, ACCOUNT, "olivia", "pw-owner-1").status_code == 200
    assert client.get(f"{CONSOLE}/assessments/").status_code == 403
    assert client.get(f"{CONSOLE}/auth/me/").status_code == 403


def test_account_lockout_is_independent_of_console(people, settings):
    settings.LOGIN_MAX_FAILURES = 2
    client, token = _csrf_client()
    for _ in range(2):
        assert _login(client, token, ACCOUNT, "olivia", "wrong").status_code == 401
    assert _login(client, token, ACCOUNT, "olivia", "pw-owner-1").status_code == 429  # locked
    # separate counters: the same username on the console door is a fresh count
    assert _login(client, token, CONSOLE, "olivia", "wrong").status_code == 401


def test_suspended_user_cannot_log_in(people):
    people["owner"].status = User.Status.SUSPENDED
    people["owner"].save()
    client, token = _csrf_client()
    r = _login(client, token, ACCOUNT, "olivia", "pw-owner-1")
    assert r.status_code == 403 and "suspended" in r.json()["detail"]
    assert client.get(f"{ACCOUNT}/auth/me/").status_code in (401, 403)  # no session was created
    # a wrong password still looks like any other failure (no account enumeration)
    assert _login(client, token, ACCOUNT, "olivia", "nope").status_code == 401


def test_account_login_requires_csrf(people):
    from rest_framework.test import APIClient

    r = APIClient(enforce_csrf_checks=True).post(
        f"{ACCOUNT}/auth/login/", {"username": "olivia", "password": "pw-owner-1"}
    )
    assert r.status_code == 403
