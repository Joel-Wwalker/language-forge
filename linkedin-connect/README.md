# LinkedIn Connect

Semi-automated assistant for sending LinkedIn connection requests to
software-engineering recruiters in the NJ/NY area. Searches with your
filters, drafts personalized notes, tracks who you've contacted in a
local SQLite log, opens each profile in a real browser tab, and waits
for you to click Send yourself.

There's also an `auto` mode that clicks Send for you. It works but
**LinkedIn will restrict your account** if you use it long enough.
Don't unless you understand that.

## How LinkedIn handles automation

- Hard weekly cap on connection requests, ~100 (sometimes lowered to
  ~20 if their heuristics flag you).
- Headless browsers detected within minutes via fingerprint checks.
- Even successful automation routinely results in account
  restriction (loss of search, loss of profile visibility) within
  days to weeks.
- Going past the cap means the Connect button greys out across the
  whole site for the next reset interval.

This script's defaults assume you want to keep your account: 10
requests per day max, 30-90s randomized delays, semi-auto by default
(you click the actual Send). At 10/day you'll burn 70/week, well
under the cap and well under the heuristic-flag threshold.

## Install

```bash
cd linkedin-connect
python -m venv .venv
. .venv/Scripts/activate              # Windows
. .venv/bin/activate                  # macOS / Linux
pip install -r requirements.txt
playwright install chromium
```

## First run

1. Edit `config.toml`. The defaults target NYC + NJ recruiters but
   you should at minimum customize the message template and the
   geo_urns if you want a different metro area.
2. Run `python connect.py`. A Chromium window opens with LinkedIn's
   login page.
3. Log in manually. Solve any 2FA / captcha. **Never type your
   password into a terminal — this script only watches the browser
   you logged into yourself.**
4. Return to the terminal and press Enter. The script then walks
   the search results, opens each candidate's profile in a tab,
   pre-fills the personalized note, and waits for your decision.
5. For each candidate the script opens the profile, clicks Connect to
   open the modal, and waits. Default config is no-note mode: the
   modal sits at "Send without a note" and you click Send. The
   terminal then prompts:
   - `y` — you clicked Send in the browser; mark as sent.
   - `n` — you skipped this one (closed the modal, didn't send).
   - `s` — same as `n`, just shorter to type.
   - `q` — quit the run; pick up where you left off next time.

   To send notes instead, edit `config.toml` and set
   `[message] skip_note = false`.

Future runs: cookies persist in `.state/playwright_userdata/`. No
re-login needed unless LinkedIn invalidates your session.

## Useful commands

```bash
# Show the search URL the config will use without opening a browser:
python connect.py --dry-run

# Print contact-DB stats:
python connect.py --show-stats

# Selectors broke (LinkedIn's HTML changed); dump pages for debugging:
python connect.py --debug-dump
```

## Switching to `auto` mode

Edit `config.toml`:

```toml
[runtime]
mode = "auto"
```

Then run with `--i-understand-the-risks`:

```bash
python connect.py --i-understand-the-risks
```

The script will refuse without that flag. Account restriction in
auto mode is not a question of "if" but "how soon" — typically
1-3 weeks at the default 10/day cap, faster if you raise it.

## State files

Everything local lives under `.state/` (gitignored):

- `contacts.db` — SQLite log of every profile considered. Tracks
  status (sent / skipped / error) so you don't double-contact.
- `playwright_userdata/` — Playwright's persistent browser profile,
  including LinkedIn cookies. Treat as you would your browser
  profile: don't share, don't commit.
- `run.log` — append-only log of every action taken.

Reset everything: `rm -rf .state/`.

## When the selectors break

LinkedIn changes class names every few months. If `--show-stats`
shows lots of `error` rows or 0 results when there clearly are some,
the CSS selectors near the top of `connect.py` are stale. Run
`--debug-dump`, open the dumped HTML, find the new class names, and
update these constants:

- `RESULT_CARD_SELECTOR`
- `RESULT_NAME_LINK`
- `RESULT_HEADLINE`
- `RESULT_LOCATION`

Plus the Connect-button locators in `click_connect_and_compose_note`.

## Honest limitations

- LinkedIn search is rate-limited; ~3 pages of 10 results each per
  run is the safe ceiling. Want more? Run again tomorrow.
- The "company" field is best-effort scraped from the headline (`X
  at Y`); often blank when the recruiter's title doesn't follow that
  pattern. The message template's `{company}` falls back to "your
  company" in that case.
- Some recruiter profiles don't show a Connect button (they have
  Connect set to mutual-connections-only). Those land in the DB as
  `error` with reason "no Connect or More button visible" and you
  move on.
- Daily-cap tracking is local; if you connect via the LinkedIn web
  UI directly between runs, the local count diverges. Adjust
  `daily_max` accordingly.
