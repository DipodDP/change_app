from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand
from django.utils import timezone

from exchanges.models import Exchange
from exchanges.views import GUEST_KEY


class Command(BaseCommand):
    help = "Delete guest exchanges whose browser session has expired."

    def handle(self, *args, **options):
        # ponytail: decodes every live session; move guest keys to their own
        # table with a last-seen date if this ever shows up as slow.
        live = {
            key
            for session in Session.objects.filter(expire_date__gt=timezone.now())
            if (key := session.get_decoded().get(GUEST_KEY))
        }
        # An ownerless row with no key is a deleted account's history, not a
        # guest's, so the empty key is never purged.
        deleted, _ = (
            Exchange.objects.filter(owner=None)
            .exclude(guest_key="")
            .exclude(guest_key__in=live)
            .delete()
        )
        self.stdout.write(f"Deleted {deleted} abandoned guest exchange(s).")
