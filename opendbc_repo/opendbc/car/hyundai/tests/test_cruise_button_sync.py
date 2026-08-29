import importlib.util
from pathlib import Path
import unittest


MODULE_PATH = Path(__file__).parents[1] / "cruise_button_sync.py"
MODULE_SPEC = importlib.util.spec_from_file_location("hyundai_cruise_button_sync", MODULE_PATH)
cruise_button_sync = importlib.util.module_from_spec(MODULE_SPEC)
MODULE_SPEC.loader.exec_module(cruise_button_sync)
CruiseButtonSync = cruise_button_sync.CruiseButtonSync
next_synthetic_counter = cruise_button_sync.next_synthetic_counter


class PcmDisplayModel:
  def __init__(self, speed, long_ticks=21):
    self.speed = speed
    self.long_ticks = long_ticks
    self.button = CruiseButtonSync.NONE
    self.hold_ticks = 0
    self.long_applied = False
    self.trace = [speed]

  def _apply_long(self):
    if self.button == CruiseButtonSync.RES_ACCEL:
      self.speed = ((self.speed // 10) + 1) * 10
    elif self.button == CruiseButtonSync.SET_DECEL:
      self.speed = ((self.speed - 1) // 10) * 10

  def step(self, button):
    if button in (CruiseButtonSync.RES_ACCEL, CruiseButtonSync.SET_DECEL):
      if button != self.button:
        self.button = button
        self.hold_ticks = 0
        self.long_applied = False
      self.hold_ticks += 1
      if self.hold_ticks >= self.long_ticks and not self.long_applied:
        self._apply_long()
        self.long_applied = True
    elif button == CruiseButtonSync.NONE:
      if self.button in (CruiseButtonSync.RES_ACCEL, CruiseButtonSync.SET_DECEL) and not self.long_applied:
        self.speed += 1 if self.button == CruiseButtonSync.RES_ACCEL else -1
      self.button = CruiseButtonSync.NONE
      self.hold_ticks = 0
      self.long_applied = False
    self.trace.append(self.speed)


class SyncHarness:
  LONG_DELAY_FRAMES = 40
  SHORT_PRESS_FRAMES = 8
  FEEDBACK_FRAMES = 30

  def __init__(self, speed):
    self.sync = CruiseButtonSync()
    self.pcm = PcmDisplayModel(speed)
    self.frame = 0
    self.counter = 0
    self.log = []

  def tick(self, target, physical=CruiseButtonSync.NONE, *, forward_physical=False,
           blocked=False, speed_from_pcm=False, enabled=True, transmit_available=True,
           reported_current=None):
    current = self.pcm.speed if reported_current is None else reported_current
    command = self.sync.update(
      frame=self.frame,
      physical_button=physical,
      target=target,
      current=current,
      enabled=enabled,
      blocked=blocked,
      speed_from_pcm=speed_from_pcm,
      long_delay_frames=self.LONG_DELAY_FRAMES,
      short_press_frames=self.SHORT_PRESS_FRAMES,
      feedback_frames=self.FEEDBACK_FRAMES,
      transmit_available=transmit_available,
    )
    transmitted = None
    if self.frame % 2 == 0:
      transmitted = physical if forward_physical else command
      if transmitted is not None:
        self.counter = (self.counter + 1) % 16
        self.pcm.step(transmitted)
    self.log.append({
      "frame": self.frame,
      "physical": physical,
      "synthetic": command,
      "state": self.sync.state,
      "counter": self.counter if transmitted is not None else None,
      "pcm": self.pcm.speed,
      "target": target,
    })
    self.frame += 1
    return command

  def physical_change(self, start, target, button, hold_frames, *, forward_physical=False):
    for frame in range(hold_frames):
      # openpilot changes its target only after the configured long threshold.
      active_target = target if hold_frames > self.LONG_DELAY_FRAMES and frame > self.LONG_DELAY_FRAMES else start
      self.tick(active_target, button, forward_physical=forward_physical)
    for _ in range(240):
      self.tick(target, CruiseButtonSync.NONE, forward_physical=forward_physical)
      if self.pcm.speed == target and self.sync.state == CruiseButtonSync.IDLE:
        break
    return self.pcm.trace


def speed_changes(trace):
  changes = [trace[0]]
  for speed in trace[1:]:
    if speed != changes[-1]:
      changes.append(speed)
  return changes


class TestCruiseButtonSync(unittest.TestCase):
  def test_short_res_and_set_change_one(self):
    for start, target, button in ((100, 101, CruiseButtonSync.RES_ACCEL),
                                  (100, 99, CruiseButtonSync.SET_DECEL)):
      with self.subTest(start=start, target=target):
        h = SyncHarness(start)
        trace = h.physical_change(start, target, button, 8)
        self.assertEqual(speed_changes(trace), [start, target], h.log)

  def test_long_press_changes_display_in_one_step(self):
    cases = ((100, 110, CruiseButtonSync.RES_ACCEL),
             (110, 100, CruiseButtonSync.SET_DECEL),
             (95, 100, CruiseButtonSync.RES_ACCEL),
             (105, 100, CruiseButtonSync.SET_DECEL))
    for start, target, button in cases:
      with self.subTest(start=start, target=target):
        h = SyncHarness(start)
        trace = h.physical_change(start, target, button, 46)
        self.assertEqual(speed_changes(trace), [start, target], h.log)

  def test_long_hold_is_continuous_at_50hz_with_sequential_counters(self):
    h = SyncHarness(100)
    h.physical_change(100, 110, CruiseButtonSync.RES_ACCEL, 46)
    transmitted = [x for x in h.log if x["synthetic"] is not None]
    first_press = next(i for i, x in enumerate(transmitted) if x["synthetic"] == CruiseButtonSync.RES_ACCEL)
    first_release = next(i for i, x in enumerate(transmitted[first_press:], first_press)
                         if x["synthetic"] == CruiseButtonSync.NONE)
    hold = transmitted[first_press:first_release]
    self.assertTrue(all(x["synthetic"] == CruiseButtonSync.RES_ACCEL for x in hold), h.log)
    self.assertTrue(all(b["frame"] - a["frame"] == 2 for a, b in zip(hold, hold[1:])), h.log)
    self.assertTrue(all((b["counter"] - a["counter"]) % 16 == 1 for a, b in zip(hold, hold[1:])), h.log)

  def test_release_before_long_threshold_stays_short(self):
    h = SyncHarness(100)
    trace = h.physical_change(100, 101, CruiseButtonSync.RES_ACCEL, 20)
    self.assertEqual(speed_changes(trace), [100, 101], h.log)

  def test_physical_long_already_processed_is_not_duplicated(self):
    h = SyncHarness(100)
    h.physical_change(100, 110, CruiseButtonSync.RES_ACCEL, 46, forward_physical=True)
    synthetic_presses = [x for x in h.log if x["synthetic"] in (CruiseButtonSync.RES_ACCEL, CruiseButtonSync.SET_DECEL)]
    self.assertEqual(speed_changes(h.pcm.trace), [100, 110], h.log)
    self.assertEqual(synthetic_presses, [], h.log)

  def test_delayed_physical_pcm_feedback_prevents_duplicate(self):
    h = SyncHarness(100)
    for frame in range(46):
      target = 110 if frame > h.LONG_DELAY_FRAMES else 100
      h.tick(target, CruiseButtonSync.RES_ACCEL)

    # Simulate the physical button reaching the PCM on its original path, but
    # the reported cruise speed arriving 200 ms after release.
    for _ in range(20):
      h.tick(110, reported_current=100)
    h.pcm.speed = 110
    for _ in range(20):
      h.tick(110)

    synthetic_presses = [x for x in h.log if x["synthetic"] in
                         (CruiseButtonSync.RES_ACCEL, CruiseButtonSync.SET_DECEL)]
    self.assertEqual(synthetic_presses, [], h.log)

  def test_pcm_feedback_delay_does_not_create_short_presses(self):
    h = SyncHarness(100)
    for frame in range(46):
      target = 110 if frame > h.LONG_DELAY_FRAMES else 100
      h.tick(target, CruiseButtonSync.RES_ACCEL)
    while h.pcm.speed != 110:
      h.tick(110, reported_current=100)
    for _ in range(20):
      h.tick(110, reported_current=100)
    for _ in range(10):
      h.tick(110)
    self.assertEqual(speed_changes(h.pcm.trace), [100, 110], h.log)
    self.assertEqual(sum(1 for x in h.log if x["synthetic"] == CruiseButtonSync.NONE), 1, h.log)

  def test_automatic_large_change_uses_only_short_presses(self):
    h = SyncHarness(100)
    for _ in range(500):
      h.tick(110)
      if h.pcm.speed == 110:
        break
    self.assertEqual(speed_changes(h.pcm.trace), list(range(100, 111)), h.log)
    self.assertNotIn(CruiseButtonSync.PRESS_LONG, [x["state"] for x in h.log])

  def _start_synthetic_long(self):
    h = SyncHarness(100)
    for frame in range(46):
      target = 110 if frame > h.LONG_DELAY_FRAMES else 100
      h.tick(target, CruiseButtonSync.RES_ACCEL)
    while h.sync.state != CruiseButtonSync.PRESS_LONG:
      h.tick(110)
    for _ in range(4):
      h.tick(110)
    return h

  def test_safety_interrupts_release_the_hold(self):
    for reason in ("brake", "brakeHold", "gas", "cancel", "driverOverride"):
      with self.subTest(reason=reason):
        h = self._start_synthetic_long()
        h.tick(110, blocked=True)
        h.tick(110, blocked=True)
        self.assertEqual(h.sync.state, CruiseButtonSync.IDLE, h.log)
        self.assertFalse(any(x["synthetic"] in (CruiseButtonSync.RES_ACCEL, CruiseButtonSync.SET_DECEL)
                             for x in h.log[-2:]), h.log)
        self.assertIn(CruiseButtonSync.NONE, [x["synthetic"] for x in h.log[-2:]], h.log)
        self.assertNotEqual(h.pcm.speed, 110, h.log)

  def test_opposite_physical_button_aborts_synthetic_hold(self):
    h = self._start_synthetic_long()
    command = h.tick(110, CruiseButtonSync.SET_DECEL)
    self.assertIsNone(command, h.log)
    self.assertEqual(h.sync.state, CruiseButtonSync.IDLE, h.log)

  def test_target_change_releases_synthetic_hold(self):
    h = self._start_synthetic_long()
    while h.frame % 2 != 0:
      h.tick(120)
    command = h.tick(120)
    self.assertEqual(command, CruiseButtonSync.NONE, h.log)

  def test_speed_from_pcm_disables_speed_sync(self):
    h = SyncHarness(100)
    for _ in range(100):
      h.tick(110, speed_from_pcm=True)
    self.assertEqual(h.pcm.speed, 100)
    self.assertFalse(any(x["synthetic"] is not None for x in h.log))

  def test_temporary_alt_template_loss_releases_before_retry(self):
    h = self._start_synthetic_long()
    h.tick(110, transmit_available=False)
    h.tick(110, transmit_available=False)
    while h.frame % 2 != 0:
      h.tick(110, transmit_available=True)
    command = h.tick(110, transmit_available=True)
    self.assertEqual(command, CruiseButtonSync.NONE, h.log)
    self.assertEqual(h.sync.state, CruiseButtonSync.FEEDBACK, h.log)

  def test_disabled_cruise_does_not_sync(self):
    h = SyncHarness(100)
    for _ in range(100):
      h.tick(110, enabled=False)
    self.assertEqual(h.pcm.speed, 100)

  def test_counter_wraparound(self):
    for path in ("Classic CLU11", "normal CAN-FD"):
      with self.subTest(path=path):
        counter, received = next_synthetic_counter(None, None, 15, 16)
        self.assertEqual(counter, 0)
        counter, received = next_synthetic_counter(counter, received, 15, 16)
        self.assertEqual(counter, 1)

    counter, received = next_synthetic_counter(None, None, 255, 256)
    self.assertEqual(counter, 0)
    counter, received = next_synthetic_counter(counter, received, 255, 256)
    self.assertEqual(counter, 1)

  def test_stale_rx_counter_does_not_rewind_synthetic_counter(self):
    counter, received = next_synthetic_counter(None, None, 5, 16)
    self.assertEqual(counter, 6)
    counter, received = next_synthetic_counter(counter, received, 5, 16)
    self.assertEqual(counter, 7)
    counter, received = next_synthetic_counter(counter, received, 6, 16)
    self.assertEqual(counter, 8)
    counter, received = next_synthetic_counter(counter, received, 9, 16)
    self.assertEqual(counter, 10)


if __name__ == "__main__":
  unittest.main()
