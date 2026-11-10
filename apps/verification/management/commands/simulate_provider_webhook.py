import json
import urllib.error
import urllib.request

from django.core.management.base import BaseCommand, CommandError

from apps.verification.models import VerificationCase
from apps.verification.provider import build_event, signed_request

EVENTS = {
    "approved": "verification.approved",
    "rejected": "verification.rejected",
    "review": "verification.needs_review",
}


class Command(BaseCommand):
    help = "Act as the mock provider: POST a signed webhook for a submitted verification case."

    def add_arguments(self, parser):
        parser.add_argument("case_id", type=int)
        parser.add_argument("outcome", choices=EVENTS)
        parser.add_argument("--reason", default="")
        parser.add_argument("--url", default="http://localhost:8000/api/verification/webhook/")
        parser.add_argument("--event-id", help="Reuse an id to test idempotency")

    def handle(self, *args, case_id, outcome, reason, url, event_id, **options):
        try:
            case = VerificationCase.objects.get(pk=case_id)
        except VerificationCase.DoesNotExist as exc:
            raise CommandError(f"No verification case {case_id}") from exc
        if not case.provider_ref:
            raise CommandError("Case has no provider reference yet (not sent to the provider).")
        payload = build_event(EVENTS[outcome], case.provider_ref, reason=reason, event_id=event_id)
        body, headers = signed_request(payload)
        request = urllib.request.Request(url, data=body, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=10) as response:
                self.stdout.write(f"{response.status} {response.read().decode()}")
        except urllib.error.HTTPError as exc:
            raise CommandError(f"{exc.code} {exc.read().decode()}") from exc
        self.stdout.write(f"event id: {payload['id']}")
        self.stdout.write(json.dumps(payload))
