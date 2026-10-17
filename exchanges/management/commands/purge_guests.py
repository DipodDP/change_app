from django.contrib.sessions.models import Session
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from exchanges.models import Exchange
from exchanges.views import GUEST_KEY


class Command(BaseCommand):
    help = "Delete guest exchanges whose browser session has expired."

    def handle(self, *args, **options):
        # ponytail: decodes every live session; move guest keys to their own
        # table with a last-seen date if this ever shows up as slow.
        sessions = [
            session.get_decoded()
            for session in Session.objects.filter(expire_date__gt=timezone.now())
        ]
        # A session signed with another SECRET_KEY decodes as empty; going on
        # would take every guest for abandoned and delete them all.
        if not all(sessions):
            raise CommandError(
                "Some sessions cannot be read; is DJANGO_SECRET_KEY the one the "
                "site runs with? Nothing was deleted."
            )
        live = {key for data in sessions if (key := data.get(GUEST_KEY))}
        # An ownerless row with no key is a deleted account's history, not a
        # guest's, so the empty key is never purged.
        deleted, _ = (
            Exchange.objects.filter(owner=None)
            .exclude(guest_key="")
            .exclude(guest_key__in=live)
            .delete()
        )
        self.stdout.write(f"Deleted {deleted} abandoned guest exchange(s).")
