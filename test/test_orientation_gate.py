from __future__ import annotations

from delivery_vlm.delivery_schema import parse_vlm_orientation_gate_response


def test_gate_recognition_branch() -> None:
    raw = '{"lines":[{"款号":"A","颜色":"","S":"","M":"","L":"","XL":"","XXL":"","小计":""}]}'
    kind, info = parse_vlm_orientation_gate_response(raw)
    assert kind == "recognition"
    assert "raw" in info


def test_gate_rotate_branch() -> None:
    raw = '{"needs_rotation": true, "rotate_clockwise_90_steps": 1}'
    kind, info = parse_vlm_orientation_gate_response(raw)
    assert kind == "rotate"
    assert info["steps"] == 1


def test_gate_rotate_zero_falls_back_to_recognition() -> None:
    raw = '{"needs_rotation": true, "rotate_clockwise_90_steps": 0}'
    kind, info = parse_vlm_orientation_gate_response(raw)
    assert kind == "recognition"


def test_gate_rotate_degrees_alias() -> None:
    raw = '{"needs_rotation": true, "rotate_degrees": -90}'
    kind, info = parse_vlm_orientation_gate_response(raw)
    assert kind == "rotate"
    assert info["steps"] == 3
