# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
#
from board import CKP, CKN, D0P, D0N, D1P, D1N, D2P, D2N
import displayio
from displayio import Bitmap, Group, OnDiskBitmap, Palette, TileGrid
import framebufferio
import gc
import picodvi
import supervisor
from terminalio import FONT
from time import sleep
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
        (bitmap, palette) = adafruit_imageload.load("sprites.bmp",
            bitmap=Bitmap, palette=Palette)
        # assemble TileGrid with gamepad using sprites from the spritesheet
        scene = TileGrid(bitmap, pixel_shader=palette, width=10, height=5,
            tile_width=8, tile_height=8, default_tile=9, x=8, y=8)
        tilemap = (
            (0, 5, 2, 3, 3, 3, 3, 4, 5, 6),            # . L . . . . . . R .
            (7, 9, 12, 9, 9, 9, 9, 17, 9, 13),         # . . dU. . . . X . .
            (7, 18, 19, 20, 9, 9, 17, 9, 17, 13),      # . dL. dR. . Y . A .
            (7, 9, 26, 9, 24, 25, 9, 17, 9, 13),       # . . dD. SeSt. B . .
            (21, 23, 23, 23, 23, 23, 23, 23, 23, 27),  # . . . . . . . . . .
        )
        for (y, row) in enumerate(tilemap):
            for (x, sprite) in enumerate(row):
                scene[x, y] = sprite
        group.append(scene)

        # Make a text label for status messages
        status = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
        status.line_spacing = 1.0
        status.anchor_point = (0, 0)
        status.anchored_position = (8, 54)
        group.append(status)

        # Make a separate text label for input event report data
        report = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
        report.line_spacing = 1.0
        report.anchor_point = (0, 0)
        report.anchored_position = (8, 54 + (12*4))
        group.append(report)

        self.display = display
        self.group = group
        self.bitmap = bitmap
        self.palette = palette
        self.scene = scene
        self.tilemap = tilemap
        self.status = status
        self.report = report

    def input_event(self, buttons, diff, refresh=True):
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
        scene = self.scene
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
        if refresh:
            self.display.refresh()

    def set_status(self, msg, refresh=True):
        # Status label updater
        self.status.text = msg
        if refresh:
            self.display.refresh()

    def set_report(self, data, refresh=True):
        # Input event report updater
        if data is None:
            self.report.text = ''
        elif isinstance(data, str):
            self.report.text = data
        else:
            msg = ' '.join(['%02x' % b for b in data])
            self.report.text = msg
        if refresh:
            self.display.refresh()


def main():

    # Configure display with requested picodvi video mode
    display = init_display(320, 240, 16)
    display.auto_refresh = False
    group = Group(scale=2)  # 2x zoom
    display.root_group = group

    # This manages all the graphics stuff for the gamepad visualizers
    gpviz = GamepadVisualizer(display, group)

    while True:
        gpviz.set_report(None, refresh=False)
        gpviz.set_status("No gamepads...")
        gc.collect()
        try:
            dev = find_usb_device()
            if dev is None:
                # No connection yet, so sleep briefly then try the find again
                sleep(0.4)
                continue
            # Found an input device, so update display with device info
            info = dev.tag if dev.tag else "%04X:%04X" % (dev.vid, dev.pid)
            gpviz.set_status(info)

            # Poll for input events until USB exception (device unplug)
            prev = 0
            for data in dev.input_event_generator():
                if data is None:
                    # This means polling was rate limited or USB timed out
                    continue
                # At this point, data should be a uint16 bitfield
                diff = prev ^ data
                prev = data
                gpviz.input_event(data, diff, refresh=False)
                gpviz.set_report('%04x' % data)
        except USBError as e:
            # This sometimes happens when devices are unplugged.
            print("USBError:", e)
        except USBTimeoutError as e:
            # This sometimes happens when devices are unplugged.
            print("USBTimeoutError:", e)
        except ValueError as e:
            # This can happen if an initialization handshake glitches
            print("ValueError:", e)


main()
