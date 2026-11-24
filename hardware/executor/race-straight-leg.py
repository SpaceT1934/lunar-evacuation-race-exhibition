import argparse
import importlib.util
import json
import math
from pathlib import Path
import signal
import socket
import sys
import time


path = Path(__file__).with_name('straight-turn.py')
spec = importlib.util.spec_from_file_location('moonfall_straight_turn', path)
control = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = control
spec.loader.exec_module(control)


def interrupted(_signal, _frame):
    raise KeyboardInterrupt


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('vehicle', choices=control.ROVERS)
    parser.add_argument('stage', choices=(1, 2, 3), type=int)
    parser.add_argument('start_x', type=float)
    parser.add_argument('start_y', type=float)
    parser.add_argument('duration_s', type=float)
    args = parser.parse_args()
    rover = control.ROVERS[args.vehicle]
    camera = control.Camera(rover)
    position = camera.read(seconds=10)
    status = control.rover_status(rover)
    if status['L'] or status['R']:
        raise RuntimeError('车未停稳')
    if args.stage == 1:
        problem = control.preflight(rover, position)
        if problem:
            raise RuntimeError(problem)
    direction = -1 if args.stage == 2 else 1
    heading = rover.right_heading + (math.pi if direction < 0 else 0)
    endpoints = [args.start_x, args.start_x + control.OUTBOUND_MM, args.start_x + 100,
                 args.start_x + control.OUTBOUND_MM]
    if (math.hypot(position[0] - endpoints[args.stage - 1], position[1] - args.start_y) > 35
            or abs(control.wrap(heading - position[2])) > 0.22):
        raise RuntimeError(f'ID {rover.tag} 第 {args.stage} 段起点或朝向不符')
    target_x = endpoints[args.stage]
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        def send(left, right):
            udp.sendto(f'{round(left)},{round(right)}'.encode(), (rover.ip, 8888))

        try:
            control.drive_straight(rover, camera, send, position, target_x, direction, args.duration_s)
            send(0, 0)
            time.sleep(.45)
            end = camera.read()
            if args.stage < 3:
                heading += math.pi
                end = control.turn_and_settle(
                    rover, camera, send, end, target_x, args.start_y, heading
                )
            settled = control.rover_status(rover)
            if settled['L'] or settled['R'] or math.hypot(end[0] - target_x, end[1] - args.start_y) > 35:
                raise RuntimeError('停车后位置或轮速不符合换段要求')
            print(json.dumps({'stage': args.stage, 'position_mm': end[:2], 'stopped': True}))
        finally:
            send(0, 0)


if __name__ == '__main__':
    signal.signal(signal.SIGTERM, interrupted)
    try:
        main()
    except (RuntimeError, OSError, KeyboardInterrupt) as error:
        print(f'{error or "实车已停止"}', file=sys.stderr)
        sys.exit(1)
