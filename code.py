# SPDX-License-Identifier: MIT
# SPDX-FileCopyrightText: Copyright 2024 Sam Blenny
#
from board import CKP, CKN, D0P, D0N, D1P, D1N, D2P, D2N
from displayio import (Bitmap, Group, OnDiskBitmap, Palette, TileGrid,
    release_displays)
from framebufferio import FramebufferDisplay
import gc
from picodvi import Framebuffer
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


def update_GUI(scene, buttons, diff):
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

def main():

    # Make sure display is configured for 320x240 8-bit
    display = supervisor.runtime.display
    if (display is None) or display.width != 320:
        release_displays()
        gc.collect()
        fb = Framebuffer(320, 240, clk_dp=CKP, clk_dn=CKN,
            red_dp=D0P, red_dn=D0N, green_dp=D1P, green_dn=D1N,
            blue_dp=D2P, blue_dn=D2N, color_depth=8)
        display = FramebufferDisplay(fb)
        supervisor.runtime.display = display
    display.auto_refresh = False
    grp = Group(scale=2)  # 2x zoom
    display.root_group = grp

    # load spritesheet and palette
    (bitmap, palette) = adafruit_imageload.load("sprites.bmp", bitmap=Bitmap,
        palette=Palette)
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
    grp.append(scene)

    # Make a text label for status messages
    status = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
    status.line_spacing = 1.0
    status.anchor_point = (0, 0)
    status.anchored_position = (8, 54)
    grp.append(status)

    # Make a separate text label for input event report data
    report = bitmap_label.Label(FONT, text="", color=0xFFFFFF, scale=1)
    report.line_spacing = 1.0
    report.anchor_point = (0, 0)
    report.anchored_position = (8, 54 + (12*4))
    grp.append(report)

    # Define status label updater with access to local vars from main()
    def set_status(msg):
        status.text = msg
        display.refresh()

    # Define report label updater with access to local vars from main()
    def set_report(data):
        if data is None:
            report.text = ''
        elif isinstance(data, str):
            report.text = data
        else:
            msg = ' '.join(['%02x' % b for b in data])
            report.text = msg
        display.refresh()

    while True:
        set_report("Finding gamepad 1...")
        gc.collect()
        device_cache = {}
        try:
            scan_result = find_usb_device(device_cache)
            if scan_result is None:
                # No connection yet, so sleep briefly then try the find again
                sleep(0.4)
                continue
            # Found an input device, so try to configure it and start polling
            dev = InputDevice(scan_result)
            sr = scan_result
            if sr.tag:
                set_status(sr.tag)
            else:
                set_status("%04X:%04X" % (sr.vid, sr.pid))

            # Poll for input events until USB error
            prev = 0
            for data in dev.input_event_generator():
                if data is None:                  # Rate limit or USB timedout
                    continue
                elif isinstance(data, int):       # SNES-like uint16 bitfield
                    diff = prev ^ data
                    prev = data
                    update_GUI(scene, data, diff)
                    set_report('%04x' % data)
                else:                             # Raw HID report bytes
                    set_report(data)
        except USBError as e:
            # This sometimes happens when devices are unplugged. Not always.
            print(e)
        except ValueError as e:
            # This can happen if an initialization handshake glitches
            print(e)


main()
