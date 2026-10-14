import re
from decimal import Decimal

from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from .forms import ExchangeForm
from .models import Currency, Exchange
from .routing import (
    Leg,
    Option,
    Path,
    best_paths,
    blocked_chain,
    chain_rate,
    compare,
    is_transfer,
    provider_ends,
)


def make(
    spent,
    spent_cur,
    received,
    received_cur,
    provider="",
    owner=None,
    received_provider="",
):
    return Exchange.objects.create(
        spent_amount=Decimal(str(spent)),
        spent_currency=spent_cur,
        received_amount=Decimal(str(received)),
        received_currency=received_cur,
        provider=provider,
        received_provider=received_provider,
        owner=owner,
    )


class SignedIn:
    """Views are behind a login, so a view test needs an owner and a session.

    Fixtures built in setUp() are assigned to that user, since every view is
    scoped to what the signed-in account actually owns.
    """

    def _pre_setup(self):
        super()._pre_setup()
        from django.contrib.auth import get_user_model

        self.user = get_user_model().objects.create_user("tester", password="pw-test-1")
        self.client.force_login(self.user)

    def _callSetUp(self):
        # Ownership is claimed after the subclass has built its fixtures:
        # setUp() runs first, then everything ownerless becomes this user's.
        super()._callSetUp()
        Exchange.objects.filter(owner__isnull=True).update(owner=self.user)


class RateTests(TestCase):
    def test_rate_is_received_per_unit_spent(self):
        e = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.assertEqual(e.rate, Decimal("0.28840000"))

    def test_rate_above_one(self):
        e = make("14.02", Currency.EUR, 5000, Currency.HUF)
        # 5000 / 14.02 = 356.6333...
        self.assertEqual(e.rate.quantize(Decimal("0.0001")), Decimal("356.6334"))


class ChainRateTests(TestCase):
    def test_single_leg_chain_is_leg_rate(self):
        e = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.assertEqual(chain_rate([e]), e.rate)

    def test_multiplies_along_the_chain(self):
        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        b = make("14.02", Currency.EUR, 5000, Currency.HUF)
        # 0.2884 * 356.6334 = 102.85...
        self.assertEqual(
            chain_rate([a, b]).quantize(Decimal("0.01")), Decimal("102.85")
        )

    def test_empty_chain_raises(self):
        with self.assertRaises(ValueError):
            chain_rate([])

    def test_disconnected_chain_raises(self):
        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        b = make(300, Currency.USD, 94800, Currency.HUF)
        with self.assertRaises(ValueError):
            chain_rate([a, b])


class BestPathTests(TestCase):
    """The scenario from the original request."""

    def setUp(self):
        self.rub_byn = make(60000, Currency.RUB, "2140.43", Currency.BYN)
        self.byn_eur = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF)
        self.byn_usd = make(100, Currency.BYN, "33.26", Currency.USD)
        self.usd_huf = make("7.34", Currency.USD, 2200, Currency.HUF)

    def test_finds_both_byn_to_huf_routes(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        self.assertEqual(len(paths), 2)

    def test_euro_route_is_cheaper(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        best = paths[0]
        self.assertEqual(
            [leg.exchange.pk for leg in best.legs],
            [self.byn_eur.pk, self.eur_huf.pk],
        )
        self.assertEqual(best.rate.quantize(Decimal("0.01")), Decimal("102.85"))

    def test_dollar_route_is_ranked_second(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        second = paths[1]
        self.assertEqual(second.rate.quantize(Decimal("0.01")), Decimal("99.69"))

    def test_paths_are_sorted_best_first(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        rates = [p.rate for p in paths]
        self.assertEqual(rates, sorted(rates, reverse=True))

    def test_longer_chain_from_rub_is_found(self):
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.HUF)
        self.assertTrue(paths)
        self.assertEqual(len(paths[0].legs), 3)

    def test_no_route_returns_empty(self):
        paths = best_paths(Exchange.objects.all(), Currency.HUF, Currency.RUB)
        self.assertEqual(paths, [])

    def test_does_not_revisit_a_currency(self):
        # A cycle back into BYN must not produce an unbounded walk.
        make(1000, Currency.HUF, "9.5", Currency.BYN)
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        for path in paths:
            visited = [path.legs[0].exchange.spent_currency] + [
                leg.exchange.received_currency for leg in path.legs
            ]
            self.assertEqual(len(visited), len(set(visited)))


class CompareTests(TestCase):
    def setUp(self):
        self.byn_eur = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF)
        self.byn_usd = make(100, Currency.BYN, "33.26", Currency.USD)
        self.usd_huf = make("7.34", Currency.USD, 2200, Currency.HUF)

    def test_best_option_has_no_penalty(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF, Decimal("100")
        )
        self.assertEqual(results[0].penalty_pct, Decimal("0.00"))

    def test_payout_for_the_given_amount(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF, Decimal("100")
        )
        self.assertEqual(results[0].payout.quantize(Decimal("1")), Decimal("10285"))
        self.assertEqual(results[1].payout.quantize(Decimal("1")), Decimal("9969"))

    def test_penalty_is_relative_to_the_best(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF, Decimal("100")
        )
        # 9969 vs 10285 -> about 3.08% worse
        self.assertEqual(results[1].penalty_pct.quantize(Decimal("0.1")), Decimal("3.1"))

    def test_shortfall_is_absolute_difference(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF, Decimal("100")
        )
        self.assertEqual(results[1].shortfall.quantize(Decimal("1")), Decimal("316"))


class ViewTests(SignedIn, TestCase):
    def setUp(self):
        # Each chain stays at one bank: funds cannot hop between providers.
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        make("14.02", Currency.EUR, 5000, Currency.HUF, "Prior")
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")
        make("7.34", Currency.USD, 2200, Currency.HUF, "Freedom")

    def test_dashboard_renders(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_comparison_lists_both_routes(self):
        response = self.client.get(
            reverse("dashboard"),
            {"base": "BYN", "target": "HUF", "amount": "100"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context["results"]), 2)

    def test_best_route_is_flagged(self):
        response = self.client.get(
            reverse("dashboard"),
            {"base": "BYN", "target": "HUF", "amount": "100"},
        )
        self.assertTrue(response.context["results"][0].is_best)
        self.assertFalse(response.context["results"][1].is_best)

    def test_can_record_an_exchange(self):
        response = self.client.post(
            reverse("exchange-create"),
            {
                "spent_amount": "60000",
                "spent_currency": "RUB",
                "received_amount": "2140.43",
                "received_currency": "BYN",
                "provider": "Belinvest",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertTrue(
            Exchange.objects.filter(provider="Belinvest").exists()
        )

    def test_rejects_zero_amount(self):
        response = self.client.post(
            reverse("exchange-create"),
            {
                "spent_amount": "0",
                "spent_currency": "RUB",
                "received_amount": "100",
                "received_currency": "BYN",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Exchange.objects.filter(spent_currency="RUB").exists())

    def test_accepts_same_currency_on_both_sides(self):
        # 100 in, 99 out is a transfer that cost 1 BYN in commission — a real
        # cost, and one the app exists to make visible rather than refuse.
        response = self.client.post(
            reverse("exchange-create"),
            {
                "spent_amount": "100",
                "spent_currency": "BYN",
                "received_amount": "99",
                "received_currency": "BYN",
                "provider": "Prior",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        moved = Exchange.objects.get(spent_currency="BYN", received_currency="BYN")
        self.assertLess(moved.rate, Decimal("1"))


class MoneyRoundingTests(TestCase):
    """All monetary output is 2dp with banker's rounding (ROUND_HALF_EVEN)."""

    def test_half_rounds_to_even_down(self):
        from .money import quantize_money

        self.assertEqual(quantize_money(Decimal("2.345")), Decimal("2.34"))

    def test_half_rounds_to_even_up(self):
        from .money import quantize_money

        self.assertEqual(quantize_money(Decimal("2.355")), Decimal("2.36"))

    def test_non_half_rounds_normally(self):
        from .money import quantize_money

        self.assertEqual(quantize_money(Decimal("2.346")), Decimal("2.35"))
        self.assertEqual(quantize_money(Decimal("2.344")), Decimal("2.34"))

    def test_always_two_places(self):
        from .money import quantize_money

        self.assertEqual(str(quantize_money(Decimal("7"))), "7.00")
        self.assertEqual(str(quantize_money(Decimal("7.1"))), "7.10")

    def test_filter_renders_two_places_with_grouping(self):
        from .templatetags.money import money

        self.assertEqual(money(Decimal("10285.3067")), "10 285.31")
        self.assertEqual(money(Decimal("100")), "100.00")

    def test_payouts_are_two_places(self):
        make(100, Currency.BYN, "28.84", Currency.EUR)
        make("14.02", Currency.EUR, 5000, Currency.HUF)
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF, Decimal("100")
        )
        self.assertEqual(results[0].payout.as_tuple().exponent, -2)


class OwnershipTests(TestCase):
    """Exchanges belong to a user."""

    def setUp(self):
        from django.contrib.auth.models import User

        self.user = User.objects.create_user("owner", password="x")

    def test_exchange_can_be_owned(self):
        e = Exchange.objects.create(
            spent_amount=Decimal("100"),
            spent_currency=Currency.BYN,
            received_amount=Decimal("28.84"),
            received_currency=Currency.EUR,
            owner=self.user,
        )
        self.assertEqual(e.owner, self.user)

    def test_owner_is_optional(self):
        e = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.assertIsNone(e.owner)

    def test_exchanges_filterable_by_owner(self):
        Exchange.objects.create(
            spent_amount=Decimal("100"),
            spent_currency=Currency.BYN,
            received_amount=Decimal("28.84"),
            received_currency=Currency.EUR,
            owner=self.user,
        )
        make(100, Currency.BYN, "33.26", Currency.USD)
        self.assertEqual(Exchange.objects.filter(owner=self.user).count(), 1)

    def test_deleting_user_keeps_exchanges(self):
        # History should survive account removal rather than vanishing.
        e = Exchange.objects.create(
            spent_amount=Decimal("100"),
            spent_currency=Currency.BYN,
            received_amount=Decimal("28.84"),
            received_currency=Currency.EUR,
            owner=self.user,
        )
        self.user.delete()
        e.refresh_from_db()
        self.assertIsNone(e.owner)

class ModeTests(TestCase):
    """The wireframe's «хочу получить» / «отправляю» toggle.

    send: I have this much base, how much target do I get?
    get:  I want this much target, how much base must I hand over?
    """

    def setUp(self):
        self.byn_eur = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF)
        self.byn_usd = make(100, Currency.BYN, "33.26", Currency.USD)
        self.usd_huf = make("7.34", Currency.USD, 2200, Currency.HUF)

    def test_send_mode_multiplies(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF,
            Decimal("100"), mode="send",
        )
        self.assertEqual(results[0].payout.quantize(Decimal("1")), Decimal("10285"))

    def test_get_mode_divides(self):
        # To end up with 10285.31 HUF I must send about 100 BYN.
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF,
            Decimal("10285.31"), mode="get",
        )
        self.assertEqual(results[0].payout.quantize(Decimal("1")), Decimal("100"))

    def test_get_mode_best_is_the_cheapest_cost(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF,
            Decimal("10000"), mode="get",
        )
        # Cheapest = smallest amount of base currency spent.
        costs = [r.payout for r in results]
        self.assertEqual(costs, sorted(costs))
        self.assertTrue(results[0].is_best)

    def test_get_mode_penalty_is_extra_cost(self):
        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF,
            Decimal("10000"), mode="get",
        )
        self.assertEqual(results[0].penalty_pct, Decimal("0.00"))
        self.assertGreater(results[1].penalty_pct, Decimal("0"))


class GroupingTests(TestCase):
    """Routes sharing a first step are grouped under it («общее начало»)."""

    def setUp(self):
        # The shared opening leg carries no bank, so either continuation can
        # pick the funds up; each continuation then stays at its own bank.
        self.rub_byn = make(60000, Currency.RUB, "2140.43", Currency.BYN)
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        make("14.02", Currency.EUR, 5000, Currency.HUF, "Prior")
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")
        make("7.34", Currency.USD, 2200, Currency.HUF, "Freedom")

    def test_routes_with_shared_prefix_are_grouped(self):
        from .routing import group_options

        results = compare(
            Exchange.objects.all(), Currency.RUB, Currency.HUF, Decimal("60000")
        )
        groups = group_options(results)
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0].shared)
        self.assertEqual(len(groups[0].options), 2)

    def test_shared_step_is_the_common_exchange(self):
        from .routing import group_options

        results = compare(
            Exchange.objects.all(), Currency.RUB, Currency.HUF, Decimal("60000")
        )
        groups = group_options(results)
        self.assertEqual(groups[0].shared_step.pk, self.rub_byn.pk)

    def test_single_route_is_not_grouped(self):
        from .routing import group_options

        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.EUR, Decimal("100")
        )
        groups = group_options(results)
        self.assertEqual(len(groups), 1)
        self.assertFalse(groups[0].shared)

    def test_ungrouped_routes_keep_their_order(self):
        from .routing import group_options

        results = compare(
            Exchange.objects.all(), Currency.BYN, Currency.HUF, Decimal("100")
        )
        groups = group_options(results)
        # BYN->EUR and BYN->USD do not share a first step
        self.assertEqual(sum(len(g.options) for g in groups), 2)


class SuggestionTests(TestCase):
    """Bank suggestions built from what is already stored."""

    def setUp(self):
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        make(200, Currency.BYN, "57.60", Currency.EUR, "Prior")
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")

    def test_banks_ranked_by_frequency(self):
        from .suggestions import bank_suggestions

        picks = bank_suggestions(Exchange.objects.all())
        self.assertEqual(picks[0].name, "Prior")
        self.assertEqual(picks[0].count, 2)

    def test_banks_can_be_ranked_by_recency(self):
        from .suggestions import bank_suggestions

        picks = bank_suggestions(Exchange.objects.all(), order="recent")
        self.assertEqual(picks[0].name, "Freedom")

    def test_bank_suggestions_filter_by_typed_prefix(self):
        from .suggestions import bank_suggestions

        picks = bank_suggestions(Exchange.objects.all(), typed="pri")
        self.assertEqual([p.name for p in picks], ["Prior"])

    def test_typed_exact_match_is_excluded(self):
        from .suggestions import bank_suggestions

        picks = bank_suggestions(Exchange.objects.all(), typed="Prior")
        self.assertNotIn("Prior", [p.name for p in picks])

    def test_bank_suggestions_respect_limit(self):
        from .suggestions import bank_suggestions

        picks = bank_suggestions(Exchange.objects.all(), limit=1)
        self.assertEqual(len(picks), 1)

    def test_blank_providers_are_ignored(self):
        from .suggestions import bank_suggestions

        make(50, Currency.BYN, "14", Currency.EUR, "")
        picks = bank_suggestions(Exchange.objects.all())
        self.assertNotIn("", [p.name for p in picks])

class NewFeatureViewTests(SignedIn, TestCase):
    def setUp(self):
        # The opening leg is unattributed so both continuations can use it;
        # each continuation stays at one bank, since funds do not move between.
        self.rub_byn = make(60000, Currency.RUB, "2140.43", Currency.BYN)
        self.byn_eur = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF, "Prior")
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")
        make("7.34", Currency.USD, 2200, Currency.HUF, "Freedom")

    def test_send_mode_is_default(self):
        r = self.client.get(reverse("dashboard"))
        self.assertFalse(r.context["is_get_mode"])

    def test_get_mode_switches_context(self):
        r = self.client.get(
            reverse("dashboard"),
            {"mode": "get", "base": "BYN", "target": "HUF", "amount": "10000"},
        )
        self.assertTrue(r.context["is_get_mode"])
        self.assertTrue(r.context["results"])

    def test_groups_are_built(self):
        r = self.client.get(
            reverse("dashboard"),
            {"base": "RUB", "target": "HUF", "amount": "60000"},
        )
        groups = r.context["groups"]
        self.assertEqual(len(groups), 1)
        self.assertTrue(groups[0].shared)

    def test_exchange_form_offers_bank_picks(self):
        r = self.client.get(reverse("exchange-create"))
        self.assertTrue(r.context["bank_picks"])

    def test_reset_clears_then_reloads(self):
        # Wiping is confirmed; reloading the example is not.
        self.client.post(reverse("reset-data"), {"confirm": "1"})
        self.assertEqual(Exchange.objects.count(), 0)
        self.client.post(reverse("reset-data"))
        self.assertEqual(Exchange.objects.count(), len(__import__("exchanges.views", fromlist=["SEED"]).SEED))

    def test_reset_requires_post(self):
        before = Exchange.objects.count()
        self.client.get(reverse("reset-data"))
        self.assertEqual(Exchange.objects.count(), before)


class EditFormSuggestionTests(SignedIn, TestCase):
    """A prefilled edit form still offers the other stored banks.

    Regression: `typed` was seeded from the record's own provider, so the
    exact-match exclusion and the substring filter between them left the
    edit page with no chips at all.
    """

    def setUp(self):
        self.a = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")

    def test_edit_page_offers_other_banks(self):
        r = self.client.get(reverse("exchange-edit", args=[self.a.pk]))
        names = [p.name for p in r.context["bank_picks"]]
        self.assertIn("OTP", names)
        self.assertIn("Freedom", names)

    def test_edit_page_omits_the_records_own_bank(self):
        r = self.client.get(reverse("exchange-edit", args=[self.a.pk]))
        self.assertNotIn("Prior", [p.name for p in r.context["bank_picks"]])

    def test_create_page_offers_everything(self):
        r = self.client.get(reverse("exchange-create"))
        names = [p.name for p in r.context["bank_picks"]]
        self.assertEqual(sorted(names), ["Freedom", "OTP", "Prior"])

    def test_typing_still_filters_on_post(self):
        r = self.client.post(
            reverse("exchange-create"),
            {"spent_amount": "", "spent_currency": "BYN",
             "received_amount": "", "received_currency": "EUR", "provider": "fre"},
        )
        self.assertEqual([p.name for p in r.context["bank_picks"]], ["Freedom"])


class RatePrecisionTests(TestCase):
    """Sub-unit rates are capped at 5 decimal places."""

    def test_caps_at_five_decimals(self):
        from .templatetags.money import rate

        self.assertEqual(rate(Decimal("0.03567383")), "0.03567")

    def test_trailing_zeros_are_trimmed(self):
        from .templatetags.money import rate

        self.assertEqual(rate(Decimal("0.28840000")), "0.2884")
        self.assertEqual(rate(Decimal("0.10000000")), "0.1")

    def test_rounds_half_to_even(self):
        from .templatetags.money import rate

        self.assertEqual(rate(Decimal("0.123455")), "0.12346")

    def test_very_small_rate_keeps_significant_digits(self):
        from .templatetags.money import rate

        # 5 decimals alone would round this to 0.00009 and lose the value;
        # such rates fall back to significant digits instead.
        self.assertNotEqual(rate(Decimal("0.00008642")), "0.00009")
        self.assertTrue(rate(Decimal("0.00008642")).startswith("0.00008642"))

    def test_never_renders_as_zero(self):
        from .templatetags.money import rate

        self.assertNotEqual(rate(Decimal("0.0000001")).rstrip("0"), "0.")

    def test_larger_rates_unchanged(self):
        from .templatetags.money import rate

        self.assertEqual(rate(Decimal("99.68937330")), "99.6894")
        self.assertEqual(rate(Decimal("356.63337")), "356.63")


class GroupShapeTests(TestCase):
    """A bucket with one option has no shared step to speak of."""

    def setUp(self):
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")

    def test_single_option_group_has_no_shared_step(self):
        from .routing import group_options

        groups = group_options(
            compare(Exchange.objects.all(), Currency.BYN, Currency.EUR, Decimal("100"))
        )
        self.assertEqual(len(groups), 1)
        self.assertIsNone(groups[0].shared_step)


class ExchangeEditTests(SignedIn, TestCase):
    def setUp(self):
        self.a = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")

    def _post(self, **overrides):
        data = {
            "spent_amount": "100",
            "spent_currency": Currency.BYN,
            "received_amount": "28.84",
            "received_currency": Currency.EUR,
            "provider": "Prior",
        }
        data.update(overrides)
        return self.client.post(reverse("exchange-edit", args=[self.a.pk]), data)

    def test_edit_saves(self):
        response = self._post(received_amount="30.00")
        self.assertEqual(response.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.received_amount, Decimal("30.00"))


class AuthRequiredTests(TestCase):
    """Every view is behind a login; anonymous visitors are bounced."""

    def setUp(self):
        self.exchange = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")

    def test_all_views_redirect_anonymous(self):
        urls = [
            reverse("dashboard"),
            reverse("exchange-create"),
            reverse("exchange-edit", args=[self.exchange.pk]),
            reverse("exchange-delete", args=[self.exchange.pk]),
            reverse("reset-data"),
        ]
        for url in urls:
            with self.subTest(url=url):
                response = self.client.get(url)
                self.assertEqual(response.status_code, 302)
                self.assertIn(reverse("login"), response["Location"])

    def test_login_page_is_reachable(self):
        self.assertEqual(self.client.get(reverse("login")).status_code, 200)


class OwnerScopingTests(TestCase):
    """One user's records are invisible and untouchable to another."""

    def setUp(self):
        from django.contrib.auth import get_user_model

        User = get_user_model()
        self.alice = User.objects.create_user("alice", password="pw-alice-1")
        self.bob = User.objects.create_user("bob", password="pw-bob-1")

        self.hers = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.hers.owner = self.alice
        self.hers.save()

        self.client.force_login(self.bob)

    def test_dashboard_hides_other_users_exchanges(self):
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "Prior")

    def test_cannot_edit_another_users_exchange(self):
        response = self.client.get(reverse("exchange-edit", args=[self.hers.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_delete_another_users_exchange(self):
        response = self.client.post(reverse("exchange-delete", args=[self.hers.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Exchange.objects.filter(pk=self.hers.pk).exists())

    def test_reset_only_clears_own_data(self):
        mine = make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")
        mine.owner = self.bob
        mine.save()
        self.client.post(reverse("reset-data"), {"confirm": "1"})
        self.assertTrue(Exchange.objects.filter(pk=self.hers.pk).exists())
        self.assertFalse(Exchange.objects.filter(pk=mine.pk).exists())


class CurrencyCatalogTests(TestCase):
    """The list has to cover the currencies people around here actually hold."""

    def test_covers_the_wider_region(self):
        codes = set(Currency.values)
        for code in ["AMD", "GEL", "TRY", "PLN", "GBP", "RSD", "AED", "UAH"]:
            self.assertIn(code, codes)

    def test_every_code_has_a_display_label(self):
        for code, label in Currency.choices:
            self.assertTrue(label.strip(), code)


class CurrencyOrderingTests(TestCase):
    """A long list is only usable if what you use most is at the top."""

    def setUp(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN)
        make("100", Currency.BYN, "28.84", Currency.EUR)
        make("14.02", Currency.EUR, 5000, Currency.HUF)

    def test_used_currencies_come_first_by_frequency(self):
        from .suggestions import currency_choices

        codes = [c for c, _ in currency_choices(Exchange.objects.all())]
        # BYN and EUR appear on two rows each, RUB and HUF on one.
        self.assertEqual(set(codes[:2]), {"BYN", "EUR"})
        self.assertEqual(set(codes[2:4]), {"HUF", "RUB"})

    def test_unused_currencies_follow_in_alphabetical_order(self):
        from .suggestions import currency_choices

        codes = [c for c, _ in currency_choices(Exchange.objects.all())]
        rest = codes[4:]
        self.assertEqual(rest, sorted(rest))
        self.assertIn("AMD", rest)

    def test_nothing_is_lost_or_duplicated(self):
        from .suggestions import currency_choices

        codes = [c for c, _ in currency_choices(Exchange.objects.all())]
        self.assertEqual(sorted(codes), sorted(Currency.values))

    def test_no_history_keeps_the_plain_alphabetical_list(self):
        from .suggestions import currency_choices

        codes = [c for c, _ in currency_choices(Exchange.objects.none())]
        self.assertEqual(codes, sorted(Currency.values))


class CurrencyFormOrderingTests(SignedIn, TestCase):
    """The forms the user actually sees have to honour that ordering."""

    def setUp(self):
        make("100", Currency.BYN, "28.84", Currency.EUR)
        make("14.02", Currency.EUR, 5000, Currency.HUF)

    def test_exchange_form_lists_used_currencies_first(self):
        response = self.client.get(reverse("exchange-create"))
        field = response.context["form"].fields["spent_currency"]
        self.assertEqual([c for c, _ in field.choices][0], "EUR")

    def test_compare_form_lists_used_currencies_first(self):
        response = self.client.get(reverse("dashboard"))
        field = response.context["form"].fields["base"]
        self.assertEqual([c for c, _ in field.choices][0], "EUR")

    def test_an_unused_currency_is_still_selectable(self):
        response = self.client.post(
            reverse("exchange-create"),
            {
                "spent_amount": "100",
                "spent_currency": "BYN",
                "received_amount": "12000",
                "received_currency": "AMD",
                "provider": "Ameria",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertTrue(
            Exchange.objects.filter(received_currency="AMD").exists()
        )


class CurrencyLabelRenderingTests(SignedIn, TestCase):
    """The label already carries the symbol; the page must not add it twice."""

    def setUp(self):
        make("100", Currency.BYN, "28.84", Currency.EUR)

    def test_dashboard_select_shows_each_symbol_once(self):
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("<option value=\"EUR\" >EUR · €</option>", body)
        self.assertNotIn("EUR · EUR", body)

    def test_exchange_form_select_shows_each_symbol_once(self):
        body = self.client.get(reverse("exchange-create")).content.decode()
        self.assertIn("EUR · €", body)
        self.assertNotIn("EUR · EUR", body)


class ChainProviderPlacementTests(SignedIn, TestCase):
    """A bank converts between two currencies, so it belongs on the edge."""

    def setUp(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        make("100", Currency.BYN, "33.26", Currency.USD, "Белинвестбанк")
        make("16.47", Currency.USD, "5800", "AMD", "Белинвестбанк")

    def _chain(self):
        response = self.client.get(
            reverse("dashboard"),
            {"mode": "send", "amount": "100", "base": "RUB", "target": "AMD"},
        )
        body = response.content.decode()
        start = body.index('class="chain"')
        return body[start : body.index("</article>", start)]

    def test_every_currency_in_the_path_is_shown(self):
        chain = self._chain()
        for symbol in ["₽", "BYN", "$", "֏"]:
            self.assertIn(symbol, chain)

    def test_the_bank_is_named_where_the_money_first_reaches_it(self):
        chain = self._chain()
        # Every leg here happens at the same bank, so it is announced once, on
        # the first edge, and stays implied after that: repeating it would
        # suggest the money moved somewhere it never went.
        self.assertEqual(chain.count("Белинвестбанк"), 1)
        # It still has to sit between the two currencies it connects rather
        # than hanging off either end of the chain.
        self.assertLess(chain.index("₽"), chain.index("Белинвестбанк"))
        self.assertLess(chain.index("Белинвестбанк"), chain.index("BYN"))

    def test_a_bank_is_marked_up_as_an_edge_not_a_hop(self):
        import re

        chain = self._chain()
        self.assertIn("hop-via", chain)
        # A provider nested inside a currency chip reads as a label on that
        # currency; it has to stand on its own between two chips instead.
        hops = re.findall(r'<span class="hop">(.*?)</span></span>', chain, re.S)
        self.assertTrue(hops)
        for hop in hops:
            self.assertNotIn("hop-via", hop)

    def test_every_edge_carries_an_arrow_whether_or_not_it_is_named(self):
        import re

        chain = self._chain()
        # Three legs means three edges. An edge whose bank is already known
        # shows no name, but it still draws its arrow, so the rail reads as
        # one continuous path instead of breaking where a label is absent.
        edges = re.findall(r'<span class="hop-link[^"]*">(.*?)</span>\s*(?=<span class="hop"|$)', chain, re.S)
        self.assertEqual(len(edges), 3)
        for edge in edges:
            self.assertIn("<svg", edge)
        self.assertEqual(sum("hop-via" in e for e in edges), 1)


class ProviderContinuityTests(TestCase):
    """Money sitting at one bank cannot spend itself at another.

    A USD balance at Prior and a USD balance at Freedom are different accounts;
    the app knows of no transfer between them, so a chain may only continue at
    the provider that produced the funds.
    """

    def setUp(self):
        self.rub_byn = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        self.byn_usd = make("100", Currency.BYN, "33.26", Currency.USD, "Prior")
        self.rub_usd = make("20000", Currency.RUB, "236.13", Currency.USD, "Freedom")
        self.usd_amd = make("16.47", Currency.USD, "5800", "AMD", "Freedom")

    def test_a_chain_cannot_hop_between_providers(self):
        paths = best_paths(Exchange.objects.all(), Currency.RUB, "AMD")
        for path in paths:
            providers = [l.exchange.provider for l in path.legs]
            self.assertNotIn("Prior", providers, "Prior USD is not Freedom USD")

    def test_the_same_provider_chain_still_works(self):
        paths = best_paths(Exchange.objects.all(), Currency.RUB, "AMD")
        self.assertEqual(len(paths), 1)
        self.assertEqual(
            [l.exchange.pk for l in paths[0].legs],
            [self.rub_usd.pk, self.usd_amd.pk],
        )

    def test_the_surviving_rate_is_the_all_freedom_one(self):
        paths = best_paths(Exchange.objects.all(), Currency.RUB, "AMD")
        expected = (Decimal("236.13") / Decimal("20000")) * (
            Decimal("5800") / Decimal("16.47")
        )
        self.assertEqual(
            paths[0].rate.quantize(Decimal("0.0001")),
            expected.quantize(Decimal("0.0001")),
        )

    def test_an_unlabelled_leg_can_bridge_two_providers(self):
        # A leg with no provider is the escape hatch: it chains to anything,
        # so a move the user has not attributed to a bank still connects.
        make("100", Currency.BYN, "33.10", Currency.USD)
        paths = best_paths(Exchange.objects.all(), Currency.RUB, "AMD")
        self.assertEqual(len(paths), 2)
        self.assertTrue(
            any("Белинвестбанк" in [l.exchange.provider for l in p.legs] for p in paths)
        )

    def test_a_blank_provider_does_not_block_the_chain(self):
        # Nothing recorded means nothing known; refusing to chain would make
        # every unlabelled exchange useless.
        make("100", Currency.BYN, "28.84", Currency.EUR)
        make("14.02", Currency.EUR, "5000", Currency.HUF)
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        self.assertEqual(len(paths), 1)


class ChainContinuityTests(TestCase):
    """chain_rate obeys the same rule the router does.

    Pricing a chain that best_paths would refuse to build tells the user a
    number for a conversion they cannot perform.
    """

    def test_a_cross_provider_chain_is_not_priced(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
            make("100", Currency.BYN, "28.84", Currency.EUR, "Prior"),
        ]
        with self.assertRaises(ValueError):
            chain_rate(steps)

    def test_the_error_names_the_two_providers(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
            make("100", Currency.BYN, "28.84", Currency.EUR, "Prior"),
        ]
        with self.assertRaises(ValueError) as ctx:
            chain_rate(steps)
        self.assertIn("Белинвестбанк", str(ctx.exception))
        self.assertIn("Prior", str(ctx.exception))

    def test_a_same_provider_chain_still_prices(self):
        steps = [
            make("100", Currency.BYN, "28.84", Currency.EUR, "Prior"),
            make("14.02", Currency.EUR, "5000", Currency.HUF, "Prior"),
        ]
        self.assertGreater(chain_rate(steps), 0)

    def test_an_unlabelled_leg_still_chains(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN),
            make("100", Currency.BYN, "28.84", Currency.EUR, "Prior"),
        ]
        self.assertGreater(chain_rate(steps), 0)

class TransferTests(TestCase):
    """Moving money between your own accounts, in one currency.

    A transfer is not a conversion: it names the bank it left and the bank it
    landed in, and may keep the same currency on both sides.
    """

    def test_a_transfer_may_keep_the_same_currency(self):
        form = ExchangeForm(
            data={
                "spent_amount": "1000",
                "spent_currency": Currency.BYN,
                "received_amount": "1000",
                "received_currency": Currency.BYN,
                "provider": "Белинвестбанк",
                "received_provider": "Prior",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_single_bank_transfer_is_also_valid(self):
        # Naming both ends says which accounts; it is not a requirement.
        form = ExchangeForm(
            data={
                "spent_amount": "1000",
                "spent_currency": Currency.BYN,
                "received_amount": "1000",
                "received_currency": Currency.BYN,
                "provider": "Prior",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_transfer_bridges_two_providers(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertEqual(len(paths), 1)

    def test_a_transfer_does_not_bridge_the_wrong_way(self):
        # The transfer moves money one way only.
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        make("100", Currency.BYN, "28.84", Currency.EUR, "Белинвестбанк")
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertEqual(len(paths), 0)

    def test_a_transfer_with_a_fee_costs_something(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
            make(
            "1000",
            Currency.BYN,
            "995",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        ),
            make("100", Currency.BYN, "28.84", Currency.EUR, "Prior"),
        ]
        lossless = (Decimal("2140.43") / Decimal("60000")) * (
            Decimal("28.84") / Decimal("100")
        )
        self.assertLess(chain_rate(steps), lossless)


class SameCurrencyCostTests(TestCase):
    """A transfer in one currency is a real cost and must be recordable.

    Banks charge to move money, including between accounts in the same
    currency. Refusing the row would hide exactly the fee this app exists to
    surface, so any same-currency row is accepted; naming both ends is a way to
    say which accounts, not a condition of being allowed to record it.
    """

    def test_a_plain_same_currency_transfer_is_accepted(self):
        form = ExchangeForm(
            data={
                "spent_amount": "1000",
                "spent_currency": Currency.BYN,
                "received_amount": "995",
                "received_currency": Currency.BYN,
                "provider": "Prior",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_a_same_currency_transfer_with_no_bank_is_accepted(self):
        form = ExchangeForm(
            data={
                "spent_amount": "1000",
                "spent_currency": Currency.BYN,
                "received_amount": "995",
                "received_currency": Currency.BYN,
                "provider": "",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)

    def test_the_commission_shows_up_in_the_rate(self):
        e = make(
            "1000",
            Currency.BYN,
            "995",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        self.assertLess(e.rate, Decimal("1"))

    def test_a_fee_bearing_transfer_lowers_the_whole_chain(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
            make(
            "1000",
            Currency.BYN,
            "995",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        ),
            make("100", Currency.BYN, "28.84", Currency.EUR, "Prior"),
        ]
        free = (Decimal("2140.43") / Decimal("60000")) * (
            Decimal("28.84") / Decimal("100")
        )
        self.assertLess(chain_rate(steps), free)

    def test_a_single_bank_same_currency_row_still_routes(self):
        # One bank moving your own money between its own accounts.
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        make("1000", Currency.BYN, "995", Currency.BYN, "Prior")
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertGreaterEqual(len(paths), 1)


class TransferDedupTests(TestCase):
    """A transfer must not manufacture a duplicate of an existing route.

    Starting a walk with a transfer assumes the funds already sit at its source
    bank, which nothing established. The chain that simply starts at the right
    bank is the same route, so offering both is noise.
    """

    def setUp(self):
        make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        make("14.02", Currency.EUR, "5000", Currency.HUF, "Prior")

    def test_a_leading_transfer_does_not_duplicate_the_route(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        self.assertEqual(len(paths), 1)

    def test_the_surviving_route_is_the_direct_one(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.HUF)
        self.assertFalse(is_transfer(paths[0].legs[0].exchange))

    def test_a_transfer_still_bridges_mid_chain(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.HUF)
        self.assertEqual(len(paths), 1)
        self.assertTrue(any(is_transfer(l.exchange) for l in paths[0].legs))


class DestinationProviderTests(TestCase):
    """Where funds land is its own field, not a convention inside a name.

    A transfer has two banks. Hiding the second one inside the provider string
    means any ordinary rename silently severs a route, so the destination gets
    a field of its own and `provider` goes back to meaning just "the bank".
    """

    def test_provider_alone_means_funds_stay_put(self):
        e = make("1000", Currency.BYN, "995", Currency.BYN, "Prior")
        self.assertEqual(provider_ends(e), ("Prior", "Prior"))

    def test_a_destination_moves_the_funds(self):
        e = make("1000", Currency.BYN, "995", Currency.BYN, "Белинвестбанк")
        e.received_provider = "Prior"
        e.save()
        self.assertEqual(provider_ends(e), ("Белинвестбанк", "Prior"))

    def test_renaming_the_bank_does_not_break_the_link(self):
        a = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        t = make("1000", Currency.BYN, "1000", Currency.BYN, "Белинвестбанк")
        t.received_provider = "Prior"
        t.save()
        b = make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.assertGreater(chain_rate([a, t, b]), 0)

        # The user relabels the source bank; the destination is untouched.
        t.provider = "Белинвестбанк (карта)"
        t.save()
        a.provider = "Белинвестбанк (карта)"
        a.save()
        self.assertGreater(chain_rate([a, t, b]), 0)

    def test_the_form_offers_a_destination_field(self):
        self.assertIn("received_provider", ExchangeForm().fields)

    def test_a_transfer_recorded_through_the_form_routes(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        form = ExchangeForm(
            data={
                "spent_amount": "1000",
                "spent_currency": Currency.BYN,
                "received_amount": "1000",
                "received_currency": Currency.BYN,
                "provider": "Белинвестбанк",
                "received_provider": "Prior",
            }
        )
        self.assertTrue(form.is_valid(), form.errors)
        form.save()
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertEqual(len(paths), 1)


class DestinationVisibilityTests(SignedIn, TestCase):
    """The destination field only means something on a transfer.

    On a conversion the money necessarily ends up at the bank that performed
    it, so the field is noise on every ordinary row. It is shown when both
    currencies match — which is exactly when a transfer is being recorded —
    and stays in the markup so the browser can reveal it as the user types.
    """

    def test_the_field_is_hidden_until_currencies_match(self):
        r = self.client.get(reverse("exchange-create"))
        row = self._destination_row(r.content.decode())
        self.assertIn("hidden", row)

    def test_editing_a_transfer_shows_the_field(self):
        t = make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
            owner=self.user,
        )
        r = self.client.get(reverse("exchange-edit", args=[t.pk]))
        row = self._destination_row(r.content.decode())
        self.assertNotIn("hidden", row)

    def test_editing_a_conversion_hides_the_field(self):
        e = make(
            "100", Currency.BYN, "28.84", Currency.EUR, "Prior", owner=self.user
        )
        r = self.client.get(reverse("exchange-edit", args=[e.pk]))
        row = self._destination_row(r.content.decode())
        self.assertIn("hidden", row)

    def test_no_template_comment_leaks_into_the_page(self):
        # `{# #}` is single-line only: spread it over several and Django prints
        # it verbatim instead of dropping it.
        r = self.client.get(reverse("exchange-create"))
        self.assertNotIn("{#", r.content.decode())

    def test_a_hidden_destination_is_still_submittable(self):
        # Reveal happens in the browser, so the input must exist either way.
        r = self.client.get(reverse("exchange-create"))
        self.assertIn('name="received_provider"', r.content.decode())

    def _destination_row(self, html):
        """The currency-gated row wrapping the destination input.

        Anchored on the `js-destination` class rather than the nearest opening
        <div>: the field is now folded inside a disclosure, so walking back
        from the input finds the panel that holds it instead of the row whose
        `hidden` these tests are about.
        """
        start = html.index('class="field js-destination')
        i = html.index('name="received_provider"', start)
        return html[start:i]


@override_settings(LANGUAGE_CODE="en")
class ResetGuardTests(SignedIn, TestCase):
    """The wipe is the only irreversible path in the app, so it is guarded.

    Deleting one exchange already asks for confirmation; deleting every
    exchange must not ask for less.
    """

    def setUp(self):
        self.keep = make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")

    def test_post_without_confirmation_does_not_wipe(self):
        # The header button alone must not be able to destroy the ledger.
        self.client.post(reverse("reset-data"))
        self.assertTrue(Exchange.objects.filter(pk=self.keep.pk).exists())

    def test_get_shows_a_confirmation_naming_the_count(self):
        body = self.client.get(reverse("reset-data")).content.decode()
        self.assertIn("1 exchange", body)

    def test_confirmed_post_wipes_only_this_owner(self):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user("other", password="pw-test-2")
        theirs = make("50", Currency.USD, "45", Currency.EUR, "Wise", owner=other)

        self.client.post(reverse("reset-data"), {"confirm": "1"})

        self.assertFalse(Exchange.objects.filter(pk=self.keep.pk).exists())
        self.assertTrue(Exchange.objects.filter(pk=theirs.pk).exists())

    def test_loading_demo_data_needs_no_confirmation(self):
        # Creating data is not destructive; only the wipe branch is guarded.
        Exchange.objects.all().delete()
        self.client.post(reverse("reset-data"))
        self.assertTrue(Exchange.objects.filter(owner=self.user).exists())


@override_settings(LANGUAGE_CODE="en")
class HeaderLabelTests(SignedIn, TestCase):
    """The header button toggles between two opposite actions, so its label
    must follow what THIS user owns, not what the database happens to hold."""

    def test_empty_account_is_offered_demo_data(self):
        from django.contrib.auth import get_user_model

        other = get_user_model().objects.create_user("other", password="pw-test-2")
        make("50", Currency.USD, "45", Currency.EUR, "Wise", owner=other)

        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("Demo data", body)
        self.assertNotIn("Clear all", body)

    def test_account_with_exchanges_is_offered_the_wipe(self):
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior", owner=self.user)
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertIn("Clear all", body)


@override_settings(LANGUAGE_CODE="en")
class DemoDataTests(SignedIn, TestCase):
    """The demo exists to show the comparison working.

    Its whole job is the dashboard's default query, so that query must return
    routes — a worked example that produces an empty state teaches the
    opposite of what it is for.
    """

    def test_demo_data_answers_the_default_query(self):
        self.client.post(reverse("reset-data"))
        rows = list(Exchange.objects.filter(owner=self.user))
        options = compare(rows, Currency.BYN, Currency.HUF, Decimal("100"))
        self.assertTrue(options, "demo data must produce at least one BYN->HUF route")

    def test_demo_data_shows_a_multi_leg_comparison(self):
        # A single-leg answer would never exercise the penalty tag or the
        # branch spine, which is the part of the product worth demonstrating.
        self.client.post(reverse("reset-data"))
        rows = list(Exchange.objects.filter(owner=self.user))
        options = compare(rows, Currency.BYN, Currency.HUF, Decimal("100"))
        self.assertGreaterEqual(len(options), 2, "demo should offer a comparison")
        self.assertTrue(
            any(len(o.legs) > 1 for o in options),
            "at least one demo route should chain more than one leg",
        )


class BlockedChainTests(TestCase):
    """Why a route is missing changes what the user should do about it.

    A currency the ledger never touches needs a new exchange. A chain that
    exists but sits at two banks needs a transfer. Telling the second user to
    "add the missing leg" sends them to record data they already have.
    """

    def test_no_path_at_all_is_not_reported_as_blocked(self):
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.assertIsNone(blocked_chain([], Currency.BYN, Currency.HUF))

    def test_unreachable_currency_is_not_blocked(self):
        rows = [make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")]
        self.assertIsNone(blocked_chain(rows, Currency.BYN, Currency.THB))

    def test_chain_split_across_banks_is_reported_with_the_joint(self):
        rows = [
            make(100, Currency.BYN, "28.84", Currency.EUR, "Prior"),
            make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP"),
        ]
        blocked = blocked_chain(rows, Currency.BYN, Currency.HUF)
        self.assertIsNotNone(blocked)
        self.assertEqual(blocked["from_provider"], "Prior")
        self.assertEqual(blocked["to_provider"], "OTP")
        self.assertEqual(blocked["currency"], Currency.EUR)

    def test_a_working_chain_is_not_reported_as_blocked(self):
        rows = [
            make(100, Currency.BYN, "28.84", Currency.EUR, "Prior"),
            make("14.02", Currency.EUR, 5000, Currency.HUF, "Prior"),
        ]
        self.assertIsNone(blocked_chain(rows, Currency.BYN, Currency.HUF))


@override_settings(LANGUAGE_CODE="en")
class BlockedEmptyStateTests(SignedIn, TestCase):
    """The dashboard must name the real obstacle, not guess at a missing leg."""

    def test_split_chain_names_both_banks(self):
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior", owner=self.user)
        make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP", owner=self.user)

        body = self.client.get(
            reverse("dashboard"),
            {"mode": "send", "base": Currency.BYN, "target": Currency.HUF,
             "amount": "100"},
        ).content.decode()

        self.assertIn("Prior", body)
        self.assertIn("OTP", body)
        self.assertNotIn("Add the missing leg", body)

    def test_genuinely_unreachable_pair_keeps_the_original_copy(self):
        make(100, Currency.BYN, "28.84", Currency.EUR, "Prior", owner=self.user)

        body = self.client.get(
            reverse("dashboard"),
            {"mode": "send", "base": Currency.BYN, "target": Currency.THB,
             "amount": "100"},
        ).content.decode()

        self.assertIn("Add the missing leg", body)


@override_settings(LANGUAGE_CODE="en")
class GetModeFramingTests(SignedIn, TestCase):
    """In get mode the amount is what the user wants to RECEIVE.

    Attaching it to the base currency states the opposite of the question,
    and the one large figure on the card changes meaning between modes, so
    both need to say which they are.
    """

    def setUp(self):
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom", owner=self.user)

    def _get(self, mode):
        return self.client.get(
            reverse("dashboard"),
            {"mode": mode, "base": Currency.BYN, "target": Currency.USD,
             "amount": "100"},
        ).content.decode()

    def test_get_mode_binds_the_amount_to_what_is_received(self):
        # `symbol` renders USD as "$", so assert on the rendered form.
        body = self._get("get")
        self.assertNotIn("100.00 BYN → USD", body)
        self.assertIn("To receive 100.00 $", body)

    def test_get_mode_names_the_figure_as_a_cost(self):
        self.assertIn("You pay", self._get("get"))

    def test_send_mode_still_reads_as_a_payout(self):
        body = self._get("send")
        self.assertIn("100.00 BYN", body)
        self.assertNotIn("You pay", body)

    def test_rate_is_quoted_in_the_direction_asked(self):
        # Asking "what does 100 USD cost?" is answered in BYN per dollar.
        body = self._get("get")
        self.assertIn("1 $ = <b>3.0066 BYN</b>", body)
        self.assertNotIn("1 BYN = <b>0.3326 $</b>", body.split('class="results"')[1])


@override_settings(LANGUAGE_CODE="en")
class HeadingHierarchyTests(SignedIn, TestCase):
    """Every page needs one h1, and the dashboard's is the job it does."""

    def test_dashboard_has_exactly_one_h1(self):
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom", owner=self.user)
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertEqual(body.count("<h1"), 1)

    def test_h1_precedes_every_h2(self):
        make(100, Currency.BYN, "33.26", Currency.USD, "Freedom", owner=self.user)
        body = self.client.get(reverse("dashboard")).content.decode()
        self.assertLess(body.index("<h1"), body.index("<h2"))

    def test_other_pages_have_an_h1_too(self):
        for name in ("exchange-create",):
            body = self.client.get(reverse(name)).content.decode()
            self.assertEqual(body.count("<h1"), 1, f"{name} needs one h1")


@override_settings(LANGUAGE_CODE="en")
class CopyPluralTests(SignedIn, TestCase):
    """Counted messages must not hardcode the English plural."""

    def test_clearing_one_reads_singular(self):
        Exchange.objects.create(
            spent_amount=Decimal("100"),
            spent_currency=Currency.BYN,
            received_amount=Decimal("30"),
            received_currency=Currency.USD,
            owner=self.user,
        )
        response = self.client.post(
            reverse("reset-data"), {"confirm": "1"}, follow=True
        )
        body = response.content.decode()
        self.assertIn("Cleared 1 exchange.", body)
        self.assertNotIn("1 exchanges", body)

    def test_clearing_several_reads_plural(self):
        for _i in range(2):
            Exchange.objects.create(
                spent_amount=Decimal("100"),
                spent_currency=Currency.BYN,
                received_amount=Decimal("30"),
                received_currency=Currency.USD,
                owner=self.user,
            )
        response = self.client.post(
            reverse("reset-data"), {"confirm": "1"}, follow=True
        )
        self.assertIn("2 exchanges", response.content.decode())


class OptionStepTests(TestCase):
    """What a chain says about each leg: whose bank, and whether to repeat it.

    `Option.steps` is the only place that decides when a bank name is worth
    printing. It is read by both the route card and the dashboard, so its
    behaviour is pinned here directly rather than through either template.
    """

    def steps(self, *exchanges):
        option = Option(
            path=Path(tuple(Leg(e) for e in exchanges)),
            payout=Decimal(0),
            penalty_pct=Decimal(0),
            shortfall=Decimal(0),
            is_best=True,
        )
        return option.steps

    def test_the_bank_is_announced_on_the_first_leg(self):
        a = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        (step,) = self.steps(a)
        self.assertEqual(step.bank, "Prior")
        self.assertTrue(step.show_bank)
        self.assertFalse(step.is_transfer)

    def test_the_same_bank_twice_is_said_once(self):
        a = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        b = make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        first, second = self.steps(a, b)
        self.assertTrue(first.show_bank)
        self.assertFalse(second.show_bank)

    def test_a_new_bank_announces_itself(self):
        a = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        b = make("100", Currency.BYN, "28.84", Currency.EUR, "Белинвестбанк")
        first, second = self.steps(a, b)
        self.assertTrue(first.show_bank)
        self.assertTrue(second.show_bank)
        self.assertEqual(second.bank, "Белинвестбанк")

    def test_a_transfer_names_where_the_money_lands(self):
        t = make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        (step,) = self.steps(t)
        self.assertTrue(step.is_transfer)
        self.assertEqual(step.bank, "Prior")
        self.assertTrue(step.show_bank)

    def test_the_leg_after_a_transfer_stays_quiet(self):
        # The transfer already said "Prior"; the conversion that follows
        # happens there, so repeating it would suggest a second move.
        t = make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        b = make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        transfer, conversion = self.steps(t, b)
        self.assertEqual(transfer.bank, "Prior")
        self.assertFalse(conversion.show_bank)

    def test_an_unnamed_leg_says_nothing(self):
        a = make("60000", Currency.RUB, "2140.43", Currency.BYN)
        (step,) = self.steps(a)
        self.assertFalse(step.show_bank)

    def test_a_bank_reappearing_after_an_unnamed_leg_is_named_again(self):
        # The middle leg records no bank, so where the money sat is unknown.
        # Returning to Prior is a claim the data does not support, and saying
        # nothing would render the chain as though it never left.
        a = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        b = make("100", Currency.BYN, "38.20", Currency.USD)
        c = make("100", Currency.USD, "38000", Currency.HUF, "Prior")
        first, middle, last = self.steps(a, b, c)
        self.assertTrue(first.show_bank)
        self.assertFalse(middle.show_bank)
        self.assertTrue(last.show_bank)
        self.assertEqual(last.bank, "Prior")


class BlockedChainTransferTests(TestCase):
    """The empty state must name the gap that is actually missing.

    `blocked_chain` re-walks with the provider rule lifted to find the joint
    that broke. Its walk has to allow a transfer to revisit a currency the
    same way `best_paths` does — a transfer is same-currency by definition, so
    a plain visited check skips every one of them and the walk reports the
    first joint it can still reach instead of the real one.
    """

    def test_a_recorded_transfer_is_not_reported_as_the_gap(self):
        # RUB→BYN at A, a recorded A→B transfer, then BYN→EUR at B: this half
        # is sound. The break is further along, at EUR.
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "A")
        make("1000", Currency.BYN, "1000", Currency.BYN, "A", received_provider="B")
        make("100", Currency.BYN, "28.84", Currency.EUR, "B")
        make("100", Currency.EUR, "38000", Currency.HUF, "C")

        self.assertEqual(
            best_paths(Exchange.objects.all(), Currency.RUB, Currency.HUF), []
        )
        broken = blocked_chain(Exchange.objects.all(), Currency.RUB, Currency.HUF)
        self.assertIsNotNone(broken)
        self.assertEqual(broken["currency"], Currency.EUR)
        self.assertEqual(broken["from_provider"], "B")
        self.assertEqual(broken["to_provider"], "C")

    def test_a_genuinely_missing_transfer_is_still_found(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "A")
        make("100", Currency.BYN, "28.84", Currency.EUR, "B")

        self.assertEqual(
            best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR), []
        )
        broken = blocked_chain(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertEqual(broken["currency"], Currency.BYN)
        self.assertEqual(broken["from_provider"], "A")
        self.assertEqual(broken["to_provider"], "B")


class TransferMarkingTests(SignedIn, TestCase):
    """A transfer is not distinguished by colour alone.

    `.is-move` tints the arrow violet, but the arrow is aria-hidden, so on its
    own the distinction never reaches the accessibility tree. A text label
    carries the meaning; the colour is shorthand for people who see it.
    """

    def setUp(self):
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")

    def _chain(self, html):
        i = html.index('class="chain"')
        return html[i : html.index("</div>", html.index("hop-link", i))]

    def test_a_transfer_carries_a_text_label(self):
        r = self.client.get(
            reverse("dashboard"),
            {"base": Currency.RUB, "target": Currency.EUR, "amount": "60000"},
        )
        html = r.content.decode()
        self.assertIn("is-move", html)
        # The label sits inside the same arrow the colour marks.
        move = html[html.index("is-move") :]
        self.assertIn("sr-only", move[: move.index("</span>", move.index("svg"))])

    def test_a_conversion_carries_no_transfer_label(self):
        r = self.client.get(
            reverse("dashboard"),
            {"base": Currency.BYN, "target": Currency.EUR, "amount": "100"},
        )
        html = r.content.decode()
        self.assertNotIn("is-move", self._chain(html))


@override_settings(LANGUAGE_CODE="en")
class GroupedBankTests(SignedIn, TestCase):
    """The shared opening leg is printed by the header, not by each branch.

    `hide_first` used to drop only the opening currency chip and leave its
    arrow behind, so the bank the header had just named was reprinted once per
    branch. The branch drops the whole leg, and announces the bank again on
    its first visible arrow so the card still stands on its own.
    """

    def setUp(self):
        # One opening leg at Prior, then two ways onward from the same bank.
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        make("14.02", Currency.EUR, "5000", Currency.HUF, "Prior")
        make("100", Currency.BYN, "33.26", Currency.USD, "Prior")
        make("7.34", Currency.USD, "2200", Currency.HUF, "Prior")

    def _branches(self, html):
        i = html.index('class="branch-body"')
        body = html[i : html.index('class="card', i)]
        return body.split('<article class="route')[1:]

    def test_a_branch_does_not_reprint_the_shared_bank(self):
        r = self.client.get(
            reverse("dashboard"),
            {"base": Currency.RUB, "target": Currency.HUF, "amount": "60000"},
        )
        html = r.content.decode()
        self.assertIn("common start", html)
        for branch in self._branches(html):
            # Once, on the branch's own first arrow — not again for the leg
            # the header already showed.
            self.assertEqual(branch.count('class="hop-via"'), 1)

    def test_a_branch_still_names_the_bank_it_continues_at(self):
        r = self.client.get(
            reverse("dashboard"),
            {"base": Currency.RUB, "target": Currency.HUF, "amount": "60000"},
        )
        for branch in self._branches(r.content.decode()):
            self.assertIn("Prior", branch)


class HiddenFieldStylingTests(TestCase):
    """A hidden row must actually be hidden.

    `.field` sets `display: flex`, and a class selector outranks the browser's
    own `[hidden] { display: none }` — so without an explicit rule the
    destination field renders in full while carrying the attribute that is
    supposed to suppress it.
    """

    def test_the_stylesheet_hides_a_hidden_field(self):
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        self.assertIn(".field[hidden]", css)

    def test_the_rule_comes_after_the_display_it_overrides(self):
        # Same specificity would let source order decide, and `.field` sets the
        # display this rule exists to beat.
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        self.assertLess(css.index(".field {"), css.index(".field[hidden]"))


class DestinationSuggestionTests(SignedIn, TestCase):
    """The destination field offers banks the same way the source one does."""

    def setUp(self):
        make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
        )
        make("100", Currency.BYN, "28.84", Currency.EUR, "Freedom")

    def _picks(self, html):
        i = html.index('id="destination-picks-label"')
        block = html[i : html.index("</div>", html.index("picks-row", i))]
        return re.findall(r'data-value="([^"]*)"', block)

    def test_destination_offers_previously_used_banks(self):
        r = self.client.get(reverse("exchange-create"))
        self.assertIn("Freedom", self._picks(r.content.decode()))

    def test_a_destination_bank_becomes_a_suggestion(self):
        # Prior was only ever recorded as a destination, never as a source.
        r = self.client.get(reverse("exchange-create"))
        self.assertIn("Prior", self._picks(r.content.decode()))

    def test_the_chips_fill_the_destination_input(self):
        r = self.client.get(reverse("exchange-create"))
        i = r.content.decode().index('id="destination-picks-label"')
        block = r.content.decode()[i : i + 900]
        self.assertIn('data-target="id_received_provider"', block)

    def test_editing_a_transfer_drops_its_own_two_banks(self):
        t = Exchange.objects.get(received_provider="Prior")
        r = self.client.get(reverse("exchange-edit", args=[t.pk]))
        picks = self._picks(r.content.decode())
        # Its own destination is already in the field, and its source is where
        # the money is leaving from — neither is a useful suggestion.
        self.assertNotIn("Prior", picks)
        self.assertNotIn("Белинвестбанк", picks)
        self.assertIn("Freedom", picks)


@override_settings(LANGUAGE_CODE="en")
class DestinationDisclosureTests(SignedIn, TestCase):
    """Inside the currency gate, the field folds behind a caret.

    Most transfers stay within one bank, where the destination adds nothing —
    so it is collapsed by default and opened by the few who need it. It starts
    open whenever there is already something to see, since a saved value
    behind a closed caret reads as a value that was lost.
    """

    def _details(self, html):
        i = html.index('class="disclose"')
        start = html.rindex("<details", 0, i + 1)
        return html[start : html.index(">", i)]

    def test_the_field_sits_inside_a_disclosure(self):
        r = self.client.get(reverse("exchange-create"))
        html = r.content.decode()
        # The disclosure is inside the currency-gated row, not around it.
        row = html.index('class="field js-destination')
        self.assertLess(row, html.index('class="disclose"'))
        self.assertLess(html.index('class="disclose"'), html.index('name="received_provider"'))

    def test_a_blank_form_starts_collapsed(self):
        r = self.client.get(reverse("exchange-create"))
        self.assertNotIn("open", self._details(r.content.decode()))

    def test_a_saved_destination_starts_open(self):
        t = make(
            "1000",
            Currency.BYN,
            "1000",
            Currency.BYN,
            "Белинвестбанк",
            received_provider="Prior",
            owner=self.user,
        )
        r = self.client.get(reverse("exchange-edit", args=[t.pk]))
        self.assertIn("open", self._details(r.content.decode()))

    def test_a_transfer_without_a_destination_stays_collapsed(self):
        t = make(
            "1000", Currency.BYN, "1000", Currency.BYN, "Prior", owner=self.user
        )
        r = self.client.get(reverse("exchange-edit", args=[t.pk]))
        self.assertNotIn("open", self._details(r.content.decode()))

    def test_the_summary_carries_the_field_label(self):
        r = self.client.get(reverse("exchange-create"))
        html = r.content.decode()
        i = html.index("<summary>")
        self.assertIn("Money ends up at", html[i : html.index("</summary>", i)])

    def test_the_input_keeps_a_label_for_screen_readers(self):
        # The visible label became the summary, so the input needs its own.
        r = self.client.get(reverse("exchange-create"))
        html = r.content.decode()
        i = html.index('for="id_received_provider"')
        self.assertIn("sr-only", html[html.rindex("<label", 0, i) : i])

    def test_the_stylesheet_draws_a_caret(self):
        css = (settings.BASE_DIR / "static" / "css" / "app.css").read_text()
        self.assertIn(".disclose > summary::before", css)
        # The default marker cannot be positioned, so it is replaced outright.
        self.assertIn("::-webkit-details-marker", css)


class MadeOnTests(SignedIn, TestCase):
    """When the conversion happened, not when it was typed in.

    A backlog entered at the desk must not outrank a rate from last week just
    because its row is newer.
    """

    def test_defaults_to_today(self):
        from django.utils import timezone

        self.assertEqual(make(100, Currency.BYN, 30, Currency.USD).made_on, timezone.localdate())

    def test_can_be_backdated_from_the_form(self):
        self.client.post(
            reverse("exchange-create"),
            {
                "spent_amount": "100",
                "spent_currency": "BYN",
                "received_amount": "30",
                "received_currency": "USD",
                "made_on": "2026-03-01",
            },
        )
        self.assertEqual(str(Exchange.objects.get().made_on), "2026-03-01")

    def test_ledger_lists_by_date_not_entry_order(self):
        recent = make(100, Currency.BYN, 30, Currency.USD)
        old = make(100, Currency.BYN, 29, Currency.USD)
        Exchange.objects.filter(pk=old.pk).update(made_on="2026-03-01")
        Exchange.objects.update(owner=self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertEqual([e.pk for e in response.context["exchanges"]], [recent.pk, old.pk])


class NoSavedRoutesTests(SignedIn, TestCase):
    """Compare finds every chain already; a hand-saved copy only went stale."""

    def test_route_pages_are_gone(self):
        from django.urls import NoReverseMatch

        for name in ("route-create", "route-edit", "route-delete"):
            with self.assertRaises(NoReverseMatch):
                reverse(name, args=[1] if name != "route-create" else [])

    def test_dashboard_offers_no_saved_routes(self):
        make(100, Currency.BYN, 30, Currency.USD, owner=self.user)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "/route/")
        self.assertNotIn("saved_routes", response.context)

class LatestPerLaneTests(SignedIn, TestCase):
    """A repeat of the same conversion replaces the old rate, not joins it.

    A lane is the currency pair plus where the money starts and lands. Only its
    newest record by `made_on` routes; older ones stay in the ledger as history.
    """

    def setUp(self):
        self.old = make(100, Currency.BYN, 28, Currency.EUR, "Prior")
        self.new = make(100, Currency.BYN, 29, Currency.EUR, "Prior")
        # Entered last, but made first: a backlog row must not win.
        self.backlog = make(100, Currency.BYN, 30, Currency.EUR, "Prior")
        Exchange.objects.filter(pk=self.old.pk).update(made_on="2026-01-01")
        Exchange.objects.filter(pk=self.backlog.pk).update(made_on="2026-02-01")

    def test_only_the_newest_record_in_a_lane_routes(self):
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.EUR)
        self.assertEqual([p.legs[0].exchange.pk for p in paths], [self.new.pk])

    def test_another_bank_is_another_lane(self):
        other = make(100, Currency.BYN, 27, Currency.EUR, "Freedom")
        paths = best_paths(Exchange.objects.all(), Currency.BYN, Currency.EUR)
        self.assertEqual(
            sorted(p.legs[0].exchange.pk for p in paths), sorted([self.new.pk, other.pk])
        )

    def test_ledger_marks_older_records(self):
        response = self.client.get(reverse("dashboard"))
        self.assertEqual(response.context["current"], {self.new.pk})
        self.assertContains(response, "is-stale", count=2)

class StylesheetVersionTests(SignedIn, TestCase):
    def test_the_stylesheet_url_changes_when_the_file_does(self):
        # Without it Chrome kept an old app.css after the fonts moved in-house,
        # and Russian fell back to a system face until a hard reload.
        self.assertRegex(
            self.client.get(reverse("dashboard")).content.decode(), r"app\.css\?v=\d+"
        )
