from __future__ import annotations

import csv
from datetime import datetime
from pathlib import Path
from typing import Any


FIELDNAMES = [
    "status",
    "company",
    "title",
    "handshake_url",
    "application_url",
    "application_type",
    "submitted_at",
    "updated_at",
    "notes",
]


FINAL_STATUSES = {
    "submitted",
    "greenhouse_ready",
    "unsupported",
    "needs_manual",
    "submit_uncertain",
    "ready_manual",
    "failed",
}


def now_string() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def status_for_handshake_job(job: Any) -> tuple[str, str]:
    """
    Convert a HandshakeJob.application_type into a tracker status.
    """

    application_type = getattr(job, "application_type", "unknown")

    if application_type == "handshake_submitted":
        return "submitted", "native Handshake resume drop auto-submitted"

    if application_type == "handshake_resume_drop":
        return "ready_manual", "native Handshake resume drop ready for manual submit"

    if application_type == "handshake_submit_uncertain":
        return "submit_uncertain", "submit was clicked but confirmation was not detected"

    if application_type == "external_greenhouse":
        return "greenhouse_ready", "external Greenhouse application discovered"

    if application_type == "external_other":
        return "unsupported", "external ATS not supported yet"

    if application_type == "handshake_screening_required":
        return "needs_manual", "required Handshake screening still needs an answer"

    if application_type in {"unknown", "external_unknown"}:
        return "needs_manual", "application flow needs manual inspection"

    if application_type == "failed":
        return "failed", "job could not be processed"

    return "needs_manual", f"unrecognized application type: {application_type}"


class ApplicationTracker:
    def __init__(self, path: Path):
        self.path = path
        self.rows: list[dict[str, str]] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            self.rows = []
            return

        with self.path.open("r", newline="", encoding="utf-8") as file:
            reader = csv.DictReader(file)
            rows = []
            for row in reader:
                normalized = {field: row.get(field, "") for field in FIELDNAMES}
                rows.append(normalized)
            self.rows = rows

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)

        with self.path.open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDNAMES)
            writer.writeheader()
            writer.writerows(self.rows)

    def find_by_handshake_url(self, handshake_url: str) -> dict[str, str] | None:
        for row in self.rows:
            if row.get("handshake_url") == handshake_url:
                return row
        return None

    def known_urls(self) -> set[str]:
        return {
            row.get("handshake_url", "")
            for row in self.rows
            if row.get("handshake_url")
        }

    def count_status(self, status: str) -> int:
        return sum(1 for row in self.rows if row.get("status") == status)

    def count_submitted(self) -> int:
        return self.count_status("submitted")

    def should_skip(self, handshake_url: str, retry_known: bool = False) -> bool:
        if retry_known:
            return False

        row = self.find_by_handshake_url(handshake_url)

        if row is None:
            return False

        return row.get("status") in FINAL_STATUSES

    def upsert(
        self,
        *,
        status: str,
        company: str,
        title: str,
        handshake_url: str,
        application_url: str = "",
        application_type: str = "",
        notes: str = "",
    ) -> None:
        row = self.find_by_handshake_url(handshake_url)
        timestamp = now_string()

        if row is None:
            row = {field: "" for field in FIELDNAMES}
            row["handshake_url"] = handshake_url
            self.rows.append(row)

        row["status"] = status
        row["company"] = company
        row["title"] = title
        row["application_url"] = application_url
        row["application_type"] = application_type
        row["updated_at"] = timestamp
        row["notes"] = notes

        if status == "submitted" and not row.get("submitted_at"):
            row["submitted_at"] = timestamp

        self.save()

    def record_handshake_job(self, job: Any) -> tuple[str, str]:
        status, notes = status_for_handshake_job(job)

        self.upsert(
            status=status,
            company=getattr(job, "company", "") or "Unknown company",
            title=getattr(job, "title", "") or "Unknown job",
            handshake_url=getattr(job, "handshake_url", "") or "",
            application_url=getattr(job, "application_url", "") or "",
            application_type=getattr(job, "application_type", "") or "",
            notes=notes,
        )

        return status, notes

    def print_summary(self) -> None:
        counts: dict[str, int] = {}

        for row in self.rows:
            status = row.get("status") or "unknown"
            counts[status] = counts.get(status, 0) + 1

        print("\nTRACKER SUMMARY")
        print("-" * 68)

        if not counts:
            print("No tracked applications yet.")
            return

        for status in sorted(counts):
            print(f"{status:18} {counts[status]}")

        print(f"\nTracker file: {self.path}")
