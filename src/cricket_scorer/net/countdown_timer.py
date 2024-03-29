#!/usr/bin/env python3

import sys
import time

# NOTE: timer starts in expired state - possibly this is not expected
# Granularity is seconds
# See https://docs.micropython.org/en/latest/library/utime.html


def make_countdown_timer(*, millis=None, seconds=None, started=True):
    assert (millis is not None) ^ (seconds is not None)
    if seconds is not None:
        millis = seconds * 1000

    # if sys.implementation.name == "micropython":
    #     time_now = lambda: time.ticks_ms()
    #     diff = time.ticks_diff
    # else:
    time_now = lambda: int(time.monotonic() * 1000)
    # Cannot import here as imported processed on file parse?
    # from operator import sub
    # diff = sub
    diff = lambda a, b: a - b

    # This MUST be an integer for micropython time.ticks_diff to work properly
    countdown_millis = int(millis)

    return CountdownTimer(time_now, diff, countdown_millis, started)


# Note to self before try to add something like an is_expired method to this class
# The semantics of something like that are confusing at best, at least I can't think
# of a nice way to do it. (If you have is_expired and just_expired and you check is_expired
# and the timer has just expired, what should just_expired return?)
class CountdownTimer:
    """
    Timer that will count down when reset or created with started=True
    Will only return that it's done via just_expired once, until reset

    t = make_countdown_timer(seconds=5, started=True)
    assert not t.just_expired()
    t.sleep_till_expired()
    assert t.just_expired() # Bit dubious this one
    t.reset()
    # Same again
    """
    def __init__(self, time_now, diff, countdown_millis, started):
        self._time_now = time_now
        self._diff = diff

        assert type(countdown_millis) is int
        self._countdown_millis = countdown_millis

        self._expired = True
        self._last = None

        if started:
            self.reset()

    def _remaining_time(self):
        return self._diff(self._last + self._countdown_millis, self._time_now())

    def just_expired(self):
        if self._expired:
            return False
        self._expired = self._remaining_time() <= 0
        return self._expired

    def sleep_till_expired(self):
        if self._expired:
            return
        t = max(self._remaining_time(), 0)
        if sys.implementation.name == "micropython":
            time.sleep_ms(t)
        else:
            time.sleep(t / 1000)

    def stop(self):
        self._expired = True

    def reset(self):
        self._last = self._time_now()
        self._expired = False
        return self


def main(argv):
    t = make_countdown_timer(seconds=5)
    # Yes side effects in asserts are bad but this is a quick test
    assert not t.just_expired()
    assert not t.just_expired()
    t.reset()
    assert not t.just_expired()
    assert not t.just_expired()
    time.sleep(4)
    t.sleep_till_expired()
    assert not t.just_expired()  # Bit dubious this one
    time.sleep(1)
    assert t.just_expired()
    assert not t.just_expired()
    t.sleep_till_expired()
    t.reset()
    assert not t.just_expired()
    assert not t.just_expired()

    print("Sleeping till expired")
    t.sleep_till_expired()


if __name__ == "__main__":
    sys.exit(main(sys.argv))
