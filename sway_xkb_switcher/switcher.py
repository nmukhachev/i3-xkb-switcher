#!/usr/bin/env python3

import argparse
import asyncio
import atexit
import logging
import os
from tempfile import gettempdir
from typing import List

from i3ipc import Event
from i3ipc.aio import Connection
from i3ipc.events import WindowEvent
from i3ipc.replies import InputReply

__version__ = "0.2.5"

class State:
    def __init__(self, conn: Connection, inputs: List[InputReply], input_identifier: str, default_lang: str):
        self._last_id = -1
        self._lang_state = {}
        self._connection = conn
        self._input_identifier = input_identifier

        for index, sway_input in enumerate(inputs):
            if sway_input.identifier == self._input_identifier:
                self._input_index = index

        if default_lang is None:
            self._default_lang = None
        else:
            for index, lang in enumerate(inputs[self._input_index].xkb_layout_names):
                if lang == default_lang:
                    self._default_lang = index

    async def window_focus(self, _: Connection, event: WindowEvent):
        current_id = event.container.id
        logging.debug("Window focus, id %d", current_id)

        if self._last_id == current_id:
            return
        
        current_lang = await self._get_lang()

        if self._last_id > 0:
            self._lang_state[self._last_id] = current_lang

        if self._default_lang is None:
            default_lang = current_lang
        else:
            default_lang = self._default_lang

        lang = self._lang_state.get(current_id, default_lang)

        await self._set_lang(lang)

        self._last_id = current_id

        logging.debug(self._lang_state)

    def window_close(self, _: Connection, event: WindowEvent):
        id_ = event.container.id
        logging.debug("Windown close, id %d", id_)

        try:
            del self._lang_state[id_]
        except KeyError:
            pass
        finally:
            self._last_id = -1

    async def _set_lang(self, lang: int):
        await self._connection.command(
            f"input {self._input_identifier} xkb_switch_layout {lang}"
        )

    async def _get_lang(self) -> int:
        inputs = await self._connection.get_inputs()
        return inputs[self._input_index].xkb_active_layout_index


async def _entrypoint(input_identifier: str, default_lang: str):
    conn = await Connection(auto_reconnect=True).connect()
    inputs = await conn.get_inputs()

    st = State(conn, inputs, input_identifier, default_lang)

    conn.on(Event.WINDOW_FOCUS, st.window_focus)
    conn.on(Event.WINDOW_CLOSE, st.window_close)

    await conn.main()


def _parse_args():
    parser = argparse.ArgumentParser(
        description="Individual keyboard layout for each i3 window"
    )
    parser.add_argument(
        "--debug",
        action="store_const",
        const=True,
        default=False,
        help="enable debug (default: false)",
    )
    parser.add_argument(
        "--version",
        action="store_const",
        const=True,
        default=False,
        help="print version and exit",
    )
    parser.add_argument(
        "--log-path", action="store", default="", help="log file path",
    )
    parser.add_argument(
        "--background",
        action="store_const",
        const=True,
        default=False,
        help="run in background (default: false)",
    )
    parser.add_argument(
        "--input-identifier", "-i",
        action="store",
        default="1:1:AT_Translated_Set_2_keyboard",
        help="keyboard identifier from output of swaymsg -t get_inputs"
    )
    parser.add_argument(
        "--default-lang", "-D",
        action="store",
        default=None,
        help="default keyboard layout for new windows"
    )

    return parser.parse_known_args()[0]


def _build_log_config(args):
    basic_cfg = dict(
        format="%(asctime)s - %(levelname)s - %(message)s",
        datefmt="%H:%M:%S",
        level=logging.DEBUG if args.debug else logging.CRITICAL,
    )

    if args.log_path != "":
        _create_path(args.log_path)
        basic_cfg["filename"] = args.log_path
        basic_cfg["filemode"] = "a"

    return basic_cfg


def main():
    args = _parse_args()

    if args.version:
        print(__version__)
        return

    # try lock process
    path = os.path.join(gettempdir(), "sway-xkb-switcher.lock")

    try:
        fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_EXCL)
    except FileExistsError:
        print("can not open lock file: " + path + ". process already exists?")
        return

    def _cleanup():
        os.close(fd)
        os.remove(path)

    logging.basicConfig(**_build_log_config(args))

    logging.debug("Start version: %s", __version__)

    if args.background:
        pid = os.fork()
        if pid != 0:
            logging.debug("Forked to: %d", pid)
            return

    atexit.register(_cleanup)
    os.write(fd, str(os.getpid()).encode())
    _start(args.input_identifier, args.default_lang)


def _start(input_identifier, default_lang):
    try:
        asyncio.get_event_loop().run_until_complete(_entrypoint(input_identifier, default_lang))
    except KeyboardInterrupt:
        logging.debug("shutdown")


def _create_path(path: str):
    if not os.path.isfile(path):
        dir_ = os.path.dirname(path)
        if dir_:
            os.makedirs(dir_, exist_ok=True)


if __name__ == "__main__":
    main()
