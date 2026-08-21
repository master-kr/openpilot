from cereal import car, log

from openpilot.selfdrive.car.car_specific import CarSpecificEvents


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

  def test_set_waits_for_pcm_rising_edge(self):
    disabled = car_state()
    set_pressed = car_state(button_type=ButtonType.decelCruise)
    events = self.events.update(set_pressed, disabled, self.cc)

    assert EventName.buttonEnable not in events.names
    assert EventName.pcmDisable in events.names

    enabled = car_state(cruise_enabled=True)
    events = self.events.update(enabled, car_state(), self.cc)
    assert EventName.pcmEnable in events.names

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

  def test_resume_from_disabled_pcm_waits_for_real_rising_edge(self):
    enabled = car_state(cruise_enabled=True)
    self.events.update(car_state(cruise_enabled=True, button_type=ButtonType.cancel), enabled, self.cc)

    disabled = car_state()
    self.events.update(disabled, enabled, self.cc)
    resume_pressed = car_state(button_type=ButtonType.accelCruise)
    events = self.events.update(resume_pressed, disabled, self.cc)
    assert EventName.buttonEnable not in events.names
    assert EventName.pcmDisable in events.names

    events = self.events.update(car_state(cruise_enabled=True), disabled, self.cc)
    assert EventName.pcmEnable in events.names
