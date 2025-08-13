# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
#
import asyncio
from board import CKP, CKN, D0P, D0N, D1P, D1N, D2P, D2N
import displayio
from displayio import Bitmap, Group, OnDiskBitmap, Palette, TileGrid
import framebufferio
import gc
import picodvi
import supervisor
from terminalio import FONT
import time
from usb.core import USBError, USBTimeoutError
import usb_host

from adafruit_display_text import bitmap_label
import adafruit_imageload
import adafruit_logging as logging

from sb_gamepad import (
    find_usb_device, InputDevice,
    UP, DOWN, LEFT, RIGHT, START, SELECT, L, R, A, B, X, Y)


def init_display(width, height, color_depth):
    # Initialize the picodvi display
    # Video mode compatibility:
    # | Video Mode     | Fruit Jam | Metro RP2350 No PSRAM    |
    # | -------------- | --------- | ------------------------ |
    # | (320, 240,  8) | Yes!      | Yes!                     |
    # | (320, 240, 16) | Yes!      | Yes!                     |
    # | (320, 240, 32) | Yes!      | MemoryError exception :( |
    # | (640, 480,  8) | Yes!      | MemoryError exception :( |
    displayio.release_displays()
    gc.collect()
    fb = picodvi.Framebuffer(width, height, clk_dp=CKP, clk_dn=CKN,
        red_dp=D0P, red_dn=D0N, green_dp=D1P, green_dn=D1N,
        blue_dp=D2P, blue_dn=D2N, color_depth=color_depth)
    display = framebufferio.FramebufferDisplay(fb)
    supervisor.runtime.display = display
    return display


class GamepadVisualizer:

    def __init__(self, display, group):
        # load spritesheet and palette
        (bitmap, palette) = adafruit_imageload.load("sprites2x.bmp",
            bitmap=Bitmap, palette=Palette)
        # assemble TileGrid with gamepad using sprites from the spritesheet
        scene_1 = TileGrid(bitmap, pixel_shader=palette, width=10, height=5,
            tile_width=16, tile_height=16, default_tile=9, x=16, y=16)
        scene_2 = TileGrid(bitmap, pixel_shader=palette, width=10, height=5,
            tile_width=16, tile_height=16, default_tile=9, x=142, y=128)
        tilemap = (
            (0, 5, 2, 3, 3, 3, 3, 4, 5, 6),            # . L . . . . . . R .
            (7, 9, 12, 9, 9, 9, 9, 17, 9, 13),         # . . dU. . . . X . .
            (7, 18, 19, 20, 9, 9, 17, 9, 17, 13),      # . dL. dR. . Y . A .
            (7, 9, 26, 9, 24, 25, 9, 17, 9, 13),       # . . dD. SeSt. B . .
            (21, 23, 23, 23, 23, 23, 23, 23, 23, 27),  # . . . . . . . . . .
        )
        for (y, row) in enumerate(tilemap):
            for (x, sprite) in enumerate(row):
                scene_1[x, y] = sprite
                scene_2[x, y] = sprite
        group.append(scene_1)
        group.append(scene_2)

        # Make a text label for status messages
        status_1 = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
        status_1.anchor_point = (0, 0)
        status_1.anchored_position = (22, 100)
        group.append(status_1)

        # Make a separate text label for input event report data
        status_2 = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
        status_2.anchor_point = (0, 0)
        status_2.anchored_position = (148, 212)
        group.append(status_2)

        self.display = display
        self.group = group
        self.bitmap = bitmap
        self.palette = palette
        self.scene_1 = scene_1
        self.scene_2 = scene_2
        self.tilemap = tilemap
        self.status_1 = status_1
        self.status_2 = status_2


    def input_event(self, buttons, diff, player=1):
        # Update TileGrid sprites to reflect changed state of gamepad buttons
        # Scene is 10 sprites wide by 5 sprites tall:
        #  Y
        #  0 . L . . . . . . R .
        #  1 . . dU. . . . X . .
        #  2 . dL. dR. . Y . A .
        #  3 . . dD. SeSt. B . .
        #  4 . . . . . . . . . .
        #    0 1 2 3 4 5 6 7 8 9 X
        #
        if player == 2:
            scene = self.scene_2
        else:
            scene = self.scene_1
        if diff & A:
            scene[8, 2] = 15 if (buttons & A) else 17
        if diff & B:
            scene[7, 3] = 15 if (buttons & B) else 17
        if diff & X:
            scene[7, 1] = 15 if (buttons & X) else 17
        if diff & Y:
            scene[6, 2] = 15 if (buttons & Y) else 17
        if diff & L:
            scene[1, 0] = 1 if (buttons & L) else 5
        if diff & R:
            scene[8, 0] = 1 if (buttons & R) else 5
        if diff & UP:
            scene[2, 1] = 8 if (buttons & UP) else 12
        if diff & DOWN:
            scene[2, 3] = 22 if (buttons & DOWN) else 26
        if diff & LEFT:
            scene[1, 2] = 14 if (buttons & LEFT) else 18
        if diff & RIGHT:
            scene[3, 2] = 16 if (buttons & RIGHT) else 20
        if diff & SELECT:
            scene[4, 3] = 10 if (buttons & SELECT) else 24
        if diff & START:
            scene[5, 3] = 11 if (buttons & START) else 25
        self.display.refresh()


    def set_status(self, msg, player=1):
        # Status label updater
        if player == 2:
            self.status_2.text = msg
        else:
            self.status_1.text = msg
        self.display.refresh()


async def gamepad_loop(gpviz, player=1):
    # Find a gamepad, poll for input, dispatch events to visualizer.
    # - gpviz: a GamepadVisualizer instance to receive input events
    # - player: 1 or 2 (which usb port to use)
    while True:
        if player == 1:
            gc.collect()
        gpviz.set_status("Player %d: [No Controller]" % player, player=player)
        await asyncio.sleep(0.002)
        try:
            dev = find_usb_device(player=player)
            if dev is None:
                # No connection yet, so sleep briefly then try the find again
                await asyncio.sleep(0.4)
                continue
            # Found an input device, so update display with device info
            info = dev.tag if dev.tag else "%04X:%04X" % (dev.vid, dev.pid)
            gpviz.set_status("Player %d: %s" % (player, info), player=player)

            # Poll for input events until USB exception (device unplug)
            prev = 0
            for data in dev.input_event_generator():
                if data is None:
                    # This means polling was rate limited or USB timed out
                    await asyncio.sleep(0.001)
                    continue
                # At this point, data should be a uint16 bitfield
                diff = prev ^ data
                prev = data
                gpviz.input_event(data, diff, player=player)
        except USBError as e:
            # This sometimes happens when devices are unplugged.
            print("USBError:", e)
        except USBTimeoutError as e:
            # This sometimes happens when devices are unplugged.
            print("USBTimeoutError:", e)
        except ValueError as e:
            # This can happen if an initialization handshake glitches
            print("ValueError:", e)


async def main():
    # Configure display with requested picodvi video mode
    display = init_display(320, 240, 16)
    display.auto_refresh = False
    group = Group(scale=1)  # 2x zoom
    display.root_group = group

    # This manages all the graphics stuff for the gamepad visualizers
    gpviz = GamepadVisualizer(display, group)

    # Start the 2-player input event loops
    await asyncio.gather(
        asyncio.create_task(gamepad_loop(gpviz, player=1)),
        asyncio.create_task(gamepad_loop(gpviz, player=2)),
    )


asyncio.run(main())
