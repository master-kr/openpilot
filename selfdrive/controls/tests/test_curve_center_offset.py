import math

import pytest

from openpilot.selfdrive.controls.lib.lane_planner_2 import get_curve_center_offset


@pytest.mark.parametrize("curve_speed, expected", [
  (0.0, 0.0),
  (50.0, 0.50),
  (-50.0, -0.50),
  (125.0, 0.25),
  (-125.0, -0.25),
  (200.0, 0.0),
  (-200.0, 0.0),
  (250.0, 0.0),
])
def test_curve_center_offset_direction_and_strength(curve_speed, expected):
  assert get_curve_center_offset(curve_speed, 0.50) == pytest.approx(expected)


def test_curve_center_offset_disabled_is_zero():
  for curve_speed in (-200.0, -50.0, 0.0, 50.0, 200.0):
    assert get_curve_center_offset(curve_speed, 0.0) == 0.0


def test_curve_center_offset_clips_to_half_meter():
  assert get_curve_center_offset(50.0, 5.0) == 0.50
  assert get_curve_center_offset(-50.0, 5.0) == -0.50


@pytest.mark.parametrize("curve_speed", [math.nan, math.inf, -math.inf])
def test_curve_center_offset_rejects_non_finite_speed(curve_speed):
  assert get_curve_center_offset(curve_speed, 0.50) == 0.0
