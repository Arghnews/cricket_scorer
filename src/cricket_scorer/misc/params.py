import copy
import collections
import inspect
import typing

from cricket_scorer.misc import my_logger
from cricket_scorer.net import udp_receive

from enum import Enum
Parameters = Enum("Parameters", "NOT_PROVIDED")

BuildFuncArgs = collections.namedtuple("BuildFuncArgs", ["func", "args"])

def add_helper(cls, name):
    add_name = "add_" + name
    assert not hasattr(cls, add_name)
    def f(self, value):
        self._simple_data[f.name] = value
        return self
    f.name = name
    setattr(cls, add_name, f)

def remove_prefix(string: str, prefix):
    assert string.startswith(prefix)
    return string[len(prefix):]

def get_method_name():
    return inspect.stack()[2][3]

def add_entry(profile_self, arg):
    name = remove_prefix(get_method_name(), "add_")
    assert name not in profile_self._simple_data
    profile_self._simple_data[name] = arg
    return profile_self

class BaseProfileBuilder:
    def __init__(self):
        self._simple_data = {}
        self._data: dict[str, BuildFuncArgs] = {}
    def add_logger(self, logger, logs_folder=None):
        assert logger in (my_logger.get_console_logger,
                my_logger.get_file_logger, my_logger.get_datetime_file_logger)
        d = {}
        if logger is not my_logger.get_console_logger:
            assert logs_folder is not None
            d["logs_folder"] = logs_folder
        self._data["logger"] = BuildFuncArgs(logger, d)
        return self
    def add_sock(self, port, host_ip_bind=Parameters.NOT_PROVIDED):
        d = {"server_port": port}
        if host_ip_bind is not Parameters.NOT_PROVIDED:
            d["host_ip_bind"] = host_ip_bind
        self._data["sock"] = BuildFuncArgs(udp_receive.SimpleUDP, d)
        return self

    def add_lookout_timeout_seconds(self, s):
        """When on and not connected, occasionally send out messages to the
        receiver in case it's come up to alert it that we're switched on."""
        return add_entry(self, s)
    def add_receive_loop_timeout_milliseconds(self, t):
        """Amount of time the socket will block and listen for network
        messages."""
        return add_entry(self, t)

    def build(self, args_class, logs_folder=None):
        for k, v in self._simple_data.items():
            assert v is not None, f"Value must be supplied for key {k}"
        if logs_folder is not None:
            assert self._data["logger"].func is not my_logger.get_console_logger
            self._data["logger"].args["logs_folder"] = logs_folder
        return args_class(self._simple_data, self._data)

class SenderProfileBuilder(BaseProfileBuilder):
    def __init__(self):
        super().__init__()
    def add_receiver_ip_port(self, ip_port):
        return add_entry(self, ip_port)
    def add_score_reader(self, reader):
        self._data["score_reader"] = BuildFuncArgs(reader, {})
        return self
    def add_new_connection_id_countdown_seconds(self, s):
        """Timer from when receive message from new client. If don't get a
        response within this timeout, will assume the client is switched off
        or we received an old message."""
        return add_entry(self, s)
    def add_last_received_timer_seconds(self, s):
        """When connected, there can be periods of little to no network
        activity. The receiver/client should ping this sender box with lookout
        messages to confirm it's still there, ie. it hasn't been switched off.
        This is the timeout for how long to wait until receiving one of those
        messages before assuming the remote end is switched off and
        disconnecting. This should therefore be realistically at least double
        the lookout_timeout on the receiver."""
        return add_entry(self, s)
    def add_resend_same_countdown_seconds(self, s):
        """We use this to avoid resending the same score again in a short amount
        of time."""
        return add_entry(self, s)

class ReceiverProfileBuilder(BaseProfileBuilder):
    def __init__(self):
        super().__init__()
    def add_score_writer(self, writer):
        return add_entry(self, writer)

class Args:
    # Potential TODO: add check to ensure opened by "with" statement
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, exc_traceback):
        if "sock" in self._ready:
            self.sock.close()

    def __init__(self, simple_data: dict,
            data: typing.Dict[str, BuildFuncArgs]):
        self._data = data
        self._ready = simple_data

    @property
    def logger(self):
        if "logger" not in self._ready:
            self._ready["logger"] = self._data["logger"].func(
                    **self._data["logger"].args)
        return self._ready["logger"]

    @property
    def sock(self):
        if "sock" not in self._ready:
            self._ready["sock"] = self._data["sock"].func(self.logger,
                    **self._data["sock"].args)
        return self._ready["sock"]

    def __getattr__(self, item):
        if item in self._ready:
            return self._ready[item]
        if item in self._data:
            return getattr(self, item)
        raise AttributeError(f"No attribute {item}")

    def __str__(self):
        return str(self._ready) + "-" + str(self._data)

class SenderArgs(Args):
    def __init__(self, simple_data: dict, data: typing.Dict[str, BuildFuncArgs]):
        super().__init__(simple_data, data)
    @property
    def score_reader(self):
        assert "score_reader" in self._data or "score_reader" in self._ready
        if "score_reader" not in self._ready:
            self._ready["score_reader"] = self._data["score_reader"].func(
                    self.logger)
        return self._ready["score_reader"]
    def __exit__(self, exc_type, exc_value, exc_traceback):
        if "score_reader" in self._ready and hasattr(self.score_reader, "close"):
            self.score_reader.close()
        return super().__exit__(exc_type, exc_value, exc_traceback)

class ReceiverArgs(Args):
    def __init__(self, simple_data: dict, data: typing.Dict[str, BuildFuncArgs]):
        super().__init__(simple_data, data)

class Profiles:
    def __init__(self, profile_type_class):
        self._d: dict[str, BaseProfileBuilder] = {}
        self._profile_type_class = profile_type_class
        self._template_profiles = set()

    def get_profile_class(self):
        return self._profile_type_class()

    def get_buildable_profile_names(self):
        return [k for k in self._d.keys() if k not in self._template_profiles]

    def add_new(self, name, profile):
        assert name not in self._d, f"Profile \"{name}\" exists already"
        assert isinstance(profile, BaseProfileBuilder)
        self._d[name] = profile
        return self._profile_type_class()

    def _copy_and_update_dict(self, update_to, update_from):
        d = copy.deepcopy(update_to)
        d.update(update_from)
        return d

    def add_based_on(self, name, based_on, profile):
        assert based_on in self._d, f"Profile \"{based_on}\" must exist"
        assert isinstance(profile, BaseProfileBuilder)
        simple_data = self._copy_and_update_dict(self._d[based_on]._simple_data,
                profile._simple_data)
        data = self._copy_and_update_dict(self._d[based_on]._data,
                profile._data)
        profile._simple_data, profile._data = simple_data, data
        return self.add_new(name, profile)

    def add_new_template(self, name, profile):
        """A template profile cannot itself be built, only other profiles
        built based on it"""
        self._template_profiles.add(name)
        return self.add_new(name, profile)

    def _build_profile(self, args_class, name, **kwargs):
        if name in self._template_profiles:
            raise RuntimeError(f"Cannot build profile \"{name}\" as it's a "
                    "template profile, only other profiles may be based off it")

        if name not in self.get_buildable_profile_names():
            raise RuntimeError(f"Profile {name} does not exist, choose from: "
                    f"{self.get_buildable_profile_names()}")

        profile = self._d[name]
        print("Profile dict:", profile)
        return profile.build(args_class, **kwargs)

class SenderProfiles(Profiles):
    def __init__(self, profile_type_class):
        super().__init__(profile_type_class)
    def build_profile(self, name, **kwargs):
        return super()._build_profile(SenderArgs, name, **kwargs)

class ReceiverProfiles(Profiles):
    def __init__(self, profile_type_class):
        super().__init__(profile_type_class)
    def build_profile(self, name, **kwargs):
        return super()._build_profile(ReceiverArgs, name, **kwargs)
