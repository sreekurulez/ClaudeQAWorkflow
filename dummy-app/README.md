# Dummy App

A minimal, in-memory test fixture application for exercising the QA workflow multi-agent system. 
This application provides specific UI flows and intentional flaws (e.g. missing `data-testid` attributes, race conditions, seeded functional bugs) to validate the agent framework's ability to locate elements, heal broken selectors, and identify application bugs.

## Setup

Ensure you have Node.js installed, then install the dependencies:

```bash
npm install
```

## Running the App

Start the application server. It will listen on port `4000` by default.

```bash
npm start
```

### Running with Seeded Bugs

To test the "flake quarantine" and "healer circuit breaker" behaviors in the agent workflow, you can start the application with a seeded functional bug. This intentionally introduces a bug into the item filter/search logic (dropping the last matching result) that cannot be fixed by the AI updating CSS selectors.

```bash
SEED_BUG=1 npm start
```

## Tests

The application is meant to be tested by the agents, but it also provides a `test:e2e` script for local Playwright runs.

```bash
npm run test:e2e
```

## Integration Contract

- Runs on `http://localhost:4000`
- Provides `POST /api/__test__/reset` for isolated state reset between E2E test runs.
