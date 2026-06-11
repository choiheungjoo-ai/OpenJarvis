"""Step 2.8 (round 2) — tests for the new CLI commands.

Covers tools show, tools policy list/set/unset, providers show/active,
and the extended status JSON keys.
"""

from __future__ import annotations

import json

from newton.cli import cli

# -- tools show ---------------------------------------------------------------


def test_tools_show_json(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "show", "echo", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["name"] == "echo"
    assert data["risk"] == 0
    assert data["risk_name"] == "SAFE"
    assert "args_schema" in data
    assert data["args_schema"]["properties"]["text"]


def test_tools_show_unknown(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "show", "ghost"])
    assert result.exit_code == 1
    assert "unknown tool" in result.output.lower()


# -- tools policy list / set / unset -----------------------------------------


def test_policy_list_empty(runner, seeded_db):
    result = runner.invoke(cli, ["tools", "policy", "list", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"policies": []}


def test_policy_set_insert_then_update(runner, seeded_db):
    # Insert
    r1 = runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo_to_file",
            "--persona",
            "jarvis",
            "--decision",
            "auto_allow",
            "--note",
            "trusted persona",
            "--json",
        ],
    )
    assert r1.exit_code == 0, r1.output
    d1 = json.loads(r1.output)
    assert d1["action"] == "inserted"
    assert d1["decision"] == "auto_allow"

    # Update same triple
    r2 = runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo_to_file",
            "--persona",
            "jarvis",
            "--decision",
            "always_deny",
            "--json",
        ],
    )
    assert r2.exit_code == 0, r2.output
    d2 = json.loads(r2.output)
    assert d2["action"] == "updated"
    assert d2["decision"] == "always_deny"
    assert d2["policy_id"] == d1["policy_id"]  # same row


def test_policy_list_filter_by_tool(runner, seeded_db):
    runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo_to_file",
            "--decision",
            "auto_allow",
            "--json",
        ],
    )
    runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo",
            "--decision",
            "always_deny",
            "--json",
        ],
    )
    result = runner.invoke(
        cli,
        ["tools", "policy", "list", "--tool", "echo", "--json"],
    )
    data = json.loads(result.output)
    assert len(data["policies"]) == 1
    assert data["policies"][0]["tool_name"] == "echo"


def test_policy_unset(runner, seeded_db):
    set_r = runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo_to_file",
            "--persona",
            "jarvis",
            "--decision",
            "auto_allow",
            "--json",
        ],
    )
    pid = json.loads(set_r.output)["policy_id"]

    unset_r = runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "unset",
            "echo_to_file",
            "--persona",
            "jarvis",
            "--json",
        ],
    )
    assert unset_r.exit_code == 0
    d = json.loads(unset_r.output)
    assert d == {"deleted": True, "policy_id": pid}

    list_r = runner.invoke(cli, ["tools", "policy", "list", "--json"])
    assert json.loads(list_r.output) == {"policies": []}


def test_policy_unset_missing(runner, seeded_db):
    result = runner.invoke(
        cli,
        ["tools", "policy", "unset", "echo", "--json"],
    )
    assert result.exit_code == 0
    d = json.loads(result.output)
    assert d["deleted"] is False


def test_policy_set_invalid_decision(runner, seeded_db):
    result = runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo_to_file",
            "--decision",
            "garbage",
        ],
    )
    assert result.exit_code != 0  # click rejects the choice


# -- policy CLI takes effect: setting always_deny blocks a previously-allowed call


def test_policy_set_always_deny_blocks_run(runner, seeded_db):
    # echo is risk 0 -> default auto_allow.
    ok = runner.invoke(
        cli, ["tools", "run", "echo", "--args", '{"text": "hi"}', "--json"]
    )
    assert json.loads(ok.output)["status"] == "ok"

    # Pin always_deny.
    runner.invoke(
        cli,
        [
            "tools",
            "policy",
            "set",
            "echo",
            "--decision",
            "always_deny",
            "--json",
        ],
    )

    blocked = runner.invoke(
        cli, ["tools", "run", "echo", "--args", '{"text": "hi"}', "--json"]
    )
    assert blocked.exit_code == 0
    d = json.loads(blocked.output)
    assert d["status"] == "denied"
    assert "always_deny" in d["error"]


# -- providers show / active --------------------------------------------------


def test_providers_show_json(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "show", "demo.echo", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert data["capability"] == "demo.echo"
    assert data["active"] == "echo_loud"
    names = [p["name"] for p in data["providers"]]
    assert names == ["echo_loud", "echo_quiet"]
    assert data["providers"][0]["active"] is True


def test_providers_show_unknown(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "show", "nope.cap"])
    assert result.exit_code == 1


def test_providers_active_prints_name_only(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "active", "demo.echo"])
    assert result.exit_code == 0
    assert result.output.strip() == "echo_loud"


def test_providers_active_json(runner, seeded_db):
    result = runner.invoke(cli, ["providers", "active", "demo.echo", "--json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data == {"capability": "demo.echo", "active": "echo_loud"}


# -- status extension ---------------------------------------------------------


def test_status_json_includes_tools_and_providers(runner, seeded_db):
    result = runner.invoke(cli, ["status", "--json"])
    assert result.exit_code == 0, result.output
    data = json.loads(result.output)
    assert "tools" in data
    assert "providers" in data
    # builtins grow over time (vault tools added in block 3); the
    # demo trio must still be present.
    assert data["tools"]["count"] >= 3
    assert data["providers"]["demo.echo"]["count"] == 2
    assert data["providers"]["demo.echo"]["active"] == "echo_loud"
