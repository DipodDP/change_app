from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from .forms import ExchangeForm
from .models import Currency, Exchange, Route, RouteStep
from .routing import Leg, best_paths, chain_rate, compare, is_transfer, provider_ends


def make(spent, spent_cur, received, received_cur, provider="", owner=None):
    return Exchange.objects.create(
        spent_amount=Decimal(str(spent)),
        spent_currency=spent_cur,
        received_amount=Decimal(str(received)),
        received_currency=received_cur,
        provider=provider,
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
        Route.objects.filter(owner__isnull=True).update(owner=self.user)


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


class SavedRouteTests(TestCase):
    def test_route_reports_its_chain_rate(self):
        a = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        b = make("14.02", Currency.EUR, 5000, Currency.HUF, "Prior")
        route = Route.objects.create(name="Prior")
        RouteStep.objects.create(route=route, exchange=a, position=0)
        RouteStep.objects.create(route=route, exchange=b, position=1)

        self.assertEqual(
            chain_rate(route.ordered_steps()).quantize(Decimal("0.01")),
            Decimal("102.85"),
        )

    def test_steps_come_back_in_position_order(self):
        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        b = make("14.02", Currency.EUR, 5000, Currency.HUF)
        route = Route.objects.create(name="ordered")
        RouteStep.objects.create(route=route, exchange=b, position=1)
        RouteStep.objects.create(route=route, exchange=a, position=0)
        self.assertEqual(route.ordered_steps(), [a, b])


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
    """Exchanges and routes belong to a user."""

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

    def test_route_can_be_owned(self):
        route = Route.objects.create(name="mine", owner=self.user)
        self.assertEqual(route.owner, self.user)


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
    """Bank and route-name suggestions built from what is already stored."""

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

    def test_route_names_proposed_from_step_banks(self):
        from .suggestions import route_name_suggestions

        steps = list(Exchange.objects.filter(provider__in=["Prior", "OTP"])[:2])
        names = route_name_suggestions(steps)
        self.assertTrue(any("–" in n for n in names))

    def test_route_name_suggestions_skip_taken_names(self):
        from .suggestions import route_name_suggestions

        steps = list(Exchange.objects.filter(provider="Prior")[:1])
        names = route_name_suggestions(steps, taken=["Prior"])
        self.assertNotIn("Prior", names)


class UsageCountTests(TestCase):
    def test_exchange_reports_how_many_routes_use_it(self):
        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        b = make("14.02", Currency.EUR, 5000, Currency.HUF)
        r1 = Route.objects.create(name="one")
        RouteStep.objects.create(route=r1, exchange=a, position=0)
        RouteStep.objects.create(route=r1, exchange=b, position=1)
        r2 = Route.objects.create(name="two")
        RouteStep.objects.create(route=r2, exchange=a, position=0)

        self.assertEqual(a.routes.count(), 2)
        self.assertEqual(b.routes.count(), 1)


class AffectedRoutesTests(TestCase):
    """Editing an exchange previews which saved routes it changes."""

    def test_lists_routes_containing_the_exchange(self):
        from .suggestions import affected_routes

        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        b = make("14.02", Currency.EUR, 5000, Currency.HUF)
        r = Route.objects.create(name="Prior–OTP")
        RouteStep.objects.create(route=r, exchange=a, position=0)
        RouteStep.objects.create(route=r, exchange=b, position=1)

        found = affected_routes(a)
        self.assertEqual([x["route"].pk for x in found], [r.pk])

    def test_reports_the_through_rate(self):
        from .suggestions import affected_routes

        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        b = make("14.02", Currency.EUR, 5000, Currency.HUF)
        r = Route.objects.create(name="Prior–OTP")
        RouteStep.objects.create(route=r, exchange=a, position=0)
        RouteStep.objects.create(route=r, exchange=b, position=1)

        found = affected_routes(a)
        self.assertEqual(found[0]["rate"].quantize(Decimal("0.01")), Decimal("102.85"))

    def test_unused_exchange_affects_nothing(self):
        from .suggestions import affected_routes

        a = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.assertEqual(affected_routes(a), [])


class RouteBuilderTests(TestCase):
    """Candidate steps split into those that fit the chain and those that do not."""

    def setUp(self):
        self.byn_eur = make(100, Currency.BYN, "28.84", Currency.EUR)
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF)
        self.usd_huf = make("7.34", Currency.USD, 2200, Currency.HUF)

    def test_empty_chain_everything_fits(self):
        from .suggestions import split_candidates

        fits, unfits = split_candidates(Exchange.objects.all(), [])
        self.assertEqual(len(fits), 3)
        self.assertEqual(unfits, [])

    def test_only_matching_currency_fits(self):
        from .suggestions import split_candidates

        fits, unfits = split_candidates(Exchange.objects.all(), [self.byn_eur])
        self.assertIn(self.eur_huf, fits)
        self.assertIn(self.usd_huf, unfits)

    def test_chosen_steps_are_not_offered_again(self):
        from .suggestions import split_candidates

        fits, unfits = split_candidates(Exchange.objects.all(), [self.byn_eur])
        self.assertNotIn(self.byn_eur, fits + unfits)


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

    def test_usage_counts_present(self):
        r = self.client.get(reverse("dashboard"))
        self.assertTrue(all("used" in row for row in r.context["rows"]))

    def test_exchange_form_offers_bank_picks(self):
        r = self.client.get(reverse("exchange-create"))
        self.assertTrue(r.context["bank_picks"])

    def test_edit_form_shows_affected_routes(self):
        route = Route.objects.create(name="Prior–OTP")
        RouteStep.objects.create(route=route, exchange=self.byn_eur, position=0)
        RouteStep.objects.create(route=route, exchange=self.eur_huf, position=1)
        r = self.client.get(reverse("exchange-edit", args=[self.byn_eur.pk]))
        self.assertEqual(len(r.context["affected"]), 1)

    def test_route_builder_splits_candidates(self):
        r = self.client.get(reverse("route-create"), {"step_ids": str(self.byn_eur.pk)})
        self.assertIn(self.eur_huf, r.context["fitting"])
        self.assertIn(self.rub_byn, r.context["not_fitting"])

    def test_route_builder_shows_the_derived_name(self):
        # The name is no longer typed: it is derived from the steps' banks.
        r = self.client.get(reverse("route-create"), {"step_ids": str(self.byn_eur.pk)})
        self.assertEqual(r.context["derived_name"], "Prior")

    def test_saving_route_preserves_click_order(self):
        r = self.client.post(
            reverse("route-create"),
            {"name": "Prior–OTP", "step_ids": f"{self.byn_eur.pk},{self.eur_huf.pk}"},
        )
        self.assertRedirects(r, reverse("dashboard"))
        route = Route.objects.get()
        self.assertEqual(route.ordered_steps(), [self.byn_eur, self.eur_huf])

    def test_disconnected_route_is_rejected(self):
        r = self.client.post(
            reverse("route-create"),
            {"name": "bad", "step_ids": f"{self.byn_eur.pk},{self.rub_byn.pk}"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertFalse(Route.objects.filter(name="bad").exists())

    def test_reset_clears_then_reloads(self):
        self.client.post(reverse("reset-data"))
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


class RouteNameSyncTests(SignedIn, TestCase):
    """Route names are regenerated from the banks on their steps.

    A name like "Белинвест–Freedom–Wise" is wrong the moment those steps stop
    using those banks, so the name follows the data.
    """

    def setUp(self):
        self.a = make(60000, Currency.RUB, "2140.43", Currency.BYN, "Белинвест")
        self.b = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.c = make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        self.route = Route.objects.create(name="Белинвест–Prior–OTP")
        for i, e in enumerate([self.a, self.b, self.c]):
            RouteStep.objects.create(route=self.route, exchange=e, position=i)

    def test_name_from_steps(self):
        from .suggestions import name_from_steps

        self.assertEqual(
            name_from_steps(self.route.ordered_steps()), "Белинвест–Prior–OTP"
        )

    def test_renames_when_a_provider_changes(self):
        from .suggestions import sync_route_names

        self.c.provider = "Wise"
        self.c.save()
        sync_route_names(self.c)
        self.route.refresh_from_db()
        self.assertEqual(self.route.name, "Белинвест–Prior–Wise")

    def test_collapses_repeated_banks(self):
        from .suggestions import name_from_steps

        for e in (self.a, self.b, self.c):
            e.provider = "Prior"
            e.save()
        self.assertEqual(name_from_steps(self.route.ordered_steps()), "Prior")

    def test_unnamed_steps_fall_back_to_currencies(self):
        from .suggestions import name_from_steps

        for e in (self.a, self.b, self.c):
            e.provider = ""
            e.save()
        self.assertEqual(
            name_from_steps(self.route.ordered_steps()), "RUB → BYN → EUR → HUF"
        )

    def test_every_route_name_reflects_its_own_steps(self):
        from .suggestions import sync_route_names

        # Sync considers all routes, so collisions are judged on current names
        # rather than stale ones; each route is named for the steps it holds.
        other = Route.objects.create(name="Untouched")
        RouteStep.objects.create(route=other, exchange=self.a, position=0)
        self.b.provider = "Freedom"
        self.b.save()
        sync_route_names(self.b)

        other.refresh_from_db()
        self.route.refresh_from_db()
        self.assertEqual(other.name, "Белинвест")
        self.assertEqual(self.route.name, "Белинвест–Freedom–OTP")

    def test_editing_provider_through_the_view_renames(self):
        r = self.client.post(
            reverse("exchange-edit", args=[self.c.pk]),
            {
                "spent_amount": "14.02",
                "spent_currency": Currency.EUR,
                "received_amount": "5000",
                "received_currency": Currency.HUF,
                "provider": "Wise",
            },
        )
        self.assertRedirects(r, reverse("dashboard"))
        self.route.refresh_from_db()
        self.assertEqual(self.route.name, "Белинвест–Prior–Wise")


class NameDisambiguationTests(TestCase):
    """Two chains through the same banks still need distinguishable names."""

    def test_identical_bank_chains_get_currency_suffix(self):
        from .suggestions import name_from_steps

        a = make(60000, Currency.RUB, "2140.43", Currency.BYN, "Bank")
        b = make(100, Currency.BYN, "28.84", Currency.EUR, "Bank")
        c = make("14.02", Currency.EUR, 5000, Currency.HUF, "Bank")
        r = Route.objects.create(name="x")
        for i, e in enumerate([a, b, c]):
            RouteStep.objects.create(route=r, exchange=e, position=i)

        plain = name_from_steps(r.ordered_steps())
        detailed = name_from_steps(r.ordered_steps(), disambiguate=True)
        self.assertEqual(plain, "Bank")
        self.assertIn("EUR", detailed)
        self.assertIn("Bank", detailed)


class NameCollisionRegressionTests(TestCase):
    """Renaming one route must account for what its siblings are called now.

    Regression: sync only looked at routes containing the edited exchange, so
    it compared against a stale sibling name and left one route suffixed and
    the other not.
    """

    def setUp(self):
        self.hub = make(60000, Currency.RUB, "2140.43", Currency.BYN, "Hub")
        self.eur = make(100, Currency.BYN, "28.84", Currency.EUR, "Bank")
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF, "Bank")
        self.usd = make(100, Currency.BYN, "33.26", Currency.USD, "Bank")
        self.usd_huf = make("7.34", Currency.USD, 2200, Currency.HUF, "Other")

        self.r_eur = Route.objects.create(name="A")
        for i, e in enumerate([self.hub, self.eur, self.eur_huf]):
            RouteStep.objects.create(route=self.r_eur, exchange=e, position=i)
        self.r_usd = Route.objects.create(name="B")
        for i, e in enumerate([self.hub, self.usd, self.usd_huf]):
            RouteStep.objects.create(route=self.r_usd, exchange=e, position=i)

    def test_both_routes_are_suffixed_when_they_collide(self):
        from .suggestions import sync_route_names

        # Make the USD tail match the EUR one, creating a collision.
        self.usd_huf.provider = "Bank"
        self.usd_huf.save()
        sync_route_names(self.usd_huf)

        self.r_eur.refresh_from_db()
        self.r_usd.refresh_from_db()
        self.assertNotEqual(self.r_eur.name, self.r_usd.name)
        # Neither should be a bare name while the other carries a suffix.
        self.assertIn("(", self.r_eur.name)
        self.assertIn("(", self.r_usd.name)

    def test_suffix_drops_when_collision_is_resolved(self):
        from .suggestions import sync_route_names

        self.usd_huf.provider = "Bank"
        self.usd_huf.save()
        sync_route_names(self.usd_huf)

        self.usd_huf.provider = "Other"
        self.usd_huf.save()
        sync_route_names(self.usd_huf)

        self.r_eur.refresh_from_db()
        self.r_usd.refresh_from_db()
        self.assertNotIn("(", self.r_eur.name)
        self.assertNotIn("(", self.r_usd.name)


class RouteEditTests(SignedIn, TestCase):
    """Saved routes can have their steps changed after creation."""

    def setUp(self):
        self.hub = make(60000, Currency.RUB, "2140.43", Currency.BYN, "Hub")
        self.eur = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.eur_huf = make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        self.usd = make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")
        self.usd_huf = make("7.34", Currency.USD, 2200, Currency.HUF, "Wise")

        self.route = Route.objects.create(name="Hub–Prior–OTP")
        for i, e in enumerate([self.hub, self.eur, self.eur_huf]):
            RouteStep.objects.create(route=self.route, exchange=e, position=i)

    def test_edit_page_renders_with_current_steps(self):
        r = self.client.get(reverse("route-edit", args=[self.route.pk]))
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.context["chosen"], [self.hub, self.eur, self.eur_huf])

    def test_edit_page_offers_only_connecting_candidates(self):
        r = self.client.get(reverse("route-edit", args=[self.route.pk]))
        # Chain ends in HUF; nothing here starts from HUF.
        self.assertEqual(r.context["fitting"], [])
        self.assertIn(self.usd, r.context["not_fitting"])

    def test_saving_replaces_the_steps(self):
        r = self.client.post(
            reverse("route-edit", args=[self.route.pk]),
            {"step_ids": f"{self.hub.pk},{self.usd.pk},{self.usd_huf.pk}"},
        )
        self.assertRedirects(r, reverse("dashboard"))
        self.route.refresh_from_db()
        self.assertEqual(
            self.route.ordered_steps(), [self.hub, self.usd, self.usd_huf]
        )

    def test_name_follows_the_new_steps(self):
        self.client.post(
            reverse("route-edit", args=[self.route.pk]),
            {"step_ids": f"{self.hub.pk},{self.usd.pk},{self.usd_huf.pk}"},
        )
        self.route.refresh_from_db()
        self.assertEqual(self.route.name, "Hub–Freedom–Wise")

    def test_no_duplicate_steps_left_behind(self):
        self.client.post(
            reverse("route-edit", args=[self.route.pk]),
            {"step_ids": f"{self.hub.pk},{self.usd.pk}"},
        )
        self.assertEqual(self.route.route_steps.count(), 2)

    def test_disconnected_edit_is_rejected(self):
        r = self.client.post(
            reverse("route-edit", args=[self.route.pk]),
            {"step_ids": f"{self.eur.pk},{self.hub.pk}"},
        )
        self.assertEqual(r.status_code, 200)
        self.route.refresh_from_db()
        # Original steps survive a rejected edit.
        self.assertEqual(len(self.route.ordered_steps()), 3)

    def test_editing_a_missing_route_is_404(self):
        r = self.client.get(reverse("route-edit", args=[9999]))
        self.assertEqual(r.status_code, 404)

    def test_dashboard_links_to_the_editor(self):
        r = self.client.get(reverse("dashboard"))
        self.assertContains(r, reverse("route-edit", args=[self.route.pk]))


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


class ExchangeDeleteTests(SignedIn, TestCase):
    """Deleting a step must leave every route it touched coherent."""

    def setUp(self):
        self.a = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.b = make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        self.route = Route.objects.create(name="Prior–OTP")
        RouteStep.objects.create(route=self.route, exchange=self.a, position=0)
        RouteStep.objects.create(route=self.route, exchange=self.b, position=1)

    def test_positions_are_resequenced(self):
        self.client.post(reverse("exchange-delete", args=[self.a.pk]))
        positions = list(
            self.route.route_steps.order_by("position").values_list("position", flat=True)
        )
        self.assertEqual(positions, [0])

    def test_route_name_is_resynced(self):
        self.client.post(reverse("exchange-delete", args=[self.a.pk]))
        self.route.refresh_from_db()
        self.assertEqual(self.route.name, "OTP")

    def test_route_left_with_no_steps_is_removed(self):
        self.client.post(reverse("exchange-delete", args=[self.a.pk]))
        self.client.post(reverse("exchange-delete", args=[self.b.pk]))
        self.assertFalse(Route.objects.filter(pk=self.route.pk).exists())


class EditBreakingRoutesTests(SignedIn, TestCase):
    """Changing a currency must not silently strand a saved route."""

    def setUp(self):
        self.a = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.b = make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        self.route = Route.objects.create(name="Prior–OTP")
        RouteStep.objects.create(route=self.route, exchange=self.a, position=0)
        RouteStep.objects.create(route=self.route, exchange=self.b, position=1)

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

    def test_breaking_edit_is_rejected(self):
        response = self._post(received_currency=Currency.USD)
        self.assertEqual(response.status_code, 200)
        self.a.refresh_from_db()
        self.assertEqual(self.a.received_currency, Currency.EUR)

    def test_breaking_edit_names_the_route(self):
        response = self._post(received_currency=Currency.USD)
        self.assertContains(response, "Prior–OTP")

    def test_harmless_edit_still_saves(self):
        response = self._post(received_amount="30.00")
        self.assertEqual(response.status_code, 302)
        self.a.refresh_from_db()
        self.assertEqual(self.a.received_amount, Decimal("30.00"))


class AuthRequiredTests(TestCase):
    """Every view is behind a login; anonymous visitors are bounced."""

    def setUp(self):
        self.exchange = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        self.route = Route.objects.create(name="Prior")
        RouteStep.objects.create(route=self.route, exchange=self.exchange, position=0)

    def test_all_views_redirect_anonymous(self):
        urls = [
            reverse("dashboard"),
            reverse("exchange-create"),
            reverse("exchange-edit", args=[self.exchange.pk]),
            reverse("exchange-delete", args=[self.exchange.pk]),
            reverse("route-create"),
            reverse("route-edit", args=[self.route.pk]),
            reverse("route-delete", args=[self.route.pk]),
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
        self.her_route = Route.objects.create(name="Prior", owner=self.alice)
        RouteStep.objects.create(route=self.her_route, exchange=self.hers, position=0)

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

    def test_cannot_delete_another_users_route(self):
        response = self.client.post(reverse("route-delete", args=[self.her_route.pk]))
        self.assertEqual(response.status_code, 404)
        self.assertTrue(Route.objects.filter(pk=self.her_route.pk).exists())

    def test_cannot_edit_another_users_route(self):
        response = self.client.get(reverse("route-edit", args=[self.her_route.pk]))
        self.assertEqual(response.status_code, 404)

    def test_cannot_build_a_route_from_another_users_steps(self):
        response = self.client.post(
            reverse("route-create"), {"step_ids": str(self.hers.pk)}
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(Route.objects.filter(owner=self.bob).exists())

    def test_reset_only_clears_own_data(self):
        mine = make(100, Currency.BYN, "33.26", Currency.USD, "Freedom")
        mine.owner = self.bob
        mine.save()
        self.client.post(reverse("reset-data"))
        self.assertTrue(Exchange.objects.filter(pk=self.hers.pk).exists())
        self.assertFalse(Exchange.objects.filter(pk=mine.pk).exists())


class NameLastResortTests(TestCase):
    """Same banks and same currency path still need distinguishable names."""

    def test_identical_shape_routes_get_distinct_names(self):
        from .suggestions import sync_route_names

        a1 = make(100, Currency.BYN, "28.84", Currency.EUR, "Prior")
        a2 = make("14.02", Currency.EUR, 5000, Currency.HUF, "OTP")
        b1 = make(200, Currency.BYN, "57.10", Currency.EUR, "Prior")
        b2 = make("28.00", Currency.EUR, 9900, Currency.HUF, "OTP")

        first = Route.objects.create(name="x")
        for i, e in enumerate([a1, a2]):
            RouteStep.objects.create(route=first, exchange=e, position=i)
        second = Route.objects.create(name="y")
        for i, e in enumerate([b1, b2]):
            RouteStep.objects.create(route=second, exchange=e, position=i)

        sync_route_names()
        first.refresh_from_db()
        second.refresh_from_db()
        self.assertNotEqual(first.name, second.name)


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

    def test_each_bank_sits_between_the_currencies_it_connects(self):
        chain = self._chain()
        # Freedom converts USD into AMD, so it must render after the $ chip
        # and before the ֏ chip rather than hanging off the end.
        last_bank = chain.rindex("Белинвестбанк")
        self.assertLess(chain.index("$"), last_bank)
        self.assertLess(last_bank, chain.index("֏"))

    def test_a_bank_is_marked_up_as_an_edge_not_a_hop(self):
        import re

        chain = self._chain()
        self.assertIn("hop-via", chain)
        # A provider nested inside a currency chip reads as a label on that
        # currency; it has to stand on its own between two chips instead.
        hops = re.findall(r'<div class="hop">(.*?)</div>', chain, re.S)
        self.assertTrue(hops)
        for hop in hops:
            self.assertNotIn("hop-via", hop)

    def test_the_chain_alternates_currency_then_bank(self):
        import re

        chain = self._chain()
        kinds = [m.group(1) for m in re.finditer(r'class="(hop-cur|hop-via)"', chain)]
        # RUB [bank] BYN [bank] USD [bank] AMD
        self.assertEqual(
            kinds,
            [
                "hop-cur", "hop-via", "hop-cur", "hop-via",
                "hop-cur", "hop-via", "hop-cur",
            ],
        )


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


class SavedRouteContinuityTests(TestCase):
    """A saved route obeys the same rule the router does.

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

    def test_the_dashboard_marks_such_a_route_broken(self):
        from .suggestions import affected_routes

        a = make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк")
        b = make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        route = Route.objects.create(name="mixed")
        for i, e in enumerate([a, b]):
            RouteStep.objects.create(route=route, exchange=e, position=i)
        item = affected_routes(a)[0]
        self.assertTrue(item["broken"])
        self.assertIsNone(item["rate"])


class TransferTests(TestCase):
    """Moving money between your own accounts, in one currency.

    A transfer is not a conversion, so it carries a provider on each end
    ("Белинвестбанк→Prior") and may keep the same currency on both sides.
    """

    def test_a_transfer_may_keep_the_same_currency(self):
        form = ExchangeForm(
            data={
                "spent_amount": "1000",
                "spent_currency": Currency.BYN,
                "received_amount": "1000",
                "received_currency": Currency.BYN,
                "provider": "Белинвестбанк→Prior",
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
        make("1000", Currency.BYN, "1000", Currency.BYN, "Белинвестбанк→Prior")
        make("100", Currency.BYN, "28.84", Currency.EUR, "Prior")
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertEqual(len(paths), 1)

    def test_a_transfer_does_not_bridge_the_wrong_way(self):
        # Белинвестбанк→Prior moves money one way only.
        make("60000", Currency.RUB, "2140.43", Currency.BYN, "Prior")
        make("1000", Currency.BYN, "1000", Currency.BYN, "Белинвестбанк→Prior")
        make("100", Currency.BYN, "28.84", Currency.EUR, "Белинвестбанк")
        paths = best_paths(Exchange.objects.all(), Currency.RUB, Currency.EUR)
        self.assertEqual(len(paths), 0)

    def test_a_transfer_with_a_fee_costs_something(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
            make("1000", Currency.BYN, "995", Currency.BYN, "Белинвестбанк→Prior"),
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
        e = make("1000", Currency.BYN, "995", Currency.BYN, "Белинвестбанк→Prior")
        self.assertLess(e.rate, Decimal("1"))

    def test_a_fee_bearing_transfer_lowers_the_whole_chain(self):
        steps = [
            make("60000", Currency.RUB, "2140.43", Currency.BYN, "Белинвестбанк"),
            make("1000", Currency.BYN, "995", Currency.BYN, "Белинвестбанк→Prior"),
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
        make("1000", Currency.BYN, "1000", Currency.BYN, "Белинвестбанк→Prior")
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
