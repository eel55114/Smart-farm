import time
from typing import Any

import yaml


def parse_pgm(pgm_file: bytes) -> dict[str, Any]:
    lines = pgm_file.split(b"\n")
    tokens = []
    raw_data_idx = 0

    for line in lines:
        cleaned = line.split(b"#")[0].strip()
        if not cleaned:
            continue
        tokens += cleaned.split()
        if len(tokens) >= 4:
            raw_data_idx = pgm_file.find(line) + len(line) + 1
            break

    file_type = tokens[0].decode()
    width = int(tokens[1])
    height = int(tokens[2])
    depth = int(tokens[3])

    raw_data = pgm_file[raw_data_idx:]

    if file_type == "P2":
        data = list(map(int, raw_data.decode().split()))
    elif file_type == "P5":
        if depth < 256:
            data = list(raw_data)
        else:
            data = [
                int.from_bytes(raw_data[i : i + 2], byteorder="big")
                for i in range(0, len(raw_data), 2)
            ]
    else:
        raise ValueError("Invalid .pgm file")

    return {
        "type": file_type,
        "width": width,
        "height": height,
        "depth": depth,
        "data": data,
    }


def convert_scale_img(num: int) -> int:
    if num == 205:
        return -1
    else:
        return round((254 - num) / 2.54)


def convert_trinary_img(num: int) -> int:
    if num == 254:
        return 0
    if num == 205:
        return -1
    else:
        return 100


def tuple_to_msg(
    name: str, created_at: int, pgm_file: bytes, yaml_file: bytes
) -> dict[str, Any]:
    map_image = parse_pgm(pgm_file)
    map_inform = yaml.safe_load(yaml_file)

    if map_inform.get("mode") == "scale":
        converted_data = [convert_scale_img(i) for i in map_image["data"]]
    else:
        converted_data = [convert_trinary_img(i) for i in map_image["data"]]

    height = map_image["height"]
    width = map_image["width"]

    map_arr = []
    for r in range(height - 1, -1, -1):
        start_idx = r * width
        end_idx = start_idx + width
        map_arr += converted_data[start_idx:end_idx]

    now = int(time.time())
    return {
        "header": {
            "stamp": {"sec": created_at, "nanosec": 0},
            "frame_id": name,
        },
        "info": {
            "map_load_time": {"sec": now, "nanosec": 0},
            "resolution": map_inform["resolution"],
            "width": width,
            "height": height,
            "origin": {
                "position": {
                    "x": map_inform["origin"][0],
                    "y": map_inform["origin"][1],
                    "z": map_inform["origin"][2],
                },
                "orientation": {
                    "x": 0.0,
                    "y": 0.0,
                    "z": 0.0,
                    "w": 1.0,
                },
            },
        },
        "data": map_arr,
    }


if __name__ == "__main__":
    with open("map.pgm", "rb") as o:
        m = o.read()
    with open("map.yaml", "rb") as o:
        y = o.read()

    print(tuple_to_msg("map", int(time.time()), m, y))
