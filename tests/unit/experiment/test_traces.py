import json

import pytest

from dsg.experiment.traces import end_to_end_columns, write_traces

MS = 1_000_000
HEADER = "request_id,request_entered_at_ns,handed_over_by,admission_phase,outcome,arrived_at_ns,started_at_ns,finished_at_ns\n"


def chain_run(tmp_path, link="requests"):
    plan = {"link": link, "nodes": [{"name": "qr"}, {"name": "face"}, {"name": "pc"}], "edges": [["qr", "face"], ["face", "pc"]]}
    (tmp_path / "run.json").write_text(json.dumps({"plan": plan}))
    for node in ("qr", "face", "pc"):
        (tmp_path / node).mkdir()
    (tmp_path / "qr" / "records.csv").write_text(
        HEADER
        + f"qr-0,0,,warmup,completed,0,{1*MS},{2*MS}\n"
        + f"qr-1,{10*MS},,measure,completed,{10*MS},{110*MS},{120*MS}\n"
        + f"qr-2,{20*MS},,measure,completed,{20*MS},{30*MS},{40*MS}\n"
        + f"qr-3,{30*MS},,measure,failed,{30*MS},{31*MS},{32*MS}\n"
    )
    (tmp_path / "face" / "records.csv").write_text(
        HEADER
        + f"qr-1,{10*MS},qr,measure,completed,{121*MS},{321*MS},{325*MS}\n"
        + f"qr-2,{20*MS},qr,measure,completed,{42*MS},{142*MS},{146*MS}\n"
    )
    (tmp_path / "pc" / "records.csv").write_text(
        HEADER + f"qr-1,{10*MS},face,measure,completed,{326*MS},{400*MS},{403*MS}\n"
    )
    return tmp_path


def test_with_rate_links_there_is_nothing_to_trace(tmp_path):
    assert write_traces(chain_run(tmp_path, link="rates")) is None
    assert not (tmp_path / "traces.csv").exists()


def test_every_measured_request_gets_one_trace_with_its_total_time(tmp_path):
    import pandas as pd

    write_traces(chain_run(tmp_path))
    traces = pd.read_csv(tmp_path / "traces.csv").set_index("request_id")
    assert list(traces.index) == ["qr-1", "qr-2", "qr-3"]
    assert traces.loc["qr-1", "total_ms"] == 403 - 10
    assert bool(traces.loc["qr-1", "completed"]) and traces.loc["qr-1", "services_passed"] == 3
    assert not bool(traces.loc["qr-2", "completed"]) and traces.loc["qr-2", "services_passed"] == 2
    assert not bool(traces.loc["qr-3", "completed"]) and traces.loc["qr-3", "services_passed"] == 0


def test_every_step_shows_handover_waiting_and_processing(tmp_path):
    import pandas as pd

    write_traces(chain_run(tmp_path))
    steps = pd.read_csv(tmp_path / "trace_steps.csv")
    of_request_1 = steps[steps["request_id"] == "qr-1"].set_index("node")
    assert list(of_request_1.index) == ["qr", "face", "pc"]
    assert list(of_request_1["position"]) == [0, 1, 2]
    assert of_request_1.loc["qr", "waiting_ms"] == 100 and of_request_1.loc["qr", "processing_ms"] == 10
    assert pd.isna(of_request_1.loc["qr", "handover_ms"])
    assert of_request_1.loc["face", "handover_ms"] == 1
    assert of_request_1.loc["pc", "handover_ms"] == 1
    parts = of_request_1[["handover_ms", "waiting_ms", "processing_ms"]].fillna(0).to_numpy().sum()
    assert parts == 403 - 10


def test_end_to_end_numbers_come_from_completed_requests_only(tmp_path):
    columns = write_traces(chain_run(tmp_path))
    assert columns["requests_entered"] == 3
    assert columns["requests_completed"] == 1
    assert columns["end_to_end_mean_ms"] == pytest.approx(393)
    assert columns["end_to_end_p99_ms"] == pytest.approx(393)


def test_a_run_without_any_completed_request_still_reports_the_counts():
    import pandas as pd

    assert end_to_end_columns(pd.DataFrame(columns=["completed", "total_ms"])) == {"requests_entered": 0, "requests_completed": 0}


def test_a_joining_step_shows_how_long_it_waited_for_its_other_inputs(tmp_path):
    import pandas as pd

    plan = {"link": "requests", "nodes": [{"name": "cam"}, {"name": "a"}, {"name": "b"}, {"name": "m"}],
            "edges": [["cam", "a"], ["cam", "b"], ["a", "m"], ["b", "m"]]}
    (tmp_path / "run.json").write_text(json.dumps({"plan": plan}))
    for node in ("cam", "a", "b", "m"):
        (tmp_path / node).mkdir()
    (tmp_path / "cam" / "records.csv").write_text(HEADER + f"cam-0,0,,measure,completed,0,0,{1*MS}\n")
    (tmp_path / "a" / "records.csv").write_text(HEADER + f"cam-0,0,cam,measure,completed,{2*MS},{2*MS},{10*MS}\n")
    (tmp_path / "b" / "records.csv").write_text(HEADER + f"cam-0,0,cam,measure,completed,{2*MS},{2*MS},{50*MS}\n")
    (tmp_path / "m" / "records.csv").write_text(
        HEADER.strip() + ",first_input_at_ns\n" + f"cam-0,0,b,measure,completed,{51*MS},{60*MS},{70*MS},{11*MS}\n"
    )
    columns = write_traces(tmp_path)
    steps = pd.read_csv(tmp_path / "trace_steps.csv").set_index("node")
    assert steps.loc["m", "waiting_for_inputs_ms"] == 40 and steps.loc["m", "waiting_ms"] == 9
    assert steps.loc["m", "handover_ms"] == 1
    assert steps.loc["a", "waiting_for_inputs_ms"] == 0
    assert columns["requests_completed"] == 1 and columns["end_to_end_mean_ms"] == 70
