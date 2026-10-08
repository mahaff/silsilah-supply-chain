# Silsilah

Agentic Supply Chain Intelligence & Governance Platform

Silsilah is a local practice system for looking at one fictional supply chain at a time. MVP 1 lets you choose Saudi Arabia or Pakistan, loads that region's synthetic data into its own SQLite file, and shows suppliers, products, inventory, purchase orders, shipments, and a few metrics.

The numbers come from the database and from short Python rules. No language model is connected. The app does not buy anything, pay anyone, or contact a supplier.

This is not legal advice, and it does not certify compliance. No regulatory text is included.

## What MVP 1 shows

- A region switch for Saudi Arabia (`ksa`) and Pakistan (`pakistan`)
- One fictional organization and one fictional supply chain in each region
- Separate SQLite databases
- Six metrics, each labeled as a database fact or a deterministic rule
- A governance panel with zero regulatory references
- A reasoning panel that says no language model is connected

The future hierarchy is already in the data model:

```text
Region -> Organization -> Supply Chain -> suppliers, products, stock, orders, shipments
```

MVP 1 stores one organization and one supply chain in each regional file. The screen names all three levels so the shape is visible.

## Synthetic datasets

Company names are fictional. Do not treat them as real businesses.

| | Saudi Arabia | Pakistan |
| --- | --- | --- |
| Organization | Wadi Demo Distributors | Ravi Demo Distributors |
| Supply chain | Riyadh-Jeddah Staples Chain | Karachi-Lahore Staples Chain |
| Currency | SAR, stored in halalas | PKR, stored in paisas |
| Suppliers | 4 | 4 |
| Products | 6 | 6 |
| Open purchase orders | 3 | 2 |
| Shipments in transit | 1 | 0 |
| Delayed shipments | 1 | 2 |
| Stock lines below reorder point | 2 | 3 |

Low stock means on-hand quantity is **lower than** the reorder point. An equal quantity is not low.

Saudi Arabia lows: Riyadh rice (15 on hand, reorder 30) and Riyadh carton boxes (10 on hand, reorder 25).

Pakistan lows: Karachi bottled water (20 / 50), Karachi detergent (12 / 20), and Lahore USB cables (8 / 10).

Prices on order lines are integers of minor units. One SAR is 100 halalas. One PKR is 100 paisas. The database does not use floating-point money.

## Risk register (MVP 2)

The register is a set of Python rules on the synthetic rows. It does not predict a delay, a stockout date, or a supplier reliability score. Severity is the word `attention` or `watch`, not a probability.

The synthetic dataset as-of date is **2026-10-01** for both regions. Overdue checks compare a shipment's expected arrival (`eta`) with that date. The screen labels it as the dataset date. It is not today's date, and the rules do not read the computer clock.

| Rule | Severity | Why |
| --- | --- | --- |
| `inventory.below_reorder` | attention | On-hand quantity is already under the reorder point. |
| `shipment.delayed_status` | attention | The shipment row already says delayed. |
| `shipment.eta_passed_not_delivered` | attention | Expected arrival is before 2026-10-01 and the shipment is not delivered. |
| `supplier.delayed_shipment_present` | watch | At least one linked shipment is delayed. One delay is not a reliability rating. |
| `supplier.order_share` | watch | At least three purchase orders and at least half of the chain. This sample does not meet the rule. |

Days of coverage use `demand_history` only when a product at a warehouse has at least two synthetic issue periods. Otherwise the risk says demand history is insufficient and does not give a stockout date. Riyadh rice and Karachi bottled water have two periods. The other low-stock lines do not.

A review status stays with the stable risk id. It is kept on the next calculation only when the evidence fingerprint still matches. If the evidence changes after a reviewed or resolved status, the risk is reopened and marked for re-review. The evidence is not deleted. Status changes are audit rows with actor `local_user`.

Supplier indicators always show delayed-shipment counts and order share. A delay proportion is shown only when that supplier has at least three linked shipments.

## Predictive risk (MVP 3)

Predictive risk is a separate section. It does not replace the risk register, and it does not read the register's rules.

The risk register applies deterministic rules to known conditions. Predictive risk is a synthetic ML demonstration. It estimates whether a departed shipment arrives after its expected date. Arrival on the expected date counts as not late. The estimate is based on synthetic historical data. It is not a real-world forecast, not a recorded fact, and not a compliance or legal determination.

Each region has its own `shipment_history` table, loaded from `regions/<region>/seed/shipment_history.csv`. Those 48 completed trips are not inserted into `shipments`. Metrics, delayed-shipment counts, supplier indicators, risk ids, reviews, and audits ignore that table.

The history is a demonstration set for checking the pipeline. Saudi Arabia trips depart from 2026-04-06. Pakistan trips depart from 2026-04-09. Both files end in early September 2026, on or before the dataset as-of date 2026-10-01. Late and on-time outcomes were assigned so that every supplier has both outcomes and the later trips still contain both outcomes. Lead time, city, and promised transit length are not a formula that produces the label.

Each file has 48 trips, 23 of them late. A trip needs three earlier trips from the same supplier before it can be used. That excludes 12 trips. The scoring model is fit on the remaining 36 (17 late, 19 on time).

Features known at departure:

| Feature | Meaning |
| --- | --- |
| Stored lead time | The supplier's lead time in the supplier table |
| Planned transit length | Expected arrival minus departure, in days |
| Same city | Whether origin and destination match |
| Earlier late share | Share of that supplier's earlier completed trips that arrived after the expected date |
| Earlier trip count | How many earlier trips that share is based on |

The earlier-trip features use `departed_on` strictly before the trip being described. They do not use that trip's arrival, lateness, or status, and they do not use a later trip.

The model is logistic regression in scikit-learn, with scaled features, `class_weight="balanced"`, and `random_state=42`. It is retrained in memory when the page loads. No model file is saved.

Evaluation on the screen is two separate reports:

- Primary: a chronological holdout. Earlier eligible trips train the evaluation model. Later eligible trips test it. On this demonstration file that is 27 training rows (13 late, 14 on time) and 9 test rows (4 late, 5 on time). If the later block did not contain at least two late and two on-time trips, the screen says the chronological holdout is not reported.
- Secondary: a stratified random split of 25 percent, also with `random_state=42`. This check is not time-ordered. A later training trip can include an earlier trip that landed in the test fold. Features for any one trip still use only earlier departures.

Both reports include accuracy, balanced accuracy, late precision, late recall, ROC AUC when both outcomes are in the test block, and the same metrics for a majority-class baseline. Those numbers describe this synthetic file. They are not a promise about real shipments. When the demonstration model's accuracy is below the majority-class baseline, the page says so.

On this file the chronological holdout does not support a forecast. Saudi Arabia accuracy is 0.44 against a majority-class baseline of 0.56. Pakistan accuracy is 0.67, with late recall of 0.25, against the same 0.56 baseline. The random-split numbers are higher for Saudi Arabia (accuracy 0.78) and level with the baseline for Pakistan (accuracy 0.56). The random split is the secondary check and is not time-ordered.

The page scores an operational shipment only when it is in transit and already has a departure date. A recorded delay or delivery is left to the risk register. A planned shipment with no departure date is not scored. If a region has no eligible shipment, the section says so. Pakistan's current operational file has no in-transit shipment, so it shows the model and the evaluations without a probability.

The three largest absolute contributions are shown as "increased the model estimate" or "decreased the model estimate". The wording does not say a supplier caused a delay.

## How the two regions stay separate

- `regions/ksa/` and `regions/pakistan/` each have their own config and CSV files.
- Seeding writes `data/ksa/war_room.sqlite` or `data/pakistan/war_room.sqlite`.
- The app opens only the file for the region you selected.
- On read, it checks that the file's stored region code matches the selection. A swapped file is refused.
- Queries filter on that file's supply chain id.

`data/` is gitignored. The CSV files are the source. Rebuild the databases whenever you want a clean copy.

## Governance

Each region has an empty `governance_references` table and a short note in `regions/<region>/governance/README.md`.

The table is ready for a later research pass that uses official government or regulator sources and records jurisdiction, authority, reference, requirement, applicability, source URL, date verified, implementation status, and a technical control id. MVP 1 does not fill that table and does not guess any legal requirement.

## Language model

`llm/null_provider.py` is the only provider. It returns a fixed note and does not read metric values into that note.

`get_provider()` always returns that null provider. `LLM_ENABLED` and `XAI_API_KEY` are ignored. No model SDK is installed. A later provider can implement `explain(facts)` in `llm/base.py` without changing how metrics are calculated.

## Run it on Windows

Use Python 3.12 and Node.js 22 LTS. Reflex builds its web page with Node, and the first run needs an internet connection to download those frontend tools. After that, the app and the databases stay on your machine.

Open PowerShell in this project folder. If activation is blocked, the execution-policy command below applies only to that window.

```powershell
py -0p
node -v

py -3.12 -m venv .venv
Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass
.\.venv\Scripts\Activate.ps1

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

Copy-Item .env.example .env
python -m persistence.seed
python -m pytest
reflex run
```

Stop `reflex run` before seeding again if Windows says the database file is locked. After this MVP, run `python -m persistence.seed` once so the risk tables, the dataset as-of date, and `shipment_history` exist. An older database file does not gain those tables by itself.

Then open [http://127.0.0.1:3217](http://127.0.0.1:3217).

The Reflex backend listens on port 8217. Those ports were chosen so they are less likely to clash with another app on ports 3000 or 8000. If either port is already in use, stop the other program and run `reflex run` again. Leave `.env` without a real API key.

On macOS or Linux, create the virtual environment the same way and activate it with `source .venv/bin/activate`. The `python` and `reflex` commands after activation are the same. There is no `Copy-Item`; use `cp .env.example .env`.

If you skip the seed command, the first page load creates a missing database from the CSV files. It does not rebuild a database that is already there. Run `python -m persistence.seed` when you want a clean reload.

## Tests

`python -m pytest` seeds temporary database files and checks:

- metric rules, including the low-stock comparison
- the Saudi Arabia and Pakistan counts above
- one organization and one supply chain per file
- an empty governance table
- the null provider does not repeat a calculated number
- a Pakistan file cannot be opened as Saudi Arabia
- history labels, prior-only features, chronological and random evaluations
- refusal when the history is too small, and a one-class chronological tail
- Saudi Arabia and Pakistan models stay on their own history
- a recorded delay is not given a probability
- MVP 2 risk ids and the six metrics stay the same after history is loaded

## Project layout

```text
app/                 Reflex pages and screen state
domain/              Models, evidence labels, metric rules, and risk rules
persistence/         Region config, SQLite schema, reads, and seeding
prediction/          Synthetic late-arrival features, model, and explanations
regions/ksa/         Saudi Arabia config, seed CSVs, governance notes
regions/pakistan/    Pakistan config, seed CSVs, governance notes
governance/          Status text for the panel
llm/                 Provider interface and the null provider
tests/               Isolation, seed, metric, risk, and prediction tests
data/                Generated SQLite files (not committed)
reflex.lock/         Frontend package list created by Reflex (kept)
```

The first `reflex run` also creates a `.web/` folder. That folder is generated output and is gitignored.

`agents/` and `simulation/` are still absent. Predictive risk lives in `prediction/` and does not add an agent.

## Decisions worth knowing

- **Region is a separate database.** Organization and supply chain are rows inside that database. That is the Region, then Organization, then Supply Chain hierarchy, with only one organization and one chain seeded.
- **Operational rows store `supply_chain_id`.** Queries filter on it so a second chain can be added later without mixing records.
- **Metrics live in `domain/metrics.py`.** The page displays them. It does not reimplement the comparisons.
- **A straight count is a database fact. A filtered count is a deterministic rule.**
- **Pandas loads and checks the CSV files.** The metric rules are ordinary Python so each comparison is easy to read.
- **The governance table is created and left empty.**
- **Order lines are in the database** even though the page shows order headers. The caption under the order table states how many lines were stored.

## Windows notes

- Use `py -3.12`, not the Microsoft Store stub that only opens the Store.
- PowerShell may refuse to run `Activate.ps1` until you set the process execution policy, as in the commands above.
- Install Node.js 22 before `reflex run`. Reflex asks for Node.js 20.19 or newer, and current Reflex also prints a notice if Node is older than 22.22. Node 22.14 still starts the app. The first run may also download Bun.
- Keep the project in a short local path such as `C:\dev\silsilah`, not in OneDrive, Desktop, or Documents. Those folders can lock SQLite and slow the Reflex frontend folder.
- Avoid spaces in the project path.
- Stop `reflex run` before running `python -m persistence.seed` if Windows reports that the database file is locked.
- Seed files are plain English ASCII so a console code page does not corrupt them.

## What is not installed

Plotly, LangGraph, a vector database, an xAI or other model SDK, Ollama, PostgreSQL, and Docker are not required. scikit-learn is installed for the synthetic late-arrival demonstration only. The null language-model provider is unchanged.

## What this version will not do

It will not place orders, send messages, approve an action, contact a supplier, recommend a purchase, simulate a recovery step, or describe a law. The late-arrival section is an estimate on synthetic history, not a real-world forecast, and it does not replace the risk register.
