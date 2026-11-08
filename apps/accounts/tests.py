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
