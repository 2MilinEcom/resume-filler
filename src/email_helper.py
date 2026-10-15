from __future__ import annotations

import email
import html
import imaplib
import os
import re
import smtplib
import time
import uuid
from dataclasses import dataclass
from email.message import EmailMessage
from email.utils import parseaddr
from pathlib import Path
from typing import Optional

try:
    from dotenv import load_dotenv
except Exception:
    load_dotenv = None

try:
    from src.answer_bank import find_saved_answer, save_answer
except Exception:
    find_saved_answer = None
    save_answer = None


ROOT = Path(__file__).resolve().parent.parent
ENV_PATH = ROOT / ".env"


@dataclass
class EmailConfig:
    bot_email: str
    app_password: str
    notify_email: str
    timeout_seconds: int = 600
    poll_seconds: int = 10


# ============================================================
# ENVIRONMENT
# ============================================================

def _load_environment() -> None:
    """
    Load .env if python-dotenv is installed.

    If it is not installed yet, use a tiny fallback parser so the bot still
    works after the file is created.
    """

    if load_dotenv is not None:
        load_dotenv(ENV_PATH)
        return

    if not ENV_PATH.exists():
        return

    try:
        for line in ENV_PATH.read_text().splitlines():
            line = line.strip()

            if not line:
                continue

            if line.startswith("#"):
                continue

            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")

            os.environ.setdefault(key, value)

    except Exception:
        pass


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)).strip())
    except Exception:
        return default


def get_email_config() -> Optional[EmailConfig]:
    _load_environment()

    bot_email = os.getenv("BOT_EMAIL", "").strip()
    app_password = (
        os.getenv("BOT_EMAIL_APP_PASSWORD", "")
        .replace(" ", "")
        .strip()
    )
    notify_email = os.getenv("NOTIFY_EMAIL", "").strip()

    if not bot_email or not app_password or not notify_email:
        return None

    return EmailConfig(
        bot_email=bot_email,
        app_password=app_password,
        notify_email=notify_email,
        timeout_seconds=_int_env(
            "EMAIL_REPLY_TIMEOUT_SECONDS",
            600,
        ),
        poll_seconds=_int_env(
            "EMAIL_REPLY_POLL_SECONDS",
            10,
        ),
    )


def email_is_configured() -> bool:
    return get_email_config() is not None


# ============================================================
# ANSWER BANK
# ============================================================

def _question_too_generic_for_answer_bank(question: str, options: list[str]) -> bool:
    """Avoid reusing/saving answers for unlabeled dropdowns.

    Handshake sometimes exposes dropdowns only as "Required dropdown question".
    Saving answers under that generic label caused unrelated future dropdowns to
    reuse stale values such as old graduation years, No/Yes, or demographic
    answers. Let the AI resolver decide these each time unless a real question
    label is available.
    """
    if not options:
        return False

    lower = " ".join(str(question or "").lower().split())
    generic = {
        "required dropdown question",
        "required radio question",
        "required screening question",
        "select one",
        "select",
        "required",
    }
    return lower in generic or not lower or len(lower) < 8


def _saved_answer_for_question(
    company: str,
    title: str,
    question: str,
    options: list[str],
) -> Optional[str]:
    if find_saved_answer is None:
        return None

    if _question_too_generic_for_answer_bank(question, options):
        return None

    try:
        answer = find_saved_answer(
            company=company,
            title=title,
            question=question,
            options=options,
        )
    except Exception as exc:
        print(f"  ⚠ Answer bank lookup failed: {exc}")
        return None

    if not answer:
        return None

    print(f"  ✓ Reusing saved answer-bank answer: {answer}")
    return answer


def _save_answer_for_question(
    company: str,
    title: str,
    question: str,
    answer: str,
    options: list[str],
    raw_reply: Optional[str],
    source: str,
) -> None:
    if save_answer is None:
        return

    if _question_too_generic_for_answer_bank(question, options):
        return

    try:
        save_answer(
            company=company,
            title=title,
            question=question,
            answer=answer,
            options=options,
            raw_reply=raw_reply,
            source=source,
        )
        print("  ✓ Saved answer to local answer bank")
    except Exception as exc:
        print(f"  ⚠ Could not save answer to answer bank: {exc}")


# ============================================================
# EMAIL BODY EXTRACTION
# ============================================================

def _plain_text_from_message(
    message: email.message.Message,
) -> str:
    parts: list[str] = []

    if message.is_multipart():
        for part in message.walk():
            content_type = part.get_content_type()
            disposition = str(
                part.get("Content-Disposition", "")
            ).lower()

            if "attachment" in disposition:
                continue

            if content_type not in {
                "text/plain",
                "text/html",
            }:
                continue

            try:
                payload = part.get_payload(
                    decode=True,
                )
                charset = (
                    part.get_content_charset()
                    or "utf-8"
                )
                text = (
                    payload.decode(
                        charset,
                        errors="replace",
                    )
                    if payload
                    else ""
                )
            except Exception:
                continue

            if content_type == "text/html":
                text = re.sub(
                    r"<br\s*/?>",
                    "\n",
                    text,
                    flags=re.I,
                )
                text = re.sub(
                    r"</p>",
                    "\n",
                    text,
                    flags=re.I,
                )
                text = re.sub(
                    r"<[^>]+>",
                    "",
                    text,
                )
                text = html.unescape(text)

            if text.strip():
                parts.append(text)

    else:
        try:
            payload = message.get_payload(
                decode=True,
            )
            charset = (
                message.get_content_charset()
                or "utf-8"
            )
            text = (
                payload.decode(
                    charset,
                    errors="replace",
                )
                if payload
                else ""
            )
            parts.append(text)

        except Exception:
            pass

    return "\n".join(parts)


# ============================================================
# REPLY CLEANING / PARSING
# ============================================================

def clean_reply_text(raw_text: str) -> str:
    """
    Keep the user's new reply and strip quoted email history/signatures.

    This is intentionally deterministic. It does not use AI.
    """

    if not raw_text:
        return ""

    text = (
        raw_text
        .replace("\r\n", "\n")
        .replace("\r", "\n")
        .replace("\u00a0", " ")
    )

    lines = text.split("\n")
    kept: list[str] = []

    quote_patterns = [
        r"^On .+ wrote:$",
        r"^On .+ at .+ wrote:$",
        r"^From:\s",
        r"^Sent:\s",
        r"^To:\s",
        r"^Subject:\s",
        r"^-{2,}\s*Original Message\s*-{2,}$",
        r"^-{2,}\s*Forwarded message\s*-{2,}$",
        r"^>+",
    ]

    for line in lines:
        stripped = line.strip()

        if any(
            re.search(
                pattern,
                stripped,
                flags=re.I,
            )
            for pattern in quote_patterns
        ):
            break

        if stripped == "--":
            break

        # Gmail mobile sometimes adds this below the real reply.
        if stripped.lower().startswith(
            "sent from my iphone"
        ):
            break

        kept.append(line)

    cleaned = "\n".join(kept).strip()
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)

    return cleaned.strip()


def first_meaningful_line(text: str) -> str:
    for line in text.splitlines():
        line = line.strip()

        if not line:
            continue

        return line

    return ""


def _strip_answer_prefix(text: str) -> str:
    """
    Handles replies like:

      Answer: 5
      Option 5
      My answer is No
      Reply: I have never worked at Robinhood
    """

    text = text.strip()

    prefixes = [
        r"^answer\s*:\s*",
        r"^reply\s*:\s*",
        r"^response\s*:\s*",
        r"^option\s*:\s*",
        r"^my answer is\s+",
        r"^i choose\s+",
        r"^i pick\s+",
        r"^select\s+",
    ]

    for pattern in prefixes:
        text = re.sub(
            pattern,
            "",
            text,
            flags=re.I,
        ).strip()

    return text


def _normalize_for_match(text: str) -> str:
    text = text.lower()
    text = text.replace("&", "and")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def _extract_leading_option_number(text: str) -> Optional[int]:
    """
    Accepts:

      5
      5.
      5)
      5 - I have never worked...
      option 5
      Option 5: ...
    """

    text = text.strip()

    match = re.match(
        r"^(?:option\s*)?(\d+)(?:\s|[.)\-:])?.*$",
        text,
        flags=re.I,
    )

    if not match:
        return None

    try:
        return int(match.group(1))
    except Exception:
        return None


def _reply_lines_to_try(cleaned: str) -> list[str]:
    """
    Try the first meaningful line first, then the full cleaned reply.

    This helps when Gmail includes extra spacing or signatures.
    """

    lines = [
        _strip_answer_prefix(line.strip())
        for line in cleaned.splitlines()
        if line.strip()
    ]

    candidates: list[str] = []

    for line in lines:
        if line and line not in candidates:
            candidates.append(line)

    full = _strip_answer_prefix(cleaned.strip())

    if full and full not in candidates:
        candidates.append(full)

    return candidates


def normalize_reply_to_option(
    reply: str | None,
    options: list[str],
) -> Optional[str]:
    """
    Match the user's email reply to an available option.

    Supported deterministic replies:

      5
      5.
      5 I have never worked at Robinhood
      Option 5
      Answer: 5
      I have never worked at Robinhood
      No
      Yes
      Skip

    Returns:
      - matching option text
      - cleaned free-text reply if no options were provided
      - None for Skip/no match
    """

    if not reply:
        return None

    cleaned = clean_reply_text(reply)

    if not cleaned:
        return None

    if cleaned.strip().lower() in {
        "skip",
        "manual",
        "manual review",
        "leave blank",
    }:
        return None

    if not options:
        return cleaned

    candidates = _reply_lines_to_try(cleaned)

    # Gmail signatures can appear under a one-word reply like "Skip".
    # Treat the first meaningful candidate as a skip/manual command even if
    # the full cleaned reply contains a signature block after it.
    skip_markers = {
        "skip",
        "manual",
        "manual review",
        "leave blank",
    }

    for candidate in candidates:
        if _normalize_for_match(candidate) in skip_markers:
            return None

    # --------------------------------------------------------
    # 1. Numeric option match.
    # --------------------------------------------------------

    for candidate in candidates:
        number = _extract_leading_option_number(
            candidate
        )

        if number is None:
            continue

        index = number - 1

        if 0 <= index < len(options):
            return options[index]

    # --------------------------------------------------------
    # 2. Exact normalized option match.
    # --------------------------------------------------------

    normalized_options = [
        (
            option,
            _normalize_for_match(option),
        )
        for option in options
    ]

    for candidate in candidates:
        normalized_candidate = _normalize_for_match(
            candidate
        )

        if not normalized_candidate:
            continue

        for option, normalized_option in normalized_options:
            if normalized_candidate == normalized_option:
                return option

    # --------------------------------------------------------
    # 3. Candidate contains option, or option contains candidate.
    #
    # This handles:
    #   "5 I have never worked at Robinhood"
    #   "I have never worked at Robinhood"
    #   "No, I have not"
    # --------------------------------------------------------

    for candidate in candidates:
        normalized_candidate = _normalize_for_match(
            candidate
        )

        if not normalized_candidate:
            continue

        for option, normalized_option in normalized_options:
            if not normalized_option:
                continue

            if normalized_option in normalized_candidate:
                return option

            if normalized_candidate in normalized_option:
                return option

    # --------------------------------------------------------
    # 4. Yes/No shorthand.
    # --------------------------------------------------------

    option_lookup = {
        _normalize_for_match(option): option
        for option in options
    }

    for candidate in candidates:
        normalized_candidate = _normalize_for_match(
            candidate
        )

        first_token = (
            normalized_candidate.split(" ")[0]
            if normalized_candidate
            else ""
        )

        if first_token in {
            "y",
            "yes",
        }:
            for key, option in option_lookup.items():
                if key in {
                    "yes",
                    "y",
                }:
                    return option

        if first_token in {
            "n",
            "no",
        }:
            for key, option in option_lookup.items():
                if key in {
                    "no",
                    "n",
                }:
                    return option

    return None


# ============================================================
# SENDING EMAIL
# ============================================================

def _send_email(
    config: EmailConfig,
    subject: str,
    body: str,
) -> None:
    message = EmailMessage()
    message["From"] = config.bot_email
    message["To"] = config.notify_email
    message["Reply-To"] = config.bot_email
    message["Subject"] = subject
    message.set_content(body)

    with smtplib.SMTP_SSL(
        "smtp.gmail.com",
        465,
    ) as smtp:
        smtp.login(
            config.bot_email,
            config.app_password,
        )
        smtp.send_message(message)


# ============================================================
# READING EMAIL
# ============================================================

def _open_inbox(
    config: EmailConfig,
) -> imaplib.IMAP4_SSL:
    mailbox = imaplib.IMAP4_SSL(
        "imap.gmail.com"
    )
    mailbox.login(
        config.bot_email,
        config.app_password,
    )
    mailbox.select("INBOX")
    return mailbox


def _search_reply_ids(
    mailbox: imaplib.IMAP4_SSL,
    question_id: str,
) -> list[bytes]:
    search_terms = [
        (
            "X-GM-RAW",
            f'"subject:RF-{question_id}"',
        ),
        (
            "SUBJECT",
            f'"RF-{question_id}"',
        ),
        (
            "SUBJECT",
            f'"[RF-{question_id}]"',
        ),
    ]

    for search_key, search_value in search_terms:
        try:
            status, data = mailbox.search(
                None,
                search_key,
                search_value,
            )

            if (
                status == "OK"
                and data
                and data[0]
            ):
                return data[0].split()

        except Exception:
            continue

    return []


def _fetch_message(
    mailbox: imaplib.IMAP4_SSL,
    message_id: bytes,
) -> Optional[email.message.Message]:
    try:
        status, data = mailbox.fetch(
            message_id,
            "(RFC822)",
        )

        if status != "OK":
            return None

        for item in data:
            if not isinstance(item, tuple):
                continue

            return email.message_from_bytes(
                item[1]
            )

    except Exception:
        return None

    return None


def wait_for_reply(
    question_id: str,
    config: EmailConfig,
) -> Optional[str]:
    deadline = time.time() + config.timeout_seconds

    while time.time() < deadline:
        mailbox: Optional[imaplib.IMAP4_SSL] = None

        try:
            mailbox = _open_inbox(config)
            message_ids = _search_reply_ids(
                mailbox,
                question_id,
            )

            # Newest messages usually have the highest id.
            for message_id in reversed(message_ids):
                message = _fetch_message(
                    mailbox,
                    message_id,
                )

                if message is None:
                    continue

                from_email = parseaddr(
                    message.get("From", "")
                )[1].lower()

                # Avoid processing weird self-copies.
                if (
                    from_email
                    == config.bot_email.lower()
                ):
                    continue

                raw_text = _plain_text_from_message(
                    message
                )
                reply = clean_reply_text(
                    raw_text
                )

                if reply:
                    return reply

        except Exception as exc:
            print(
                f"  ⚠ Email reply check failed: {exc}"
            )

        finally:
            if mailbox is not None:
                try:
                    mailbox.logout()
                except Exception:
                    pass

        time.sleep(config.poll_seconds)

    return None


# ============================================================
# PUBLIC QUESTION API
# ============================================================

def ask_application_question(
    company: str,
    title: str,
    question: str,
    options: Optional[list[str]] = None,
) -> Optional[str]:
    """
    Send an application question to the user and wait for a reply.

    Returns:
      - matched option text for option-based questions
      - raw cleaned reply text for open-ended questions
      - None on Skip/no reply/config failure
    """

    options = options or []

    saved_answer = _saved_answer_for_question(
        company=company,
        title=title,
        question=question,
        options=options,
    )

    if saved_answer:
        return saved_answer

    config = get_email_config()

    if config is None:
        print(
            "  ⚠ Email is not configured. "
            "Falling back to Terminal input."
        )

        print(
            f"\nQUESTION from {company} — {title}"
        )
        print(question)

        if options:
            print("\nOptions:")
            for index, option in enumerate(
                options,
                start=1,
            ):
                print(f"  {index}. {option}")

        answer = input(
            "\nReply here, or type Skip: "
        ).strip()

        normalized_answer = normalize_reply_to_option(
            answer,
            options,
        )

        if normalized_answer:
            _save_answer_for_question(
                company=company,
                title=title,
                question=question,
                answer=normalized_answer,
                options=options,
                raw_reply=answer,
                source="terminal",
            )

        return normalized_answer

    question_id = uuid.uuid4().hex[:8].upper()
    subject = (
        f"Resume Filler Question [RF-{question_id}]"
    )

    if options:
        option_lines = [
            f"{index}. {option}"
            for index, option in enumerate(
                options,
                start=1,
            )
        ]

        option_block = (
            "\nReply with one of these options, "
            "or reply Skip:\n"
            + "\n".join(option_lines)
            + "\n\n"
            "Examples that work:\n"
            "  1\n"
            "  1. First option text\n"
            "  Option 1\n"
            "  First option text"
        )

    else:
        option_block = (
            "\nReply with the exact text to enter, "
            "or reply Skip."
        )

    body = (
        "Resume Filler needs your answer before it can continue.\n\n"
        f"Company: {company}\n"
        f"Job: {title}\n\n"
        "Question:\n"
        f"{question}\n"
        f"{option_block}\n\n"
        f"Question ID: RF-{question_id}\n\n"
        "The bot will wait for your reply and then continue."
    )

    try:
        _send_email(
            config,
            subject,
            body,
        )

    except Exception as exc:
        print(
            f"  ⚠ Could not send email question: {exc}"
        )
        return None

    print(
        f"  ✉ Emailed question to {config.notify_email}"
    )
    print(
        f"  Waiting up to "
        f"{config.timeout_seconds // 60} "
        "minutes for reply..."
    )

    reply = wait_for_reply(
        question_id,
        config,
    )

    if not reply:
        print(
            "  ⚠ No email reply received before timeout"
        )
        return None

    if options:
        matched = normalize_reply_to_option(
            reply,
            options,
        )

        if matched:
            print(
                f"  ✓ Email reply matched option: {matched}"
            )
            _save_answer_for_question(
                company=company,
                title=title,
                question=question,
                answer=matched,
                options=options,
                raw_reply=reply,
                source="email",
            )
            return matched

        print(
            "  ⚠ Email reply did not match any available option"
        )
        print(
            "  Reply received was:"
        )
        print(
            f"    {clean_reply_text(reply)}"
        )
        return None

    cleaned = clean_reply_text(reply)

    if cleaned.lower() in {
        "skip",
        "manual",
        "manual review",
        "leave blank",
    }:
        return None

    print("  ✓ Email reply received")
    _save_answer_for_question(
        company=company,
        title=title,
        question=question,
        answer=cleaned,
        options=options,
        raw_reply=reply,
        source="email",
    )
    return cleaned