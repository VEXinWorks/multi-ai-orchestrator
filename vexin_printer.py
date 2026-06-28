#!/usr/bin/env python3
"""
vexin_printer.py — Direct printer control via SDCP v3.0 WebSocket protocol

Works without auth (printer is on trusted Tailscale network).
Targets the Elegoo Centauri Carbon at 192.168.100.119 or vexinworks-web:3030.
"""

import asyncio
import json
import sys
import os
import time
import argparse
import websockets
from urllib.parse import urlparse

# Default target
DEFAULT_HOST = os.environ.get("PRINTER_HOST", "vexinworks-web")
DEFAULT_PORT = int(os.environ.get("PRINTER_PORT", "3030"))

class CentauriCarbon:
    def __init__(self, host=DEFAULT_HOST, port=DEFAULT_PORT):
        self.uri = f"ws://{host}:{port}/websocket"
        self.ws = None
        self.request_id = 1
        self.last_status = None

    async def connect(self):
        self.ws = await websockets.connect(self.uri, ping_interval=None, close_timeout=5)
        print(f"[+] Connected to {self.uri}", file=sys.stderr)
        return self.ws

    async def close(self):
        if self.ws:
            await self.ws.close()

    async def send_cmd(self, cmd, data=None, timeout=10):
        """Send a SDCP command and return the response."""
        msg_id = str(self.request_id)
        self.request_id += 1
        msg = {
            "Id": msg_id,
            "Data": {"Cmd": cmd, **({"Data": data} if data else {})}
        }
        await self.ws.send(json.dumps(msg))
        try:
            resp = await asyncio.wait_for(self.ws.recv(), timeout=timeout)
            return json.loads(resp)
        except asyncio.TimeoutError:
            return {"error": "timeout"}

    async def get_status(self):
        """Cmd 0 = GetStatus"""
        return await self.send_cmd(0)

    async def get_attributes(self):
        """Cmd 1 = GetAttributes"""
        return await self.send_cmd(1)

    async def push_status(self):
        """Cmd 128 = PushStatus (subscribe to updates)"""
        return await self.send_cmd(128)

    async def start_print(self, filename, plate=None, timelapse=False, bed_leveling=True):
        """Cmd 256 = StartPrint - filename relative to printer's storage"""
        data = {
            "Filename": filename,
            "Timelapse": timelapse,
            "BedLeveling": bed_leveling,
        }
        if plate is not None:
            data["PlateIdx"] = plate
        return await self.send_cmd(256, data)

    async def pause_print(self):
        """Cmd 129 = PausePrint"""
        return await self.send_cmd(129)

    async def resume_print(self):
        """Cmd 131 = ResumePrint"""
        return await self.send_cmd(131)

    async def cancel_print(self):
        """Cmd 130 = CancelPrint"""
        return await self.send_cmd(130)

    async def set_light(self, on=True):
        """Cmd 403 = SetLight — note: command value is INVERTED (0=ON, 1=OFF)"""
        # From the printer protocol doc
        return await self.send_cmd(403, {"LightStatus": {"SecondLight": 0 if on else 1}})

    async def set_nozzle_temp(self, temp):
        return await self.send_cmd(33, {"TempTargetNozzle": temp})

    async def set_bed_temp(self, temp):
        return await self.send_cmd(33, {"TempTargetHotbed": temp})

    async def move(self, x=None, y=None, z=None, speed=3000):
        """Send G-code move via Cmd 258"""
        gcode = f"G0"
        if x is not None: gcode += f" X{x}"
        if y is not None: gcode += f" Y{y}"
        if z is not None: gcode += f" Z{z}"
        gcode += f" F{speed}"
        return await self.send_cmd(258, {"Cmd": gcode})

    async def send_gcode(self, gcode):
        """Send arbitrary G-code"""
        return await self.send_cmd(258, {"Cmd": gcode})

    async def list_files(self, path="/"):
        """Cmd 258 = ListFiles via SDCP, but easier via direct G-code listing"""
        return await self.send_cmd(258, {"Cmd": f"M20 {path}"})

    async def home_axes(self, axes="XYZ"):
        return await self.send_cmd(258, {"Cmd": f"G28 {axes}"})

    async def disable_motors(self):
        return await self.send_cmd(258, {"Cmd": "M84"})


async def main():
    parser = argparse.ArgumentParser(description="Centauri Carbon direct control")
    sub = parser.add_subparsers(dest="cmd")

    # status
    p_status = sub.add_parser("status", help="get printer status")
    p_status.add_argument("--host", default=DEFAULT_HOST)
    p_status.add_argument("--port", type=int, default=DEFAULT_PORT)
    p_status.add_argument("--watch", "-w", type=int, default=0,
                          help="refresh every N seconds (0 = once)")

    # light
    p_light = sub.add_parser("light", help="toggle chamber light")
    p_light.add_argument("state", choices=["on", "off"])
    p_light.add_argument("--host", default=DEFAULT_HOST)
    p_light.add_argument("--port", type=int, default=DEFAULT_PORT)

    # temp
    p_temp = sub.add_parser("temp", help="set temperatures")
    p_temp.add_argument("--nozzle", type=int, default=None)
    p_temp.add_argument("--bed", type=int, default=None)
    p_temp.add_argument("--host", default=DEFAULT_HOST)
    p_temp.add_argument("--port", type=int, default=DEFAULT_PORT)

    # pause/resume/cancel
    for cmd_name in ["pause", "resume", "cancel"]:
        p = sub.add_parser(cmd_name, help=f"{cmd_name} current print")
        p.add_argument("--host", default=DEFAULT_HOST)
        p.add_argument("--port", type=int, default=DEFAULT_PORT)

    # send gcode
    p_gcode = sub.add_parser("gcode", help="send arbitrary G-code")
    p_gcode.add_argument("gcode", help="G-code command(s), space-separated")
    p_gcode.add_argument("--host", default=DEFAULT_HOST)
    p_gcode.add_argument("--port", type=int, default=DEFAULT_PORT)

    # start print
    p_print = sub.add_parser("print", help="start a print")
    p_print.add_argument("filename", help="filename on printer (e.g., 'Hulk.gcode')")
    p_print.add_argument("--host", default=DEFAULT_HOST)
    p_print.add_argument("--port", type=int, default=DEFAULT_PORT)

    args = parser.parse_args()
    if not args.cmd:
        parser.print_help()
        sys.exit(1)

    host = getattr(args, "host", DEFAULT_HOST)
    port = getattr(args, "port", DEFAULT_PORT)
    printer = CentauriCarbon(host, port)

    try:
        await printer.connect()

        if args.cmd == "status":
            if args.watch > 0:
                while True:
                    result = await printer.get_status()
                    status = result.get("Status", {})
                    print(json.dumps(status, indent=2)[:600])
                    print("---")
                    time.sleep(args.watch)
            else:
                result = await printer.get_status()
                status = result.get("Status", {})
                pi = status.get("PrintInfo", {})
                print(f"Status code: {status.get('CurrentStatus')}")
                print(f"Nozzle: {status.get('TempOfNozzle', 0):.1f}°C / target {status.get('TempTargetNozzle', 0)}°C")
                print(f"Bed:    {status.get('TempOfHotbed', 0):.1f}°C / target {status.get('TempTargetHotbed', 0)}°C")
                print(f"Box:    {status.get('TempOfBox', 0):.1f}°C")
                print(f"Position: {status.get('CurrenCoord')}")
                print(f"Print: layer {pi.get('CurrentLayer')}/{pi.get('TotalLayer')} (status code {pi.get('Status')})")
                print(f"Light: {status.get('LightStatus', {}).get('SecondLight')}")
                if pi.get('Progress'):
                    print(f"Progress: {pi.get('Progress')}%")

        elif args.cmd == "light":
            on = args.state == "on"
            result = await printer.set_light(on)
            print(f"light {args.state}: {result.get('Status', result)}")

        elif args.cmd == "temp":
            if args.nozzle is not None:
                r = await printer.set_nozzle_temp(args.nozzle)
                print(f"nozzle target {args.nozzle}°C: {r.get('Status', r)}")
            if args.bed is not None:
                r = await printer.set_bed_temp(args.bed)
                print(f"bed target {args.bed}°C: {r.get('Status', r)}")

        elif args.cmd in ("pause", "resume", "cancel"):
            method = getattr(printer, f"{args.cmd}_print")
            result = await method()
            print(f"{args.cmd}: {result.get('Status', result)}")

        elif args.cmd == "gcode":
            result = await printer.send_gcode(args.gcode)
            print(f"gcode {args.gcode!r}: {result}")

        elif args.cmd == "print":
            result = await printer.start_print(args.filename)
            print(f"start {args.filename}: {result}")

    finally:
        await printer.close()


if __name__ == "__main__":
    asyncio.run(main())
