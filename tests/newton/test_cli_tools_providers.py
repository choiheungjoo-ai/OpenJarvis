"""Step 2.8 — tests for the tools and providers CLI groups."""

from __future__ import annotations

import json

from newton.cli import cli


def _parse_trailing_json(output: str) -> dict:
    """Find the CLI's --json result object within mixed CLI output.

    The blocking approval prompt writes to the same stream and isn't newline-
    separated from the JSON, so simple line/index slicing is unreliable. The
    --json result is the only object containing a top-level "status" key, so
    scan candidate brace-balanced substrings and return the one that parses
    AND has "status".
    """
    for i, ch in enumerate(output):
        if ch != "{":
            continue
        depth = 0
        for j in range(i, len(output)):
            if output[j] == "{":
                depth += 1
            elif output[j] == "}":
                depth -= 1
                if depth == 0:
                    chunk = output[i : j + 1]
                    try:
                        obj = json.loads(chunk)
                    except json.JSONDecodeError:
                        break
                    if isinstance(obj, dict) and "status" in obj:
                        return obj
                    break
    raise AssertionError(f"no status JSON found in output:\n{output}")


# -- tools list ---------------------------------------------------------------


def test_tools_list_json(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    names = [t["name"] for t in data["tools"]]
    # demo trio present; risk-sorted so echo (risk 0) leads.
    assert {"echo", "system_info", "echo_to_file"} <= set(names)
    assert names[0] == "echo"
    assert data["tools"][0]["risk"] == 0
    assert data["tools"][0]["risk_name"] == "SAFE"


def test_tools_list_human(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "list"])
    assert result.exit_code == 0
    assert "echo" in result.output
    assert "system_info" in result.output


# -- tools run: safe tool (no approval) ---------------------------------------


def test_tools_run_echo_no_approval_needed(runner, seeded_db):
    result = runner.invoke(
        cli, ["tools", "run", "echo", "--args", '{"text": "hi"}', "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"
    assert data["data"] == {"text": "hi"}


def test_tools_run_bad_args_json(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "run", "echo", "--args", "not-json"])
    assert result.exit_code == 1
    assert "error" in result.output.lower()


def test_tools_run_unknown_tool(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "run", "ghost", "--args", "{}"])
    assert result.exit_code == 1
    assert "unknown tool" in result.output.lower()


# -- tools run: gated tool (approval) -----------------------------------------


def test_tools_run_gated_with_yes_flag(runner, seeded_db):
    # echo_to_file is risk 2 -> gated. --yes auto-approves.
    result = runner.invoke(
        cli,
        [
            "tools",
            "run",
            "echo_to_file",
            "--args",
            '{"relative_path": "note.txt", "text": "hi"}',
            "--yes",
            "--json",
        ],
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["status"] == "ok"


def test_tools_run_gated_approve_via_prompt(runner, seeded_db):
    # No --yes: blocking CLI prompt. Feed "y" on stdin.
    result = runner.invoke(
        cli,
        [
            "tools",
            "run",
            "echo_to_file",
            "--args",
            '{"relative_path": "p.txt", "text": "x"}',
            "--json",
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    data = _parse_trailing_json(result.output)
    assert data["status"] == "ok"


def test_tools_run_gated_deny_via_prompt(runner, seeded_db):
    result = runner.invoke(
        cli,
        [
            "tools",
            "run",
            "echo_to_file",
            "--args",
            '{"relative_path": "p.txt", "text": "x"}',
            "--json",
        ],
        input="n\n",
    )
    assert result.exit_code == 0, result.output
    data = _parse_trailing_json(result.output)
    assert data["status"] == "denied"


# -- providers list -----------------------------------------------------------


def test_providers_list_json(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "list", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "demo.echo" in data
    assert data["demo.echo"]["active"] == "echo_loud"
    names = [p["name"] for p in data["demo.echo"]["providers"]]
    assert names == ["echo_loud", "echo_quiet"]


def test_providers_list_filter_capability(runner, seeded_db):
    result = runner.invoke(
        cli, ["providers", "list", "--capability", "demo.echo", "--json"]
    )
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert list(data.keys()) == ["demo.echo"]


# -- providers swap (permanent persists) --------------------------------------


def test_providers_swap_permanent_persists(runner, seeded_db):
    swap = runner.invoke(
        cli,
        [
            "providers",
            "swap",
            "demo.echo",
            "echo_quiet",
            "--scope",
            "permanent",
            "--json",
        ],
    )
    assert swap.exit_code == 0, swap.output

    # A fresh command (new process-equivalent) should see the persisted choice.
    listing = runner.invoke(cli, ["providers", "list", "--json"])
    data = json.loads(listing.output)
    assert data["demo.echo"]["active"] == "echo_quiet"


def test_providers_swap_unknown_provider(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "swap", "demo.echo", "ghost"])
    assert result.exit_code == 1
    assert "unknown provider" in result.output.lower()


# -- providers test / usage / health ------------------------------------------


def test_providers_test_runs_active(runner, seeded_db):
    result = runner.invoke(
        cli, ["providers", "test", "demo.echo", "--text", "Hello", "--json"]
    )
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["provider_name"] == "echo_loud"
    assert data["data"] == {"text": "HELLO"}


def test_providers_usage_json(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "usage", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "demo.echo" in data
    assert "echo_loud" in data["demo.echo"]["providers"]


def test_providers_health_json(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "health", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["demo.echo"]["echo_loud"] is True
    assert data["demo.echo"]["echo_quiet"] is True
