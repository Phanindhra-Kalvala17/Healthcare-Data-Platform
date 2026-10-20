from streamlit.testing.v1 import AppTest

from config import settings
from orchestration import pipeline


def test_dashboard_renders_without_patient_identifiers(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    pipeline.run(tmp_path, generate_patients=100)

    app = AppTest.from_file("../dashboard/app.py", default_timeout=30).run()
    assert not app.exception
    assert app.metric[0].value == "succeeded"
    shown = " ".join(str(df.value.to_csv()) for df in app.dataframe)
    assert "P0000" not in shown  # raw patient IDs never reach the dashboard


def test_dashboard_handles_no_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "DATA_DIR", tmp_path)
    app = AppTest.from_file("../dashboard/app.py", default_timeout=30).run()
    assert not app.exception
    assert "No pipeline runs yet" in app.info[0].value
