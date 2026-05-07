insert into plant_type(id, name) values(1, "토마토");
insert into plant_type(id, name) values(2, "딸기");

insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-02 13:21:00', 1, 0.51, 0.0);
insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-02 13:21:00', 2, 0.29, 0.25);

insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-03 13:21:00', 1, 0.50, 0.0);
insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-03 13:21:00', 2, 0.31, 0.25);

insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-04 13:25:00', 1, 0.55, 0.25);
insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-04 13:25:00', 2, 0.35, 0.25);

insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-05 13:31:00', 1, 0.58, 0.25);
insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-05 13:31:00', 2, 0.39, 0.50);

insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-06 13:16:00', 1, 0.61, 0.25);
insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-06 13:16:00', 2, 0.43, 0.50);

insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-07 13:20:00', 1, 0.628, 0.0);
insert into plant_statistics(created_at, type_id, avg_maturity, disease_ratio)
values('2025-05-07 13:20:00', 2, 0.485, 0.25);

insert into plant(id, name, type_id, maturity, is_disease)
values(1, "토마토 1", 1, 0.64, 0);
insert into plant(id, name, type_id, maturity, is_disease)
values(2, "토마토 2", 1, 0.61, 0);
insert into plant(id, name, type_id, maturity, is_disease)
values(3, "토마토 3", 1, 0.67, 0);
insert into plant(id, name, type_id, maturity, is_disease)
values(4, "토마토 4", 1, 0.6, 0);

insert into plant(id, name, type_id, maturity, is_disease)
values(5, "딸기 1", 2, 0.45, 1);
insert into plant(id, name, type_id, maturity, is_disease)
values(6, "딸기 2", 2, 0.49, 0);
insert into plant(id, name, type_id, maturity, is_disease)
values(7, "딸기 3", 2, 0.50, 0);
insert into plant(id, name, type_id, maturity, is_disease)
values(8, "딸기 4", 2, 0.50, 0);

---

