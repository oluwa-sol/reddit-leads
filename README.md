# Reddit Leads

Checks 16 subreddits every 2 hours for posts under 6 hours old where someone asks for help with automation, follow-ups, CRM, invoices or admin, and sends them to Discord.

- **EMAILABLE**: the poster shared their own website or business link. Email that business's public contact, mention the post in line one.
- **REPLY ONLY**: anonymous. Reply in the thread or skip. Never look anonymous posters up elsewhere.
- Freight and logistics posts are excluded (Komtora non-solicit).

## Setup

1. Create a Reddit app at https://www.reddit.com/prefs/apps (type: script). Note the client ID and secret.
2. Add GitHub secrets: `DISCORD_WEBHOOK_URL`, `REDDIT_CLIENT_ID`, `REDDIT_CLIENT_SECRET`.
3. Run the workflow once by hand (Actions, Reddit Leads, Run workflow).

Local test: `python leads.py --dry-run` (needs the two Reddit variables set; Reddit blocks anonymous requests).

Edit `SUBREDDITS`, `INTENT` and `TOPIC` in `leads.py` to tune what gets flagged.
