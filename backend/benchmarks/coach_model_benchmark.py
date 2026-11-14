"""C427B - isolated Coach model benchmark (gpt-6-luna vs gpt-4.1).

Standalone: not imported by any endpoint, never changes OPENAI_MODEL in production.
It replays the production chat path (llm_coach.enrich_chat_response: same prompts,
guard-rails, Responses API parameters, response cleaning) on private anonymised
fixtures, once per model, and measures latency, tokens and cost.

Without --live nothing is sent to OpenAI (plan only). Live calls need the key in
OPENAI_API_KEY, an explicit authorisation flag + env var, a declared remaining
budget, and a verified price grid. See docs/C427B_COACH_MODEL_BENCHMARK.md.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import statistics
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

DEFAULT_MODELS = ("gpt-6-luna", "gpt-4.1")
HARD_BUDGET_CEILING_USD = 1.0
AUTH_ENV_VAR = "C427B_PAID_CALLS_AUTHORIZED"
AUTH_ENV_VALUE = "yes"
PREMIUM_PRICE_EUR = 4.99
QUESTIONS_PER_USER_MONTH = 30
SUBSCRIBER_COUNTS = (100, 500, 1000)
CHARS_PER_TOKEN_UPPER = 2.5  # conservative: overestimates input tokens for the pre-call budget guard
SYSTEM_PROMPT_HEADROOM_CHARS = 9000


@dataclass(frozen=True)
class Turn:
    message: str
    context_key: str


@dataclass(frozen=True)
class Scenario:
    id: str
    label: str
    turns: tuple[Turn, ...]
    # Follow-ups feed the same model's own earlier answers back as history (continuity test);
    # only the first turn of a chain has strictly identical inputs across models.
    chained: bool = False


SCENARIOS: tuple[Scenario, ...] = (
    Scenario("S1_accel_0511", "Séance du 05/11 : accélérations",
             (Turn("Qu'as-tu observé dans les tours de cette séance ?", "s0511"),)),
    Scenario("S2_retain_0511", "Suivi 05/11 : à retenir",
             (Turn("Qu'as-tu observé dans les tours de cette séance ?", "s0511"),
              Turn("Qu'est-ce que je dois retenir surtout ?", "s0511")), chained=True),
    Scenario("S3_analysis_0311", "Séance du 03/11 : analyse et historique",
             (Turn("Analyse cette sortie et situe-la par rapport à mon historique.", "s0311"),)),
    Scenario("S4_improve_0311", "Suivi 03/11 : conseil",
             (Turn("Analyse cette sortie et situe-la par rapport à mon historique.", "s0311"),
              Turn("Comment améliorer ma prochaine séance de ce type ?", "s0311")), chained=True),
    Scenario("S5_compare", "Comparaison de deux séances",
             (Turn("Compare ces deux séances.", "comparison"),)),
    Scenario("S6_heart_rate", "Fréquence cardiaque et limites",
             (Turn("Que dit ma fréquence cardiaque sur cette séance, et jusqu'où puis-je l'interpréter ?",
                   "s0311"),)),
    Scenario("S7_followup", "Conversation de suivi (3 tours)",
             (Turn("Résume cette séance.", "s0311"),
              Turn("Et le cardio ?", "s0311"),
              Turn("Donc, qu'est-ce que je fais pour la prochaine ?", "s0311")), chained=True),
    Scenario("S8_missing_data", "Données manquantes",
             (Turn("Quelle est ma VO2max, mon seuil lactique et ma qualité de sommeil de cette nuit ?",
                   "s0311"),)),
)
# "Plan d'entraînement actuel" is intentionally absent: the general-chat context builder persists
# served prescriptions (see server._build_coach_llm_context), so it cannot be exported read-only.


# ---------------------------------------------------------------- statistics

def percentile_nearest_rank(values: list[float], pct: float) -> Optional[float]:
    if not values:
        return None
    ordered = sorted(values)
    rank = max(1, math.ceil(pct / 100 * len(ordered)))
    return ordered[min(rank, len(ordered)) - 1]


def summarize(values: list[float]) -> dict[str, Optional[float]]:
    if not values:
        return {"n": 0, "median": None, "min": None, "max": None, "p95_indicative": None, "mean": None}
    return {
        "n": len(values),
        "median": round(statistics.median(values), 4),
        "min": round(min(values), 4),
        "max": round(max(values), 4),
        "p95_indicative": round(percentile_nearest_rank(values, 95), 4),
        "mean": round(statistics.fmean(values), 4),
    }


# ---------------------------------------------------------------- pricing / budget

@dataclass(frozen=True)
class Price:
    input_per_mtok: float
    cached_per_mtok: float
    output_per_mtok: float


def parse_price(spec: str) -> tuple[str, Price]:
    """MODEL=input,cached,output in USD per 1M tokens."""
    try:
        model, rest = spec.split("=", 1)
        inp, cached, out = (float(x) for x in rest.split(","))
    except ValueError as exc:
        raise ValueError(f"invalid --price '{spec}', expected MODEL=input,cached,output") from exc
    if min(inp, cached, out) < 0 or not model.strip():
        raise ValueError(f"invalid --price '{spec}'")
    return model.strip(), Price(inp, cached, out)


def cost_usd(price: Price, input_tokens: int, cached_tokens: int, output_tokens: int) -> float:
    uncached = max(input_tokens - cached_tokens, 0)
    return (uncached * price.input_per_mtok + cached_tokens * price.cached_per_mtok
            + output_tokens * price.output_per_mtok) / 1_000_000


def worst_case_call_cost(price: Price, prompt_chars: int, max_output_tokens: int) -> float:
    est_input = math.ceil(prompt_chars / CHARS_PER_TOKEN_UPPER)
    return cost_usd(price, est_input, 0, max_output_tokens)


class BudgetGuard:
    """Stops the run before a call that could exceed the ceiling, or when usage is untrackable."""

    def __init__(self, ceiling_usd: float, max_calls: int):
        self.ceiling = ceiling_usd
        self.max_calls = max_calls
        self.spent = 0.0
        self.calls = 0
        self.stop_reason: Optional[str] = None

    def check(self, worst_case: float) -> bool:
        if self.stop_reason:
            return False
        if self.calls >= self.max_calls:
            self.stop_reason = "max_calls_reached"
        elif self.spent + worst_case > self.ceiling:
            self.stop_reason = "budget_ceiling_would_be_exceeded"
        return self.stop_reason is None

    def record(self, actual_cost: Optional[float], worst_case: float) -> None:
        self.calls += 1
        if actual_cost is None:
            # Usage not reported: charge the worst case and stop, consumption is no longer reliable.
            self.spent += worst_case
            self.stop_reason = "usage_untrackable"
        else:
            self.spent += actual_cost


# ---------------------------------------------------------------- safety checks

def assert_outside_repo(path: Path, what: str) -> Path:
    resolved = path.expanduser().resolve()
    if resolved == REPO_ROOT or REPO_ROOT in resolved.parents:
        raise SystemExit(f"{what} must be outside the repository ({REPO_ROOT}).")
    return resolved


def check_live_authorization(args: argparse.Namespace, api_key: str) -> None:
    problems = []
    if not api_key:
        problems.append("OPENAI_API_KEY is not set")
    if not args.i_authorize_paid_calls or os.environ.get(AUTH_ENV_VAR) != AUTH_ENV_VALUE:
        problems.append(
            f"explicit authorisation missing (--i-authorize-paid-calls and {AUTH_ENV_VAR}={AUTH_ENV_VALUE})")
    if args.remaining_budget_usd is None:
        problems.append("--remaining-budget-usd (checked in the OpenAI dashboard) is required")
    elif args.remaining_budget_usd < args.budget_usd:
        problems.append("remaining OpenAI budget is below the experiment ceiling")
    if not 0 < args.budget_usd <= HARD_BUDGET_CEILING_USD:
        problems.append(f"--budget-usd must be in (0, {HARD_BUDGET_CEILING_USD}]")
    if problems:
        raise SystemExit("Live run refused: " + "; ".join(problems))


def load_fixtures(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    contexts = data.get("contexts") if isinstance(data, dict) else None
    if not isinstance(contexts, dict) or not contexts:
        raise SystemExit("Fixture file must be a JSON object with a non-empty 'contexts' object.")
    return contexts


# ---------------------------------------------------------------- run

@dataclass
class CallRecord:
    scenario: str
    turn: int
    model: str
    repetition: int
    success: bool
    error: Optional[str]
    api_duration_sec: Optional[float]
    total_duration_sec: float
    input_tokens: Optional[int]
    cached_tokens: Optional[int]
    output_tokens: Optional[int]
    reasoning_tokens: Optional[int]
    cost_usd: Optional[float]
    response_chars: int = 0
    response: Optional[str] = field(default=None, repr=False)


Caller = Callable[..., Awaitable[tuple[Optional[str], bool, dict]]]


def build_schedule(scenarios: list[Scenario], models: list[str], repetitions: int):
    """Yield (repetition, scenario, turn_index, ordered models); model order alternates each step."""
    step = 0
    for rep in range(repetitions):
        for scenario in scenarios:
            for turn_index in range(len(scenario.turns)):
                order = list(models) if (rep + step) % 2 == 0 else list(reversed(models))
                yield rep, scenario, turn_index, order
                step += 1


def _prompt_chars(turn: Turn, context: dict, history: list[dict]) -> int:
    return (len(json.dumps(context, ensure_ascii=False)) + len(turn.message)
            + sum(len(str(m.get("content", ""))) for m in history) + SYSTEM_PROMPT_HEADROOM_CHARS)


async def run_benchmark(
    *,
    contexts: dict[str, Any],
    models: list[str],
    prices: dict[str, Price],
    repetitions: int,
    budget: BudgetGuard,
    max_output_tokens: int,
    caller: Caller,
    set_model: Callable[[str], None],
) -> tuple[list[CallRecord], list[str]]:
    scenarios, skipped = [], []
    for scenario in SCENARIOS:
        missing = sorted({t.context_key for t in scenario.turns} - set(contexts))
        if missing:
            skipped.append(f"{scenario.id}: skipped, missing context(s) {', '.join(missing)}")
        else:
            scenarios.append(scenario)

    records: list[CallRecord] = []
    histories: dict[tuple[str, int, str], list[dict]] = {}
    failed_chains: set[tuple[str, int, str]] = set()

    for rep, scenario, turn_index, order in build_schedule(scenarios, models, repetitions):
        turn = scenario.turns[turn_index]
        context = contexts[turn.context_key]
        for model in order:
            key = (scenario.id, rep, model)
            if key in failed_chains:
                continue
            history = histories.setdefault(key, []) if scenario.chained else []
            worst = worst_case_call_cost(prices[model], _prompt_chars(turn, context, history), max_output_tokens)
            if not budget.check(worst):
                return records, skipped + [f"stopped: {budget.stop_reason}"]
            set_model(model)
            started = time.perf_counter()
            text, ok, meta = await caller(
                user_message=turn.message,
                context=context,
                conversation_history=list(history),
                user_id="benchmark",
            )
            total = time.perf_counter() - started
            in_t, cached_t, out_t = (meta.get(k) for k in ("input_tokens", "cached_input_tokens", "output_tokens"))
            actual = (cost_usd(prices[model], in_t, cached_t or 0, out_t)
                      if in_t is not None and out_t is not None else None)
            budget.record(actual, worst)
            records.append(CallRecord(
                scenario=scenario.id, turn=turn_index, model=model, repetition=rep, success=bool(ok and text),
                error=None if ok else str(meta.get("error") or "unknown"),
                api_duration_sec=meta.get("duration_sec"), total_duration_sec=round(total, 3),
                input_tokens=in_t, cached_tokens=cached_t, output_tokens=out_t,
                reasoning_tokens=meta.get("reasoning_tokens"), cost_usd=actual,
                response_chars=len(text or ""), response=text,
            ))
            if scenario.chained:
                if ok and text:
                    history.extend([{"role": "user", "content": turn.message},
                                    {"role": "assistant", "content": text}])
                else:
                    failed_chains.add(key)
    return records, skipped


# ---------------------------------------------------------------- reporting

def model_stats(records: list[CallRecord], model: str) -> dict[str, Any]:
    rows = [r for r in records if r.model == model]
    ok = [r for r in rows if r.success]

    def col(attr: str, source=ok) -> list[float]:
        return [getattr(r, attr) for r in source if getattr(r, attr) is not None]

    costs = col("cost_usd", rows)
    return {
        "calls": len(rows),
        "success": len(ok),
        "errors": sorted({r.error for r in rows if r.error}),
        "api_latency_sec": summarize(col("api_duration_sec")),
        "total_latency_sec": summarize(col("total_duration_sec")),
        "input_tokens_mean": summarize(col("input_tokens"))["mean"],
        "cached_tokens_mean": summarize(col("cached_tokens"))["mean"],
        "output_tokens": summarize(col("output_tokens")),
        "reasoning_tokens_mean": summarize(col("reasoning_tokens"))["mean"],
        "cost_usd_per_response_mean": round(statistics.fmean(costs), 6) if costs else None,
        "cost_usd_total_measured": round(sum(costs), 6) if costs else None,
    }


def economics(mean_cost: Optional[float], eur_per_usd: Optional[float]) -> dict[str, Any]:
    if mean_cost is None:
        return {}
    monthly = mean_cost * QUESTIONS_PER_USER_MONTH
    out: dict[str, Any] = {"usd_per_user_month_30q": round(monthly, 4)}
    for n in SUBSCRIBER_COUNTS:
        out[f"usd_{n}_subscribers_month"] = round(monthly * n, 2)
    if eur_per_usd:
        out["share_of_premium_price_pct"] = round(monthly * eur_per_usd / PREMIUM_PRICE_EUR * 100, 2)
    return out


def _fmt(value: Any) -> str:
    return "n/a" if value is None else str(value)


def render_report(stats: dict[str, dict], econ: dict[str, dict], meta: dict[str, Any]) -> str:
    models = list(stats)
    lines = [
        "# C427B - Coach model benchmark report",
        "",
        f"Mode: **{meta['mode']}**. Spent (estimated from measured tokens, USD): {_fmt(meta['spent_usd'])}. "
        f"Calls: {meta['calls']}. Stop reason: {_fmt(meta['stop_reason'])}.",
        "Small sample: medians/P95 are indicative, not statistically representative. "
        "No response text, identifier or Garmin value appears in this report.",
        "",
        "| Indicateur | " + " | ".join(models) + " |",
        "|---|" + "---|" * len(models),
    ]

    def row(label: str, fn) -> None:
        lines.append(f"| {label} | " + " | ".join(_fmt(fn(stats[m])) for m in models) + " |")

    row("Appels (succès/total)", lambda s: f"{s['success']}/{s['calls']}")
    row("Latence API médiane (s)", lambda s: s["api_latency_sec"]["median"])
    row("Latence API min / max (s)", lambda s: f"{s['api_latency_sec']['min']} / {s['api_latency_sec']['max']}")
    row("Latence API P95 indicatif (s)", lambda s: s["api_latency_sec"]["p95_indicative"])
    row("Durée totale script médiane (s)", lambda s: s["total_latency_sec"]["median"])
    row("Tokens entrée moyens", lambda s: s["input_tokens_mean"])
    row("Tokens en cache moyens", lambda s: s["cached_tokens_mean"])
    row("Tokens sortie moyens", lambda s: s["output_tokens"]["mean"])
    row("Tokens raisonnement moyens", lambda s: s["reasoning_tokens_mean"])
    row("Coût moyen par réponse (USD)", lambda s: s["cost_usd_per_response_mean"])
    row("Erreurs", lambda s: ", ".join(s["errors"]) or "aucune")
    for label, key in (("Coût 30 q/mois/utilisateur (USD)", "usd_per_user_month_30q"),
                       ("Coût 100 abonnés/mois (USD)", "usd_100_subscribers_month"),
                       ("Coût 500 abonnés/mois (USD)", "usd_500_subscribers_month"),
                       ("Coût 1000 abonnés/mois (USD)", "usd_1000_subscribers_month"),
                       ("Part de l'abonnement 4,99 € (%)", "share_of_premium_price_pct")):
        lines.append(f"| {label} | " + " | ".join(_fmt(econ[m].get(key)) for m in models) + " |")
    lines += [
        "",
        "Coûts calculés à partir des tokens mesurés et de la grille fournie via --price (à vérifier contre la "
        "page de tarification OpenAI) ; ce sont des estimations, pas la facture. Durée API = durée de l'appel "
        "OpenAI (llm_coach). La durée totale du backend (Mongo, contexte, garde-fous) n'est pas mesurée ici.",
        "",
        "## Évaluation manuelle (à remplir en aveugle, jamais pré-remplie)",
        "",
        "| Critère /5 | " + " | ".join(models) + " |",
        "|---|" + "---|" * len(models),
    ]
    for criterion in ("Exactitude des chiffres Garmin", "Structure de séance", "Conclusions sportives",
                      "Conseils applicables", "Naturel conversationnel", "Continuité des suivis",
                      "Limites physiologiques"):
        lines.append(f"| {criterion} | " + " | ".join("à évaluer" for _ in models) + " |")
    lines += ["", "Défauts éliminatoires et erreurs à signaler séparément (comptes par modèle) : chiffre inventé, "
              "mauvaise séance, fractionné fictif, interprétation physiologique non autorisée, prescription "
              "contraire à Training V2, fuite inter-utilisateurs, réponse peu utile."]
    return "\n".join(lines) + "\n"


def write_blind_files(out_dir: Path, records: list[CallRecord], seed: int) -> None:
    """Anonymised responses for blind scoring; the label->model key is a separate file."""
    rng = random.Random(seed)
    grouped: dict[str, list[CallRecord]] = {}
    for rec in records:
        if rec.response is not None:
            grouped.setdefault(f"{rec.scenario}|rep{rec.repetition}|turn{rec.turn}", []).append(rec)
    anonymised, key_map = [], {}
    for item_key, items in grouped.items():
        rng.shuffle(items)
        for letter, rec in zip("ABCDEFGH", items):
            anonymised.append({"item": item_key, "label": letter, "response": rec.response})
            key_map[f"{item_key}|{letter}"] = rec.model
    for name, payload in (("responses_blind_private.json", anonymised), ("blind_key_private.json", key_map)):
        target = out_dir / name
        target.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        target.chmod(0o600)


# ---------------------------------------------------------------- live wiring

async def check_models_available(models: list[str], api_key: str) -> dict[str, str]:
    """models.retrieve is free. llm_coach sends only model/instructions/input/store/max_output_tokens,
    never a reasoning parameter, so the non-reasoning gpt-4.1 receives nothing incompatible."""
    from openai import AsyncOpenAI
    client = AsyncOpenAI(api_key=api_key, timeout=15.0, max_retries=0)
    result = {}
    try:
        for model in models:
            try:
                await client.models.retrieve(model)
                result[model] = "available"
            except Exception as exc:  # status only: never echo the message
                result[model] = f"unavailable_{getattr(exc, 'status_code', type(exc).__name__)}"
    finally:
        await client.close()
    return result


def install_live_instrumentation(llm_coach, max_output_tokens: int) -> None:
    original = llm_coach._record_usage

    def record_usage(metadata, response):
        original(metadata, response)
        usage = getattr(response, "usage", None)
        details = getattr(usage, "output_tokens_details", None)
        reasoning = getattr(details, "reasoning_tokens", None)
        if isinstance(reasoning, int):
            metadata["reasoning_tokens"] = reasoning

    llm_coach._record_usage = record_usage
    llm_coach.LLM_MAX_OUTPUT_TOKENS = max_output_tokens


def parse_args(argv: Optional[list[str]] = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--fixtures", required=True, type=Path, help="private anonymised fixtures JSON (outside the repo)")
    p.add_argument("--out-dir", required=True, type=Path, help="private output directory (outside the repo)")
    p.add_argument("--models", nargs="+", default=list(DEFAULT_MODELS))
    p.add_argument("--repetitions", type=int, default=3)
    p.add_argument("--price", action="append", default=[], metavar="MODEL=IN,CACHED,OUT",
                   help="verified USD per 1M tokens; required for every model in live mode")
    p.add_argument("--eur-per-usd", type=float, default=None, help="needed only for the 4.99 EUR share")
    p.add_argument("--budget-usd", type=float, default=HARD_BUDGET_CEILING_USD)
    p.add_argument("--remaining-budget-usd", type=float, default=None)
    p.add_argument("--max-calls", type=int, default=60)
    p.add_argument("--max-output-tokens", type=int, default=2000)
    p.add_argument("--live", action="store_true", help="perform paid OpenAI calls")
    p.add_argument("--i-authorize-paid-calls", action="store_true")
    p.add_argument("--seed", type=int, default=427)
    return p.parse_args(argv)


def main(argv: Optional[list[str]] = None) -> int:
    args = parse_args(argv)
    fixtures = assert_outside_repo(args.fixtures, "--fixtures")
    out_dir = assert_outside_repo(args.out_dir, "--out-dir")
    if args.repetitions < 1 or args.max_calls < 1 or args.max_output_tokens < 1:
        raise SystemExit("repetitions, max-calls and max-output-tokens must be >= 1.")
    try:
        prices = dict(parse_price(s) for s in args.price)
    except ValueError as exc:
        raise SystemExit(str(exc))
    contexts = load_fixtures(fixtures)

    runnable = [s for s in SCENARIOS if {t.context_key for t in s.turns} <= set(contexts)]
    planned = sum(len(s.turns) for s in runnable) * len(args.models) * args.repetitions
    print(f"Plan: {len(runnable)}/{len(SCENARIOS)} scenarios, {len(args.models)} models, "
          f"{args.repetitions} repetitions = {planned} calls (cap {args.max_calls}, budget {args.budget_usd} USD).")
    if not args.live:
        print("Dry run: no OpenAI call made. Add --live with the required authorisations to execute.")
        return 0

    api_key = os.environ.get("OPENAI_API_KEY", "")
    check_live_authorization(args, api_key)
    missing_prices = [m for m in args.models if m not in prices]
    if missing_prices:
        raise SystemExit(f"Live run refused: no verified --price for {', '.join(missing_prices)}.")
    if planned > args.max_calls:
        print(f"Warning: plan exceeds --max-calls; the run will stop after {args.max_calls} calls.")

    availability = asyncio.run(check_models_available(args.models, api_key))
    print("Model availability:", availability)
    if any(v != "available" for v in availability.values()):
        raise SystemExit("Live run refused: a model is not available for this account.")

    import llm_coach
    install_live_instrumentation(llm_coach, args.max_output_tokens)

    def set_model(model: str) -> None:
        llm_coach.LLM_MODEL = model

    budget = BudgetGuard(args.budget_usd, args.max_calls)
    records, notes = asyncio.run(run_benchmark(
        contexts=contexts, models=args.models, prices=prices, repetitions=args.repetitions, budget=budget,
        max_output_tokens=args.max_output_tokens, caller=llm_coach.enrich_chat_response, set_model=set_model,
    ))

    out_dir.mkdir(parents=True, exist_ok=True)
    stats = {m: model_stats(records, m) for m in args.models}
    econ = {m: economics(stats[m]["cost_usd_per_response_mean"], args.eur_per_usd) for m in args.models}
    report = render_report(stats, econ, {
        "mode": "live (real OpenAI calls)", "spent_usd": round(budget.spent, 6),
        "calls": budget.calls, "stop_reason": budget.stop_reason,
    })
    if notes:
        report += "\n## Notes\n\n" + "\n".join(f"- {n}" for n in notes) + "\n"
    (out_dir / "report.md").write_text(report, encoding="utf-8")
    metrics = [{k: v for k, v in r.__dict__.items() if k != "response"} for r in records]
    (out_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    write_blind_files(out_dir, records, args.seed)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
