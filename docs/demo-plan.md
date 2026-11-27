# Final demo plan — 2026-12-15

Owner: @cuhsuan (PM) · Reviewer: @wagyboy · Issue: #16

The term-project demo shows how we tested two business hypotheses on Desk Shop with feature toggles, and what the pilot data says. This page fixes the data window in advance and says who presents what.

## Timeline (fixed in advance)

| Date | Milestone | Owner |
|---|---|---|
| 11/25 – 12/08 | Pilot data collection (fixed 14-day window, no early stop) | @Liyun0011 monitors `/admin/metrics`; @cuhsuan follows up with participants; @wagyboy keeps the site and CI healthy |
| 12/01 | Midpoint check: has every participant visited? Send reminders if not | @cuhsuan, @Liyun0011 |
| 12/09 | Stop the experiment; compute rates and 95% intervals; apply the decision rule | @Liyun0011 |
| 12/10 – 12/14 | Prepare slides, results and the live demo; one full rehearsal | All |
| 12/15 | Final presentation and demo; flag expiry for `quick_buy` and `stock_badge` | All; flag owner @Liyun0011 |

## Who presents what

| # | Part | Presenter | What to show |
|---|---|---|---|
| 1 | Goal and hypotheses | 陳昱瑄 (PM) | Project goal, the two toggles, H1 and H2 with their success metrics and guardrails |
| 2 | Live demo | 陳致安 (Developer) | GitHub sign-in; switch `quick_buy` and `stock_badge` ON/OFF in the admin console; a customer gets 403 on admin pages; the kill switch |
| 3 | Results | 劉芳瑜 (QA) | `/admin/metrics` and the per-variant summary CSV: rates, 95% intervals, and what the decision rule says |
| 4 | Lessons and next steps | 陳昱瑄 (PM) | What we learned about running the experiment; what happens to each flag after its expiry |

## Participants

Pilot with 3 non-team users invited by the PM via Instagram. They sign in with their own GitHub account and are not given the admin role, so their visits are counted. With this sample the 95% intervals are expected to overlap; the result is reported as observed, following the Task 3 decision rule (no forced rollout decision).

## Demo-day checklist

- [ ] Open https://desk-shop.onrender.com about 2 minutes before presenting (the Render service sleeps when idle; the first load takes about a minute)
- [ ] Presenter laptop signed in as admin
- [ ] After live switching, set both toggles back to their experiment state
- [ ] Backup slides with ON/OFF screenshots and the metrics, in case the site is down
- [ ] Rehearsal date agreed in the team chat

## Risks

| Risk | Mitigation |
|---|---|
| Sample too small to show a difference | Present it as a pilot; show observed numbers and intervals, not a verdict |
| Site is asleep or down during the demo | Warm it up beforehand; fall back to backup slides |
| Live switching leaves a toggle in the wrong state | Checklist item above; the flag owner confirms after the demo |
