#!/usr/bin/env python3

import os
import sys
import imaplib
import smtplib
import sqlite3
import ssl
import email
import re
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime, formataddr, make_msgid
from pathlib import Path


# ---------------------------
# Configuration loading
# ---------------------------

DEFAULT_CONFIG = {
    "SMTP_HOST": "smtp.gmail.com",
    "SMTP_PORT": "587",
    "SMTP_STARTTLS": "true",
    "IMAP_HOST": "imap.gmail.com",
    "IMAP_PORT": "993",
    # For Gmail, the Sent folder is usually "[Gmail]/Sent Mail"
    "IMAP_SENT_FOLDER": "[Gmail]/Sent Mail",
    "FROM_NAME": "",
    "TRACK_SUBJECT_TOKEN": "[FU]",
    "FOLLOWUP_AFTER_DAYS": "3",
    "MAX_FOLLOWUPS_PER_THREAD": "1",
    "SQLITE_DB_PATH": "./auto_followup.sqlite3",
    "TEMPLATE_PATH": "./templates/followup.txt",
    "TIMEZONE": "UTC",
    "DRY_RUN": "true",
}


def load_env_from_file(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    with dotenv_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if (value.startswith("\"") and value.endswith("\"")) or (
                value.startswith("'") and value.endswith("'")
            ):
                value = value[1:-1]
            os.environ.setdefault(key, value)


def get_config() -> dict:
    # Load .env in current directory if present
    load_env_from_file(Path(".env"))

    config = dict(DEFAULT_CONFIG)
    for key in list(DEFAULT_CONFIG.keys()) + [
        "EMAIL_USERNAME",
        "EMAIL_PASSWORD",
        "FROM_EMAIL",
    ]:
        val = os.environ.get(key)
        if val is not None:
            config[key] = val
    return config


# ---------------------------
# Utilities
# ---------------------------


def parse_bool(value: str) -> bool:
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def get_local_tz(tz_name: str):
    try:
        import zoneinfo  # Python 3.9+

        return zoneinfo.ZoneInfo(tz_name)
    except Exception:
        return timezone.utc


def ensure_parent_dir(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def decode_mime_header(raw_header) -> str:
    if not raw_header:
        return ""
    try:
        return str(make_header(decode_header(raw_header)))
    except Exception:
        return raw_header if isinstance(raw_header, str) else str(raw_header)


# ---------------------------
# Database layer (sqlite)
# ---------------------------


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS threads (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT UNIQUE NOT NULL,
    subject TEXT,
    recipients TEXT,
    date_sent_utc TEXT NOT NULL,
    followup_sent INTEGER NOT NULL DEFAULT 0,
    reply_detected INTEGER NOT NULL DEFAULT 0,
    followups_sent_count INTEGER NOT NULL DEFAULT 0
);
"""


class StateStore:
    def __init__(self, db_path: Path):
        ensure_parent_dir(db_path)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute(SCHEMA_SQL)
        self.conn.commit()

    def add_thread_if_missing(self, message_id: str, subject: str, recipients: str, date_sent_utc: datetime) -> None:
        self.conn.execute(
            """
            INSERT OR IGNORE INTO threads(message_id, subject, recipients, date_sent_utc)
            VALUES (?, ?, ?, ?)
            """,
            (message_id, subject, recipients, date_sent_utc.replace(tzinfo=timezone.utc).isoformat()),
        )
        self.conn.commit()

    def mark_reply_detected(self, message_id: str) -> None:
        self.conn.execute(
            "UPDATE threads SET reply_detected = 1 WHERE message_id = ?",
            (message_id,),
        )
        self.conn.commit()

    def mark_followup_sent(self, message_id: str) -> None:
        self.conn.execute(
            "UPDATE threads SET followup_sent = 1, followups_sent_count = followups_sent_count + 1 WHERE message_id = ?",
            (message_id,),
        )
        self.conn.commit()

    def get_pending_threads(self):
        cur = self.conn.execute(
            "SELECT message_id, subject, recipients, date_sent_utc, followup_sent, reply_detected, followups_sent_count FROM threads"
        )
        rows = cur.fetchall()
        results = []
        for row in rows:
            results.append(
                {
                    "message_id": row[0],
                    "subject": row[1] or "",
                    "recipients": row[2] or "",
                    "date_sent_utc": datetime.fromisoformat(row[3]).replace(tzinfo=timezone.utc),
                    "followup_sent": bool(row[4]),
                    "reply_detected": bool(row[5]),
                    "followups_sent_count": int(row[6] or 0),
                }
            )
        return results


# ---------------------------
# IMAP helpers
# ---------------------------


class ImapClient:
    def __init__(self, host: str, port: int, username: str, password: str):
        self.host = host
        self.port = port
        self.username = username
        self.password = password
        self.conn = None

    def __enter__(self):
        return self

    def connect(self):
        self.conn = imaplib.IMAP4_SSL(self.host, self.port)
        typ, data = self.conn.login(self.username, self.password)
        if typ != "OK":
            raise RuntimeError(f"IMAP login failed: {data}")

    def select_mailbox(self, mailbox: str = "INBOX"):
        typ, _ = self.conn.select(mailbox)
        if typ != "OK":
            raise RuntimeError(f"Failed to select mailbox {mailbox}")

    def search(self, *criteria) -> list:
        # criteria example: ("HEADER", "Message-ID", "<...>")
        typ, data = self.conn.search(None, *criteria)
        if typ != "OK":
            return []
        # data is a list with a single bytes object of space-separated ids
        if not data or not data[0]:
            return []
        ids = data[0].split()
        return [msg_id.decode("utf-8") for msg_id in ids]

    def fetch_message(self, msg_id: str) -> email.message.Message:
        typ, data = self.conn.fetch(msg_id, "(RFC822)")
        if typ != "OK" or not data or not data[0]:
            raise RuntimeError(f"Failed to fetch message id {msg_id}")
        raw = data[0][1]
        return email.message_from_bytes(raw)

    def logout(self):
        try:
            self.conn.logout()
        except Exception:
            pass


# ---------------------------
# SMTP helper
# ---------------------------


class SmtpClient:
    def __init__(self, host: str, port: int, starttls: bool, username: str, password: str):
        self.host = host
        self.port = port
        self.starttls = starttls
        self.username = username
        self.password = password
        self.server = None

    def connect(self):
        self.server = smtplib.SMTP(self.host, self.port, timeout=30)
        self.server.ehlo()
        if self.starttls:
            context = ssl.create_default_context()
            self.server.starttls(context=context)
            self.server.ehlo()
        if self.username:
            self.server.login(self.username, self.password)

    def send_message(self, message: EmailMessage):
        self.server.send_message(message)

    def quit(self):
        try:
            self.server.quit()
        except Exception:
            pass


# ---------------------------
# Core logic
# ---------------------------


def extract_text_body(msg: email.message.Message) -> str:
    if msg.is_multipart():
        for part in msg.walk():
            content_type = part.get_content_type()
            disp = part.get("Content-Disposition", "").lower()
            if content_type == "text/plain" and "attachment" not in disp:
                try:
                    return part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", errors="replace")
                except Exception:
                    continue
    else:
        if msg.get_content_type() == "text/plain":
            try:
                return msg.get_payload(decode=True).decode(msg.get_content_charset() or "utf-8", errors="replace")
            except Exception:
                return msg.get_payload()
    return ""


def normalize_subject(subject: str) -> str:
    subject = subject.strip()
    # Remove common reply prefixes for matching
    subject = re.sub(r"^(re|fw|fwd):\s*", "", subject, flags=re.IGNORECASE)
    return subject


def find_new_tracked_threads(imap: ImapClient, sent_folder: str, subject_token: str, state: StateStore) -> int:
    imap.select_mailbox(sent_folder)
    # Search for recent messages with the token in Subject
    # Using SINCE to limit scanning window (last 30 days)
    since_date = (datetime.utcnow() - timedelta(days=30)).strftime("%d-%b-%Y")
    try:
        ids = imap.search("SINCE", since_date, "SUBJECT", f'"{subject_token}"')
    except Exception:
        ids = imap.search("ALL")
    added = 0
    for msg_id in ids:
        msg = imap.fetch_message(msg_id)
        raw_subject = msg.get("Subject", "")
        subject = decode_mime_header(raw_subject)
        if subject_token.lower() not in subject.lower():
            continue
        raw_message_id = msg.get("Message-ID")
        if not raw_message_id:
            # Skip messages without a message-id
            continue
        message_id_clean = raw_message_id.strip()

        # Recipients: To + Cc
        recipients = []
        for hdr in ("To", "Cc"):
            if msg.get(hdr):
                recipients.append(msg.get(hdr))
        recipients_str = ", ".join(filter(None, recipients))

        # Date
        date_hdr = msg.get("Date")
        try:
            date_dt = parsedate_to_datetime(date_hdr)
            if date_dt.tzinfo is None:
                date_dt = date_dt.replace(tzinfo=timezone.utc)
            date_dt_utc = date_dt.astimezone(timezone.utc)
        except Exception:
            date_dt_utc = datetime.utcnow().replace(tzinfo=timezone.utc)

        state.add_thread_if_missing(message_id_clean, subject, recipients_str, date_dt_utc)
        added += 1
    return added


def detect_replies(imap: ImapClient, state: StateStore) -> int:
    imap.select_mailbox("INBOX")
    updated = 0
    for t in state.get_pending_threads():
        if t["reply_detected"]:
            continue
        # Search for In-Reply-To header matching original message-id
        try:
            ids = imap.search("HEADER", "In-Reply-To", t["message_id"])
        except Exception:
            ids = []
        if ids:
            state.mark_reply_detected(t["message_id"])
            updated += 1
            continue
        # Fallback: search in References header
        try:
            ids = imap.search("HEADER", "References", t["message_id"])
        except Exception:
            ids = []
        if ids:
            state.mark_reply_detected(t["message_id"])
            updated += 1
    return updated


def load_template(template_path: Path) -> str:
    if not template_path.exists():
        # Default template
        return (
            "Hi {recipient_name},\n\n"
            "Just checking back on this. Did you have a chance to review my note below?\n\n"
            "Thanks,\n{from_name}"
        )
    return template_path.read_text(encoding="utf-8")


def parse_recipients(recipients_str: str) -> list:
    # Very simple parse – rely on email.utils.getaddresses via email.message parsing
    from email.utils import getaddresses

    addresses = getaddresses([recipients_str])
    return [(name, addr) for name, addr in addresses if addr]


def build_followup_message(
    from_name: str,
    from_email: str,
    to_addresses: list,
    original_subject: str,
    original_message_id: str,
    body_template: str,
) -> EmailMessage:
    msg = EmailMessage()
    msg["Subject"] = f"Re: {original_subject}"
    msg["From"] = formataddr((from_name, from_email)) if from_name else from_email
    msg["To"] = ", ".join([formataddr((n, a)) if n else a for n, a in to_addresses])
    msg["In-Reply-To"] = original_message_id
    msg["References"] = original_message_id

    # Personalize body per the first recipient for simplicity
    recipient_name = to_addresses[0][0] if to_addresses else "there"
    if not recipient_name:
        recipient_name = to_addresses[0][1].split("@")[0] if to_addresses else "there"

    body = body_template.format(
        recipient_name=recipient_name,
        from_name=from_name or from_email,
        original_subject=original_subject,
    )
    msg.set_content(body)
    return msg


def send_due_followups(
    smtp: SmtpClient,
    state: StateStore,
    from_name: str,
    from_email: str,
    days_after: int,
    max_followups: int,
    template_text: str,
    dry_run: bool,
) -> int:
    now_utc = datetime.utcnow().replace(tzinfo=timezone.utc)
    sent = 0
    for t in state.get_pending_threads():
        if t["reply_detected"]:
            continue
        if t["followups_sent_count"] >= max_followups:
            continue
        age_days = (now_utc - t["date_sent_utc"]).days
        if age_days < days_after:
            continue
        # Build and send follow-up
        to_list = parse_recipients(t["recipients"]) or []
        if not to_list:
            continue
        message = build_followup_message(
            from_name=from_name,
            from_email=from_email,
            to_addresses=to_list,
            original_subject=normalize_subject(t["subject"]),
            original_message_id=t["message_id"],
            body_template=template_text,
        )
        if dry_run:
            print(f"[DRY-RUN] Would send follow-up to: {message['To']} | subj: {message['Subject']}")
        else:
            smtp.send_message(message)
            print(f"Sent follow-up to: {message['To']} | subj: {message['Subject']}")
        state.mark_followup_sent(t["message_id"])
        sent += 1
    return sent


# ---------------------------
# Main entry
# ---------------------------


def main(argv=None) -> int:
    cfg = get_config()

    required = ["EMAIL_USERNAME", "EMAIL_PASSWORD", "FROM_EMAIL"]
    missing = [k for k in required if not cfg.get(k)]
    if missing:
        print(f"Missing required config: {', '.join(missing)}", file=sys.stderr)
        return 2

    smtp_host = cfg.get("SMTP_HOST")
    smtp_port = int(cfg.get("SMTP_PORT", "587"))
    smtp_starttls = parse_bool(cfg.get("SMTP_STARTTLS", "true"))

    imap_host = cfg.get("IMAP_HOST")
    imap_port = int(cfg.get("IMAP_PORT", "993"))
    sent_folder = cfg.get("IMAP_SENT_FOLDER")

    from_email = cfg.get("FROM_EMAIL")
    from_name = cfg.get("FROM_NAME", "")

    subject_token = cfg.get("TRACK_SUBJECT_TOKEN", "[FU]")
    days_after = int(cfg.get("FOLLOWUP_AFTER_DAYS", "3"))
    max_followups = int(cfg.get("MAX_FOLLOWUPS_PER_THREAD", "1"))
    db_path = Path(cfg.get("SQLITE_DB_PATH", "./auto_followup.sqlite3")).resolve()
    template_path = Path(cfg.get("TEMPLATE_PATH", "./templates/followup.txt")).resolve()
    dry_run = parse_bool(cfg.get("DRY_RUN", "true"))

    # Prepare state and clients
    state = StateStore(db_path)

    # IMAP scan: discover new threads and detect replies
    imap_client = ImapClient(imap_host, imap_port, cfg.get("EMAIL_USERNAME"), cfg.get("EMAIL_PASSWORD"))
    imap_client.connect()
    try:
        added = find_new_tracked_threads(imap_client, sent_folder, subject_token, state)
        if added:
            print(f"Indexed {added} tracked messages from Sent.")
        updated = detect_replies(imap_client, state)
        if updated:
            print(f"Updated {updated} threads as replied.")
    finally:
        imap_client.logout()

    # Send due follow-ups
    template_text = load_template(template_path)
    smtp_client = SmtpClient(smtp_host, smtp_port, smtp_starttls, cfg.get("EMAIL_USERNAME"), cfg.get("EMAIL_PASSWORD"))
    smtp_client.connect()
    try:
        sent = send_due_followups(
            smtp_client,
            state,
            from_name,
            from_email,
            days_after,
            max_followups,
            template_text,
            dry_run,
        )
        print(f"Follow-ups processed: {sent}")
    finally:
        smtp_client.quit()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())