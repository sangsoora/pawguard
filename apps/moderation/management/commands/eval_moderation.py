import json

from django.core.management.base import BaseCommand, CommandError

from apps.moderation.evaluation import DATASET, evaluate, load_dataset
from apps.moderation.llm import AnthropicClassifier


class Command(BaseCommand):
    help = "Score the moderation pipeline against the labelled dataset (precision/recall/cost)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--llm",
            action="store_true",
            help="Also run the LLM stage on ambiguous cases (real API calls, costs money).",
        )
        parser.add_argument("--json", action="store_true", help="Print the report as JSON.")
        parser.add_argument("--dataset", default=str(DATASET))

    def handle(self, *args, llm, dataset, **options):
        classifier = None
        if llm:
            try:
                classifier = AnthropicClassifier()
            except Exception as exc:
                raise CommandError(f"Could not create the LLM classifier: {exc}") from exc

        from pathlib import Path

        report = evaluate(load_dataset(Path(dataset)), classifier)
        if options["json"]:
            self.stdout.write(json.dumps(report.as_dict(), indent=2))
            return

        r = report.as_dict()
        self.stdout.write(f"Dataset: {r['total']} messages  |  LLM stage: {'on' if llm else 'off'}")
        for title, key in (
            ("Auto-flag (flagged only)", "auto_flag"),
            ("Overall (flagged + needs_review)", "overall"),
        ):
            m = r[key]
            self.stdout.write(
                f"{title:<34} precision {m['precision']:.3f}  recall {m['recall']:.3f}  "
                f"f1 {m['f1']:.3f}   (tp {m['tp']} fp {m['fp']} fn {m['fn']} tn {m['tn']})"
            )
        self.stdout.write(f"Routing: {r['routing']}")
        self.stdout.write(f"LLM: {r['llm']}")
        if r["errors"]:
            self.stdout.write(self.style.WARNING("\nMisclassified:"))
            for e in r["errors"]:
                self.stdout.write(f"  [{e['label']:>5} -> {e['verdict']}] {e['text'][:90]}")
