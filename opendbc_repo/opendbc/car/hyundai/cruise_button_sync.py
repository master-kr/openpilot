from __future__ import annotations

import math


def next_synthetic_counter(last_counter: int | None, last_received: int | None,
                           received: int, modulo: int) -> tuple[int, int]:
  received %= modulo
  if last_counter is None:
    return (received + 1) % modulo, received

  # The cached RX value can lag behind injected messages. Only resynchronize
  # when RX has moved forward in modulo space; otherwise keep the synthetic
  # sequence monotonic and never repeat an earlier counter.
  received_distance = (received - last_counter) % modulo
  if 0 < received_distance <= modulo // 2:
    return (received + 1) % modulo, received
  return (last_counter + 1) % modulo, received


class CruiseButtonSync:
  """Generate explicit short presses or one continuous long press at 50 Hz."""

  NONE = 0
  RES_ACCEL = 1
  SET_DECEL = 2

  IDLE = "idle"
  PRESS_SHORT = "press_short"
  PRESS_LONG = "press_long"
  FEEDBACK = "feedback"

  def __init__(self):
    self.state = self.IDLE
    self.active_button = self.NONE
    self.request_target = 0
    self.press_ticks = 0
    self.feedback_ticks = 0

    self.physical_button = self.NONE
    self.physical_hold_frames = 0
    self.physical_long = False
    self.released_button = self.NONE
    self.released_long = False
    self.release_grace_frames = 0

    self.pending_button = self.NONE
    self.pending_long = False
    self.pending_target = 0
    self.pending_wait_ticks = 0

    self.long_intent_button = self.NONE
    self.long_intent_target = 0
    self.release_pending = False

  @staticmethod
  def _direction(target: int, current: int) -> int:
    if target > current:
      return CruiseButtonSync.RES_ACCEL
    if target < current:
      return CruiseButtonSync.SET_DECEL
    return CruiseButtonSync.NONE

  @staticmethod
  def _send_ticks(control_frames: int) -> int:
    # CarController runs at 100 Hz while stock Hyundai button messages are 50 Hz.
    return max(1, math.ceil(max(1, control_frames) / 2))

  def _clear_synthetic(self, clear_long_intent: bool = True):
    self.state = self.IDLE
    self.active_button = self.NONE
    self.request_target = 0
    self.press_ticks = 0
    self.feedback_ticks = 0
    self.pending_button = self.NONE
    self.pending_long = False
    self.pending_target = 0
    self.pending_wait_ticks = 0
    if clear_long_intent:
      self.long_intent_button = self.NONE
      self.long_intent_target = 0

  def _queue_released_intent(self, button: int, long_press: bool, target: int, current: int,
                             feedback_frames: int):
    if self._direction(target, current) != button:
      return
    self.pending_button = button
    self.pending_long = long_press
    self.pending_target = target
    # Give the PCM its configured feedback window to report a physical press
    # it already received before synthesizing a duplicate.
    self.pending_wait_ticks = self._send_ticks(feedback_frames)
    self.release_grace_frames = 0

  def observe_physical(self, button: int, target: int, current: int,
                       long_delay_frames: int, feedback_frames: int):
    button = int(button)
    if self.release_grace_frames > 0:
      self.release_grace_frames -= 1

    if button in (self.RES_ACCEL, self.SET_DECEL):
      if button != self.physical_button:
        self.physical_button = button
        self.physical_hold_frames = 1
        self.physical_long = False
      else:
        self.physical_hold_frames += 1
      if self.physical_hold_frames > max(1, long_delay_frames):
        self.physical_long = True
      return

    if self.physical_button in (self.RES_ACCEL, self.SET_DECEL):
      released_button = self.physical_button
      released_long = self.physical_long
      self.released_button = released_button
      self.released_long = released_long
      self.release_grace_frames = 10
      self._queue_released_intent(released_button, released_long, target, current, feedback_frames)

    self.physical_button = self.NONE
    self.physical_hold_frames = 0
    self.physical_long = False

    # Allow for the target-speed update and PCM feedback arriving one or two
    # control cycles after the physical release event.
    if (self.pending_button == self.NONE and self.release_grace_frames > 0 and
        self.released_button == self._direction(target, current)):
      self._queue_released_intent(self.released_button, self.released_long, target, current, feedback_frames)
      self.release_grace_frames = 0

  def update(self, *, frame: int, physical_button: int, target: int, current: int,
             enabled: bool, blocked: bool, speed_from_pcm: bool,
             long_delay_frames: int, short_press_frames: int,
             feedback_frames: int, transmit_available: bool = True) -> int | None:
    """Return RES/SET/NONE for a transmit tick, or None for no synthetic frame."""
    target = int(target)
    current = int(current)
    self.observe_physical(physical_button, target, current, long_delay_frames, feedback_frames)
    send_tick = frame % 2 == 0 and transmit_available
    was_pressing = self.state in (self.PRESS_SHORT, self.PRESS_LONG)

    if not transmit_available:
      if was_pressing:
        self.release_pending = True
        self._clear_synthetic(clear_long_intent=False)
      return None

    if blocked or speed_from_pcm or not enabled:
      if was_pressing:
        self.release_pending = True
      self._clear_synthetic()
      if send_tick and self.release_pending and physical_button == self.NONE:
        self.release_pending = False
        return self.NONE
      return None

    # Driver input always wins. Do not inject a NONE over the driver's frame.
    if physical_button != self.NONE:
      self._clear_synthetic()
      self.release_pending = False
      return None

    if not send_tick:
      return None

    if self.release_pending:
      self.release_pending = False
      self.state = self.FEEDBACK
      self.feedback_ticks = self._send_ticks(feedback_frames)
      return self.NONE

    direction = self._direction(target, current)
    if direction == self.NONE:
      if was_pressing:
        self._clear_synthetic()
        return self.NONE
      self._clear_synthetic()
      return None

    if self.pending_button != self.NONE:
      if target != self.pending_target or direction != self.pending_button:
        self.pending_button = self.NONE
        self.pending_long = False
        self.pending_wait_ticks = 0
      elif self.pending_wait_ticks > 0:
        self.pending_wait_ticks -= 1
        return None
      else:
        if self.pending_long:
          self.long_intent_button = self.pending_button
          self.long_intent_target = self.pending_target
        self.pending_button = self.NONE
        self.pending_long = False

    if self.long_intent_button != self.NONE:
      if target != self.long_intent_target or direction != self.long_intent_button:
        if was_pressing:
          self._clear_synthetic()
          return self.NONE
        self.long_intent_button = self.NONE
        self.long_intent_target = 0

    if self.state in (self.PRESS_SHORT, self.PRESS_LONG):
      if target != self.request_target or direction != self.active_button:
        self._clear_synthetic()
        return self.NONE

      press_limit = (self._send_ticks(long_delay_frames) + 1 if self.state == self.PRESS_LONG else
                     min(self._send_ticks(short_press_frames), max(1, self._send_ticks(long_delay_frames) - 2)))
      if self.press_ticks >= press_limit:
        was_long = self.state == self.PRESS_LONG
        self.state = self.FEEDBACK
        self.press_ticks = 0
        self.feedback_ticks = self._send_ticks(feedback_frames)
        if not was_long:
          self.long_intent_button = self.NONE
          self.long_intent_target = 0
        return self.NONE

      self.press_ticks += 1
      return self.active_button

    if self.state == self.FEEDBACK:
      if self.feedback_ticks > 0:
        self.feedback_ticks -= 1
        return None
      self.state = self.IDLE

    if direction == self.SET_DECEL and current < 31:
      return None
    if direction == self.RES_ACCEL and current >= 160:
      return None

    use_long = self.long_intent_button == direction and self.long_intent_target == target
    self.state = self.PRESS_LONG if use_long else self.PRESS_SHORT
    self.active_button = direction
    self.request_target = target
    self.press_ticks = 1
    return direction
