from cereal import car, log
from opendbc.car.hyundai.carstate import PREV_BUTTON_SAMPLES

from openpilot.selfdrive.car.car_specific import CarSpecificEvents
from openpilot.selfdrive.selfdrived.state import StateMachine


ButtonType = car.CarState.ButtonEvent.Type
EventName = log.OnroadEvent.EventName
GearShifter = car.CarState.GearShifter


def hyundai_params(pcm_cruise=True):
  cp = car.CarParams.new_message()
  cp.brand = "hyundai"
  cp.pcmCruise = pcm_cruise
  return cp


def car_state(cruise_enabled=False, button_type=None):
  cs = car.CarState.new_message()
  cs.gearShifter = GearShifter.drive
  cs.cruiseState.available = True
  cs.cruiseState.enabled = cruise_enabled
  if button_type is not None:
    buttons = cs.init("buttonEvents", 1)
    buttons[0].type = button_type
    buttons[0].pressed = True
  return cs


class TestHyundaiPcmCruiseEvents:
  def setup_method(self):
    self.events = CarSpecificEvents(hyundai_params())
    self.cc = car.CarControl.new_message()

  def test_set_bridges_pcm_response_delay(self):
    disabled = car_state()
    set_pressed = car_state(button_type=ButtonType.decelCruise)
    events = self.events.update(set_pressed, disabled, self.cc)

    assert EventName.buttonEnable in events.names
    assert EventName.pcmDisable not in events.names

    for _ in range(PREV_BUTTON_SAMPLES - 1):
      events = self.events.update(disabled, disabled, self.cc)
      assert EventName.pcmDisable not in events.names

    enabled = car_state(cruise_enabled=True)
    events = self.events.update(enabled, disabled, self.cc)
    assert EventName.pcmEnable in events.names

  def test_pcm_disable_returns_if_stock_cruise_never_enables(self):
    disabled = car_state()
    self.events.update(car_state(button_type=ButtonType.decelCruise), disabled, self.cc)

    for _ in range(PREV_BUTTON_SAMPLES - 1):
      events = self.events.update(disabled, disabled, self.cc)
      assert EventName.pcmDisable not in events.names

    events = self.events.update(disabled, disabled, self.cc)
    assert EventName.pcmDisable in events.names

  def test_cancel_blocks_stale_pcm_rising_edge_until_resume(self):
    enabled = car_state(cruise_enabled=True)
    cancel_pressed = car_state(cruise_enabled=True, button_type=ButtonType.cancel)
    events = self.events.update(cancel_pressed, enabled, self.cc)
    assert EventName.buttonCancel in events.names

    stale_rising = car_state(cruise_enabled=True)
    events = self.events.update(stale_rising, car_state(), self.cc)
    assert EventName.pcmEnable not in events.names

    resume_pressed = car_state(cruise_enabled=True, button_type=ButtonType.accelCruise)
    events = self.events.update(resume_pressed, stale_rising, self.cc)
    assert EventName.buttonEnable in events.names

  def test_resume_from_disabled_pcm_bridges_real_rising_edge(self):
    enabled = car_state(cruise_enabled=True)
    self.events.update(car_state(cruise_enabled=True, button_type=ButtonType.cancel), enabled, self.cc)

    disabled = car_state()
    self.events.update(disabled, enabled, self.cc)
    resume_pressed = car_state(button_type=ButtonType.accelCruise)
    events = self.events.update(resume_pressed, disabled, self.cc)
    assert EventName.buttonEnable in events.names
    assert EventName.pcmDisable not in events.names

    events = self.events.update(car_state(cruise_enabled=True), disabled, self.cc)
    assert EventName.pcmEnable in events.names

  def test_pcm_drop_without_button_intent_disables_immediately(self):
    enabled = car_state(cruise_enabled=True)
    disabled = car_state()
    events = self.events.update(disabled, enabled, self.cc)
    assert EventName.pcmDisable in events.names

  def test_set_cancel_resume_state_machine_sequence(self):
    state_machine = StateMachine()
    disabled = car_state()

    events = self.events.update(car_state(button_type=ButtonType.decelCruise), disabled, self.cc)
    assert state_machine.update(events) == (True, True)

    for _ in range(PREV_BUTTON_SAMPLES - 1):
      events = self.events.update(disabled, disabled, self.cc)
      assert state_machine.update(events) == (True, True)

    enabled = car_state(cruise_enabled=True)
    events = self.events.update(enabled, disabled, self.cc)
    assert state_machine.update(events) == (True, True)

    events = self.events.update(car_state(cruise_enabled=True, button_type=ButtonType.cancel), enabled, self.cc)
    assert state_machine.update(events) == (False, False)

    # A stale PCM rising edge after CANCEL must not re-engage openpilot.
    events = self.events.update(enabled, disabled, self.cc)
    assert state_machine.update(events) == (False, False)

    events = self.events.update(car_state(cruise_enabled=True, button_type=ButtonType.accelCruise), enabled, self.cc)
    assert state_machine.update(events) == (True, True)
