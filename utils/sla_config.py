"""Phase 5 (Module C): configurable SLA / staleness thresholds used to
flag overdue manual-review and outstanding verification work on the
officer dashboard.

IMPORTANT: these numbers are DEMONSTRATION DEFAULTS only. They are not
derived from any official AICTE/APH service-level commitment and are
not an officially established deadline of any kind. They exist purely
so the prototype can demonstrate an "overdue work" alert; change them
freely for demo purposes.
"""

# Days after which an unresolved "manual review required" verification
# request is flagged as overdue on the dashboard.
MANUAL_REVIEW_SLA_DAYS = 3

# Days after which a "source unavailable" verification request is
# flagged as overdue (i.e. no manual resolution recorded in that time).
SOURCE_UNAVAILABLE_SLA_DAYS = 5

# Days after which a verification request still sitting in the initial
# "pending" state is flagged as overdue.
VERIFICATION_PENDING_SLA_DAYS = 2