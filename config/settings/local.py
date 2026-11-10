from .base import *  # noqa: F403

DEBUG = True
# host.docker.internal: how Prometheus (in Docker) reaches Django on the host to scrape /metrics/.
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "host.docker.internal"]

# The Vite dev server (React console) proxies /api to Django from this origin.
CSRF_TRUSTED_ORIGINS = ["http://localhost:5173", "http://127.0.0.1:5173"]

# Dev-only webhook secret so `simulate_provider_webhook` works out of the box.
VERIFICATION_WEBHOOK_SECRET = env("VERIFICATION_WEBHOOK_SECRET", default="dev-webhook-secret")  # noqa: F405
