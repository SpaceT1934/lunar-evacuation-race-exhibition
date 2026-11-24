import argparse
import base64
import json
import math
import socket
import sys
import time
import urllib.request
from dataclasses import dataclass
from urllib.error import URLError

import cv2
import numpy as np


CAMERA_URL = 'http://127.0.0.1:4182/live-frame'
ANCHOR_IDS = (5, 6, 7, 4)
FIELD_MM = np.float32([[0, 0], [747, 0], [747, 337], [0, 337]])
OUTBOUND_MM = 478
HEADING_TOLERANCE = math.radians(4)
HTTP = urllib.request.build_opener(urllib.request.ProxyHandler({}))


@dataclass(frozen=True)
class Rover:
    ip: str
    tag: int
    right_heading: float
    start_y: tuple[int, int]


ROVERS = {
    'blue': Rover('192.168.116.40', 1, math.radians(-88.65), (40, 86)),
    'gold': Rover('192.168.116.122', 0, math.radians(-1.7), (245, 288)),
}


def read_json(url, timeout):
    with HTTP.open(url, timeout=timeout) as response:
        return json.load(response)


def rover_status(rover):
    return read_json(f'http://{rover.ip}/status', 3)


def wrap(angle):
    return math.atan2(math.sin(angle), math.cos(angle))


def clamp(value, low, high):
    return max(low, min(high, value))


class Camera:
    def __init__(self, rover):
        dictionary = cv2.aruco.getPredefinedDictionary(cv2.aruco.DICT_APRILTAG_36H11)
        params = cv2.aruco.DetectorParameters()
        params.minDistanceToBorder = 1
        self.detector = cv2.aruco.ArucoDetector(dictionary, params)
        self.rover = rover
        self.required_tags = (*ANCHOR_IDS, rover.tag)
        self.stamp = 0
        self.anchors = None
        self.matrix = None

    def read(self, seconds=4):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                frame = read_json(CAMERA_URL, 1)
                if frame.get('stamp', 0) > self.stamp and frame.get('age', 999) < 180:
                    pose = self.detect(frame)
                    if pose is not None:
                        self.stamp = frame['stamp']
                        return pose
            except (URLError, TimeoutError, ValueError, KeyError):
                pass
            time.sleep(0.07)
        raise TimeoutError(f'相机未提供新鲜的 ID {self.rover.tag} 及四角定位')

    def detect(self, frame):
        image = np.frombuffer(base64.b64decode(frame['image']), np.uint8)
        gray = cv2.imdecode(image, cv2.IMREAD_GRAYSCALE)
        if gray is None:
            return None
        padded = cv2.copyMakeBorder(gray, 32, 32, 32, 32, cv2.BORDER_CONSTANT, value=250)
        corners, ids, _ = self.detector.detectMarkers(padded)
        if ids is None or not all(tag_id in ids for tag_id in self.required_tags):
            sharpened = cv2.addWeighted(padded, 2, cv2.GaussianBlur(padded, (5, 5), 0), -1, 0)
            corners, ids, _ = self.detector.detectMarkers(sharpened)
        if ids is None or not all(tag_id in ids for tag_id in self.required_tags):
            return None
        tags = {
            int(tag_id): points.reshape(4, 2) - 32
            for tag_id, points in zip(ids.ravel(), corners)
        }
        anchors = np.float32([tags[tag_id].mean(axis=0) for tag_id in ANCHOR_IDS])
        if self.matrix is None:
            self.anchors = anchors
            self.matrix = cv2.getPerspectiveTransform(anchors, FIELD_MM)
        if np.max(np.linalg.norm(anchors - self.anchors, axis=1)) > 6:
            raise RuntimeError('场地标签或相机位置变化')
        rover = tags[self.rover.tag]
        landmarks = np.float32([[rover.mean(axis=0), rover[:2].mean(axis=0)]])
        center, edge = cv2.perspectiveTransform(landmarks, self.matrix)[0]
        vector = edge - center
        return float(center[0]), float(center[1]), math.atan2(vector[1], vector[0])


def preflight(rover, position):
    x, y, heading = position
    min_y, max_y = rover.start_y
    if not (90 <= x <= 135 and min_y <= y <= max_y and abs(wrap(heading - rover.right_heading)) <= 0.2):
        return f'请把 ID {rover.tag} 放回对应车道的左侧起步区，车头朝右'
    return None


def drive_straight(rover, camera, send, origin, target_x, travel_direction=1, duration_s=None):
    position = previous = reference = origin
    movement_at = time.monotonic()
    started = movement_at
    distance = abs(target_x - origin[0])
    deadline = started + max(30, (duration_s or 0) + 15)
    while time.monotonic() < deadline:
        x, y, heading = position
        remaining, cross = travel_direction * (target_x - x), origin[1] - y
        if abs(remaining) <= 12 and abs(cross) <= 20:
            return
        if not (min(origin[0], target_x) - 28 <= x <= max(origin[0], target_x) + 28 and abs(cross) < 36):
            raise RuntimeError('直行超出可用赛道范围')
        if math.hypot(x - reference[0], y - reference[1]) > 4:
            reference = position
            movement_at = time.monotonic()
        stalled = max(0, time.monotonic() - movement_at - 0.35)
        direction = 1 if remaining >= 0 else -1
        correction = travel_direction * direction * clamp(
            math.atan2(cross, max(44, abs(remaining))), -0.31, 0.31
        )
        bearing = rover.right_heading + (math.pi if travel_direction < 0 else 0)
        heading_error = wrap(bearing + correction - heading)
        if abs(heading_error) > 0.4:
            power = math.copysign(clamp(30 + 24 * abs(heading_error) + stalled * 20, 35, 66),
                                  heading_error)
            send(power, -power)
        else:
            steer = clamp(41 * heading_error, -21, 21)
            advance = direction * travel_direction * (x - previous[0])
            approach = max(0, abs(remaining) - max(0, advance) * 1.35)
            pace = 0
            if duration_s and direction > 0:
                scheduled = distance * min(1, (time.monotonic() - started) / duration_s)
                pace = clamp((scheduled - (distance - remaining)) * 0.28, -14, 8)
            power = direction * clamp(38 + min(15, approach * 0.22) + stalled * 22 + pace, 28, 66)
            send(power + steer, power - steer)
        previous = position
        try:
            position = camera.read(seconds=0.25)
        except TimeoutError:
            send(0, 0)
            position = camera.read()
    raise RuntimeError('直行超时')


def turn_and_settle(rover, camera, send, position, target_x, start_y, target_heading=None):
    def check_zone(current):
        if abs(current[0] - target_x) > 35 or abs(current[1] - start_y) > 39:
            raise RuntimeError('掉头偏离预设区域')

    def settled_pose():
        send(0, 0)
        time.sleep(0.45)
        first = camera.read()
        time.sleep(0.15)
        second = camera.read()
        check_zone(second)
        stationary = abs(wrap(second[2] - first[2])) <= math.radians(1.5)
        return second, stationary

    deadline = time.monotonic() + 40
    if target_heading is None:
        target_heading = rover.right_heading + math.pi
    direction = math.copysign(1, wrap(target_heading - position[2]))
    last_heading = position[2]
    movement_at = time.monotonic()
    started = movement_at
    observed_step = 0
    while time.monotonic() < deadline:
        check_zone(position)
        remaining = direction * wrap(target_heading - position[2])
        if remaining <= math.radians(24) + max(0, observed_step) * 1.4:
            break
        if abs(wrap(position[2] - last_heading)) >= math.radians(2):
            last_heading = position[2]
            movement_at = time.monotonic()
        elapsed = time.monotonic() - started
        stalled = max(0, time.monotonic() - movement_at - 0.3)
        power = min(38 + elapsed * 38, 37 + math.degrees(remaining) * 0.18 + stalled * 17, 67)
        send(direction * power, -direction * power)
        previous = position
        try:
            position = camera.read(seconds=0.25)
        except TimeoutError:
            send(0, 0)
            position = camera.read()
        observed_step = direction * wrap(position[2] - previous[2])

    position, stationary = settled_pose()
    boost = 0
    previous_direction = None
    while time.monotonic() < deadline:
        error = wrap(target_heading - position[2])
        if not stationary:
            position, stationary = settled_pose()
            continue
        if abs(error) <= HEADING_TOLERANCE:
            status = rover_status(rover)
            if not (status['L'] or status['R']):
                return position
            position, stationary = settled_pose()
            continue
        direction = math.copysign(1, error)
        if direction != previous_direction:
            boost = 0
        power = clamp(48 + math.degrees(abs(error)) * 0.36 + boost, 48, 75)
        duration = clamp(0.035 + abs(error) * 0.055 + boost * 0.002, 0.035, 0.105)
        before = position
        try:
            send(direction * power, -direction * power)
            time.sleep(duration)
        finally:
            send(0, 0)
        position, stationary = settled_pose()
        moved = abs(wrap(position[2] - before[2]))
        boost = min(boost + 4, 24) if moved < math.radians(1.5) else 0
        previous_direction = direction
    raise RuntimeError(f'掉头超时，停稳前最后测得误差 {abs(math.degrees(wrap(target_heading - position[2]))):.1f}°')


def main():
    parser = argparse.ArgumentParser(description='实车固定动作：直行 47.8 cm，掉头 180°，停车')
    parser.add_argument('--rover', choices=ROVERS, default='blue', help='blue 为 ID 1，gold 为 ID 0')
    parser.add_argument('--check', action='store_true', help='只读取相机和选定车辆的状态')
    args = parser.parse_args()
    rover = ROVERS[args.rover]
    camera = Camera(rover)
    status = rover_status(rover)
    origin = camera.read(seconds=10)
    problem = preflight(rover, origin)
    if status['L'] or status['R']:
        problem = f'ID {rover.tag} 未停稳'
    if args.check:
        print(json.dumps({'rover': args.rover, 'ip': rover.ip, 'tag': rover.tag,
                          'position_mm': origin[:2], 'heading_deg': math.degrees(origin[2]),
                          'rover_status': status, 'ready': problem is None, 'message': problem},
                         ensure_ascii=False))
        return
    if problem:
        raise RuntimeError(problem)

    target_x = origin[0] + OUTBOUND_MM
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as udp:
        def send(left, right):
            udp.sendto(f'{round(left)},{round(right)}'.encode(), (rover.ip, 8888))

        try:
            drive_straight(rover, camera, send, origin, target_x)
            send(0, 0)
            time.sleep(0.4)
            before_turn = camera.read()
            stopped = rover_status(rover)
            if stopped['L'] or stopped['R']:
                raise RuntimeError('到点后未确认轮速归零')
            print(f'直行完成：向右走了 {before_turn[0] - origin[0]:.1f} mm', flush=True)
            end = turn_and_settle(rover, camera, send, before_turn, target_x, origin[1])
        finally:
            send(0, 0)
    heading_error = abs(math.degrees(wrap(rover.right_heading + math.pi - end[2])))
    print(f'掉头停稳：角度误差 {heading_error:.1f}°，'
          f'位置误差 {math.hypot(end[0] - target_x, end[1] - origin[1]):.1f} mm')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, OSError, KeyboardInterrupt) as error:
        print(f'测试结束：{error or "手动中止"}', file=sys.stderr)
        sys.exit(1)
