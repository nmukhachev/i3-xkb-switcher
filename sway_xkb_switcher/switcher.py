#!/usr/bin/env python3

import argparse
import asyncio
import atexit
import logging
import os
from tempfile import gettempdir

from i3ipc import Event
from i3ipc.aio import Connection
from i3ipc.events import WindowEvent

__version__ = "0.3.0"

class State:
    def __init__(self, conn: Connection, default_lang: str):                                                                                                   
        self._last_id = -1
        self._lang_state = {}
        self._connection = conn
        self._default_lang = default_lang

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

    async def _set_lang(self, lang):
        if isinstance(lang, str): # just a layout name
            inputs = await self._connection.get_inputs()
            for inp in inputs:
                if inp.type == 'keyboard':
                    for layout_index, layout_name in enumerate(inp.xkb_layout_names):
                        if lang == layout_name:
                            await self._connection.command(f"input {inp.identifier} xkb_switch_layout {layout_index}")
        else: # input id to layout index map
            for input_id in lang:
                await self._connection.command(f"input {input_id} xkb_switch_layout {lang[input_id]}")

    async def _get_lang(self) -> {}:
        input_to_layout_index = {}
        inputs = await self._connection.get_inputs()
        for i in inputs:
            if i.type == 'keyboard':
                input_to_layout_index[i.identifier] = i.xkb_active_layout_index

        return input_to_layout_index

async def _entrypoint(default_lang: str):
    conn = await Connection(auto_reconnect=True).connect()

    st = State(conn, default_lang)

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
    _start(args.default_lang)


def _start(default_lang):
    try:
        asyncio.get_event_loop().run_until_complete(_entrypoint(default_lang))
    except KeyboardInterrupt:
        logging.debug("shutdown")


def _create_path(path: str):
    if not os.path.isfile(path):
        dir_ = os.path.dirname(path)
        if dir_:
            os.makedirs(dir_, exist_ok=True)


if __name__ == "__main__":
    main()
