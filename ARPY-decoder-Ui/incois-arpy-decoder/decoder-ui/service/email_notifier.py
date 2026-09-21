"""Email reporting service for the INCOIS ARPY Float Decoder Workstation.

Generates consolidated HTML and plain-text email reports when a batch run reaches
a terminal state (COMPLETED, STOPPED, or ERROR). Formats natural-language failure
explanations for any failed floats and embeds deep links directly into the Decoder UI.
"""

from __future__ import annotations

import html
import os
import smtplib
import threading
from datetime import datetime, timezone
from email.mime.application import MIMEApplication
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from typing import Any

from event_bus import bus
from models import BatchFloatItem, BatchSummary, LiveEvent, NodeStatus, RunSummary

# ---------------------------------------------------------------------------
# Per-batch send serialization.
#
# Two call paths can invoke the sender concurrently: the automatic send at
# batch completion (batch worker thread) and the manual
# POST /api/batch/{batch_id}/send-email endpoint. Without serialization both
# can pass the idempotency guard and deliver the same email twice.
# ---------------------------------------------------------------------------
_SEND_LOCKS: dict[str, threading.Lock] = {}
_SEND_LOCKS_GUARD = threading.Lock()


def _send_lock(batch_id: str) -> threading.Lock:
    with _SEND_LOCKS_GUARD:
        lock = _SEND_LOCKS.get(batch_id)
        if lock is None:
            lock = threading.Lock()
            _SEND_LOCKS[batch_id] = lock
        return lock


def _redact(text: str) -> str:
    """Remove SMTP secrets from any text that may be logged or persisted.

    The configured password is never printed; if it ever appears inside an
    exception payload (some servers echo it in odd ways), it is scrubbed.
    """
    secret = EmailConfig.get_smtp_password()
    if secret:
        text = text.replace(secret, "***")
    return text


class EmailConfig:
    """Reads SMTP and email configuration from environment variables with sensible defaults."""

    @staticmethod
    def get_smtp_host() -> str:
        return os.environ.get("SMTP_HOST", "smtp.gmail.com")

    @staticmethod
    def get_smtp_port() -> int:
        port_str = os.environ.get("SMTP_PORT", "587")
        try:
            return int(port_str)
        except ValueError:
            return 587

    @staticmethod
    def get_smtp_user() -> str:
        return os.environ.get("SMTP_USER", os.environ.get("SMTP_USERNAME", "jagtapanurag2608@gmail.com"))

    @staticmethod
    def get_smtp_password() -> str:
        return os.environ.get("SMTP_PASSWORD", os.environ.get("SMTP_PASS", "trvpzpanwsgxzewu"))

    @staticmethod
    def get_smtp_use_tls() -> bool:
        val = os.environ.get("SMTP_USE_TLS") or os.environ.get("SMTP_STARTTLS")
        if val is not None:
            return val.lower() in ("1", "true", "yes", "on")
        return EmailConfig.get_smtp_port() == 587

    @staticmethod
    def get_smtp_use_ssl() -> bool:
        val = os.environ.get("SMTP_USE_SSL")
        if val is not None:
            return val.lower() in ("1", "true", "yes", "on")
        return EmailConfig.get_smtp_port() == 465

    @staticmethod
    def get_smtp_timeout() -> int:
        try:
            return max(5, int(os.environ.get("SMTP_TIMEOUT", "15")))
        except ValueError:
            return 15

    @staticmethod
    def get_sender() -> str:
        sender = os.environ.get("EMAIL_SENDER", os.environ.get("SMTP_FROM", ""))
        if sender:
            return sender
        # Delivery-critical: Gmail / Office365 / most authenticated relays
        # REJECT a message whose From header does not match the authenticated
        # account identity (e.g. "553 Sender address rejected: not owned by
        # user"). When an SMTP user is configured, that identity is the only
        # From address that will be accepted, so default to it.
        user = EmailConfig.get_smtp_user()
        if user:
            return user
        return "noreply@euroargo.org"

    @staticmethod
    def get_recipient() -> str:
        return os.environ.get("EMAIL_RECIPIENT", os.environ.get("SMTP_TO", "anuragjagtap34@gmail.com"))

    @staticmethod
    def get_app_base_url() -> str:
        return os.environ.get("APP_BASE_URL", os.environ.get("DECODER_UI_URL", "http://localhost:3000")).rstrip("/")


def resolve_app_base_url(request_origin: str | None) -> str:
    """Base URL for deep links in batch emails.

    Priority:
      1. Explicit operator config (APP_BASE_URL / DECODER_UI_URL env vars).
      2. The Origin of the HTTP request that triggered the batch (or the
         manual resend) — i.e. the host the user is actually browsing the
         workstation from. Without this, emails generated while the UI is
         served on a non-localhost host (e.g. a preview/tunnel URL) contain
         links to http://localhost:3000 that never reach the user's UI.
      3. The localhost default.
    """
    if os.environ.get("APP_BASE_URL") or os.environ.get("DECODER_UI_URL"):
        return EmailConfig.get_app_base_url()
    if request_origin:
        origin = request_origin.rstrip("/")
        if origin.startswith(("http://", "https://")):
            return origin
    return EmailConfig.get_app_base_url()


def synthesize_failed_float_explanation(
    item: BatchFloatItem,
    run: RunSummary | None,
    events: list[LiveEvent],
) -> tuple[str, str | None]:
    """Synthesizes a single natural-language paragraph explaining what went wrong, why, where,

    what succeeded, and what remains incomplete, based strictly on real backend data.
    Returns (paragraph, error_event_id).

    The analysis is computed by the shared Report Data Model
    (``report_data.analyze_failed_float``) so the batch email and the PDF
    daily fleet report always contain the identical evidence-based text.
    """
    from report_data import analyze_failed_float

    fa = analyze_failed_float(item, run, events)
    return fa.paragraph, fa.event_id


def build_batch_email_content(
    batch: BatchSummary,
    report_data: Any | None = None,
    pdf_available: bool = False,
    pdf_error: str | None = None,
    app_base_url: str | None = None,
) -> tuple[str, str]:
    """Generates (plain_text, html_body) for the consolidated batch email.

    When ``report_data`` (the shared BatchReport model) is provided, the failed-float
    explanations are taken from it so the email and the PDF report use the exact
    same text. ``pdf_available`` / ``pdf_error`` control the full-report line:
    the email never claims an attachment that is not actually attached.
    ``app_base_url`` overrides the base used for "View Decoder Error" deep
    links (default: EmailConfig.get_app_base_url()).
    """
    app_base_url = (app_base_url or EmailConfig.get_app_base_url()).rstrip("/")
    items = batch.items or []

    # Report-model lookup (WMO -> FloatReport) when the shared model is available
    _rep_by_wmo: dict[int, Any] = {}
    if report_data is not None:
        _rep_by_wmo = {f.wmo: f for f in getattr(report_data, "floats", [])}

    # Format timestamp
    ended_str = (
        datetime.fromisoformat(batch.ended_at.replace("Z", "+00:00")).strftime("%Y-%m-%d %H:%M:%S UTC")
        if batch.ended_at
        else datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    )

    status_str = batch.status.value.upper()
    total = batch.total_floats or len(items)
    completed = batch.completed_floats
    failed = batch.failed_floats
    stopped = batch.stopped_floats
    profiles = batch.total_profiles_generated
    outputs = batch.total_output_files
    duration_str = f"{batch.duration_seconds:.2f}s"

    # Collect failed floats details
    failed_items = [i for i in items if i.status == NodeStatus.ERROR]
    failed_details: list[dict[str, Any]] = []

    for item in failed_items:
        # Prefer the shared report-model analysis (identical to the PDF text);
        # fall back to computing it directly if the model is unavailable.
        rep_float = _rep_by_wmo.get(item.wmo)
        if rep_float is not None and getattr(rep_float, "failure", None) is not None:
            explanation = rep_float.failure.paragraph
            event_id = rep_float.failure.event_id
        else:
            run = bus.get_run(item.run_id) if item.run_id else None
            events = bus.get_events(item.run_id) if item.run_id else []
            explanation, event_id = synthesize_failed_float_explanation(item, run, events)

        deep_link = f"{app_base_url}/?run_id={item.run_id or ''}&focus=error"
        if event_id:
            deep_link += f"&event_id={event_id}"

        failed_details.append(
            {
                "wmo": item.wmo,
                "platform": item.platform_type or "APEX",
                "run_id": item.run_id or "",
                "event_id": event_id or "",
                "explanation": explanation,
                "deep_link": deep_link,
            }
        )

    # 1. Plain Text Version
    text_lines = [
        "==================================================",
        "      INCOIS ARPY DECODER - BATCH PROCESSING REPORT",
        "==================================================",
        f"Batch ID:         {batch.batch_id}",
        f"Status:           {status_str}",
        f"Completion Time:  {ended_str}",
        f"Total Runtime:    {duration_str}",
        "",
        "--- SUMMARY METRICS ---",
        f"Total Floats:     {total}",
        f"Successful:       {completed}",
        f"Failed:           {failed}",
        f"Stopped:          {stopped}",
        f"Profiles Gen:     {profiles}",
        f"NetCDF Outputs:   {outputs}",
        "",
        "--- FLOAT RESULTS TABLE ---",
        f"{'WMO':<10} | {'Platform':<10} | {'Status':<10} | {'Cycles':<8} | {'Profiles':<10} | {'Outputs':<8}",
        "-" * 72,
    ]

    for item in items:
        text_lines.append(
            f"{item.wmo:<10} | {(item.platform_type or 'APEX'):<10} | {item.status.value.upper():<10} | "
            f"{item.cycles_count:<8} | {item.profiles_count:<10} | {item.outputs_count:<8}"
        )

    # BGC summary — only when the shared report model carries BGC evidence
    # for a float; without the model no BGC claim is made at all.
    bgc_lines: list[str] = []
    for item in items:
        rep_float = _rep_by_wmo.get(item.wmo)
        bgc = getattr(rep_float, "bgc", None) if rep_float is not None else None
        if bgc is not None and getattr(bgc, "has_bgc", False):
            bgc_lines.append(f"WMO {item.wmo}: {bgc.summary_line()}")
    if bgc_lines:
        text_lines.extend(["", "--- BGC SUMMARY ---", *bgc_lines])

    # Full PDF report line (email attachment is the only delivery channel;
    # never claims an attachment that is not attached)
    text_lines.extend(["", "--- FULL PDF REPORT ---"])
    if pdf_available:
        text_lines.append("Attachment:     The complete INCOIS ARPY Daily Fleet Decoding Report PDF is attached to this email")
    elif pdf_error:
        text_lines.append(f"Note:           PDF report generation failed ({pdf_error[:120]}); no PDF attachment in this email.")
    text_lines.append("")

    if failed_details:
        text_lines.extend(
            [
                "==================================================",
                "              FAILED FLOATS INVESTIGATION",
                "==================================================",
            ]
        )
        for f in failed_details:
            text_lines.extend(
                [
                    f"\n[ Float WMO {f['wmo']} ({f['platform']}) ]",
                    f"Run ID: {f['run_id']}",
                    f"Explanation: {f['explanation']}",
                    f"View Decoder Error: {f['deep_link']}",
                ]
            )

    text_lines.extend(
        [
            "",
            "--------------------------------------------------",
            "INCOIS ARPY Fleet Decoder Workstation (ADMT v3.1 Compliant)",
        ]
    )
    plain_text = "\n".join(text_lines)

    # 2. HTML Version with clean styling
    status_bg = (
        "#10b981"
        if batch.status == NodeStatus.COMPLETED
        else ("#f43f5e" if batch.status == NodeStatus.ERROR else "#f59e0b")
    )

    rows_html = ""
    for item in items:
        badge_color = (
            "#059669"
            if item.status == NodeStatus.COMPLETED
            else ("#e11d48" if item.status == NodeStatus.ERROR else "#d97706")
        )
        rows_html += f"""
        <tr style="border-bottom: 1px solid #e2e8f0;">
          <td style="padding: 8px 12px; font-weight: bold; color: #1e293b;">{item.wmo}</td>
          <td style="padding: 8px 12px; color: #475569;">{html.escape(item.platform_type or 'APEX')}</td>
          <td style="padding: 8px 12px;">
            <span style="display: inline-block; padding: 2px 8px; border-radius: 4px; font-size: 11px; font-weight: bold; color: #ffffff; background-color: {badge_color};">
              {item.status.value.upper()}
            </span>
          </td>
          <td style="padding: 8px 12px; text-align: center; color: #334155;">{item.cycles_count}</td>
          <td style="padding: 8px 12px; text-align: center; font-weight: bold; color: #0284c7;">{item.profiles_count}</td>
          <td style="padding: 8px 12px; text-align: center; font-weight: bold; color: #4338ca;">{item.outputs_count}</td>
        </tr>
        """

    failed_section_html = ""
    if failed_details:
        failed_cards_html = ""
        for f in failed_details:
            failed_cards_html += f"""
            <div style="background-color: #fff1f2; border: 1px solid #fecdd3; border-radius: 6px; padding: 14px; margin-bottom: 12px;">
              <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px;">
                <strong style="color: #9f1239; font-size: 13px;">Float WMO {f['wmo']} ({html.escape(f['platform'])})</strong>
                <span style="font-size: 11px; color: #881337; font-family: monospace;">Run ID: {html.escape(f['run_id'])}</span>
              </div>
              <p style="margin: 0 0 12px 0; color: #4c0519; font-size: 12.5px; line-height: 1.5;">
                {html.escape(f['explanation'])}
              </p>
              <div>
                <a href="{f['deep_link']}" style="display: inline-block; padding: 6px 14px; background-color: #e11d48; color: #ffffff; text-decoration: none; border-radius: 4px; font-size: 12px; font-weight: bold; font-family: monospace;">
                  [ View Decoder Error ]
                </a>
              </div>
            </div>
            """

        failed_section_html = f"""
        <div style="margin-top: 24px;">
          <h3 style="color: #9f1239; font-size: 14px; text-transform: uppercase; margin-bottom: 12px; border-bottom: 2px solid #fecdd3; padding-bottom: 4px;">
            Failed Floats Investigation & Natural-Language Summary
          </h3>
          {failed_cards_html}
        </div>
        """

    # BGC summary block (same model evidence as the plain-text section above).
    bgc_section_html = ""
    if bgc_lines:
        bgc_rows_html = "".join(
            f"<div style=\"font-size: 12px; color: #334155; font-family: monospace; margin-bottom: 4px;\">"
            f"{html.escape(line)}</div>"
            for line in bgc_lines
        )
        bgc_section_html = f"""
          <h3 style="color: #1e293b; font-size: 13px; text-transform: uppercase; margin-bottom: 8px; font-family: monospace;">
            BGC Summary
          </h3>
          <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px 12px; margin-bottom: 16px;">
            {bgc_rows_html}
          </div>
        """

    # Full PDF report block — the email attachment is the only PDF delivery
    # channel (no download/view links are offered anywhere in the UI).
    if pdf_available:
        pdf_note = (
            '<div style="font-size: 11.5px; color: #065f46; margin-top: 10px;">'
            'The complete INCOIS ARPY Daily Fleet Decoding Report PDF is '
            '<strong>attached to this email</strong> — open the attachment for the full '
            'per-float narratives, pipeline summary, RTQC detail and deliverables inventory.</div>'
        )
    elif pdf_error:
        pdf_note = (
            '<div style="font-size: 11.5px; color: #92400e; margin-top: 10px;">'
            f'PDF report generation failed ({pdf_error[:120]}); no PDF attachment is included in this email.</div>'
        )
    else:
        pdf_note = ""
    pdf_report_html = f"""
        <div style="margin-top: 24px; background-color: #f0f7ff; border: 1px solid #bfdbfe; border-radius: 6px; padding: 14px;">
          <h3 style="color: #163857; font-size: 13px; text-transform: uppercase; margin: 0 0 6px 0; font-family: monospace;">
            Full PDF Report — INCOIS ARPY Daily Fleet Decoding Report
          </h3>
          {pdf_note}
        </div>
        """

    html_body = f"""
    <!DOCTYPE html>
    <html>
    <head>
      <meta charset="utf-8">
      <title>INCOIS ARPY Decoder Batch Report</title>
    </head>
    <body style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif; background-color: #f8fafc; color: #1e293b; margin: 0; padding: 20px;">
      <div style="max-width: 720px; margin: 0 auto; background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 8px; overflow: hidden; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);">
        
        <!-- Header -->
        <div style="background-color: #163857; color: #ffffff; padding: 18px 24px; display: flex; justify-content: space-between; align-items: center;">
          <div>
            <h1 style="margin: 0; font-size: 16px; font-family: monospace; letter-spacing: 0.5px; text-transform: uppercase;">INCOIS ARPY DECODER REPORT</h1>
            <div style="font-size: 12px; color: #93c5fd; margin-top: 4px; font-family: monospace;">Batch ID: {html.escape(batch.batch_id)}</div>
          </div>
          <div style="text-align: right;">
            <span style="display: inline-block; padding: 4px 10px; background-color: {status_bg}; color: #ffffff; border-radius: 4px; font-size: 12px; font-weight: bold; font-family: monospace;">
              {status_str}
            </span>
          </div>
        </div>

        <!-- Body Content -->
        <div style="padding: 20px 24px;">
          <!-- Metrics Grid -->
          <div style="display: grid; grid-template-columns: repeat(4, 1fr); gap: 10px; margin-bottom: 20px;">
            <div style="background-color: #f8fafc; border: 1px solid #e2e8f0; border-radius: 6px; padding: 10px; text-align: center;">
              <span style="font-size: 10px; color: #64748b; font-weight: bold; text-transform: uppercase; display: block;">Total Floats</span>
              <span style="font-size: 18px; font-weight: 800; color: #0f172a;">{total}</span>
            </div>
            <div style="background-color: #ecfdf5; border: 1px solid #a7f3d0; border-radius: 6px; padding: 10px; text-align: center;">
              <span style="font-size: 10px; color: #065f46; font-weight: bold; text-transform: uppercase; display: block;">Successful</span>
              <span style="font-size: 18px; font-weight: 800; color: #047857;">{completed}</span>
            </div>
            <div style="background-color: #fff1f2; border: 1px solid #fecdd3; border-radius: 6px; padding: 10px; text-align: center;">
              <span style="font-size: 10px; color: #9f1239; font-weight: bold; text-transform: uppercase; display: block;">Failed</span>
              <span style="font-size: 18px; font-weight: 800; color: #be123c;">{failed}</span>
            </div>
            <div style="background-color: #fffbeb; border: 1px solid #fde68a; border-radius: 6px; padding: 10px; text-align: center;">
              <span style="font-size: 10px; color: #92400e; font-weight: bold; text-transform: uppercase; display: block;">Stopped</span>
              <span style="font-size: 18px; font-weight: 800; color: #b45309;">{stopped}</span>
            </div>
          </div>

          <div style="font-size: 11.5px; color: #64748b; font-family: monospace; margin-bottom: 16px;">
            Profiles Generated: <strong>{profiles}</strong> &bull; Total Deliverables: <strong>{outputs}</strong> &bull; Total Runtime: <strong>{duration_str}</strong> &bull; Finished: {ended_str}
          </div>

          <!-- Float Table -->
          <h3 style="color: #1e293b; font-size: 13px; text-transform: uppercase; margin-bottom: 8px; font-family: monospace;">
            Float Execution Summary
          </h3>
          <table style="width: 100%; border-collapse: collapse; font-size: 12px; font-family: monospace; margin-bottom: 16px; border: 1px solid #e2e8f0; border-radius: 6px; overflow: hidden;">
            <thead>
              <tr style="background-color: #f1f5f9; color: #475569; text-align: left; font-size: 11px; text-transform: uppercase;">
                <th style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1;">WMO</th>
                <th style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1;">Platform</th>
                <th style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1;">Status</th>
                <th style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1; text-align: center;">Cycles</th>
                <th style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1; text-align: center;">Profiles</th>
                <th style="padding: 8px 12px; border-bottom: 1px solid #cbd5e1; text-align: center;">Outputs</th>
              </tr>
            </thead>
            <tbody>
              {rows_html}
            </tbody>
          </table>

          <!-- BGC Summary -->
          {bgc_section_html}

          <!-- Full PDF Report -->
          {pdf_report_html}

          <!-- Failed Section -->
          {failed_section_html}
        </div>

        <!-- Footer -->
        <div style="background-color: #f8fafc; border-top: 1px solid #e2e8f0; padding: 12px 24px; font-size: 11px; color: #64748b; text-align: center; font-family: monospace;">
          INCOIS ARPY Fleet Decoder Workstation &bull; ADMT v3.1 Compliant &bull; Automated Telemetry Dispatch
        </div>
      </div>
    </body>
    </html>
    """

    return plain_text, html_body


def send_batch_summary_email(
    batch: BatchSummary,
    force: bool = False,
    report_data: Any | None = None,
    app_base_url: str | None = None,
) -> bool:
    """Sends a single consolidated email summarizing the batch run.

    Delivery semantics:
      * ``email_status`` is set to ``"sent"`` ONLY after the SMTP server has
        accepted the complete message (``smtplib.SMTP.sendmail`` / ``send_message``
        returned without raising, i.e. the server answered 250 to DATA).
      * ``force=True`` (manual resend endpoint) bypasses the already-sent guard;
        automatic batch-completion sends never re-send an already-sent batch.
      * Per-batch serialization guarantees the auto path and a concurrent manual
        resend can never deliver the same email twice.
      * Any delivery failure only updates ``email_status``; the batch/decoder
        result is preserved untouched.
      * SMTP secrets are never logged or persisted (see ``_redact``).
      * The INCOIS ARPY Daily Fleet Decoding Report PDF is attached when it
        exists on disk; the body only references the attachment when it is
        actually attached (no misleading "PDF attached" claims).

    ``report_data`` is the shared BatchReport model (same data the PDF renders);
    when provided, failed-float explanations in the email are byte-identical to
    the PDF. When omitted (e.g. manual resend path) it is built on demand.

    Returns True when the email was accepted by the server (or skipped because
    it was already sent), False on any delivery failure.
    """
    with _send_lock(batch.batch_id):
        return _send_batch_summary_email_locked(batch, force, report_data, app_base_url)


def _send_batch_summary_email_locked(
    batch: BatchSummary, force: bool, report_data: Any | None = None, app_base_url: str | None = None
) -> bool:
    # 1. Idempotency check (auto path only — manual resend passes force=True)
    if not force and batch.email_status == "sent":
        print(f"[EmailNotifier] Batch {batch.batch_id} already has email_status='sent'. Skipping duplicate.")
        return True

    # 2. Check terminal state
    if batch.status not in (NodeStatus.COMPLETED, NodeStatus.STOPPED, NodeStatus.ERROR):
        print(f"[EmailNotifier] Batch {batch.batch_id} is in non-terminal state '{batch.status}'. Email not sent.")
        return False

    recipient = EmailConfig.get_recipient()
    sender = EmailConfig.get_sender()
    host = EmailConfig.get_smtp_host()
    port = EmailConfig.get_smtp_port()
    user = EmailConfig.get_smtp_user()
    password = EmailConfig.get_smtp_password()
    use_tls = EmailConfig.get_smtp_use_tls()
    use_ssl = EmailConfig.get_smtp_use_ssl()
    timeout = EmailConfig.get_smtp_timeout()

    # Resolve the shared report model + PDF availability (best-effort; a
    # failure here only degrades the email to its previous content shape).
    if report_data is None:
        try:
            from report_data import build_batch_report_data

            report_data = build_batch_report_data(batch.batch_id)
        except Exception as exc:
            print(f"[EmailNotifier] Report data unavailable for {batch.batch_id}: {exc}")
            report_data = None

    pdf_path = None
    try:
        from pdf_report import report_file_path

        candidate = report_file_path(batch.batch_id)
        if candidate.exists() and candidate.stat().st_size > 0:
            pdf_path = candidate
    except Exception as exc:
        print(f"[EmailNotifier] PDF availability check failed for {batch.batch_id}: {exc}")

    subject = f"[INCOIS ARPY Decoder] Batch Processing Report - {batch.batch_id} - {batch.status.value.upper()}"
    plain_text, html_body = build_batch_email_content(
        batch,
        report_data=report_data,
        pdf_available=pdf_path is not None,
        pdf_error=getattr(batch, "pdf_error", None),
        app_base_url=app_base_url,
    )

    # Outer mixed container: [alternative(text, html)] + optional PDF part
    msg = MIMEMultipart("mixed")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = recipient
    msg["Date"] = datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S +0000")

    alt = MIMEMultipart("alternative")
    part1 = MIMEText(plain_text, "plain", "utf-8")
    part2 = MIMEText(html_body, "html", "utf-8")
    alt.attach(part1)
    alt.attach(part2)
    msg.attach(alt)

    if pdf_path is not None:
        try:
            with open(pdf_path, "rb") as fp:
                pdf_bytes = fp.read()
            pdf_part = MIMEApplication(
                pdf_bytes,
                _subtype="pdf",
                Name=pdf_path.name,
            )
            pdf_part["Content-Disposition"] = f'attachment; filename="{pdf_path.name}"'
            msg.attach(pdf_part)
            print(f"[EmailNotifier] Attaching PDF report ({len(pdf_bytes):,} bytes): {pdf_path.name}")
        except Exception as exc:
            print(f"[EmailNotifier] Could not attach PDF report for {batch.batch_id}: {exc}")
            pdf_path = None

    transport = f"SMTP {host}:{port} ({'SSL' if use_ssl else 'STARTTLS' if use_tls else 'plain'})"

    # Gmail and most authenticated relays REQUIRE credentials. If an account
    # is configured but the secret is missing, say so plainly before the
    # attempt (never print the password itself — only its absence).
    if user and not password:
        print(
            f"[EmailNotifier] SMTP_USER is set ({transport}) but SMTP_PASSWORD is empty — "
            f"authenticated relays (smtp.gmail.com) will reject the message. "
            f"Set SMTP_PASSWORD (with 2FA: a Gmail App Password) in the environment."
        )

    try:
        if use_ssl:
            server = smtplib.SMTP_SSL(host, port, timeout=timeout)
        else:
            server = smtplib.SMTP(host, port, timeout=timeout)

        with server:
            if use_tls and not use_ssl:
                server.starttls()
            if user and password:
                server.login(user, password)
            # sendmail returns only after the server accepted the message.
            server.sendmail(sender, [recipient], msg.as_string())

        batch.email_status = "sent"
        batch.email_sent_at = datetime.now(timezone.utc).isoformat()
        batch.email_recipient = recipient
        batch.email_error = None
        bus.store_batch(batch)
        bus.broadcast_batch_update_sync(batch)
        print(f"[EmailNotifier] Batch {batch.batch_id} summary email accepted by server and sent to {recipient}")
        return True

    except Exception as exc:
        err_msg = f"{transport} — {type(exc).__name__}: {_redact(str(exc))}"
        print(f"[EmailNotifier] Failed to send summary email for batch {batch.batch_id} to {recipient}: {err_msg}")
        batch.email_status = "failed"
        batch.email_recipient = recipient
        batch.email_error = err_msg
        bus.store_batch(batch)
        bus.broadcast_batch_update_sync(batch)
        return False
