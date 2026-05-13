# PROJECT_CONTEXT

Заповни цей файл перед початком роботи агента.

Якщо обов'язкові поля лишаються незаповненими, агент має
зупинитися до початку будь-якої задачі.

## 1. Stack

- Project name: `Deutsch Trainer Bot`
- Primary languages: `Not selected yet. Product vision defines a Telegram bot, but does not define implementation language.`
- Runtime / platform: `Telegram Bot platform; application runtime is not selected yet.`
- Main frameworks / libraries: `Not selected yet. Required integrations: Telegram Bot API, Quiz Bank API, payment/subscription provider.`
- Data stores: `Required by product vision, implementation not selected yet. Must persist users, training sessions, user answers, topic progress, mistakes, and subscriptions.`
- Default user-facing language: `German. All bot messages, buttons, results, progress, paywall copy, recommendations, and answer explanations must be German.`

## 2. Project structure

- Root entrypoints: `Not created yet. Future root entrypoint should start the Telegram bot.`
- Source directories: `Not created yet. Future source code should cover Telegram interface, training sessions, progress, mistakes, subscriptions, Quiz Bank API client, and admin metrics.`
- Test directories: `Not created yet.`
- Config / infra directories: `.agent/`
- Read-only or protected paths: `.agent/core/ unless the task explicitly changes the agent rule bundle.`

## 3. Key commands

| Purpose | Command | Notes |
|---|---|---|
| Test | `Not defined yet` | No implementation stack or test suite exists yet. |
| Lint | `Not defined yet` | Define after choosing implementation language and tooling. |
| Build | `Not defined yet` | Define after choosing implementation language and runtime. |
| Dev / Run | `Not defined yet` | Future command should run the Telegram bot locally. |

## 4. External dependencies

| System / service | Purpose | Access mode | Notes |
|---|---|---|---|
| Telegram Bot API | User-facing bot interface | API token / webhook or polling | Required for all bot flows. |
| Quiz Bank API | Source of quiz content | HTTP API client | Bot must not duplicate the question bank. |
| Payment / subscription provider | Plus and Pro subscriptions, one-time purchases | Provider API / webhooks | Exact provider is not selected yet. |
| Product analytics / admin metrics | Activation, retention, learning value, monetization metrics | Internal storage or analytics service | Exact implementation is not selected yet. |

## 5. Project constraints

- Protected paths: `.agent/core/ is normative; change only on explicit rule-bundle tasks. Do not modify unrelated root legacy normative files.`
- Secrets / credentials locations: `Not created yet. Future Telegram tokens, Quiz Bank API keys, payment credentials, and database credentials must stay outside committed files.`
- Deploy / production boundaries: `Not defined yet. No deploy or production action is allowed without an explicit user request.`
- Approval-required operations: `Choosing or changing the implementation stack, adding dependencies, adding migrations/schema, configuring payments, deploys, production changes, and git push.`
- Restricted hosts / environments: `Production Telegram bot, production Quiz Bank API, production payment provider, and production database. Exact hosts are not defined yet.`
- Project-specific forbidden actions: `Do not duplicate Quiz Bank content inside the bot. Do not show Ukrainian or English copy in the user-facing learning interface. Do not invent paid-plan behavior outside the product vision. Do not change product strategy without explicit request.`

## 6. Git settings

- Default / protected branch: `main`
- Branching strategy: `Work on feature branches for code changes; do not push directly to main.`
- Merge strategy: `Not selected yet. Ask before merge, squash, or rebase.`
- PR title format: `Conventional Commits style, for example docs: add product vision`
- PR requirements: `Describe scope, changed files, checks run, and unresolved risks.`
