/**
 * 로봇 수동 제어 및 실시간 지도 시각화 스크립트
 */

class FPSCalculator {
    constructor(elementSelector) {
        this.elem = document.querySelector(elementSelector);
        this.lastSignal = performance.now();
        this.lastRenew = -1500;
        this.deque = [];
    }

    update() {
        if (!this.elem) return;
        const now = performance.now();
        const gap = now - this.lastSignal;
        this.deque.push(gap);
        if (this.deque.length > 20) {
            this.deque.shift();
        }
        const meanGap = this.deque.reduce((x, y) => x + y, 0) / this.deque.length;
        if (now - this.lastRenew > 500) {
            const round = meanGap < 1000 ? 0 : 1;
            this.elem.innerText = (1000 / meanGap).toFixed(round);
            this.lastRenew = now;
        }
        this.lastSignal = now;
    }
}

document.addEventListener("DOMContentLoaded", () => {
    const currentRobotId = ROBOT_CONFIG.currentRobotId;
    if (!currentRobotId || currentRobotId === 'null') {
        console.warn("선택된 로봇 ID가 없습니다.");
        return;
    }

    const socket = io();
    const frontFPS = new FPSCalculator("#framerate_front");
    const sideFPS = new FPSCalculator("#framerate_side");

    // 이미지 스트리밍 업데이트
    const updateImage = (elementId, arrayBuffer) => {
        const imgElement = document.getElementById(elementId);
        if (!imgElement) return;

        const blob = new Blob([new Uint8Array(arrayBuffer)], { type: "image/jpeg" });
        const imageUrl = URL.createObjectURL(blob);

        imgElement.onload = () => URL.revokeObjectURL(imageUrl);
        imgElement.src = imageUrl;
    };

    // 소켓 이미지 렌더링 이벤트 등록
    socket.on(`render_${currentRobotId}_front`, (data) => {
        updateImage('img_front', data);
        frontFPS.update();
    });

    socket.on(`render_${currentRobotId}_side`, (data) => {
        updateImage('img_side', data);
        sideFPS.update();
    });

    // 로봇 모드 UI 동기화
    const updateModeUI = (mode) => {
        const radio = document.getElementById(`mode-${mode}`);
        if (radio) radio.checked = true;

        const dpadControl = document.getElementById("dpadControl");
        if (dpadControl) {
            if (mode === "manual") {
                dpadControl.classList.remove("opacity-50", "pe-none");
            } else {
                dpadControl.classList.add("opacity-50", "pe-none");
            }
        }
    };

    let lastRobotPose = null; // 지도 재로드 시 사용을 위해 위치 캐싱
    let robotMarker = null;

    // 실시간 데이터 수신 핸들러 맵
    const liveHandlers = {
        battery(payload) {
            const batteryElem = document.getElementById("robot-battery-percent");
            if (batteryElem && payload.data !== undefined) {
                const pct = payload.data > 1.0 ? payload.data : (payload.data * 100);
                batteryElem.innerText = Math.round(pct);
            }
        },
        state(payload) {
            const stateElem = document.getElementById("robot-current-state");
            if (stateElem && payload.state !== undefined) {
                stateElem.innerText = payload.state;
            }
        },
        robot_mode(payload) {
            if (payload.data !== undefined) {
                updateModeUI(payload.data);
            }
        },
        amcl_pose(payload) {
            try {
                if (!payload.pose?.pose) return;
                const { position, orientation } = payload.pose.pose;
                if (!position || !orientation) return;

                const { x, y } = position;
                const { z: qz, w: qw } = orientation;
                if (x === undefined || y === undefined || qz === undefined || qw === undefined) return;

                const yaw = 2 * Math.atan2(qz, qw);
                lastRobotPose = { x, y, yaw };
                drawRobotPosition(x, y, yaw);

                // 초기 위치 마커가 존재하면 제거
                if (initialPoseMarker && canvas) {
                    canvas.remove(initialPoseMarker);
                    initialPoseMarker = null;
                    canvas.requestRenderAll();
                }
            } catch (err) {
                console.error("Error parsing amcl_pose data:", err);
            }
        }
    };

    socket.on(`robot_${currentRobotId}_live`, (data) => {
        if (!data?.payload || !data.type) return;
        const handler = liveHandlers[data.type];
        if (handler) {
            handler(data.payload);
        }
    });

    // 로봇 위치 표시 그리기
    const drawRobotPosition = (x, y, yawRad) => {
        if (!canvas || mapWidth === 0 || mapHeight === 0) return;

        const px = (x - mapOriginX) / mapResolution;
        const py = mapHeight - ((y - mapOriginY) / mapResolution);
        const scaleFactor = (0.306 / mapResolution) / 114;
        const yawDegree = -yawRad * (180 / Math.PI) + 90;
        const zoom = canvas.getZoom();

        if (!robotMarker) {
            const pathData = "M -17 8 C 7 -7 -7 -7 18 8 C 32 17 56 10 57 30 V 94 C 57 107 52 112 40 112 H -40 C -52 112 -57 107 -57 94 V 30 C -57 10 -32 17 -17 8 Z";
            robotMarker = new fabric.Path(pathData, {
                fill: 'rgba(8,204,133, 0.3)',
                stroke: 'rgba(7, 177, 98, 1.0)',
                strokeWidth: 3 / zoom,
                strokeUniform: true,
                originX: 'center',
                originY: 0.65,
                selectable: false,
                hoverCursor: 'default',
                scaleX: scaleFactor,
                scaleY: scaleFactor,
                left: px,
                top: py,
                angle: yawDegree
            });
            canvas.add(robotMarker);
        } else {
            robotMarker.set({
                left: px,
                top: py,
                scaleX: scaleFactor,
                scaleY: scaleFactor,
                angle: yawDegree,
                strokeWidth: 3 / zoom
            });
        }
        robotMarker.bringToFront();
        canvas.requestRenderAll();
    };

    // Fabric 캔버스 상태 관리 변수들
    let canvas;
    let mapWidth = 0;
    let mapHeight = 0;
    let mapResolution = 0.05;
    let mapOriginX = 0;
    let mapOriginY = 0;
    let currentMarker = null;
    let mapImageObject = null;
    let minZoom = 0.1;

    let isSetInitialMode = false;
    let initialPoseMarker = null;
    let initialDragStart = null;
    let isInitialDragging = false;
    let lastInitialAngleDeg = 0;

    const INITIAL_CIRCLE_RADIUS = 12;
    const INITIAL_LINE_LENGTH = 40;

    // 마커 스케일 갱신 (줌 변경 대응)
    const updateMarkerScale = () => {
        if (!canvas) return;
        const zoom = canvas.getZoom();
        if (currentMarker) {
            currentMarker.set({
                scaleX: 1 / zoom,
                scaleY: 1 / zoom
            });
        }
        if (robotMarker) {
            robotMarker.set({
                strokeWidth: 3 / zoom
            });
        }
        if (initialPoseMarker) {
            drawInitialPoseMarker(
                initialPoseMarker.canvasX,
                initialPoseMarker.canvasY,
                initialPoseMarker.angleDeg
            );
        }
    };

    // 맵 API 호출 및 드로잉
    const current_robot_map = () => {
        const errorOverlay = document.getElementById('map-error-overlay');
        const errorMessage = document.getElementById('map-error-message');
        const scaleBar = document.getElementById('map-scale-bar');

        fetch(`/api/robot_current_map?robot=${currentRobotId}`)
            .then(res => {
                if (!res.ok) {
                    return res.json().then(errData => {
                        throw new Error(errData.error || "Failed to load map");
                    });
                }
                return res.json();
            })
            .then(data => {
                // 정상 수신 시 오버레이 숨김
                if (errorOverlay) errorOverlay.classList.add('d-none');

                mapWidth = data.width;
                mapHeight = data.height;
                mapResolution = data.resolution || 0.05;
                if (data.origin) {
                    mapOriginX = data.origin[0];
                    mapOriginY = data.origin[1];
                } else {
                    mapOriginX = -(mapWidth * mapResolution) / 2;
                    mapOriginY = -(mapHeight * mapResolution) / 2;
                }

                const dataUrl = drawOccupancyGrid(mapWidth, mapHeight, data.array, data.mode);

                if (currentMarker) {
                    canvas.remove(currentMarker);
                    currentMarker = null;
                    document.getElementById('btn-moveto').disabled = true;
                }
                if (mapImageObject) {
                    canvas.remove(mapImageObject);
                }

                fabric.Image.fromURL(dataUrl, (img) => {
                    mapImageObject = img;
                    img.set({
                        left: 0,
                        top: 0,
                        selectable: false,
                        hoverCursor: 'default',
                        imageSmoothing: false
                    });
                    canvas.add(img);
                    canvas.sendToBack(img);
                    resetMapViewport();

                    if (lastRobotPose) {
                        drawRobotPosition(lastRobotPose.x, lastRobotPose.y, lastRobotPose.yaw);
                    }
                });
            })
            .catch(err => {
                console.error('Error fetching map:', err);

                // 에러 메시지 갱신 및 노출
                if (errorMessage) {
                    errorMessage.innerText = err.message || "맵 정보가 없습니다. '일정 계획'에서 로봇 맵을 설정해 주세요.";
                }
                if (errorOverlay) {
                    errorOverlay.classList.remove('d-none');
                }
                // 스케일바 숨김
                if (scaleBar) {
                    scaleBar.classList.add('d-none');
                }
                // 캔버스 객체 초기화 (배경 어둡게 유지)
                if (canvas) {
                    canvas.clear();
                    canvas.setBackgroundColor('#212529', canvas.renderAll.bind(canvas));
                }
                if (currentMarker) currentMarker = null;
                if (mapImageObject) mapImageObject = null;
                const btnMove = document.getElementById('btn-moveto');
                if (btnMove) btnMove.disabled = true;
            });
    };

    // 뷰포트 재설정
    const resetMapViewport = () => {
        if (!mapImageObject) return;
        const scaleX = canvas.width / mapWidth;
        const scaleY = canvas.height / mapHeight;
        minZoom = Math.min(scaleX, scaleY) * 0.95;

        const vpt = canvas.viewportTransform;
        vpt[0] = minZoom;
        vpt[3] = minZoom;
        vpt[4] = (canvas.width - mapWidth * minZoom) / 2;
        vpt[5] = (canvas.height - mapHeight * minZoom) / 2;

        canvas.setViewportTransform(vpt);
        constrainViewport(canvas, mapImageObject, mapWidth, mapHeight);
        updateMarkerScale();
        updateScaleBar(canvas, mapImageObject, mapResolution);
        canvas.requestRenderAll();
    };

    // 모드 라디오 버튼 이벤트 바인딩
    document.querySelectorAll('input[name="robotMode"]').forEach(radio => {
        radio.addEventListener("change", function() {
            if (this.checked) {
                const val = this.value;
                const dpad = document.getElementById("dpadControl");
                if (dpad) {
                    if (val === "manual") {
                        dpad.classList.remove("opacity-50", "pe-none");
                    } else {
                        dpad.classList.add("opacity-50", "pe-none");
                    }
                }
                fetch(`/api/change_robot_state?mode=${val}&robot=${currentRobotId}`);
            }
        });
    });

    // 방향 컨트롤 버튼 이벤트 바인딩
    document.querySelectorAll(".robot-control").forEach(btn => {
        btn.addEventListener("click", function() {
            const data = this.getAttribute('data-info');
            fetch(`/api/control_robot?direction=${data}&robot=${currentRobotId}`);
        });
    });

    // Fabric 캔버스 초기화
    const canvasContainer = document.getElementById('map').parentElement;
    canvas = new fabric.Canvas('map', {
        width: canvasContainer.clientWidth,
        height: canvasContainer.clientHeight,
        selection: false,
        fireRightClick: true,
        fireMiddleClick: true
    });

    window.addEventListener('resize', () => {
        if (canvas && canvasContainer) {
            canvas.setWidth(canvasContainer.clientWidth);
            canvas.setHeight(canvasContainer.clientHeight);
            resetMapViewport();
        }
    });

    // 마우스 휠 줌 기능
    canvas.on('mouse:wheel', (opt) => {
        const delta = opt.e.deltaY;
        let zoom = canvas.getZoom();
        zoom *= 0.999 ** delta;
        zoom = Math.max(minZoom, Math.min(50, zoom));
        canvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
        constrainViewport(canvas, mapImageObject, mapWidth, mapHeight);
        updateMarkerScale();
        updateScaleBar(canvas, mapImageObject, mapResolution);
        opt.e.preventDefault();
        opt.e.stopPropagation();
    });

    // 드래그 패닝 처리
    let isDragging = false;
    let lastPosX, lastPosY;

    canvas.on('mouse:down', (opt) => {
        const evt = opt.e;
        if (evt.button === 2 || evt.button === 1) {
            isDragging = true;
            canvas.selection = false;
            lastPosX = evt.clientX;
            lastPosY = evt.clientY;
            opt.e.preventDefault();
            opt.e.stopPropagation();
        }
    });

    canvas.on('mouse:move', (opt) => {
        if (isDragging) {
            const e = opt.e;
            const vpt = canvas.viewportTransform;
            vpt[4] += e.clientX - lastPosX;
            vpt[5] += e.clientY - lastPosY;
            constrainViewport(canvas, mapImageObject, mapWidth, mapHeight);
            canvas.requestRenderAll();
            lastPosX = e.clientX;
            lastPosY = e.clientY;
        }
    });

    canvas.on('mouse:up', () => {
        canvas.setViewportTransform(canvas.viewportTransform);
        isDragging = false;
    });

    canvas.upperCanvasEl.addEventListener('contextmenu', (e) => e.preventDefault());

    // 초기 위치 지정 마커 그리기 헬퍼
    const drawInitialPoseMarker = (canvasX, canvasY, angleDeg) => {
        const zoom = canvas.getZoom();
        const scaleFactor = (0.306 / mapResolution) / 114;

        if (!initialPoseMarker) {
            const pathData = "M -17 8 C 7 -7 -7 -7 18 8 C 32 17 56 10 57 30 V 94 C 57 107 52 112 40 112 H -40 C -52 112 -57 107 -57 94 V 30 C -57 10 -32 17 -17 8 Z";
            initialPoseMarker = new fabric.Path(pathData, {
                fill: 'rgba(255, 0, 0, 0.25)',
                stroke: 'red',
                strokeWidth: 3 / zoom,
                strokeUniform: true,
                originX: 'center',
                originY: 0.65,
                selectable: false,
                hoverCursor: 'crosshair',
                scaleX: scaleFactor,
                scaleY: scaleFactor,
                left: canvasX,
                top: canvasY,
                angle: angleDeg
            });
            canvas.add(initialPoseMarker);
        } else {
            initialPoseMarker.set({
                left: canvasX,
                top: canvasY,
                angle: angleDeg,
                scaleX: scaleFactor,
                scaleY: scaleFactor,
                strokeWidth: 3 / zoom
            });
        }
        initialPoseMarker.canvasX = canvasX;
        initialPoseMarker.canvasY = canvasY;
        initialPoseMarker.angleDeg = angleDeg;
        canvas.requestRenderAll();
    };

    // 캔버스 좌클릭: 목표 지정 또는 초기 위치 설정
    canvas.on('mouse:down', (opt) => {
        const evt = opt.e;
        if (evt.button === 2 || evt.button === 1) return;

        const pointer = canvas.getPointer(evt);
        if (pointer.x < 0 || pointer.x > mapWidth || pointer.y < 0 || pointer.y > mapHeight) return;

        if (isSetInitialMode) {
            isInitialDragging = true;
            initialDragStart = { x: pointer.x, y: pointer.y };
            drawInitialPoseMarker(pointer.x, pointer.y, 0);
            return;
        }

        if (opt.target && opt.target.name === 'goal-marker') {
            canvas.remove(opt.target);
            currentMarker = null;
            document.getElementById('btn-moveto').disabled = true;
            canvas.renderAll();
            return;
        }

        if (currentMarker) {
            canvas.remove(currentMarker);
        }

        const zoom = canvas.getZoom();
        const pathString = `M -5 0 C 0 10, 0 10, 5 0 C 17 -22, -17 -22, -5 0 Z`;
        currentMarker = new fabric.Path(pathString, {
            fill: 'rgba(150,200,255, 0.5)',
            stroke: 'rgba(12, 104, 239, 1.0)',
            strokeWidth: 3,
            name: 'goal-marker',
            originX: 'center',
            originY: 'bottom',
            scaleX: 1 / zoom,
            scaleY: 1 / zoom,
            left: pointer.x,
            top: pointer.y
        });

        canvas.add(currentMarker);
        canvas.renderAll();
        document.getElementById('btn-moveto').disabled = false;
    });

    // 드래그 중인 경우 초기 위치 마커 방향 실시간 업데이트
    canvas.on('mouse:move', (opt) => {
        if (!isSetInitialMode || !isInitialDragging || !initialDragStart) return;
        const pointer = canvas.getPointer(opt.e);
        const dx = pointer.x - initialDragStart.x;
        const dy = pointer.y - initialDragStart.y;
        lastInitialAngleDeg = Math.atan2(dx, -dy) * (180 / Math.PI);
        drawInitialPoseMarker(initialDragStart.x, initialDragStart.y, lastInitialAngleDeg);
    });

    // 마우스 드래그가 끝났을 때 초기 위치 API 호출 및 모드 해제
    canvas.on('mouse:up', () => {
        if (!isSetInitialMode || !isInitialDragging || !initialDragStart) return;
        isInitialDragging = false;

        if (!initialPoseMarker) return;
        const angleDeg = lastInitialAngleDeg;
        const canvasX = initialDragStart.x;
        const canvasY = initialDragStart.y;

        const mx = canvasX * mapResolution + mapOriginX;
        const my = (mapHeight - canvasY) * mapResolution + mapOriginY;
        const yawRad = (90 - angleDeg) * (Math.PI / 180);

        fetch('/api/robot_set_initial_pose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x: mx, y: my, yaw: yawRad, robot: parseInt(currentRobotId) })
        })
        .then(res => res.json())
        .then(data => console.log('초기 위치 설정 완료:', data))
        .catch(err => console.error('초기 위치 설정 에러:', err));

        initialDragStart = null;
        isSetInitialMode = false;

        const btn = document.getElementById('btn-set-initial');
        if (btn) {
            btn.classList.remove('btn-danger', 'active');
            btn.classList.add('btn-secondary');
        }
        canvas.defaultCursor = 'default';
        canvas.hoverCursor = 'move';
    });

    // 목표 위치로 이동 전송 버튼 이벤트 바인딩
    document.getElementById('btn-moveto').addEventListener('click', () => {
        if (!currentMarker) return;

        const mx = currentMarker.left * mapResolution + mapOriginX;
        const my = (mapHeight - currentMarker.top) * mapResolution + mapOriginY;

        fetch('/api/robot_moveto', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ x: mx, y: my, robot: parseInt(currentRobotId) })
        })
        .then(res => res.json())
        .catch(err => console.error('Error sending move command:', err));
    });

    // 지도 새로고침 버튼 이벤트 바인딩
    document.getElementById('btn-refresh-map').addEventListener('click', current_robot_map);

    // 초기 위치 지정 모드 토글 버튼 이벤트 바인딩
    document.getElementById('btn-set-initial').addEventListener('click', function() {
        isSetInitialMode = !isSetInitialMode;

        if (isSetInitialMode) {
            this.classList.remove('btn-secondary');
            this.classList.add('btn-danger', 'active');
            if (initialPoseMarker) {
                canvas.remove(initialPoseMarker);
                initialPoseMarker = null;
                canvas.requestRenderAll();
            }
            canvas.defaultCursor = 'crosshair';
            canvas.hoverCursor = 'crosshair';
        } else {
            this.classList.remove('btn-danger', 'active');
            this.classList.add('btn-secondary');
            canvas.defaultCursor = 'default';
            canvas.hoverCursor = 'move';
            isInitialDragging = false;
            initialDragStart = null;
        }
    });

    // 첫 지도 렌더링 호출
    current_robot_map();
});
