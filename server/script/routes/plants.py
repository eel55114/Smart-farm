import json
from datetime import datetime, timedelta

from db_instance import db
from flask import Blueprint, render_template, request

plants_bp = Blueprint("plants", __name__, url_prefix="/plants")


@plants_bp.route("/")
def plants():
    db_error = False
    types, err = db.get_active_plant_type()
    if err is not None:
        types = dict()

    # 현재 작물 정보 쿼리
    plants_data, err = db.get_current_plant()
    if err is not None:
        db_error = True
        plants_data = []

    status_data = dict()
    for type_id, type_name in types.items():
        status_data[type_name] = []

    # 현재 작물 정보를 작물 타입별로 분류
    for plant in plants_data:
        type_name = types.get(plant.type_id)
        if type_name:
            plant.maturity = max(min(round(plant.maturity * 100, 1), 100), 0)
            status_data[type_name].append(plant)

    page = request.args.get("page", 1, type=int)
    days = request.args.get("days", 5, type=int)

    type_ids = list(types.keys())

    per_page = 15
    offset = (page - 1) * per_page

    history_records, count, err = db.get_plant_statistics(
        type_ids=type_ids, n=per_page, offset=offset
    )
    if err is not None:
        db_error = True
        history_records = []
        count = 0

    has_next = (offset + per_page) < count
    history_data = []
    history_columns = ["이력 ID", "일시", "작물 종류", "평균 성장도", "병충해 피해율"]

    for h in history_records:
        temp = [
            h.id,
            h.created_at.strftime("%Y-%m-%d %H:%M"),
            types.get(h.type_id, "Unknown"),
            f"{round(h.avg_maturity * 100, 2)}%",
            f"{round(h.disease_ratio * 100, 2)}%",
        ]

        history_data.append(temp)

    latest_records, _, err = db.get_plant_statistics(type_ids=type_ids, n=1)
    if err is not None:
        db_error = True
    start_date_str = request.args.get("start_date")
    end_date_str = request.args.get("end_date")

    parsed_custom_date = False

    if start_date_str:
        try:
            start_date = datetime.strptime(start_date_str, "%Y-%m-%d")

            if end_date_str:
                end_date = datetime.strptime(end_date_str, "%Y-%m-%d").replace(
                    hour=23, minute=59, second=59
                )
            else:
                end_date = datetime.now().replace(hour=23, minute=59, second=59)

            parsed_custom_date = True
        except ValueError:
            pass

    if not parsed_custom_date:
        end_date = datetime.now().replace(hour=23, minute=59, second=59)
        start_date = (end_date - timedelta(days=days - 1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    graph_records, _, err = db.get_plant_statistics(
        type_ids=type_ids, start_date=start_date, end_date=end_date
    )
    if err is not None:
        db_error = True

    labels = []
    curr = start_date
    while curr.date() <= end_date.date():
        labels.append(curr.strftime("%y%m%d"))
        curr += timedelta(days=1)

    charts_data = {}

    if graph_records:
        for type_id in type_ids:
            type_name = types[type_id]
            avg_mat = []
            dis_rat = []

            type_records = [r for r in graph_records if r.type_id == type_id]
            records_by_date = {}
            for r in type_records:
                date_str = r.created_at.strftime("%y%m%d")
                records_by_date.setdefault(date_str, []).append(r)

            for label in labels:
                if label in records_by_date:
                    day_recs = records_by_date[label]
                    avg_mat.append(
                        round(sum(r.avg_maturity for r in day_recs) / len(day_recs), 3)
                    )
                    dis_rat.append(
                        round(sum(r.disease_ratio for r in day_recs) / len(day_recs), 3)
                    )
                else:
                    avg_mat.append(None)
                    dis_rat.append(None)

            maturity_fg_color = "rgba(40, 167, 69, 1)"
            maturity_bg_color = "rgba(40, 167, 69, 0.2)"
            disease_fg_color = "rgba(220, 53, 69, 1)"
            disease_bg_color = "rgba(220, 53, 69, 0.2)"

            charts_data[type_name] = {
                "labels": labels,
                "datasets": [
                    {
                        "label": "평균 성장도",
                        "data": avg_mat,
                        "borderColor": maturity_fg_color,
                        "backgroundColor": maturity_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                    {
                        "label": "병충해 비율",
                        "data": dis_rat,
                        "borderColor": disease_fg_color,
                        "backgroundColor": disease_bg_color,
                        "spanGaps": False,
                        "tension": 0.1,
                    },
                ],
            }

    return render_template(
        "plants.html",
        status_data=status_data,
        history_data=history_data,
        history_columns=history_columns,
        page=page,
        has_next=has_next,
        days=days,
        charts_data=json.dumps(charts_data),
        db_error=db_error,
    )
