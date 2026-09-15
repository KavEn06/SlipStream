# Verification and Model Promotion

## Repeatable Verification

Run migrations against the intended database:

```bash
python3 -m alembic upgrade head
python3 -m alembic check
python3 -m alembic downgrade base
python3 -m alembic upgrade head
```

Run backend correctness, integration, smoke capacity, and compile checks:

```bash
python3 -m unittest discover -s tests -v
python3 -m src.benchmarks.bulk_ingest \
  --rows 5000 --batch-size 500 --query-limit 100 \
  --report data/benchmarks/smoke.json
python3 -m compileall -q src tests migrations
```

Run frontend verification:

```bash
cd frontend
npm ci
npm test
npm run typecheck
npm run build
```

The routine CI workflow performs the migration round-trip and benchmark smoke on PostgreSQL. SQLite migration/repository/benchmark tests run inside the backend suite. CI deliberately does not run the 500,001-row default benchmark or any network import.

## What the Tests Protect

- Migration head/model parity, downgrade/re-upgrade, indexes, and milestone tables.
- Bounded set-based native/processed upserts, update idempotency, and feedback persistence.
- Assetto Corsa mappings, fallback timestamps, lap reconstruction, half-open assignment, artifact imports, and pinned count arithmetic.
- Database-backed processing, transactional processed writes, analysis persistence, filesystem compatibility, condition precedence, and health responses.
- Whole-lap/session grouped holdout and cross-validation with no sample-row leakage.
- Fixed-seed experiment reproducibility and interval-coverage metric calculation.
- Scenario section improvement plus whole-lap veto, driver-consistency perturbation scaling, nearby support, ensemble disagreement, uncertainty, and OOD fallback.
- Exactly seven default detectors; two research detectors require explicit enablement.
- API condition bounds, expected-band response shape, route registration, display-lap normalization, and fallback health contracts.
- Frontend expected-band interpolation and manual-condition request shaping.

## Promotion Criteria

There are two different meanings of promotion:

1. The current offline experiment runner selects the candidate with the lowest grouped-cross-validation composite score among candidates in that run. The composite includes profile error, section/lap pace error, faster-lap ranking, interval coverage, and event timing. The immutable holdout is evaluated and persisted but is not used to choose the winner.
2. Production release promotion is a separate review gate. A candidate must use immutable whole-lap/session groups with no leakage, reproduce at its declared seed and source revisions, report calibration/coverage, avoid material regressions on the untouched holdout, preserve deterministic detector authority, declare compatible features/grid dimensions, pass OOD/support abstention tests, and load from a checksum-verified artifact.

The current code does not automatically compare a new run with an incumbent against all production gates. A registry `champion` therefore means “selected within this declared offline run,” not proven causal benefit or automatic deployment approval.

## Interpretation and OOD Rules

Learned output is advisory. Measured telemetry, detector gates, and lap-time reconciliation remain authoritative. Expected bands represent observational associations in supported data, not causal prescriptions.

Scenario candidates are small, driver-consistency-scaled perturbations. They are rejected unless every configured family predicts section improvement, the whole-lap prediction does not regress, support is sufficient, families agree, and uncertainty is bounded. Wet conditions, high tyre wear, a cold track, or model-declared exclusions cause abstention and a deterministic conservative cue. Low-support or uncertain inputs also fall back or produce no learned detail. No path promises seconds saved.

Manual session conditions override source metadata. Missing values remain absent or enter declared model defaults/imputation; they are not measured observations. Health endpoints expose missing champions, artifacts, effective laps, and database availability as fallback reasons.

## Feedback Scope

Recommendation IDs, driver-baseline snapshots, versioned outcome/rating contracts, and database tables are compatibility scaffolds. Outcome association is not automated, the frontend has no rating workflow, ratings/outcomes are marked `training_eligible: false`, and there is no live or online retraining. Any future feedback-to-training path requires explicit comparability rules, consent/governance, leakage controls, offline evaluation, and the promotion gates above.
