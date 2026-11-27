# Test plan — Desk Shop feature-toggle experiment

Owner: @Liyun0011 (QA) · Reviewer: @cuhsuan · Issue: #15

This plan turns the manual tests from Assignment 10 into a checklist the team can re-run before the final demo on 2026-12-15. It also says how to check the experiment data after the pilot ends.

## When to run it

| When | What | Who |
|---|---|---|
| Every push and pull request | Automated tests and security checks in CI (`devsecops.yml`) | CI |
| After a pull request that changes `app/` is deployed | Smoke test: TC-01, TC-02, TC-09 | @Liyun0011 |
| 2026-12-09, after the experiment stops | Data checks: DC-01 to DC-04 | @Liyun0011 |
| 2026-12-10 to 12-14, before the rehearsal | Full regression: TC-01 to TC-12 | @Liyun0011 |
| 2026-12-15, right after the live demo | TC-08 again, so both toggles are back in their experiment state | @Liyun0011 |

## Rules for testing on production

- Announce in the team chat before changing any toggle, and again when done.
- Change toggles only in `/admin`. Never edit the database by hand.
- After testing, set both toggles back to **enabled, rollout 50**, then press **Reset** on each row so the `flags.json` defaults apply again.
- Test as an admin. Admin events are excluded from `/admin/metrics`, so test clicks and purchases do not change the experiment data.
- Do not change toggles during the data window (11/25 – 12/08) unless the test is needed. If you do, write the time in the chat so the data can be checked.

## Environment

| Item | Value |
|---|---|
| Production | https://desk-shop.onrender.com |
| Admin console | `/admin` (toggles, audit log), `/admin/metrics` (experiment numbers) |
| Test account | an admin account; the tester's own bucket is not used, states are forced with rollout 100 / 0 |
| Low-stock items | SKU-300, SKU-400, SKU-600, SKU-800 (stock ≤ 5) |

## Manual test cases

| ID | Type | Precondition | Steps | Expected | Automated test |
|---|---|---|---|---|---|
| TC-01 | Baseline | Defaults | Open `/admin` | Both toggles enabled, 50% | — |
| TC-02 | ON | Both rollout 100 | Reload the product list | "Buy now" on all 8 products; "Only N left" on the 4 low-stock items | `test_stock_badge_on_and_off` |
| TC-03 | OFF | `quick_buy` 0, `stock_badge` 100 | Reload | No "Buy now"; badges shown | `test_quick_buy_off_hides_button_and_refuses_crafted_post` |
| TC-04 | Security | As TC-03 | Send a crafted `POST /buy/SKU-300` with `source=list` from the browser console | 403 Forbidden | `test_quick_buy_off_hides_button_and_refuses_crafted_post` |
| TC-05 | OFF | `quick_buy` 100, `stock_badge` 0 | Reload | "Buy now" shown; no badges | `test_stock_badge_on_and_off` |
| TC-06 | Security (control) | As TC-05 | Same crafted POST | 200, lands on `/thanks/SKU-300` | `test_quick_buy_on_shows_button_and_buys_from_list` |
| TC-07 | Kill switch | Both rollout 100 | Untick enabled, press **Save** on each row, reload | State says KILLED; both features gone | `test_kill_switch_beats_everything` |
| TC-08 | Switch and restore | After TC-07 | Set enabled + 50, press **Reset** on each row, read the audit log | Every change is logged; no redeploy needed | `test_admin_switch_takes_effect_on_next_request_and_is_audited` |
| TC-09 | Access | Signed out (private window) | Open `/admin` | Redirect to `/login` | `test_pages_require_sign_in` |
| TC-10 | Access | Signed in as a customer | Open `/admin`, `/admin/events.csv`, `/admin/summary.csv` | 403 for each | `test_customer_cannot_open_admin` (an admin cannot test this by hand) |
| TC-11 | Admin console | A toggle is KILLED | Read the "You get" column | Says "off (killed)", not "on" | `test_admin_console_shows_killed_flag_as_off` |
| TC-12 | CI | Latest commit on `main` | Open the latest Actions run | All CI jobs green; all tests pass | the whole suite |

Lessons from Assignment 10 that apply here:

- Press **Save** on the row you changed, then check the State column. Ticking the box alone changes nothing.
- Chrome blocks pasting into the DevTools console until you type `allow pasting`.

## Data checks after the pilot (2026-12-09)

| ID | Check | Expected |
|---|---|---|
| DC-01 | Download `summary.csv` from `/admin/metrics` | 4 data rows: H1 on/off, H2 on/off |
| DC-02 | Compare each row with the tables on `/admin/metrics` | Same users, counts, rates and 95% intervals |
| DC-03 | Check the users column | Only the invited non-team users are counted; no admin |
| DC-04 | Read the audit log for 11/25 – 12/08 | No toggle change during the window, or each change is explained in the chat |

After the checks, apply the decision rule from Assignment 10 (Task 3): if the 95% intervals overlap, the result is inconclusive and is reported as observed.

## Reporting a defect

Open an issue with: steps, expected result, actual result, screenshot, and impact. Link it to the test case ID (for example "Found in TC-11"). After the fix is merged and deployed, re-run the test case and close the issue.
