# Email Auto Follow-up (IMAP/SMTP)

This tool sends a polite follow-up email if you haven't received a reply after N days (default: 3). It works with any IMAP/SMTP provider (Gmail, Outlook, etc.) and runs on Linux via cron or systemd.

How it works
- You send emails as usual and include a small subject token (default: "[FU]") in messages you want tracked.
- The script scans your Sent mailbox for those messages, tracks their Message-IDs in a local SQLite database, and checks your Inbox for replies.
- If no reply is detected after the configured number of days, it sends one follow-up email and stops (configurable).

Quick start
1) Prepare credentials
- Gmail: enable IMAP and create an App Password for SMTP/IMAP. Use the app password as EMAIL_PASSWORD.
- Outlook/Office365: ensure IMAP/SMTP is enabled and use an app password if required by your tenant.

2) Copy config and edit
```bash
cd /workspace/auto_followup
cp config.example.env .env
# Edit .env with your details
```

3) Customize your follow-up template (optional)
- Edit `templates/followup.txt` (placeholders: `{recipient_name}`, `{from_name}`, `{original_subject}`)

4) Dry-run
```bash
python3 auto_followup.py
```
- The default `.env` uses DRY_RUN=true, so no emails are sent. You'll see what would be sent.

5) Mark emails to track
- When composing an email you care about, include `[FU]` in the Subject (you can change the token in `.env`).
- Example subject: `Project update [FU]`

6) Schedule
- Cron example (every 30 minutes):
```bash
*/30 * * * * cd /workspace/auto_followup && /usr/bin/python3 auto_followup.py >> auto_followup.log 2>&1
```
- Or use systemd timers if you prefer.

Configuration (.env)
- EMAIL_USERNAME: IMAP/SMTP login username, usually your email address
- EMAIL_PASSWORD: IMAP/SMTP password or app password
- FROM_EMAIL: The From email address used to send follow-ups
- FROM_NAME: Optional display name used in From
- SMTP_HOST/SMTP_PORT/SMTP_STARTTLS: Outgoing SMTP settings
- IMAP_HOST/IMAP_PORT: Incoming IMAP settings
- IMAP_SENT_FOLDER: Your Sent folder name. Common examples:
  - Gmail: `[Gmail]/Sent Mail`
  - Outlook: `Sent Items`
  - Generic: `Sent`
- TRACK_SUBJECT_TOKEN: Subject marker to track (default `[FU]`)
- FOLLOWUP_AFTER_DAYS: Days to wait before following up (default `3`)
- MAX_FOLLOWUPS_PER_THREAD: Number of follow-ups to attempt (default `1`)
- SQLITE_DB_PATH: Where to store the local state DB (default `./auto_followup.sqlite3`)
- TEMPLATE_PATH: Path to the follow-up text template (default `./templates/followup.txt`)
- TIMEZONE: Display timezone if needed (currently informational)
- DRY_RUN: `true` or `false`

Template variables
- `{recipient_name}`: Name derived from the first recipient
- `{from_name}`: Your configured display name or email address
- `{original_subject}`: Original subject without reply prefixes

Notes and tips
- Replies are detected by searching for your original Message-ID in `In-Reply-To` or `References` headers.
- If your provider uses a different Sent folder path, set `IMAP_SENT_FOLDER` correctly, or the script won't discover messages to track.
- To track older messages, keep the token in the subject and the script will index them (scans the last 30 days by default).
- The subject token is only a marker for tracking. It will still appear in the recipient's subject unless you remove it yourself before sending.

Security
- Prefer provider-specific app passwords over your main password.
- Keep `.env` out of version control.

Troubleshooting
- If nothing is indexed, verify `IMAP_SENT_FOLDER` and the subject token are correct.
- If follow-ups are not sent, check that DRY_RUN is `false`, credentials are valid, and SMTP settings are correct.
- Check `auto_followup.log` if running via cron.