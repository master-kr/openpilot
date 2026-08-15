from types import SimpleNamespace

from openpilot.selfdrive.car.cruise import ButtonType, CRUISE_LONG_PRESS, VCruiseCarrot


class FakeParams:
  def __init__(self):
    self.values = {
      "ExperimentalMode": False,
      "LongitudinalPersonality": 2,
      "LongitudinalPersonalityMax": 3,
      "MyDrivingMode": 3,
    }

  def get_bool(self, key):
    return bool(self.values.get(key, False))

  def get_int(self, key):
    return int(self.values.get(key, 0))

  def put_bool_nonblocking(self, key, value):
    self.values[key] = bool(value)

  def put_int_nonblocking(self, key, value):
    self.values[key] = int(value)


def make_helper(car_name="hyundai", oem_mode=1):
  helper = object.__new__(VCruiseCarrot)
  helper.CP = SimpleNamespace(carName=car_name)
  helper._hyundai_kia_button_mode = oem_mode
  helper._cruise_button_mode = 2
  helper._cruise_speed_unit = 10
  helper._cruise_speed_unit_basic = 5
  helper._cruise_button_long_delay = 2
  helper.is_metric = True
  helper.button_cnt = 0
  helper.button_prev = ButtonType.unknown
  helper.button_long_time = 2
  helper.long_pressed = False
  helper.params = FakeParams()
  return helper


def button_event(button_type, pressed):
  return SimpleNamespace(type=button_type, pressed=pressed)


def prepare(helper, speed, *events):
  return helper._prepare_buttons(SimpleNamespace(buttonEvents=list(events)), speed)


def run_button_action(helper, button_type, long_pressed):
  def prepare_buttons(CS, speed):
    return speed, button_type, long_pressed

  def carrot_command(speed, event, held):
    return speed, event, held

  def update_cruise_state(CS, CC, speed):
    return speed

  def add_log(message):
    pass

  helper._prepare_buttons = prepare_buttons
  helper._carrot_command = carrot_command
  helper._update_cruise_state = update_cruise_state
  helper._add_log = add_log
  helper.autoCruiseControl_cancel_timer = 0
  helper._cruise_cancel_state = False
  helper._paddle_decel_active = False
  helper._paddle_mode = 0
  helper._cancel_button_mode = 1
  helper._lfa_button_mode = 1
  helper._lat_enabled = True
  helper.useLaneLineSpeed = 30
  helper.useLaneLineSpeedApply = 30
  helper.CP.openpilotLongitudinalControl = True
  return helper._update_cruise_buttons(SimpleNamespace(pcmCruiseGap=0), SimpleNamespace(enabled=True), 83)


def test_hyundai_oem_short_press_uses_one_kph():
  helper = make_helper()

  prepare(helper, 83, button_event(ButtonType.accelCruise, True))
  speed, button_type, long_pressed = prepare(helper, 83, button_event(ButtonType.accelCruise, False))

  assert speed == 84
  assert button_type == ButtonType.accelCruise
  assert not long_pressed


def test_hyundai_oem_short_decel_uses_one_kph():
  helper = make_helper()

  prepare(helper, 83, button_event(ButtonType.decelCruise, True))
  speed, button_type, long_pressed = prepare(helper, 83, button_event(ButtonType.decelCruise, False))

  assert speed == 82
  assert button_type == ButtonType.decelCruise
  assert not long_pressed


def test_hyundai_oem_without_lfa_uses_same_speed_buttons():
  helper = make_helper(oem_mode=2)

  prepare(helper, 83, button_event(ButtonType.accelCruise, True))
  speed, button_type, long_pressed = prepare(helper, 83, button_event(ButtonType.accelCruise, False))

  assert speed == 84
  assert button_type == ButtonType.accelCruise
  assert not long_pressed


def test_hyundai_oem_hold_snaps_to_ten_kph():
  helper = make_helper()

  prepare(helper, 83, button_event(ButtonType.accelCruise, True))
  result = None
  for _ in range(CRUISE_LONG_PRESS):
    result = prepare(helper, 83)

  speed, button_type, long_pressed = result
  assert speed == 90
  assert button_type == ButtonType.accelCruise
  assert long_pressed

  speed, button_type, long_pressed = prepare(helper, speed, button_event(ButtonType.accelCruise, False))
  assert speed == 90
  assert button_type == 0
  assert not long_pressed


def test_hyundai_oem_decel_hold_snaps_down_to_ten_kph():
  helper = make_helper()

  prepare(helper, 83, button_event(ButtonType.decelCruise, True))
  result = None
  for _ in range(CRUISE_LONG_PRESS):
    result = prepare(helper, 83)

  speed, button_type, long_pressed = result
  assert speed == 80
  assert button_type == ButtonType.decelCruise
  assert long_pressed


def test_oem_mode_is_limited_to_hyundai_kia():
  helper = make_helper(car_name="toyota")

  prepare(helper, 83, button_event(ButtonType.accelCruise, True))
  speed, _, _ = prepare(helper, 83, button_event(ButtonType.accelCruise, False))

  assert speed == 85  # Existing Carrot CruiseSpeedUnitBasic value is preserved.


def test_mode_zero_preserves_existing_carrot_units():
  helper = make_helper(oem_mode=0)

  prepare(helper, 83, button_event(ButtonType.accelCruise, True))
  speed, _, _ = prepare(helper, 83, button_event(ButtonType.accelCruise, False))

  assert speed == 85


def test_live_mode_change_clears_partial_button_hold():
  helper = make_helper(oem_mode=0)
  helper.button_cnt = 20
  helper.button_prev = ButtonType.accelCruise
  helper.long_pressed = True

  helper._set_hyundai_kia_button_mode(1)

  assert helper.button_cnt == 0
  assert helper.button_prev == ButtonType.unknown
  assert not helper.long_pressed


def test_oem_mode_does_not_use_carrot_user_speed_table():
  helper = make_helper()
  helper._cruise_button_mode = 3
  helper._cruise_speed_table = [30, 50, 80, 110, 130]

  speed = helper._v_cruise_desired(SimpleNamespace(), 83)

  assert speed == 83


def test_oem_cruise_main_off_keeps_lateral_control_enabled():
  helper = make_helper()
  helper.cruise_state_available_last = True
  helper._lat_enabled = True

  helper._update_cruise_main_lateral(False)

  assert helper._lat_enabled


def test_oem_without_lfa_cruise_main_off_disables_lateral_control():
  helper = make_helper(oem_mode=2)
  helper.cruise_state_available_last = True
  helper._lat_enabled = True

  helper._update_cruise_main_lateral(False)

  assert not helper._lat_enabled


def test_oem_without_lfa_cruise_main_on_enables_lateral_control():
  helper = make_helper(oem_mode=2)
  helper.cruise_state_available_last = False
  helper._lat_enabled = False

  helper._update_cruise_main_lateral(True)

  assert helper._lat_enabled


def test_oem_startup_with_cruise_main_off_preserves_lateral_state():
  helper = make_helper()
  helper.cruise_state_available_last = False
  helper._lat_enabled = True

  helper._update_cruise_main_lateral(False)

  assert helper._lat_enabled


def test_oem_cancel_does_not_look_like_cruise_main_off():
  helper = make_helper()
  helper.cruise_state_available_last = True
  helper._lat_enabled = True

  helper._update_cruise_main_lateral(True)

  assert helper._lat_enabled


def test_lfa_hold_still_emits_lanemode_toggle():
  helper = make_helper()

  prepare(helper, 83, button_event(ButtonType.lfaButton, True))
  result = None
  for _ in range(CRUISE_LONG_PRESS + 20):
    result = prepare(helper, 83)

  _, button_type, long_pressed = result
  assert button_type == ButtonType.lfaButton
  assert long_pressed


def test_oem_cancel_keeps_lateral_control_enabled():
  helper = make_helper()

  run_button_action(helper, ButtonType.cancel, False)

  assert helper._cruise_cancel_state
  assert helper._lat_enabled


def test_oem_cancel_hold_keeps_lateral_control_enabled():
  helper = make_helper()

  run_button_action(helper, ButtonType.cancel, True)

  assert helper._cruise_cancel_state
  assert helper._lat_enabled


def test_oem_without_lfa_cancel_short_and_hold_keep_lateral_control_enabled():
  for long_pressed in (False, True):
    helper = make_helper(oem_mode=2)

    run_button_action(helper, ButtonType.cancel, long_pressed)

    assert helper._cruise_cancel_state
    assert helper._lat_enabled


def test_oem_lfa_short_toggles_lateral_control():
  helper = make_helper()

  run_button_action(helper, ButtonType.lfaButton, False)

  assert not helper._lat_enabled


def test_oem_without_lfa_ignores_lfa_short_event():
  helper = make_helper(oem_mode=2)

  run_button_action(helper, ButtonType.lfaButton, False)

  assert helper._lat_enabled
  assert not helper._paddle_decel_active


def test_oem_lfa_hold_toggles_lanemode_in_action_handler():
  helper = make_helper()

  run_button_action(helper, ButtonType.lfaButton, True)

  assert helper.useLaneLineSpeedApply == 0


def test_oem_without_lfa_ignores_lfa_hold_event():
  helper = make_helper(oem_mode=2)

  run_button_action(helper, ButtonType.lfaButton, True)

  assert helper.useLaneLineSpeedApply == 30


def test_oem_gap_hold_toggles_experimental_for_openpilot_long():
  helper = make_helper()

  run_button_action(helper, ButtonType.gapAdjustCruise, True)

  assert helper.params.get_bool("ExperimentalMode")


def test_oem_gap_short_handles_zero_personality_max_safely():
  helper = make_helper()
  helper.params.values["LongitudinalPersonalityMax"] = 0

  run_button_action(helper, ButtonType.gapAdjustCruise, False)

  assert helper.params.get_int("LongitudinalPersonality") == 0
