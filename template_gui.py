#!/usr/bin/env python3

import copy
import io
from logging import disable
import multiprocessing
import os
import sys
import time
import types
import typing

import PySimpleGUI as sg
from PySimpleGUI.PySimpleGUI import DEBUGGER_VARIABLE_DETAILS_FONT, Ok
import plyer

from cricket_scorer.misc import profiles
from cricket_scorer.misc.params import SenderProfileBuilder
from cricket_scorer.net import connection
from cricket_scorer.score_handlers.scoredata import ScoreData

# This will be either reading from the excel spreadsheet via xlwings
# Or from the I2C ports
# Or just prints out numbers as a dummy generator
def score_reader_f(*args):
    print("score_reader_f sender started with args:", *args)
    for num in range(1000000):
        # print("Getting net num", num)
        epoch_time = int(time.time()) // 5
        yield bytes([epoch_time % 10] * 9)

# This will be the networking code function that control will be handed to that
# will send it to the other scoreboard
async def score_sender_func(*args):
    print("score_sender_func started with args:", *args)
    while 1:
        #  print("score sender start iter")
        val = (yield)
        #  print("Sending", val, "to scoreboard")

class OnlyPrintOnDiff:
    def __init__(self):
        self.buf = io.StringIO()
        self.prev = None
    def print(self, *args, **kwargs):
        print(*args, file = self.buf, **kwargs)
    def print_contents_if_diff(self):
        contents = self.buf.getvalue()

        if contents != self.prev:
            print(contents, end = "")

        self.prev = contents
        self.buf = io.StringIO()

class BetterTimer:
    def __init__(self) -> None:
        self._timers = {}
    def restart(self):
        self._timers.clear()
    def start(self, name):
        total, started = self._timers.setdefault(name, (0, -1))
        assert started == -1, "Must be stopped before starting"
        self._timers[name] = (total, time.time())
    def stop(self, name):
        assert name in self._timers
        total, started = self._timers.get(name)
        assert started != -1, "Must be started before stopped"
        total += time.time() - started
        self._timers[name] = (total, -1)
    def running(self, name):
        return name in self._timers and self._timers[name][1] != -1
    def summary(self):
        for k in self._timers:
            if self.running(k):
                self.stop(k)
        for name, (t, _) in self._timers.items():
            print(name, "->", t)

def notify_disconnected(title, message, timeout = 15):

    plyer.notification.notify(
    title = title,
    message = message,
    timeout = timeout,
    )

def main():

    sg.theme('Dark Blue 3')  # please make your creations colorful

    initial = os.path.dirname(os.path.realpath(__file__))

    # https://en.wikipedia.org/wiki/List_of_Microsoft_Office_filename_extensions
    extensions = (
        ("All Excel files", "*.xl*"),
        ("ALL Files", "*.*"),
        ("Excel workbook", "*.xlsx"),
        ("Excel macro-enabled workbook", "*.xlsm"),
        ("Legacy Excel worksheets", "*.xls"),
        ("Legacy Excel macro", "*.xlm"),
        )

    user_settings_file = sg.UserSettings()
    # This seems to NEED to be called to initialise the default filename

    # Printing this in a Windows 8 virtualmachine at least breaks, with module __main__ has
    # no attribute __FILE__ - this works from a file not from a script
    # I think the problem is elsewhere
    # print("Using settings file:", user_settings_file.get_filename())
    # Must set this
    user_settings_file.set_location("cricket-scorer-cache.json")
    print("Using settings file:", user_settings_file.get_filename())

    keys = {
            "spreadsheet_path": r"C:\Users\example\path\to\cricket.xlsx",
            "worksheet": "Sheet1",
            "total": "A2",
            "wickets": "B2",
            "overs": "C2",
            "innings": "D2",
            "logs_folder": "",
            # TODO: change this to live
            "profile": "test_sender_args_excel",
            "log_level": "WARNING",
    }

    settings = dict.fromkeys(keys, "")
    saved_settings = {}

    if user_settings_file.exists():
        saved_settings.update(user_settings_file.read())
    else:
        print(f"No settings file at {user_settings_file.get_filename()}")
        settings.update(keys)

    if set(saved_settings.keys()) != set(keys):
        try:
            if user_settings_file.exists():
                user_settings_file.delete_file()
        except Exception as e:
            print(f"Error deleting user settings file {user_settings_file.get_filename()}",
                  file=sys.stderr)
        saved_settings.clear()

    settings.update(saved_settings)

    sender_profiles = profiles.sender_profiles

    profile_names = sender_profiles.get_buildable_profile_names()
    profiles_listbox = [sg.Listbox(
        profile_names,
        default_values=[settings["profile"]],
        # [sender_profiles.get_buildable_profile_names()],
        size=(max(map(len, profile_names)), len(profile_names)),
        select_mode=sg.LISTBOX_SELECT_MODE_SINGLE,
        enable_events=True,
        key="profile",
    )]

    # settings = {
    #         "spreadsheet_path": r"",
    #         #  "spreadsheet_selector": r"C:\Users\justin\cricket.xlsx",
    #         "worksheet": "Sheet1",
    #         "total": "A2",
    #         "wickets": "B2",
    #         "overs": "C2",
    #         "innings": "D2",
    #         "logs_folder": "",
    #         # "serialisation_order": ["total", "wickets", "overs", "innings"],
    #         }

    user_settings_layout = [
                #  [sg.Text('Spreadsheet')
                    #  ],

                #  [sg.FileBrowse(key = "spreadsheet_selector",
                    #  enable_events = True,
                    #  initial_folder = initial, file_types = extensions)
                    #  ],

                [sg.Text("Spreadsheet:"),
                    sg.FileBrowse(key = "spreadsheet_selector",
                        #  enable_events = True,
                        target = "spreadsheet_path",
                        initial_folder=os.path.dirname(settings["spreadsheet_path"]),
                        # initial_folder = "",
                        # size=(30, 1),
                        file_types=extensions),
                    sg.Text(settings["spreadsheet_path"], auto_size_text = True,
                        size = (80, 1),
                        key = "spreadsheet_path")
                    ],

                [sg.Text("Worksheet name:"), sg.Input(settings["worksheet"],
                    key = "worksheet")
                    ],

                [sg.Text("Cells where scores live in spreadsheet:")
                    ],
                [
                    sg.Text("Total:"), sg.Input(settings["total"],
                        size = (9, 1), key = "total"),
                    sg.Text("Wickets:"), sg.Input(settings["wickets"],
                        size = (9, 1), key = "wickets"),
                    sg.Text("Overs:"), sg.Input(settings["overs"],
                        size = (9, 1), key = "overs"),
                    sg.Text("1st Innings:"), sg.Input(settings["innings"],
                        size = (9, 1), key = "innings"),
                    ],

                [sg.Text("Logs folder:"),
                    sg.FolderBrowse(key = "logs_folder_selector",
                        #  enable_events = True,
                        target = "logs_folder_selected",
                        initial_folder=(settings["logs_folder"]),
                    ),
                        # initial_folder = "",
                        # size=(30, 1),
                    sg.Text(settings["logs_folder"], auto_size_text = True,
                        size = (80, 1),
                        key = "logs_folder_selected")
                    ],
    ]

    user_actions_layout = [
        [sg.Column(
            [
                [
                    sg.Button("Run", font=("arial", 20),
                              size=(10, 1), # Width is size of "Save & Quit" button text
                              enable_events=True,
                              pad=((5, 25), (5, 5)),
                              key="run")
                ],
                [
                    sg.Quit("Save & Quit", font=("arial", 20),
                            pad=((5, 25), (5, 5)), key="save_and_quit"),
                ],
            ],
        ),
        sg.Column(
            [
                [
                    sg.Save(key="Save"),
                ],
                [
                    sg.Quit("Quit without saving settings", pad=(
                        5, 5), key="quit_without_saving"),
                ],
            ],
        ),
        ]
    ]

    user_actions_layout = [
        [
            sg.Button("Run", font=("arial", 20),
                      # Width is size of "Save & Quit" button text
                      size=(10, 1),
                      enable_events=True,
                      pad=((5, 25), (5, 5)),
                      key="run"),
            sg.Quit("Save & Quit", font=("arial", 20),
                    pad=((5, 25), (5, 5)), key="save_and_quit"),
            sg.Save(key="Save"),
            sg.Quit("Quit without saving settings", pad=(
                5, 5), key="quit_without_saving"),
        ],
    ]

    # user_actions_layout = [
    #     [sg.Button("Run", font=("arial", 20), enable_events=True,
    #                pad=((5, 25), (5, 5)),
    #                key="run"), sg.Save(key="Save")],
    #     [sg.Quit("Save & Quit", font=("arial", 20),
    #              pad=((5, 25), (5, 5)), key="save_and_quit"),
    #      sg.Quit("Quit without saving settings", pad=(
    #          5, 5), key="quit_without_saving")],
    # ]

    # layout2 = [
    #     [sg.Text("hi"), sg.Text("there")],
    #     # sg.Sizegrip(),
    # ]

    status_text_format_warning_initial = {
        "font": ("arial", 24),
        # "relief": sg.RELIEF_SUNKEN,
        # "pad": (10, 10),
        "text_color": "black",
        "background_color": "red",
    }

    status_text_format_warning_initial_smaller = copy.deepcopy(
        status_text_format_warning_initial)
    status_text_format_warning_initial_smaller["font"] = ("arial", 18)

    status_layout = [
            [
                sg.Text("Not running", key="is_running",
                        **status_text_format_warning_initial),
                sg.Text("Not connected", key="is_connected",
                        **status_text_format_warning_initial),
                sg.Text("Settings changed, click Run to reload",
                        size=(16, 2),
                        auto_size_text=True,
                        **status_text_format_warning_initial_smaller,
                        key="settings_changed",
                        justification="center"),
                sg.Text("Some text here asdjkfalsjdf asdjkf jasdkl", size=(10,3)),
            ],
    ]

    # dev_toggle_button_layout = [sg.Checkbox("Advanced/developer settings", default=False,
    #                                         enable_events=True, key="dev_layout_toggle")]

    dev_layout = [sg.Frame("Only touch these if you know what you're doing",
                [
                 [sg.Text("Settings cache file:"), sg.Text(
                     user_settings_file.get_filename())],
                 [sg.Button("Delete saved settings",
                            key="delete_saved_settings")],
                 profiles_listbox,
                ],
                key="dev_layout",
        )]

    log_output_layout = [
        [
            sg.OptionMenu(["WARNING", "INFO", "DEBUG"],
                          size=(10, 2), default_value="INFO", key="log_level"),
        ],
        [
            sg.Multiline(size=(140, 15), font=("arial", 12), key="log_output",
                      echo_stdout_stderr=True, reroute_stdout=True,
                      reroute_stderr=True,
                      write_only=True, auto_refresh=True,
                      disabled=True,
                      ),
        ]
    ]

    config_tab_layout = [
        [sg.Frame("User settings", user_settings_layout)],
    ]

    log_tab_layout = [
        [sg.Frame("Log output", log_output_layout)],
    ]

    developer_tab_layout = [
        [sg.Frame("Enable developer/advanced settings",
                  [dev_layout]),
         ],
    ]

    tab_group_layout = [
        [
            sg.Tab("Configuration", config_tab_layout, key="config_tab"),
            sg.Tab("Log output", log_tab_layout, key="log_tab"),
            sg.Tab("Advanced/developer settings",
                   developer_tab_layout, key="developer_tab"),
        ],
    ]

    layout = [
        [sg.Frame("Status", status_layout, pad=((5, 5), (5, 15)))],
        [sg.TabGroup(tab_group_layout, key="tab_group_layout",
                     pad=((55, 5), (5, 20))), ],
        [sg.Frame("User actions", user_actions_layout, vertical_alignment="center",
                  pad=((5, 5), (20, 5)),
                  )],
        # [
        #     sg.Button("hi order"),
        # ],
    ]

    layout[-1].append(sg.Sizegrip())

    state = types.SimpleNamespace(
        timer=BetterTimer(),
        settings=settings,
        saved_settings=saved_settings,
        running_settings=None,
        running=False,
        scoredata=ScoreData(),
    )
        # dev_layout_toggle=False)

    # TODO: in logger highlight error lines in colours

    try:
        window = sg.Window('Cricket Scorer - Spreadsheet selector', layout,
                finalize = True,
                # size = (800, 600),
                return_keyboard_events = True,
                resizable=True,
                font = ("arial", 13),
                )
        window.set_min_size((640, 480))

        # Have a printout on the GUI for errors? Logger specific printout? Wrap
        # Change it so that the GUI loop encompasses all
        # Then fix the logging
        # GUI element to show logging etc.
        # Check how logging file stuff works/doesn't
        # Then done

        done = False
        while not done:
            with sender_profiles.build_profile(state.settings["profile"]) as args:
                done = loop(window, state, args, user_settings_file)

        # while True:
            # with sender_profiles.build_profile(state.settings["profile"]) as args:
            # print("Arguments from profile used:", args)
            # sender_connection = connection.Sender(args)
                # if done:
                #     break

    finally:
        state.timer.summary()
        window.close()

def run(state, args):
    # FIXME: this and other stuff that can fail like networking stuff
    # Needs to be wrapped in try catches and log failures
    print("RUN with args:")
    print(args)
    print("RUN with state:")
    print(state)
    args.score_reader.refresh_excel(state.settings["spreadsheet_path"],
                    state.settings["worksheet"], state.settings["total"],
                    state.settings["wickets"], state.settings["overs"],
                    state.settings["innings"])

    state.running_settings = copy.deepcopy(state.settings)
    state.running = True

# TODO: yes
def loop(window, state, args, user_settings_file):

    connected = False
    done = False

    status_text_format_ok = {"background_color": "green"}
    status_text_format_warning = {"background_color": "red"}

    print("Initial state.settings[profile]", state.settings["profile"])

    printer = OnlyPrintOnDiff()
    # _print = lambda *args, **kwargs: printer.print(*args, **kwargs)
    _print = lambda *args, **kwargs: None

    window["settings_changed"].update(**status_text_format_warning)

    try:
        sender_connection = connection.Sender(args)
    except Exception as e:
        args.log.error(f"Problem initialising socket to listen for connection: {str(e)}")
    # sender_connection IS in scope here

    if state.running:
        run(state, args)

    sg.cprint("hi", text_color="red", window=window, key="log_output")
    state.timer.start("loop")
    while True:
        _print()

        state.timer.start("window.read")
        event, values = window.read(timeout = 10)
        state.timer.stop("window.read")
        # if values["spreadsheet_selector"]:
        #     values["spreadsheet"] = values["spreadsheet_selector"]
        #     settings["spreadsheet"] = values["spreadsheet_selector"]

        _print(event)

        if event == "Save":
            _print("Saving settings", state.settings)

            s = set(values.keys()) & set(state.settings.keys())
            _print([(k, state.settings[k], values[k]) for k in s if values[k] != state.settings[k]])

            user_settings_file.write_new_dictionary(state.settings)
            state.saved_settings = copy.deepcopy(state.settings)

        if event == "save_and_quit" or event == sg.WIN_CLOSED:
            print(args.score_reader)
            print(type(args.score_reader))
            user_settings_file.write_new_dictionary(state.settings)
            done = True
            break

        if event == "quit_without_saving":
            done = True
            break

        if event == "run":
            _print("Run")
            _print(state.settings)
            _print(values)
            s = set(values.keys()) & set(state.settings.keys())
            _print([(k, state.settings[k], values[k]) for k in s if values[k] != state.settings[k]])

            _print("Calling reader.start with " + str(state.settings))

            # In the event Run is clicked, and we're already running, and the profile
            # has been changed, need to break out of this loop so things like the socket
            # can be reacquired
            if not state.running:
                run(state, args)
            elif state.settings["profile"] != state.running_settings["profile"]:
                assert state.running
                assert state.running_settings["profile"] is not None
                done = False
                break

            # Convert Args to typing.ContextManager?
            # can simplify init stuff?
            # have this be a function, parameters including args and sender_connection
            # can make sure to close them cleanly
            # context managers more?
            # Need to properly consider, and handle closing of stuff now

        if event == "delete_saved_settings":
            user_settings_file.delete_file()
            state.saved_settings.clear()
            print("Deleting cached file")
            pass

        _print("Event, values:", event, values)
        _print(window["spreadsheet_path"])

        # if event == "dev_layout_toggle":
        #     if state.dev_layout_toggle:
        #         # Hide
        #         window["dev_layout"].update(visible=False)
        #         state.dev_layout_toggle = False
        #         window["dev_layout_toggle"].update(value = False)
        #     else:
        #         # Show
        #         window["dev_layout"].update(visible=True)
        #         state.dev_layout_toggle = True
        #         window["dev_layout_toggle"].update(value = True)

        for k, v in values.items():
            if k == "spreadsheet_selector":
                if v:
                    state.settings["spreadsheet_path"] = v
            elif k == "logs_folder_selector":
                if v:
                    state.settings["logs_folder"] = v
            elif k == "profile":
                if v:
                    assert isinstance(v, list)
                    assert len(v) == 1
                    cp = state.settings["profile"]
                    state.settings["profile"] = v[0]
                    if state.settings["profile"] != cp:
                        print("Updating state.settings[profile] to", state.settings["profile"])
            elif k == "tab_group_layout":
                pass
            elif k == "log_level":
                # TODO
                ...
            elif k in state.settings:
                state.settings[k] = v
            else:
                assert False, (f"Unhandled value in gui values \"{k}\": \"{v}\", "
                               "values: {values}")

        state.timer.start("reader")
        if state.running:
            old_scoredata = state.scoredata
            state.scoredata = args.score_reader.read_score()
            if old_scoredata != state.scoredata:
                _print("New scoredata:", state.scoredata)
        state.timer.stop("reader")

        state.timer.start("network poll")
        if state.running:
            sender_connection.poll(state.scoredata.score)
        state.timer.stop("network poll")

        if sender_connection.is_connected():
            connected = True
            window["is_connected"].update("Connected", **status_text_format_ok)
        else:
            window["is_connected"].update("Not connected",
                                          **status_text_format_warning)
            if connected:
                connected = False
                state.timer.start("desktop notify disconnect")
                notify_disconnected("cricket-scorer disconnected",
                                    "cricket-scorer has lost connection")
                state.timer.stop("desktop notify disconnect")

        if state.running:
            window["is_running"].update("Running", **status_text_format_ok)
        else:
            window["is_running"].update(
                "Not running", **status_text_format_warning)

        if state.running and state.settings != state.running_settings:
            window["settings_changed"].update(visible=True)
        else:
            window["settings_changed"].update(visible=False)

        # Update gui
        # if values["spreadsheet_selector"]:
        # window["spreadsheet_text"].update(values["spreadsheet_selector"])
        # state.settings["spreadsheet"] = values["spreadsheet_selector"]

        #  _print(state.settings)
        #  _print(values)
        s = set(values.keys()) & set(state.settings.keys())
        _print([(k, state.settings[k], values[k]) for k in s if values[k] != state.settings[k]])
        _print("state.Settings:", state.settings)
        _print("Saved settings:", state.saved_settings)
        _print("Values:", values)
        # if saved_settings != settings:
        # if any(True for k in s if values[k] != settings[k]):
        #  if values != settings:
        _print("Updating")

        # else:
            # _print("Not showing")
            # window["run_label"].update(visible = False)

        #  if values == last_values:
            #  continue

            #  #  _print("Updating!")
            #  #  _print("spreadsheet now:", spreadsheet)
        #  if values["sheet"]:
            #  settings["sheet"] = values["sheet"]
            #  #  _print("spreadsheet now:", spreadsheet)
            #  window["sheet"].update(settings["sheet"])

        printer.print_contents_if_diff()
        #  printer = OnlyPrintOnDiff(printer)
    #  print("Selected file at", values["Browse"])

    state.timer.stop("loop")
    state.running_settings = None
    printer.print_contents_if_diff()
    return done

if __name__ == "__main__":
    multiprocessing.freeze_support()
    sys.exit(main())
