import json

from slacalc.cli import main


def run(capsys, *argv):
    code = main(list(argv))
    out = capsys.readouterr()
    return code, out.out, out.err


def test_budget_text(capsys):
    code, out, _ = run(capsys, "budget", "99.9")
    assert code == 0
    assert "43m 12s" in out
    assert "99.9%" in out


def test_compose_json(capsys):
    code, out, _ = run(capsys, "compose", "lb * (app | app) * db", "--set", "lb=99.99", "app=99.9", "db=99.95", "--json")
    data = json.loads(out)
    assert code == 0
    assert 0.9993 < data["availability"] < 0.9994
    assert next(iter(data["improvement_if_downtime_halved"])) == "db"


def test_latency_exit_code_reflects_slo(capsys, tmp_path):
    f = tmp_path / "s.csv"
    f.write_text("latency_ms\n" + "\n".join(str(i) for i in range(1, 101)))
    assert run(capsys, "latency", str(f), "--slo", "p99<=200")[0] == 0
    code, out, _ = run(capsys, "latency", str(f), "--slo", "p99<=50")
    assert code == 1
    assert "MISSED" in out


def test_burn_page(capsys):
    code, out, _ = run(capsys, "burn", "--slo", "99.9", "--good", "98200", "--total", "100000", "--window", "1h")
    assert code == 0
    assert "18.00x" in out
    assert "Alert: page" in out


def test_errors_go_to_stderr(capsys):
    code, out, err = run(capsys, "compose", "a * b", "--set", "a=99")
    assert code == 2
    assert out == ""
    assert "No availability given for component 'b'" in err


def test_missing_file(capsys, tmp_path):
    code, _, err = run(capsys, "latency", str(tmp_path / "nope.csv"))
    assert code == 2
    assert "error:" in err
