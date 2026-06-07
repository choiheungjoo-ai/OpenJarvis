"""Tool approval policy: resolution and risk-based defaults.

Decision order (most specific first):

    1. (tool, persona, user)   exact row
    2. (tool, persona, NULL)   persona-wide
    3. (tool, NULL,    user)   user-wide
    4. (tool, NULL,    NULL)   tool-wide
    5. risk-based default in code  (no row matched)

The risk default is fail-safe: anything that can change the world
(risk >= WRITE_LOCAL) requires approval unless a row explicitly relaxes it.

This module decides *what* the policy says (auto_allow / require_approval /
always_deny). The Step 2.6 approval channel handles the prompt for the
``require_approval`` case. ``always_deny`` short-circuits the channel
entirely.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.tool_policy import (
    DECISION_ALWAYS_DENY,
    DECISION_AUTO_ALLOW,
    DECISION_REQUIRE_APPROVAL,
    ToolPolicy,
)
from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult

# Risk levels at or above this need approval by default (step 5 fallback).
_APPROVAL_THRESHOLD = RiskLevel.WRITE_LOCAL


def default_decision(risk: RiskLevel) -> str:
    """Risk-based fallback used when no DB row matches.

    risk 0 (SAFE), 1 (READ_LOCAL)            -> auto_allow
    risk 2 (WRITE_LOCAL) and above           -> require_approval
    """
    if RiskLevel(risk) >= _APPROVAL_THRESHOLD:
        return DECISION_REQUIRE_APPROVAL
    return DECISION_AUTO_ALLOW


# Specificity score for a matched row. Higher wins. A row matches only if
# each non-NULL field equals the request; NULL fields are wildcards.
def _match_score(policy: ToolPolicy, persona_id: str, user_id: str) -> int | None:
    if policy.persona_id is not None and policy.persona_id != persona_id:
        return None
    if policy.user_id is not None and policy.user_id != user_id:
        return None
    score = 0
    if policy.persona_id is not None:
        score += 2  # persona match more specific than user match
    if policy.user_id is not None:
        score += 1
    return score


@dataclass(frozen=True)
class PolicyDecision:
    """Result of resolving policy for one (tool, persona, user)."""

    decision: str  # auto_allow | require_approval | always_deny
    source: str  # "db" or "risk_default"
    policy_id: int | None = None


def resolve_policy(
    session: Session, tool: Tool, context: ToolContext
) -> PolicyDecision:
    """Resolve the policy decision for ``tool`` in this context.

    Loads candidate rows for the tool, picks the most specific match, and
    falls back to the risk-based default when nothing matches.
    """
    rows = (
        session.execute(select(ToolPolicy).where(ToolPolicy.tool_name == tool.name))
        .scalars()
        .all()
    )

    best: ToolPolicy | None = None
    best_score = -1
    for row in rows:
        score = _match_score(row, context.persona_id, context.user_id)
        if score is not None and score > best_score:
            best, best_score = row, score

    if best is not None:
        return PolicyDecision(
            decision=best.decision, source="db", policy_id=best.policy_id
        )

    return PolicyDecision(decision=default_decision(tool.risk), source="risk_default")


def _summarize_args(args: object, limit: int = 200) -> str:
    """Short, non-sensitive preview of args for the audit log."""
    try:
        dumped = args.model_dump()
    except AttributeError:
        dumped = args
    text = repr(dumped)
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _log_decision(
    session_factory,
    *,
    tool: Tool,
    context: ToolContext,
    decision: str,
    policy_source: str,
    channel: str,
    args_summary: str,
) -> None:
    """Write one row to tool_approvals. Best-effort, never blocks dispatch."""
    from newton.models.tool_approval import ToolApproval

    with session_factory() as session:
        session.add(
            ToolApproval(
                tool_name=tool.name,
                risk_level=int(tool.risk),
                persona_id=context.persona_id,
                user_id=context.user_id,
                decision=decision,
                policy_source=policy_source,
                channel=channel,
                args_summary=args_summary,
            )
        )


def build_policy_hook(session_factory, approval_channel=None):
    """Return a PolicyHook enforcing the approval policy.

    ``session_factory`` is a zero-arg callable returning a context-managed
    Session (e.g. ``newton.db.get_session``).

    ``approval_channel`` is an optional ApprovalChannel. Behaviour:

      * decision == auto_allow         -> None (allow), no audit log
      * decision == always_deny        -> denied, logged with channel='policy'
      * decision == require_approval:
          - no channel  -> needs_approval (safe default), not logged
          - channel     -> prompt; log outcome; allow or deny
    """

    async def hook(tool: Tool, args: object, context: ToolContext) -> ToolResult | None:
        with session_factory() as session:
            verdict = resolve_policy(session, tool, context)

        if verdict.decision == DECISION_AUTO_ALLOW:
            return None  # allowed, not an audit event

        summary = _summarize_args(args)

        if verdict.decision == DECISION_ALWAYS_DENY:
            _log_decision(
                session_factory,
                tool=tool,
                context=context,
                decision="denied",
                policy_source=verdict.source,
                channel="policy",
                args_summary=summary,
            )
            return ToolResult(
                status="denied",
                error="policy: always_deny",
                metadata={
                    "tool": tool.name,
                    "risk": int(tool.risk),
                    "policy_source": verdict.source,
                    "policy_decision": verdict.decision,
                },
            )

        # require_approval — needs a channel.
        if approval_channel is None:
            return ToolResult(
                status="needs_approval",
                metadata={
                    "tool": tool.name,
                    "risk": int(tool.risk),
                    "policy_source": verdict.source,
                    "policy_id": verdict.policy_id,
                },
            )

        from newton.tools.approval import ApprovalRequest

        outcome = await approval_channel.request(
            ApprovalRequest(
                tool_name=tool.name,
                risk_level=int(tool.risk),
                persona_id=context.persona_id,
                user_id=context.user_id,
                args_summary=summary,
                policy_source=verdict.source,
            )
        )

        _log_decision(
            session_factory,
            tool=tool,
            context=context,
            decision=outcome.decision,
            policy_source=verdict.source,
            channel=getattr(approval_channel, "name", "unknown"),
            args_summary=summary,
        )

        if outcome.approved:
            return None
        return ToolResult(
            status="denied",
            error=outcome.reason or "approval denied",
            metadata={
                "tool": tool.name,
                "risk": int(tool.risk),
                "policy_source": verdict.source,
            },
        )

    return hook


__all__ = [
    "PolicyDecision",
    "build_policy_hook",
    "default_decision",
    "resolve_policy",
]
