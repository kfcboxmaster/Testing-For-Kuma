# Uptime Kuma — QA Automation Suite
For the course of Quality Assurance at Astana IT University.

## Prerequisites

- Python 3.10+
- Node.js 18+ (to run Uptime Kuma locally)
- [Allure CLI](https://allurereport.org/docs/install/) (for reports — requires Java)

---

## 1. Start Uptime Kuma

```bash
cd uptime-kuma
npm install
npm run dev
```

The app will be available at **http://localhost:3001**.

**First run only:** open http://localhost:3001 in your browser and complete the setup wizard to create an admin account.

> The tests expect the credentials set in `tests/ui/conftest.py` (`ADMIN_USER` / `ADMIN_PASS`). Update those values to match your account if needed.

---

## 2. Install Python dependencies

```bash
pip install -r tests/requirements.txt
```

---

## 3. Install Playwright browser (one-time)

```bash
python -m playwright install chromium
```

---

## 4. Run the tests

```bash
# All UI tests
pytest tests/ui/ -v

# All tests (UI + REST API + Socket.IO)
pytest tests/ -v
```

Results are written to `allure-results/` automatically.

---

## 5. View the Allure report

```bash
allure serve allure-results
```

---

## Project structure

```
tests/
├── conftest.py          # shared base_url fixture
├── pytest.ini           # allure output config
├── requirements.txt     # Python dependencies
├── rest_api/            # Member 1 — REST API tests (requests)
├── socket_api/          # Member 2 — Socket.IO API tests (python-socketio)
└── ui/                  # Member 3 — E2E browser tests (Playwright)
    ├── conftest.py      # login fixture + viewport/timeout setup
    ├── pages/           # Page Object Model classes
    └── test_*.py        # test files
```

---

## Tips

- Run a single test file: `pytest tests/ui/test_login.py -v`
- Run headed (see the browser): add `--headed` flag
- Slow down actions for debugging: add `--slowmo=800`
- Skip Allure output for quick local runs: add `-p no:allure`
