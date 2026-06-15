import json
from datetime import datetime, timedelta

from db_instance import db
from flask import Blueprint, render_template, request

environment_bp = Blueprint("environment", __name__)


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
        if i.type_id in [1, 2, 5]:  # 조도, 습도, 토양습도
            value = f"{min(round(i.value * 100, 2), 100)}%"
        elif i.type_id == 3:  # 온도
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

    page = request.args.get("page", 1, type=int)
    days = request.args.get("days", 5, type=int)
    region_id = request.args.get("region", type=int)
    regions_filter = [region_id] if region_id else None

    per_page = 15
    offset = (page - 1) * per_page

    history_records, count, err = db.get_sensor_history(
        n=per_page, offset=offset, regions=regions_filter
    )
    if err is not None:
        db_error = True
        history_records = []
        count = 0

    has_next = (offset + per_page) < count
    history_data = []
    history_columns = [
        "기준 시간",
        "센서 ID",
        "센서 유형",
        "최댓값",
        "평균값",
        "최솟값",
    ]

    for h in history_records:
        temp = [
            h.time_bucket.strftime("%Y-%m-%d %H:%M"),
            h.sensor_id,
            h.sensor_type_name,
            round(h.max, 2),
            round(h.avg, 2),
            round(h.min, 2),
        ]
        history_data.append(temp)

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

    # 2. X축 라벨 생성
    labels = []
    curr = start_date
    while curr.date() <= end_date.date():
        labels.append(curr.strftime("%y%m%d"))
        curr += timedelta(days=1)

    graph_records, _, err = db.get_sensor_history(
        start_date=start_date, end_date=end_date, regions=regions_filter
    )
    if err is not None:
        db_error = True

    charts_data = {}
    if graph_records:
        # 센서 종류 파악
        types = {}
        for r in graph_records:
            types[r.sensor_type] = r.sensor_type_name

        for type_id, type_name in types.items():
            avg_vals = []
            max_vals = []
            min_vals = []

            type_records = [r for r in graph_records if r.sensor_type == type_id]
            records_by_date = {}
            for r in type_records:
                date_str = r.time_bucket.strftime("%m%d %H:%M:%S")
                records_by_date.setdefault(date_str, []).append(r)

            for label in labels:
                if label in records_by_date:
                    day_recs = records_by_date[label]
                    avg_vals.append(
                        round(sum(r.avg for r in day_recs) / len(day_recs), 2)
                    )
                    max_vals.append(round(max(r.max for r in day_recs), 2))
                    min_vals.append(round(min(r.min for r in day_recs), 2))
                else:
                    avg_vals.append(None)
                    max_vals.append(None)
                    min_vals.append(None)

            avg_fg_color = "rgba(0, 123, 255, 1)"
            avg_bg_color = "rgba(0, 123, 255, 0.2)"
            max_fg_color = "rgba(220, 53, 69, 1)"
            max_bg_color = "rgba(220, 53, 69, 0.2)"
            min_fg_color = "rgba(40, 167, 69, 1)"
            min_bg_color = "rgba(40, 167, 69, 0.2)"

            charts_data[type_name] = {
                "labels": labels,
                "datasets": [
                    {
                        "label": "최댓값",
                        "data": max_vals,
                        "borderColor": max_fg_color,
                        "backgroundColor": max_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                    {
                        "label": "평균값",
                        "data": avg_vals,
                        "borderColor": avg_fg_color,
                        "backgroundColor": avg_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                    {
                        "label": "최솟값",
                        "data": min_vals,
                        "borderColor": min_fg_color,
                        "backgroundColor": min_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                ],
            }

    return render_template(
        "environment.html",
        history_data=history_data,
        history_columns=history_columns,
        page=page,
        has_next=has_next,
        days=days,
        charts_data=json.dumps(charts_data),
        db_error=db_error,
        count=count,
        per_page=per_page,
    )
