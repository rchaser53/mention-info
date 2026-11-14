# Codex scheduled task

Create a **local recurring Codex schedule** for this repository. Run once per day (suggested: 09:00 Asia/Tokyo). Do not add a GitHub Actions cron.

Use this as the schedule prompt:

> Research publicly reported supply-chain attacks that were first disclosed or confirmed during the rolling 24 hours ending now. Search the web and verify candidate incidents against primary advisories or statements from affected maintainers, vendors, or incident responders. Use reputable independent reporting when primary information is incomplete. Exclude ordinary vulnerabilities, software outages, and unverified claims unless there is evidence of malicious compromise of a package, build system, dependency, source repository, signing/release process, or distribution channel.
>
> Set an exact UTC start and end time for the rolling 24-hour window. Check the incident/publication timestamps, not merely the search result's crawl date. If the date cannot be established, exclude the item and state that no verified incident was found for it. Deduplicate reports about the same incident.
>
> Assign exactly one severity to each verified incident: CRITICAL for broad or severe confirmed compromise of critical infrastructure or widespread active impact; HIGH for confirmed malicious distribution or compromise with significant user impact; MEDIUM for concrete but limited or still uncertain attack impact; LOW for limited impact, an unsuccessful attempt, or weak attack linkage. Explain the impact and confidence briefly and cite direct source URLs.
>
> Prepare a JSON object with `window_start`, `window_end`, and `findings`. Each finding must contain `title`, `severity` (LOW, MEDIUM, HIGH, or CRITICAL), `url` (best primary source URL), `published_at` (ISO 8601 when known), `source`, and a concise `summary` explaining what happened and the severity rationale. If no qualifying incidents are verified, use an empty findings array. Save the JSON to a temporary file, then run `mention-info-notify < report.json` from this repository. Do not print or expose `SLACK_WEBHOOK_URL`. The CLI sends Slack notifications only for HIGH and CRITICAL. Report the search window, incident count by severity, and the sources checked in the Codex run summary; if nothing qualifies, explicitly say no verified attacks were found.
