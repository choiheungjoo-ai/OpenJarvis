"""Tool approval policy: resolution and risk-based defaults.

Decision order (most specific first):

    1. (tool, persona, user)   exact row
    2. (tool, persona, NULL)   persona-wide
    3. (tool, NULL,    user)   user-wide
    4. (tool, NULL,    NULL)   tool-wide
    5. risk-based default in code  (no row matched)

The risk default is fail-safe: anything that can change the world
(risk >= WRITE_LOCAL) requires approval unless a row explicitly relaxes it.

This module decides *whether approval is required*.  It does not prompt for
approval — that is the Step 2.6 approval channel.  ``build_policy_hook`` here
returns a hook that DENIES anything requiring approval, which keeps dispatch
safe until 2.6 wires a real prompt in.
"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from newton.models.tool_policy import ToolPolicy
from newton.tools.base import RiskLevel, Tool, ToolContext, ToolResult

# Risk levels at or above this need approval by default (step 5 fallback).
_APPROVAL_THRESHOLD = RiskLevel.WRITE_LOCAL


def default_requires_approval(risk: RiskLevel) -> bool:
    """Risk-based fallback used when no DB row matches.

    risk 0 (SAFE), 1 (READ_LOCAL)            -> no approval
    risk 2 (WRITE_LOCAL) and above           -> approval required
    """
    return RiskLevel(risk) >= _APPROVAL_THRESHOLD


# Specificity score for a matched row.  Higher wins.  A row matches only if
# each non-NULL field equals the request; NULL fields are wildcards.
def _match_score(policy: ToolPolicy, persona_id: str, user_id: str) -> int | None:
    if policy.persona_id is not None and policy.persona_id != persona_id:
        return None
    if policy.user_id is not None and policy.user_id != user_id:
        return None
    score = 0
    if policy.persona_id is not None:
        score += 2  # persona match is more specific than user match
    if policy.user_id is not None:
        score += 1
    return score


@dataclass(frozen=True)
class PolicyDecision:
    """Result of resolving policy for one (tool, persona, user)."""

    require_approval: bool
    source: str  # "db" if a row decided it, "risk_default" otherwise
    policy_id: int | None = None


def resolve_policy(
    session: Session, tool: Tool, context: ToolContext
) -> PolicyDecision:
    """Resolve whether ``tool`` needs approval for this context.

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
            require_approval=bool(best.require_approval),
            source="db",
            policy_id=best.policy_id,
        )

    return PolicyDecision(
        require_approval=default_requires_approval(tool.risk),
        source="risk_default",
    )


def _summarize_args(args: object, limit: int = 200) -> str:
    """Short, non-sensitive preview of args for the audit log."""
    try:
        dumped = args.model_dump()  # pydantic BaseModel
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
    """Write one row to tool_approvals. Best-effort; never blocks dispatch."""
    # Imported lazily so policy.py has no hard import of the model at module
    # load (keeps the resolution helpers usable without the approvals table).
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

    ``approval_channel`` is an optional :class:`~newton.tools.approval.
    ApprovalChannel`. Behaviour when a call needs approval:

      * no channel  -> return ``needs_approval`` (safe default; nothing runs,
        nothing logged — matches the Step 2.5 behaviour).
      * channel      -> prompt it; log the outcome to ``tool_approvals``;
        return ``None`` (allow) on approval or ``denied`` on refusal.

    Calls that do not need approval return ``None`` and are not logged.
    """

    async def hook(tool: Tool, args: object, context: ToolContext) -> ToolResult | None:
        with session_factory() as session:
            decision = resolve_policy(session, tool, context)

        if not decision.require_approval:
            return None  # allowed, not an audit event

        # Gated. Without a channel, fall back to the safe default: refuse,
        # and do not log (no decision was actually made by anyone).
        if approval_channel is None:
            return ToolResult(
                status="needs_approval",
                metadata={
                    "tool": tool.name,
                    "risk": int(tool.risk),
                    "policy_source": decision.source,
                    "policy_id": decision.policy_id,
                },
            )

        # Ask the channel, then record the decision.
        from newton.tools.approval import ApprovalRequest

        summary = _summarize_args(args)
        outcome = await approval_channel.request(
            ApprovalRequest(
                tool_name=tool.name,
                risk_level=int(tool.risk),
                persona_id=context.persona_id,
                user_id=context.user_id,
                args_summary=summary,
                policy_source=decision.source,
            )
        )

        _log_decision(
            session_factory,
            tool=tool,
            context=context,
            decision=outcome.decision,
            policy_source=decision.source,
            channel=getattr(approval_channel, "name", "unknown"),
            args_summary=summary,
        )

        if outcome.approved:
            return None  # approved -> dispatch proceeds to execute
        return ToolResult(
            status="denied",
            error=outcome.reason or "approval denied",
            metadata={
                "tool": tool.name,
                "risk": int(tool.risk),
                "policy_source": decision.source,
            },
        )

    return hook


__all__ = [
    "PolicyDecision",
    "build_policy_hook",
    "default_requires_approval",
    "resolve_policy",
]
