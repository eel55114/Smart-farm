import json
from datetime import datetime, timedelta

from db_instance import db
from flask import Blueprint, current_app, render_template, request

environment_bp = Blueprint("environment", __name__)


@environment_bp.route("/api/save_actuator_threshold", methods=["POST"])
def save_actuator_threshold():
    """웹 대시보드에서 수정된 임계값을 저장하고 MQTT 명령을 발송합니다."""
    body = request.get_json() or {}
    actuator_id = body.get("actuator_id")
    threshold_str = body.get("threshold_value")  # 예: "20+15"

    if not actuator_id or threshold_str is None:
        return "Invalid parameters", 400

    # 1. 액추에이터의 region_id 조회
    actuators, err = db.get_current_actuator(actuator_ids=[actuator_id])
    if err or not actuators:
        return "Actuator not found", 404
    region_id = actuators[0].region_id or 1

    # 2. DB 및 MQTT용 raw 값들 계산
    thresholds_list, err2 = db.get_actuator_thresholds(actuator_ids=[actuator_id])
    mqtt_threshold_str = threshold_str  # 기본값
    if not err2 and thresholds_list:
        thresholds_list.sort(key=lambda x: x.sensor_type_id)
        values = str(threshold_str).split("+")
        
        save_list = []
        mqtt_vals = []
        for idx, t in enumerate(thresholds_list):
            if idx < len(values):
                try:
                    val = float(values[idx])
                    # 습도류(1, 3, 5)는 UI(0~100) 값을 원본 소수(0~1)로 변환
                    if t.sensor_type_id in [1, 3, 5]:
                        val = val / 100.0
                    t.threshold_value = val
                    save_list.append(t)
                    # 소수점 둘째자리까지 정밀하게 원본 MQTT 데이터로 설정
                    mqtt_vals.append(str(round(val, 2)))
                except ValueError:
                    pass
        if save_list:
            db.save_actuator_thresholds(save_list)
        if mqtt_vals:
            mqtt_threshold_str = "+".join(mqtt_vals)

    # 3. MQTT 전송 (스펙: smartfarm/{region_id}/iot/command/actuator/{actuator_id})
    connector = current_app.config.get("MQTT_CONNECTOR")
    if connector:
        topic = f"smartfarm/{region_id}/iot/command/actuator/{actuator_id}"
        connector.publish(topic, {"data": str(mqtt_threshold_str)})
        print(f"[Actuator Threshold Command] Published {mqtt_threshold_str} to {topic}")

    return {"status": "success"}, 200


@environment_bp.route("/api/control_actuator")
def control_actuator():
    device = request.args.get("device", "", type=str)
    data = request.args.get("data", 0, type=int)

    # if device == "light":
    #     resp = requests.get(f"{HUB_ENDPOINT}/light?on={data}")

    # if resp.status_code == 200:
    #     return "", 200
    # else:
    #     return "Hub not respond.", 400
    pass  # todo
    return "", 200


@environment_bp.route("/api/current_sensors")
def get_current_sensors():
    db_error = False
    region_id = request.args.get("region", type=int)
    regions_filter = [region_id] if region_id else None

    sensors, err = db.get_current_sensor(regions=regions_filter)
    if err is not None:
        db_error = True

    data = []
    for i in sensors:
        is_danger = False
        if i.type_id in [1, 3, 5]:  # 조도, 습도, 토양습도
            value = f"{min(round(i.value * 100, 2), 100)}%"
        elif i.type_id == 2:  # 온도
            value = f"{i.value}°C"
        elif i.type_id == 4:  # 화염
            value = f"{'화재' if i.value > 0.5 else '없음'}"
            is_danger = i.value > 0.5
        else:
            value = "알 수 없음"

        display_name = i.name if (i.name and i.name.strip()) else i.type_name
        temp = {
            "id": i.id,
            "region_id": i.region_id,
            "region_name": i.region_name,
            "name": i.name,
            "type_id": i.type_id,
            "type_name": i.type_name,
            "display_name": display_name,
            "value": value,
            "is_danger": is_danger,
        }
        data.append(temp)
    return render_template(
        "_sensor_state.html",
        data=data,
        db_error=db_error,
    )


@environment_bp.route("/environment")
def environment():
    db_error = False

    days = request.args.get("days", 5, type=int)
    region_id = request.args.get("region", type=int)
    regions_filter = [region_id] if region_id else None

    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    parsed_custom_date = False
    if start_date_str and end_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")
            end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                hour=23, minute=59, second=59
            )
            parsed_custom_date = True
        except ValueError:
            pass

    if not parsed_custom_date:
        # 종료일 인자가 없을 경우에만 현재 시간을 종료일로 설정
        end_date = datetime.now()
        start_date = (end_date - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    graph_records, _, err = db.get_sensor_history(
        start_date=start_date, end_date=end_date, regions=regions_filter
    )
    if err is not None:
        db_error = True

    # 2. X축 라벨 생성 (데이터베이스의 실제 time_bucket 기반으로 상세 시간단위 라벨 생성)
    labels = []
    if graph_records:
        unique_buckets = sorted(list({r.time_bucket for r in graph_records}))
        labels = [b.strftime("%m%d %H:%M:%S") for b in unique_buckets]

    charts_data = {}
    if graph_records:
        # 센서 ID → 표시명 매핑 (현재 센서 목록에서 조회)
        sensor_meta, _ = db.get_current_sensor(regions=regions_filter)
        sensor_label_map = {
            s.id: (s.name.strip() if s.name and s.name.strip() else f"{s.type_name} #{s.id}")
            for s in sensor_meta
        }

        # 센서별 색상 팔레트 (순환)
        palette = [
            ("rgba(13,110,253,1)",   "rgba(13,110,253,0.15)"),   # blue
            ("rgba(220,53,69,1)",    "rgba(220,53,69,0.15)"),    # red
            ("rgba(25,135,84,1)",    "rgba(25,135,84,0.15)"),    # green
            ("rgba(255,193,7,1)",    "rgba(255,193,7,0.15)"),    # yellow
            ("rgba(111,66,193,1)",   "rgba(111,66,193,0.15)"),   # purple
            ("rgba(13,202,240,1)",   "rgba(13,202,240,0.15)"),   # cyan
            ("rgba(253,126,20,1)",   "rgba(253,126,20,0.15)"),   # orange
            ("rgba(102,16,242,1)",   "rgba(102,16,242,0.15)"),   # indigo
        ]

        # 타입별로 그룹화
        types = {}
        for r in graph_records:
            types[r.sensor_type] = r.sensor_type_name

        for type_id, type_name in types.items():
            type_records = [r for r in graph_records if r.sensor_type == type_id]

            # 해당 타입에 속하는 sensor_id 목록 (순서 고정)
            sensor_ids = sorted({r.sensor_id for r in type_records})

            datasets = []
            for idx, sid in enumerate(sensor_ids):
                color_fg, color_bg = palette[idx % len(palette)]
                sensor_records = [r for r in type_records if r.sensor_id == sid]

                # 상세 시간단위 매핑 (time_bucket 별 매핑)
                records_by_bucket = {
                    r.time_bucket.strftime("%m%d %H:%M:%S"): r
                    for r in sensor_records
                }

                avg_vals = []
                for label in labels:
                    if label in records_by_bucket:
                        r = records_by_bucket[label]
                        avg_vals.append(round(r.avg, 2))
                    else:
                        avg_vals.append(None)

                sensor_name = sensor_label_map.get(sid, f"#{sid}")
                datasets.append({
                    "label": sensor_name,
                    "data": avg_vals,
                    "borderColor": color_fg,
                    "backgroundColor": color_bg,
                    "spanGaps": False,
                    "tension": 0.1,
                })

            charts_data[type_name] = {
                "labels": labels,
                "datasets": datasets,
            }

    # 액추에이터 정보 쿼리 및 가공
    actuators = []
    db_actuators, err1 = db.get_current_actuator(regions=regions_filter)
    if err1:
        db_error = True
    else:
        actuator_ids = [a.id for a in db_actuators]
        thresholds = []
        if actuator_ids:
            db_thresholds, err2 = db.get_actuator_thresholds(actuator_ids=actuator_ids)
            if err2:
                db_error = True
            else:
                thresholds = db_thresholds

        SENSOR_LIMITS = {
            1: {"min": 0, "max": 100, "unit": "%"},  # 조도
            2: {"min": 0, "max": 50, "unit": "°C"},  # 온도
            3: {"min": 0, "max": 100, "unit": "%"},  # 습도
            4: {"min": 0, "max": 1, "unit": ""},  # 화염
            5: {"min": 0, "max": 100, "unit": "%"},  # 토양습도
        }

        # actuator_id 별로 thresholds 그룹화
        thresh_map = {}
        for t in thresholds:
            limits = SENSOR_LIMITS.get(
                t.sensor_type_id, {"min": 0, "max": 100, "unit": ""}
            )
            t.min_val = limits["min"]
            t.max_val = limits["max"]
            t.unit = limits["unit"]
            # 습도류(1, 3, 5)는 UI 표시를 위해 100을 곱하고 정수로 반올림
            if t.sensor_type_id in [1, 3, 5]:
                t.threshold_value = int(round(t.threshold_value * 100))
            else:
                t.threshold_value = int(round(t.threshold_value))
            thresh_map.setdefault(t.actuator_id, []).append(t)

        for a in db_actuators:
            display_name = a.name if (a.name and a.name.strip()) else a.type_name
            t_list = thresh_map.get(a.id, [])
            t_list.sort(key=lambda x: x.sensor_type_id)

            actuators.append(
                {
                    "id": a.id,
                    "type_id": a.type_id,
                    "type_name": a.type_name,
                    "region_id": a.region_id,
                    "region_name": a.region_name,
                    "name": a.name,
                    "display_name": display_name,
                    "thresholds": t_list,
                }
            )

    return render_template(
        "environment.html",
        days=days,
        charts_data=json.dumps(charts_data),
        db_error=db_error,
        actuators=actuators,
    )
