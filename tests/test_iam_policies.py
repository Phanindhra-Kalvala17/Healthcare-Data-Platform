import json

from scripts.validate_iam_policies import POLICIES, POLICY_DIR, render


def test_every_policy_file_is_validated():
    assert {p.name for p in POLICY_DIR.iterdir()} == set(POLICIES)


def test_policies_render_to_valid_json():
    for name in POLICIES:
        doc = json.loads(render(name))
        assert doc["Version"] == "2012-10-17" and doc["Statement"], name
