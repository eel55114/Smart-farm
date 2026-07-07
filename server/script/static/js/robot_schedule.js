/**
 * 로봇 일정 계획 - 지도 뷰어 & 계획 관리 스크립트
 *
 * - Fabric.js 기반 지도 렌더링 (패닝·줌)
 * - 계획(plan) CRUD: 계획 선택자 / 노드 선택자 / 저장 메뉴
 * - 지도 위 웨이포인트 마커 (줌 무관 고정 크기)
 */

// ── 모듈 레벨 공유 상태 ─────────────────────────────────────────────────────
let canvas        = null;
let mapImageObject = null;
let mapWidth = 0, mapHeight = 0;
let mapResolution = 0.05;
let mapOriginX = 0, mapOriginY = 0;
let minZoom  = 0.1;
let currentMapName = null;
let isMapEditMode = false;

// 드래그 패닝 내부 상태
let _pan_active = false, _pan_x = 0, _pan_y = 0;

// 줌 변경 훅 (initPlanManager 가 덮어씀)
let _onZoomChange = () => {};

// ── 진입점 ─────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => { requestAnimationFrame(init); });

function init() {
    const container = document.getElementById('map-canvas-pane');

    canvas = new fabric.Canvas('map-canvas', {
        width:  container.clientWidth,
        height: container.clientHeight,
        selection:       false,
        fireRightClick:  true,
        fireMiddleClick: true,
    });

    // 창 크기 변경 대응
    window.addEventListener('resize', () => {
        canvas.setWidth(container.clientWidth);
        canvas.setHeight(container.clientHeight);
        _resetViewport();
    });

    // 마우스 휠 줌
    canvas.on('mouse:wheel', (opt) => {
        const delta = opt.e.deltaY;
        let zoom = canvas.getZoom();
        zoom *= 0.999 ** delta;
        zoom = Math.max(minZoom, Math.min(50, zoom));
        canvas.zoomToPoint({ x: opt.e.offsetX, y: opt.e.offsetY }, zoom);
        constrainViewport(canvas, mapImageObject, mapWidth, mapHeight);
        updateScaleBar(canvas, mapImageObject, mapResolution, 'map-scale-bar', 'scale-label', 'scale-line');
        _onZoomChange();
        opt.e.preventDefault();
        opt.e.stopPropagation();
    });

    // 우·중클릭 드래그 패닝
    canvas.on('mouse:down', (opt) => {
        if (opt.e.button === 2 || opt.e.button === 1) {
            _pan_active = true;
            canvas.selection = false;
            _pan_x = opt.e.clientX;
            _pan_y = opt.e.clientY;
            opt.e.preventDefault();
            opt.e.stopPropagation();
        }
    });
    canvas.on('mouse:move', (opt) => {
        if (!_pan_active) return;
        const vpt = canvas.viewportTransform;
        vpt[4] += opt.e.clientX - _pan_x;
        vpt[5] += opt.e.clientY - _pan_y;
        constrainViewport(canvas, mapImageObject, mapWidth, mapHeight);
        canvas.requestRenderAll();
        _pan_x = opt.e.clientX;
        _pan_y = opt.e.clientY;
    });
    canvas.on('mouse:up', () => {
        canvas.setViewportTransform(canvas.viewportTransform);
        _pan_active = false;
    });
    canvas.upperCanvasEl.addEventListener('contextmenu', (e) => e.preventDefault());

    // 계획 관리자 초기화 (canvas 확보 후)
    initPlanManager();

    // 지도 편집 관리자 이벤트 초기화
    initMapEditorEvents();

    // 초기 지도 + 계획 로드
    const initMap = document.getElementById('map-select')?.value;
    if (initMap) {
        currentMapName = initMap;
        _loadMap(initMap, () => {
            if (window._planLoadPlans) window._planLoadPlans(initMap);
        });
    }
}

// ── 뷰포트 ─────────────────────────────────────────────────────────────────
function _resetViewport() {
    if (!mapImageObject || mapWidth === 0) return;
    const sx = canvas.width  / mapWidth;
    const sy = canvas.height / mapHeight;
    minZoom = Math.min(sx, sy) * 0.95;
    const vpt = canvas.viewportTransform;
    vpt[0] = minZoom; vpt[3] = minZoom;
    vpt[4] = (canvas.width  - mapWidth  * minZoom) / 2;
    vpt[5] = (canvas.height - mapHeight * minZoom) / 2;
    canvas.setViewportTransform(vpt);
    constrainViewport(canvas, mapImageObject, mapWidth, mapHeight);
    updateScaleBar(canvas, mapImageObject, mapResolution, 'map-scale-bar', 'scale-label', 'scale-line');
    _onZoomChange();
    canvas.requestRenderAll();
}

// ── 지도 로드 ───────────────────────────────────────────────────────────────
function _loadMap(mapName, callback) {
    if (!mapName) return;
    const scaleBar    = document.getElementById('map-scale-bar');
    const placeholder = document.getElementById('map-placeholder');

    fetch(`/api/map_data/${encodeURIComponent(mapName)}`)
        .then(r => r.ok ? r.json() : r.json().then(e => Promise.reject(new Error(e.error))))
        .then(data => {
            mapWidth          = data.width;
            mapHeight         = data.height;
            mapResolution     = data.resolution || 0.05;
            mapOriginX        = data.origin?.[0] ?? -(data.width * mapResolution) / 2;
            mapOriginY        = data.origin?.[1] ?? -(data.height * mapResolution) / 2;
            mapMode           = data.mode || 'trinary';
            mapNegate         = data.negate || 0;
            mapOccupiedThresh = data.occupied_thresh || 0.65;
            mapFreeThresh     = data.free_thresh || 0.196;

            if (mapImageObject) { canvas.remove(mapImageObject); mapImageObject = null; }

            const url = drawOccupancyGrid(mapWidth, mapHeight, data.array, data.mode);
            fabric.Image.fromURL(url, (img) => {
                mapImageObject = img;
                img.set({ left: 0, top: 0, selectable: false, hoverCursor: 'default', imageSmoothing: false });
                canvas.add(img);
                canvas.sendToBack(img);
                _resetViewport();
                if (placeholder) placeholder.style.display = 'none';
                if (scaleBar)    scaleBar.classList.remove('d-none');
                
                if (typeof callback === 'function') {
                    callback();
                } else {
                    if (window._planRerenderMarkers) window._planRerenderMarkers();
                }
            });
        })
        .catch(err => {
            console.error('[Map Load]', err);
            canvas.clear();
            canvas.setBackgroundColor('#212529', canvas.renderAll.bind(canvas));
            mapImageObject = null; mapWidth = 0; mapHeight = 0;
            if (placeholder) placeholder.style.display = 'flex';
            if (scaleBar)    scaleBar.classList.add('d-none');
        });
}

function _clearMap() {
    canvas.clear();
    canvas.setBackgroundColor('#212529', canvas.renderAll.bind(canvas));
    mapImageObject = null; mapWidth = 0; mapHeight = 0;
    const placeholder = document.getElementById('map-placeholder');
    const scaleBar    = document.getElementById('map-scale-bar');
    if (placeholder) placeholder.style.display = 'flex';
    if (scaleBar)    scaleBar.classList.add('d-none');
}

// ── 드롭다운 변경 시 템플릿에서 호출 ──────────────────────────────────────
window.scheduleLoadMap = function(mapName) {
    currentMapName = mapName || null;
    if (mapName) {
        _loadMap(mapName, () => {
            if (window._planLoadPlans) window._planLoadPlans(mapName);
        });
    } else {
        _clearMap();
        if (window._planClearPlans) window._planClearPlans();
    }
};


// ══════════════════════════════════════════════════════════════════════════════
// 계획 관리자
// ══════════════════════════════════════════════════════════════════════════════
function initPlanManager() {

    // 웨이포인트 마커 패스
    const D_PATH  = 'M -40 30 C 4 -3 -4 -3 40 30 C 51 39 55 41 55 57 V 100 C 55 109 49 119 34 112 C 7 100 -7 100 -34 112 C -49 118 -55 109 -55 100 V 57 C -55 40 -51 39 -40 30 Z';
    const UD_PATH = 'M -20 6 C -10 -2, 10 -2, 20 6 C 30 14, 46 30, 54 40 C 62 50, 62 70, 54 80 C 46 90, 30 106, 20 114 C 10 122, -10 122, -20 114 C -30 106, -46 90, -54 80 C -62 70, -62 50, -54 40 C -46 30, -30 14, -20 6 Z';
    const MS_PATH = D_PATH; // 촬영 마커는 지향 마커와 동일한 패스, 초록색으로 구분
    const TARGET_PX = 24;
    const D_NAT  = 110;
    const UD_NAT = 124;
    const MS_NAT = D_NAT;  // 촬영 마커 자연 크기 = 지향 마커와 동일

    // 계획 상태
    let plans = [];
    let selectedIdx   = -1;   // plans 배열 인덱스
    let editedPlan    = null;  // 현재 편집 중인 깊은 복사본
    let isDirty       = false;
    let waypointMarkers = [];
    let waypointLines = [];
    let activeEditSeq = -1;   // 편집 모드인 노드의 sequence 인덱스
    let dragSrc       = -1;   // 드래그 소스 sequence 인덱스

    // 위치 재설정 상태 변수
    let isPositionResettingActive = false;
    let positionResetStart = null;
    let isPositionDragging = false;

    function resetPositionResetState() {
        isPositionResettingActive = false;
        positionResetStart = null;
        isPositionDragging = false;
        if (canvas) {
            canvas.defaultCursor = 'default';
            canvas.hoverCursor = 'move';
        }
    }

    function changeActiveEditSeq(seqIdx) {
        resetPositionResetState();
        activeEditSeq = seqIdx;
    }

    // DOM 참조
    const elPlanDropdown  = document.getElementById('plan-dropdown');
    const elBtnAddPlan    = document.getElementById('btn-add-plan');
    const elBtnDelPlan    = document.getElementById('btn-delete-plan');
    const elNodeSelector  = document.getElementById('node-selector');
    const elPlanName      = document.getElementById('plan-name-input');
    const elNodeList      = document.getElementById('node-list-container');
    const elBtnAddNode    = document.getElementById('btn-add-node');
    const elSaveMenu      = document.getElementById('save-menu');
    const elBtnCancel     = document.getElementById('btn-cancel-plan');
    const elBtnSave       = document.getElementById('btn-save-plan');

    // 추가 스케줄 및 실행 메뉴 DOM 참조
    const elScheduleSelector = document.getElementById('schedule-selector');
    const elScheduleListContainer = document.getElementById('schedule-list-container');
    const elBtnAddSchedule = document.getElementById('btn-add-schedule');
    const elExecuteMenu = document.getElementById('execute-menu');
    const elBtnExecutePlan = document.getElementById('btn-execute-plan');

    let activeEditSchedId = -1;  // 편집 중인 스케줄 ID (-1이면 없음)

    // ── 헬퍼 ──────────────────────────────────────────────────────────────
    const dc = o => JSON.parse(JSON.stringify(o));

    function orderedNodes() {
        if (!editedPlan) return [];
        return editedPlan.sequence
            .map(id => editedPlan.waypoint.find(w => w.id === id))
            .filter(Boolean);
    }

    function markDirty() { isDirty = true; syncSaveMenu(); }

    function syncSaveMenu() {
        elSaveMenu.style.display = (isDirty && editedPlan) ? 'flex' : 'none';
        elExecuteMenu.style.display = editedPlan ? 'block' : 'none';
    }

    function w2c(wx, wy) {           // world → canvas 좌표 변환
        return {
            x: (wx - mapOriginX) / mapResolution,
            y: mapHeight - (wy - mapOriginY) / mapResolution,
        };
    }

    function c2w(cx, cy) {           // canvas → world 좌표 변환
        return {
            x: cx * mapResolution + mapOriginX,
            y: (mapHeight - cy) * mapResolution + mapOriginY,
        };
    }

    // ── 서버 통신 ──────────────────────────────────────────────────────────
    async function writePlans() {
        if (!currentMapName) return;
        try {
            await fetch(`/api/plans/${encodeURIComponent(currentMapName)}`, {
                method:  'PUT',
                headers: { 'Content-Type': 'application/json' },
                body:    JSON.stringify({ plans }),
            });
        } catch (e) { console.error('[Plan Write]', e); }
    }

    // ── 로드 / 클리어 ──────────────────────────────────────────────────────
    async function loadPlans(mapName) {
        try {
            const res  = await fetch(`/api/plans/${encodeURIComponent(mapName)}`);
            const data = await res.json();
            plans = data.plans || [];
            plans.forEach(p => {
                if (!p.schedule) p.schedule = [];
            });
        } catch (e) { console.error('[Plan Load]', e); plans = []; }

        selectedIdx   = plans.length > 0 ? 0 : -1;
        editedPlan    = selectedIdx >= 0 ? dc(plans[selectedIdx]) : null;
        if (editedPlan && !editedPlan.schedule) editedPlan.schedule = [];
        isDirty       = false;
        activeEditSchedId = -1;
        changeActiveEditSeq(-1);
        renderDropdown();
        renderNodeList();
        renderScheduleList();
        renderMarkers();
        syncSaveMenu();
    }

    function clearPlans() {
        plans = []; selectedIdx = -1; editedPlan = null;
        isDirty = false;
        activeEditSchedId = -1;
        changeActiveEditSeq(-1);
        clearMarkers();
        renderDropdown();
        renderNodeList();
        renderScheduleList();
        syncSaveMenu();
    }

    // ── 계획 드롭다운 ──────────────────────────────────────────────────────
    function renderDropdown() {
        elPlanDropdown.innerHTML = '';
        if (plans.length === 0) {
            const o = document.createElement('option');
            o.value = ''; o.textContent = '계획 없음';
            elPlanDropdown.appendChild(o);
            elBtnDelPlan.disabled = true;
        } else {
            plans.forEach((p, i) => {
                const o = document.createElement('option');
                o.value = i; o.textContent = p.name;
                if (i === selectedIdx) o.selected = true;
                elPlanDropdown.appendChild(o);
            });
            elBtnDelPlan.disabled = false;
        }
        elBtnAddPlan.disabled = !currentMapName;
    }

    elPlanDropdown.addEventListener('change', () => {
        const idx = parseInt(elPlanDropdown.value);
        if (isNaN(idx) || idx < 0) return;
        selectedIdx   = idx;
        editedPlan    = dc(plans[selectedIdx]);
        if (editedPlan && !editedPlan.schedule) editedPlan.schedule = [];
        isDirty       = false;
        activeEditSchedId = -1;
        changeActiveEditSeq(-1);
        renderNodeList();
        renderScheduleList();
        renderMarkers();
        syncSaveMenu();
    });

    // 계획 추가
    elBtnAddPlan.addEventListener('click', async () => {
        if (!currentMapName) return;
        const base = '새 계획';
        let name = base, n = 2;
        const used = plans.map(p => p.name);
        while (used.includes(name)) name = `${base} (${n++})`;
        plans.push({ name, waypoint: [], sequence: [], schedule: [] });
        await writePlans();
        selectedIdx   = plans.length - 1;
        editedPlan    = dc(plans[selectedIdx]);
        isDirty       = false;
        activeEditSchedId = -1;
        changeActiveEditSeq(-1);
        renderDropdown();
        renderNodeList();
        renderScheduleList();
        renderMarkers();
        syncSaveMenu();
    });

    // 계획 삭제
    elBtnDelPlan.addEventListener('click', () => {
        if (selectedIdx < 0 || plans.length === 0) return;
        showConfirm(
            '계획 삭제',
            `'${plans[selectedIdx].name}'을(를) 삭제하시겠습니까?`,
            async () => {
                plans.splice(selectedIdx, 1);
                await writePlans();
                selectedIdx   = plans.length > 0 ? Math.min(selectedIdx, plans.length - 1) : -1;
                editedPlan    = selectedIdx >= 0 ? dc(plans[selectedIdx]) : null;
                if (editedPlan && !editedPlan.schedule) editedPlan.schedule = [];
                isDirty       = false;
                activeEditSchedId = -1;
                changeActiveEditSeq(-1);
                renderDropdown();
                renderNodeList();
                renderScheduleList();
                renderMarkers();
                syncSaveMenu();
            }
        );
    });

    // ── 노드 리스트 ────────────────────────────────────────────────────────
    function renderNodeList() {
        elNodeList.innerHTML = '';

        if (!editedPlan) {
            elPlanName.value = '';
            elPlanName.disabled = true;
            elBtnAddNode.style.display = 'none';
            elNodeList.innerHTML = currentMapName
                ? '<p class="text-muted text-center small py-3 mb-0">계획을 선택하거나 추가하세요.</p>'
                : '<p class="text-muted text-center small py-3 mb-0">지도를 선택하세요.</p>';
            return;
        }

        elPlanName.value = editedPlan.name;
        elPlanName.disabled = false;
        elBtnAddNode.style.display = 'block';

        orderedNodes().forEach((node, seqIdx) => {
            elNodeList.appendChild(makeNodeCard(node, seqIdx));
        });
    }

    // ── 노드 카드 ──────────────────────────────────────────────────────────
    function makeNodeCard(node, seqIdx) {
        const inEdit = seqIdx === activeEditSeq;
        const card = document.createElement('div');
        card.className = 'node-card' + (inEdit ? ' node-card--edit' : '');
        card.dataset.seqIdx = seqIdx;

        if (!inEdit) {
            /* ── 일반 모드 ── */
            const tDeg = (node.theta * 180 / Math.PI).toFixed(0);
            card.draggable = true;
            card.innerHTML =
                `<span class="node-drag-handle" title="드래그하여 순서 조정">⠿</span>` +
                `<span class="badge bg-secondary node-id-badge">${node.id}</span>` +
                `<span class="node-coords">` +
                    `x<b>${parseFloat(node.x).toFixed(2)}</b> ` +
                    `y<b>${parseFloat(node.y).toFixed(2)}</b>` +
                    (node.type !== 'ud' ? ` 각도<b>${tDeg}</b>` : '') +
                `</span>` +
                `<span class="badge ${node.type === 'd' ? 'bg-primary' : node.type === 'ms' ? 'bg-success' : 'bg-warning text-dark'} node-type-badge">${node.type === 'd' ? '지향' : node.type === 'ms' ? '촬영' : '위치'}</span>` +
                `<button class="btn-node-del" title="노드 삭제">✕</button>`;

            card.querySelector('.btn-node-del').addEventListener('click', (e) => {
                e.stopPropagation();
                showConfirm('노드 삭제', `순서 ${seqIdx + 1}번 노드(id:${node.id})를 삭제하시겠습니까?`, () => deleteNode(seqIdx));
            });

            card.addEventListener('click', () => {
                changeActiveEditSeq(seqIdx);
                renderNodeList();
                renderMarkers();
            });

            // 마우스 호버 시 마커 빨간색 하이라이트
            card.addEventListener('mouseenter', () => {
                if (activeEditSeq === -1) {
                    const marker = waypointMarkers[seqIdx];
                    if (marker) {
                        marker.set({
                            fill: 'rgba(220, 53, 69, 0.28)',
                            stroke: '#dc3545'
                        });
                        canvas.requestRenderAll();
                    }
                }
            });
            card.addEventListener('mouseleave', () => {
                if (activeEditSeq === -1) {
                    const marker = waypointMarkers[seqIdx];
                    if (marker) {
                        const isD = node.type === 'd';
                        const isMs = node.type === 'ms';
                        marker.set({
                            fill: isD ? 'rgba(13,110,253,0.28)' : isMs ? 'rgba(59,191,78,0.28)' : 'rgba(255,160,0,0.28)',
                            stroke: isD ? '#0d6efd' : isMs ? '#3bbf4e' : '#ff8c00'
                        });
                        canvas.requestRenderAll();
                    }
                }
            });

            /* 드래그&드롭 */
            card.addEventListener('dragstart', (e) => {
                dragSrc = seqIdx;
                e.dataTransfer.effectAllowed = 'move';
                setTimeout(() => card.classList.add('node-card--dragging'), 0);
            });
            card.addEventListener('dragend', () => {
                card.classList.remove('node-card--dragging');
                elNodeList.querySelectorAll('.node-card--over').forEach(c => c.classList.remove('node-card--over'));
                dragSrc = -1;
            });
            card.addEventListener('dragover', (e) => {
                e.preventDefault();
                e.dataTransfer.dropEffect = 'move';
                elNodeList.querySelectorAll('.node-card--over').forEach(c => c.classList.remove('node-card--over'));
                if (dragSrc !== seqIdx) card.classList.add('node-card--over');
            });
            card.addEventListener('dragleave', () => card.classList.remove('node-card--over'));
            card.addEventListener('drop', (e) => {
                e.preventDefault();
                card.classList.remove('node-card--over');
                if (dragSrc >= 0 && dragSrc !== seqIdx) {
                    const seq = editedPlan.sequence;
                    const [moved] = seq.splice(dragSrc, 1);
                    seq.splice(seqIdx, 0, moved);
                    dragSrc = -1;
                    markDirty();
                    renderNodeList();
                    renderMarkers();
                }
            });

        } else {
            /* ── 편집 모드 ── */
            const tDeg = (node.theta * 180 / Math.PI).toFixed(1);
            card.draggable = false;
            card.innerHTML =
                `<div class="d-flex align-items-center gap-2 mb-2">` +
                    `<span class="badge bg-secondary">${node.id}</span>` +
                    `<div class="btn-group btn-group-sm ms-auto">` +
                        `<input type="radio" class="btn-check" name="ne-type-${seqIdx}" id="ne-d-${seqIdx}" value="d" autocomplete="off" ${node.type === 'd' ? 'checked' : ''}>` +
                        `<label class="btn btn-outline-primary" for="ne-d-${seqIdx}">지향</label>` +
                        `<input type="radio" class="btn-check" name="ne-type-${seqIdx}" id="ne-ud-${seqIdx}" value="ud" autocomplete="off" ${node.type === 'ud' ? 'checked' : ''}>` +
                        `<label class="btn btn-outline-warning" for="ne-ud-${seqIdx}">위치</label>` +
                        `<input type="radio" class="btn-check" name="ne-type-${seqIdx}" id="ne-ms-${seqIdx}" value="ms" autocomplete="off" ${node.type === 'ms' ? 'checked' : ''}>` +
                        `<label class="btn btn-outline-success" for="ne-ms-${seqIdx}">촬영</label>` +
                    `</div>` +
                `</div>` +
                `<div class="d-flex gap-1 mb-2">` +
                    `<div class="flex-fill"><label class="node-edit-label">x (m)</label>` +
                        `<input id="ne-x-${seqIdx}" type="number" class="form-control form-control-sm" value="${parseFloat(node.x).toFixed(3)}" step="0.01"></div>` +
                    `<div class="flex-fill"><label class="node-edit-label">y (m)</label>` +
                        `<input id="ne-y-${seqIdx}" type="number" class="form-control form-control-sm" value="${parseFloat(node.y).toFixed(3)}" step="0.01"></div>` +
                    `<div class="flex-fill"><label class="node-edit-label">각도</label>` +
                        `<input id="ne-t-${seqIdx}" type="number" class="form-control form-control-sm" value="${tDeg}" step="1"></div>` +
                `</div>` +
                `<button class="btn btn-outline-danger btn-sm w-100 mb-2 ne-reset-pos">위치 재설정</button>` +
                `<div class="d-flex gap-1">` +
                    `<button class="btn btn-outline-secondary btn-sm flex-fill ne-cancel">취소</button>` +
                    `<button class="btn btn-primary btn-sm flex-fill ne-confirm border-0 shadow-sm">확인</button>` +
                `</div>`;

            const btnReset = card.querySelector('.ne-reset-pos');
            if (btnReset) {
                btnReset.addEventListener('click', () => {
                    isPositionResettingActive = !isPositionResettingActive;
                    if (isPositionResettingActive) {
                        btnReset.classList.remove('btn-outline-danger');
                        btnReset.classList.add('btn-danger', 'active');
                        btnReset.textContent = '지도를 클릭 후 드래그하세요';
                        canvas.defaultCursor = 'crosshair';
                        canvas.hoverCursor = 'crosshair';
                    } else {
                        btnReset.classList.remove('btn-danger', 'active');
                        btnReset.classList.add('btn-outline-danger');
                        btnReset.textContent = '위치 재설정';
                        canvas.defaultCursor = 'default';
                        canvas.hoverCursor = 'move';
                    }
                });
            }

            card.querySelector('.ne-cancel').addEventListener('click', () => {
                changeActiveEditSeq(-1);
                renderNodeList();
                renderMarkers();
            });
            card.querySelector('.ne-confirm').addEventListener('click', () => {
                const xv = parseFloat(document.getElementById(`ne-x-${seqIdx}`).value);
                const yv = parseFloat(document.getElementById(`ne-y-${seqIdx}`).value);
                const tv = parseFloat(document.getElementById(`ne-t-${seqIdx}`).value);
                const type = document.querySelector(`input[name="ne-type-${seqIdx}"]:checked`)?.value || node.type;
                if (!isNaN(xv) && !isNaN(yv) && !isNaN(tv)) {
                    node.x = xv; node.y = yv;
                    node.theta = tv * Math.PI / 180;
                    node.type  = type;
                    changeActiveEditSeq(-1);
                    markDirty();
                    renderNodeList();
                    renderMarkers();
                }
            });
        }

        return card;
    }

    // 노드 삭제
    function deleteNode(seqIdx) {
        const nodeId = editedPlan.sequence[seqIdx];
        editedPlan.sequence.splice(seqIdx, 1);
        editedPlan.waypoint = editedPlan.waypoint.filter(w => w.id !== nodeId);
        resetPositionResetState();
        if (activeEditSeq === seqIdx)       activeEditSeq = -1;
        else if (activeEditSeq > seqIdx)    activeEditSeq--;
        markDirty();
        renderNodeList();
        renderMarkers();
    }

    function addNodeAt(wx, wy) {
        if (!editedPlan) return;
        const nextId = editedPlan.waypoint.length > 0
            ? Math.max(...editedPlan.waypoint.map(w => w.id)) + 1 : 0;
        editedPlan.waypoint.push({ id: nextId, type: 'ud', x: wx, y: wy, theta: 0 });
        editedPlan.sequence.push(nextId);
        markDirty();
        renderNodeList();
        renderMarkers();
        elNodeSelector.scrollTop = elNodeSelector.scrollHeight;
    }

    // 노드 추가
    elBtnAddNode.addEventListener('click', () => {
        if (!editedPlan) return;
        const cx = mapWidth / 2;
        const cy = mapHeight / 2;
        const worldPos = c2w(cx, cy);
        addNodeAt(worldPos.x, worldPos.y);
    });

    // 계획 이름 변경
    elPlanName.addEventListener('input', () => {
        if (editedPlan) { editedPlan.name = elPlanName.value; markDirty(); }
    });

    // ── 저장 / 취소 ────────────────────────────────────────────────────────
    elBtnSave.addEventListener('click', async () => {
        if (!editedPlan || !isDirty) return;
        changeActiveEditSeq(-1);
        plans[selectedIdx] = dc(editedPlan);
        await writePlans();
        isDirty = false;
        renderDropdown();
        renderNodeList();
        syncSaveMenu();
    });

    elBtnCancel.addEventListener('click', () => {
        editedPlan    = selectedIdx >= 0 ? dc(plans[selectedIdx]) : null;
        if (editedPlan && !editedPlan.schedule) editedPlan.schedule = [];
        isDirty       = false;
        activeEditSchedId = -1;
        changeActiveEditSeq(-1);
        renderNodeList();
        renderScheduleList();
        renderMarkers();
        syncSaveMenu();
    });

    // ── 캔버스 웨이포인트 마커 ─────────────────────────────────────────────
    function renderMarkers() {
        clearMarkers();
        if (!editedPlan || mapWidth === 0 || !canvas) return;

        const zoom = canvas.getZoom();
        const nodes = orderedNodes();

        // 1. 순서가 정의된 노드들 사이에 파란색 점선 경로 연결 그리기
        for (let i = 0; i < nodes.length - 1; i++) {
            const p1 = w2c(nodes[i].x, nodes[i].y);
            const p2 = w2c(nodes[i + 1].x, nodes[i + 1].y);

            const line = new fabric.Line([p1.x, p1.y, p2.x, p2.y], {
                stroke:          'rgba(13, 110, 253, 0.5)', // 투명도 50%의 파란 선
                strokeWidth:     1.2 / zoom, // 줌에 상관없이 화면상 1.2px 두께로 가늘게 표시
                strokeDashArray: [5 / zoom, 5 / zoom], // 줌에 상관없이 화면상 일정 크기 점선패턴 유지
                selectable:      false,
                hoverCursor:     'default',
                evented:         false
            });
            waypointLines.push(line);
            canvas.add(line);
            if (mapImageObject) {
                line.bringForward(); // 맵 이미지보다는 무조건 위에 오도록 설정
            }
        }

        // 2. 각 노드 마커 그리기
        nodes.forEach((node, seqIdx) => {
            const isD  = node.type === 'd';
            const isMs = node.type === 'ms';
            const nat = isD ? D_NAT : isMs ? MS_NAT : UD_NAT;
            const sizeFactor = (isD || isMs) ? 0.7 : 0.8; // d/ms 마커는 70%, ud 마커는 80% 크기
            const sc  = (TARGET_PX * sizeFactor) / (nat * zoom);
            const sw  = 3 * nat / (TARGET_PX * sizeFactor); // 화면상 외곽선 두께가 항상 3px이 되도록 비율 계산
            const pos = w2c(node.x, node.y);
            const ang = (isD || isMs) ? -(node.theta * 180 / Math.PI) + 90 : 0;

            const inEdit = seqIdx === activeEditSeq;
            const fill   = inEdit ? 'rgba(220,53,69,0.28)'
                         : isD    ? 'rgba(13,110,253,0.28)'
                         : isMs   ? 'rgba(59,191,78,0.28)'
                         :          'rgba(255,160,0,0.28)';
            const stroke = inEdit ? '#dc3545'
                         : isD    ? '#0d6efd'
                         : isMs   ? '#3bbf4e'
                         :          '#ff8c00';

            const m = new fabric.Path(isMs ? MS_PATH : isD ? D_PATH : UD_PATH, {
                fill:         fill,
                stroke:       stroke,
                strokeWidth:  sw,
                originX:      'center',
                originY:      'center',
                left:         pos.x,
                top:          pos.y,
                angle:        ang,
                scaleX:       sc,
                scaleY:       sc,
                selectable:   false,
                hoverCursor:  'default',
                name:         'waypoint-marker',
                data:         { seqIdx, nat, sizeFactor }
            });
            waypointMarkers.push(m);
            canvas.add(m);
        });

        // 맵 배경 이미지를 가장 뒤로 보냄
        if (mapImageObject) {
            mapImageObject.sendToBack();
        }
        canvas.requestRenderAll();
    }

    function clearMarkers() {
        waypointMarkers.forEach(m => canvas && canvas.remove(m));
        waypointMarkers = [];
        waypointLines.forEach(l => canvas && canvas.remove(l));
        waypointLines = [];
    }

    function updateConnectedLines(seqIdx, cx, cy) {
        if (seqIdx > 0) {
            const prevLine = waypointLines[seqIdx - 1];
            if (prevLine) {
                prevLine.set({ x2: cx, y2: cy });
            }
        }
        if (seqIdx < orderedNodes().length - 1) {
            const nextLine = waypointLines[seqIdx];
            if (nextLine) {
                nextLine.set({ x1: cx, y1: cy });
            }
        }
    }

    function updateMarkerScales() {
        if (!canvas) return;
        const zoom = canvas.getZoom();
        waypointMarkers.forEach(m => {
            const sc = (TARGET_PX * m.data.sizeFactor) / (m.data.nat * zoom);
            m.set({ scaleX: sc, scaleY: sc });
        });
        waypointLines.forEach(l => {
            l.set({
                strokeWidth:     1.2 / zoom,
                strokeDashArray: [5 / zoom, 5 / zoom]
            });
        });
        canvas.requestRenderAll();
    }

    // 캔버스 좌클릭 이벤트 핸들러
    canvas.on('mouse:down', (opt) => {
        if (isMapEditMode) return;
        if (!editedPlan) return;
        const evt = opt.e;
        if (evt.button === 2 || evt.button === 1) return; // 우클릭/휠클릭 패닝 동작은 제외

        const pointer = canvas.getPointer(evt);
        if (pointer.x < 0 || pointer.x > mapWidth || pointer.y < 0 || pointer.y > mapHeight) return;

        // 1. 위치 재설정 모드가 활성화되어 있고 노드를 편집 중인 경우 클릭한 위치로 좌표 설정 및 드래그 시작
        if (isPositionResettingActive && activeEditSeq >= 0) {
            isPositionDragging = true;
            positionResetStart = { x: pointer.x, y: pointer.y };

            const worldPos = c2w(pointer.x, pointer.y);
            const elX = document.getElementById(`ne-x-${activeEditSeq}`);
            const elY = document.getElementById(`ne-y-${activeEditSeq}`);
            const elT = document.getElementById(`ne-t-${activeEditSeq}`);
            if (elX) elX.value = worldPos.x.toFixed(3);
            if (elY) elY.value = worldPos.y.toFixed(3);
            if (elT) elT.value = "0.0"; // 클릭 시 일단 헤딩각을 0도로 채움 (드래그 방향에 따라 갱신)

            const marker = waypointMarkers[activeEditSeq];
            if (marker) {
                marker.set({
                    left: pointer.x,
                    top: pointer.y,
                    angle: 90 // 0도 헤딩각은 Fabric 각도로 90도 회전
                });
                updateConnectedLines(activeEditSeq, pointer.x, pointer.y); // 점선 연결 갱신
                canvas.requestRenderAll();
            }
            return;
        }

        // 2. waypoint 마커 클릭 시 해당 노드를 편집 모드로 설정
        if (opt.target && opt.target.name === 'waypoint-marker') {
            const seqIdx = opt.target.data.seqIdx;
            if (seqIdx !== undefined && seqIdx !== null) {
                changeActiveEditSeq(seqIdx);
                renderNodeList();
                renderMarkers();
            }
            return;
        }
    });

    // 드래그 방향에 따라 헤딩각(theta) 계산 핸들러
    canvas.on('mouse:move', (opt) => {
        if (isMapEditMode) return;
        if (!editedPlan || !isPositionResettingActive || !isPositionDragging || !positionResetStart) return;

        const pointer = canvas.getPointer(opt.e);
        const dx = pointer.x - positionResetStart.x;
        const dy = pointer.y - positionResetStart.y;

        let angleDeg = 90; // Default Fabric angle pointing East
        let thetaRad = 0;

        if (dx !== 0 || dy !== 0) {
            angleDeg = Math.atan2(dx, -dy) * (180 / Math.PI);
            thetaRad = (90 - angleDeg) * (Math.PI / 180);
        }

        // 각도 입력창 실시간 업데이트 (도 단위)
        const elT = document.getElementById(`ne-t-${activeEditSeq}`);
        if (elT) {
            let thetaDeg = 90 - angleDeg;
            if (thetaDeg > 180) thetaDeg -= 360;
            if (thetaDeg <= -180) thetaDeg += 360;
            elT.value = thetaDeg.toFixed(1);
        }

        const marker = waypointMarkers[activeEditSeq];
        if (marker) {
            marker.set({ angle: angleDeg });
            canvas.requestRenderAll();
        }
    });

    // 드래그 마우스 업 핸들러
    canvas.on('mouse:up', () => {
        if (isMapEditMode) return;
        if (isPositionDragging) {
            isPositionDragging = false;
            isPositionResettingActive = false;

            // UI 버튼 일반 상태로 복원
            const btnReset = document.querySelector('.ne-reset-pos');
            if (btnReset) {
                btnReset.classList.remove('btn-danger', 'active');
                btnReset.classList.add('btn-outline-danger');
                btnReset.textContent = '위치 재설정';
            }

            // 캔버스 마우스 커서 일반으로 복원
            canvas.defaultCursor = 'default';
            canvas.hoverCursor = 'move';
        }
    });

    // ── 스케줄 리스트 렌더링 ──────────────────────────────────────────────────
    function renderScheduleList() {
        elScheduleListContainer.innerHTML = '';
        if (!editedPlan) {
            elScheduleSelector.style.display = 'none';
            return;
        }

        elScheduleSelector.style.display = 'block';

        if (!editedPlan.schedule) {
            editedPlan.schedule = [];
        }

        editedPlan.schedule.forEach((sched) => {
            elScheduleListContainer.appendChild(makeScheduleCard(sched));
        });
    }

    function makeScheduleCard(sched) {
        const inEdit = sched.id === activeEditSchedId;
        const card = document.createElement('div');
        
        if (!inEdit) {
            /* ── 일반 모드 ── */
            const hourStr = String(sched.hour).padStart(2, '0');
            const minuteStr = String(sched.minute).padStart(2, '0');

            card.className = 'schedule-card d-flex align-items-center justify-content-between p-2 border rounded mb-1 bg-white';
            card.style.cursor = 'pointer';
            card.innerHTML =
                `<span class="fw-bold text-dark" style="font-size: 0.875rem;">${sched.name}</span>` +
                `<span class="badge bg-light text-dark border" style="font-size: 0.875rem;">매일 ${hourStr}시 ${minuteStr}분</span>`;
            
            card.addEventListener('click', () => {
                activeEditSchedId = sched.id;
                renderScheduleList();
            });
        } else {
            /* ── 스케줄 편집 모드 ── */
            card.className = 'schedule-card schedule-card--edit p-3 border rounded border-primary mb-1 bg-light';
            card.innerHTML =
                `<div class="mb-2">` +
                    `<label class="form-label small text-secondary fw-bold mb-1">일정 이름</label>` +
                    `<input type="text" id="sched-edit-name-${sched.id}" class="form-control form-control-sm" value="${sched.name}">` +
                `</div>` +
                `<div class="d-flex align-items-center gap-1 mb-3">` +
                    `<span class="small text-dark fw-semibold">매일</span>` +
                    `<input type="number" id="sched-edit-hour-${sched.id}" class="form-control form-control-sm text-center" style="width: 65px;" value="${sched.hour}" min="0" max="23">` +
                    `<span class="small text-dark fw-semibold">시</span>` +
                    `<input type="number" id="sched-edit-minute-${sched.id}" class="form-control form-control-sm text-center" style="width: 65px;" value="${sched.minute}" min="0" max="59">` +
                    `<span class="small text-dark fw-semibold">분</span>` +
                `</div>` +
                `<div class="d-flex gap-1 justify-content-end">` +
                    `<button class="btn btn-outline-danger btn-sm px-2 py-1 btn-sched-del">삭제</button>` +
                    `<div class="ms-auto"></div>` +
                    `<button class="btn btn-outline-secondary btn-sm px-3 py-1 btn-sched-cancel">취소</button>` +
                    `<button class="btn btn-primary btn-sm px-3 py-1 btn-sched-confirm border-0 shadow-sm">확인</button>` +
                `</div>`;
            
            card.querySelector('.btn-sched-del').addEventListener('click', (e) => {
                e.stopPropagation();
                showConfirm('일정 삭제', `스케줄 '${sched.name}'을(를) 삭제하시겠습니까?`, () => {
                    editedPlan.schedule = editedPlan.schedule.filter(s => s.id !== sched.id);
                    activeEditSchedId = -1;
                    markDirty();
                    renderScheduleList();
                });
            });

            card.querySelector('.btn-sched-cancel').addEventListener('click', (e) => {
                e.stopPropagation();
                activeEditSchedId = -1;
                renderScheduleList();
            });

            card.querySelector('.btn-sched-confirm').addEventListener('click', (e) => {
                e.stopPropagation();
                const newName = document.getElementById(`sched-edit-name-${sched.id}`).value.trim();
                let newHour = parseInt(document.getElementById(`sched-edit-hour-${sched.id}`).value);
                let newMinute = parseInt(document.getElementById(`sched-edit-minute-${sched.id}`).value);

                if (!newName) {
                    alert('일정 이름을 입력해 주세요.');
                    return;
                }
                if (isNaN(newHour) || newHour < 0 || newHour > 23) {
                    alert('시는 0에서 23 사이의 숫자여야 합니다.');
                    return;
                }
                if (isNaN(newMinute) || newMinute < 0 || newMinute > 59) {
                    alert('분은 0에서 59 사이의 숫자여야 합니다.');
                    return;
                }

                sched.name = newName;
                sched.hour = newHour;
                sched.minute = newMinute;

                activeEditSchedId = -1;
                markDirty();
                renderScheduleList();
            });
        }

        return card;
    }

    // 일정 추가 이벤트 바인딩
    elBtnAddSchedule.addEventListener('click', () => {
        if (!editedPlan) return;
        if (!editedPlan.schedule) editedPlan.schedule = [];

        const nextSchedId = editedPlan.schedule.length > 0
            ? Math.max(...editedPlan.schedule.map(s => s.id)) + 1 : 0;
        
        const newSched = {
            id: nextSchedId,
            name: "일정 " + (nextSchedId + 1),
            hour: 12,
            minute: 0
        };

        editedPlan.schedule.push(newSched);
        activeEditSchedId = nextSchedId;
        markDirty();
        renderScheduleList();
    });

    // ── 계획 실행 처리 ────────────────────────────────────────────────────────
    let execModal = null;

    elBtnExecutePlan.addEventListener('click', () => {
        if (!editedPlan) return;
        if (!execModal) {
            execModal = new bootstrap.Modal(document.getElementById('execute-modal'));
        }
        execModal.show();
    });

    document.getElementById('execute-modal-ok').addEventListener('click', () => {
        if (execModal) {
            execModal.hide();
        }
        executeCurrentPlan();
    });

    async function executeCurrentPlan() {
        if (!editedPlan) return;
        if (typeof ROBOT_ID === 'undefined' || !ROBOT_ID) {
            alert('연결된 로봇 ID가 없습니다.');
            return;
        }

        const payload = {
            sequence: editedPlan.sequence,
            waypoint: editedPlan.waypoint
        };

        try {
            const res = await fetch('/api/robot_send_waypoint', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    robot: ROBOT_ID,
                    waypoint: payload.waypoint,
                    sequence: payload.sequence
                })
            });
            const data = await res.json();
            if (res.ok) {
                alert('웨이포인트 전송 및 계획 실행 명령이 성공적으로 전송되었습니다.');
            } else {
                alert('실행 전송 실패: ' + (data.error || '알 수 없는 오류'));
            }
        } catch (e) {
            console.error('[Plan Execute]', e);
            alert('명령 전송 중 서버 연결 오류 발생');
        }
    }

    // ── 전역 노출 ──────────────────────────────────────────────────────────
    window._planLoadPlans      = loadPlans;
    window._planClearPlans     = plans => {}; // No-op to avoid breaking, clearPlans will be called below
    window._planClearPlans     = clearPlans;
    window._planRerenderMarkers = renderMarkers;
    _onZoomChange = updateMarkerScales;  // 줌 훅 연결
}


// ── 확인 모달 헬퍼 ──────────────────────────────────────────────────────────
function showConfirm(title, body, onOk) {
    const el = document.getElementById('confirm-modal');
    document.getElementById('confirm-modal-title').textContent = title;
    document.getElementById('confirm-modal-body').textContent  = body;
    // 이전 리스너 제거 후 새 버튼으로 교체
    const old   = document.getElementById('confirm-modal-ok');
    const fresh = old.cloneNode(true);
    old.replaceWith(fresh);
    fresh.addEventListener('click', () => {
        bootstrap.Modal.getInstance(el)?.hide();
        onOk();
    });
    new bootstrap.Modal(el).show();
}


// ══════════════════════════════════════════════════════════════════════════════
// 지도 편집 관리자 (Map Editor Manager)
// ══════════════════════════════════════════════════════════════════════════════
let mapMode = 'trinary';
let mapNegate = 0;
let mapOccupiedThresh = 0.65;
let mapFreeThresh = 0.196;
let currentPgmPixels = [];
let originalPgmPixels = [];
let editUndoStack = [];
let editRedoStack = [];
let editDrawMode = 'pencil'; // 'pencil', 'line', 'rect'
let editDrawColor = 0; // default: Black
let editBrushSize = 1;
let editFillInner = false;

// Drawing state
let editIsDrawing = false;
let editStartPos = null;
let editLastPos = null;
let editTempShape = null;

// PGM 픽셀 값 -> ROS OccupancyGrid 값
function pgmToRos(pgmVal, mode = 'trinary', negate = 0, occupied_thresh = 0.65, free_thresh = 0.196) {
    let occ;
    if (negate) {
        occ = pgmVal / 255.0;
    } else {
        occ = (255.0 - pgmVal) / 255.0;
    }

    if (mode === 'scale') {
        if (pgmVal === 205) return -1;
        return Math.round(occ * 100.0);
    } else if (mode === 'raw') {
        return pgmVal;
    } else {
        // trinary
        if (occ > occupied_thresh) return 100;
        else if (occ < free_thresh) return 0;
        else return -1;
    }
}

// 전체 PGM 픽셀 배열 -> ROS 1차원 grid 배열 변환 (Y축 반전 보정 포함)
function getRosArrayFromPgm(pgmPixels, width, height, mode, negate, occupiedThresh, freeThresh) {
    const rosArray = new Array(width * height);
    for (let r = 0; r < height; r++) {
        const rosY = height - 1 - r;
        for (let c = 0; c < width; c++) {
            const pgmVal = pgmPixels[r * width + c];
            rosArray[rosY * width + c] = pgmToRos(pgmVal, mode, negate, occupiedThresh, freeThresh);
        }
    }
    return rosArray;
}

function renderPgmPixelsToCanvas() {
    if (!mapWidth || !mapHeight || !currentPgmPixels.length) return;
    const rosArray = getRosArrayFromPgm(
        currentPgmPixels,
        mapWidth,
        mapHeight,
        mapMode,
        mapNegate,
        mapOccupiedThresh,
        mapFreeThresh
    );
    const url = drawOccupancyGrid(mapWidth, mapHeight, rosArray, mapMode);
    
    if (mapImageObject) {
        const imgEl = mapImageObject.getElement();
        if (imgEl) {
            imgEl.src = url;
            mapImageObject.dirty = true;
            canvas.requestRenderAll();
            
            imgEl.onload = () => {
                mapImageObject.dirty = true;
                canvas.requestRenderAll();
            };
        }
    }
}

// 브러시 크기(1~4)에 따른 단일 점 드로잉
function paintBrush(pixels, width, height, cx, cy, brushSize, color) {
    const start = -Math.floor((brushSize - 1) / 2);
    const end = start + brushSize;
    for (let dy = start; dy < end; dy++) {
        for (let dx = start; dx < end; dx++) {
            const px = cx + dx;
            const py = cy + dy;
            if (px >= 0 && px < width && py >= 0 && py < height) {
                pixels[py * width + px] = color;
            }
        }
    }
}

// Bresenham's line algorithm
function drawLinePixels(pixels, width, height, x0, y0, x1, y1, brushSize, color) {
    const dx = Math.abs(x1 - x0);
    const dy = Math.abs(y1 - y0);
    const sx = (x0 < x1) ? 1 : -1;
    const sy = (y0 < y1) ? 1 : -1;
    let err = dx - dy;

    let cx = x0;
    let cy = y0;

    while (true) {
        paintBrush(pixels, width, height, cx, cy, brushSize, color);
        if (cx === x1 && cy === y1) break;
        const e2 = 2 * err;
        if (e2 > -dy) {
            err -= dy;
            cx += sx;
        }
        if (e2 < dx) {
            err += dx;
            cy += sy;
        }
    }
}

// 직사각형/정사각형 드로잉
function drawRectPixels(pixels, width, height, x0, y0, x1, y1, brushSize, color, fill) {
    const minX = Math.min(x0, x1);
    const maxX = Math.max(x0, x1);
    const minY = Math.min(y0, y1);
    const maxY = Math.max(y0, y1);

    if (fill) {
        for (let y = minY; y <= maxY; y++) {
            for (let x = minX; x <= maxX; x++) {
                if (x >= 0 && x < width && y >= 0 && y < height) {
                    pixels[y * width + x] = color;
                }
            }
        }
    } else {
        drawLinePixels(pixels, width, height, minX, minY, maxX, minY, brushSize, color);
        drawLinePixels(pixels, width, height, minX, maxY, maxX, maxY, brushSize, color);
        drawLinePixels(pixels, width, height, minX, minY, minX, maxY, brushSize, color);
        drawLinePixels(pixels, width, height, maxX, minY, maxX, maxY, brushSize, color);
    }
}

// Callback: start editing
window.onMapEditModeStart = function() {
    const elMapSelect = document.getElementById('map-select');
    if (elMapSelect) {
        currentMapName = elMapSelect.value || null;
    }
    if (!currentMapName) return;
    isMapEditMode = true;

    // 1. 계획 마커 숨김
    if (typeof window._planClearPlans === 'function') {
        window._planClearPlans();
    }

    // 2. 백엔드에서 raw PGM pixels 조회
    fetch(`/api/map_pgm_pixels/${encodeURIComponent(currentMapName)}`)
        .then(res => {
            if (!res.ok) throw new Error('PGM 픽셀 데이터를 가져오지 못했습니다.');
            return res.json();
        })
        .then(data => {
            currentPgmPixels = data.pixels;
            originalPgmPixels = data.pixels.slice();
            editUndoStack = [];
            editRedoStack = [];
            
            // 3. UI 컨트롤 연동
            syncEditUIControls();
            
            // 커서 십자선으로 변경
            canvas.defaultCursor = 'crosshair';
            canvas.hoverCursor = 'crosshair';
            canvas.requestRenderAll();
        })
        .catch(err => {
            console.error('[Map Edit]', err);
            alert(err.message);
            if (typeof window.exitEditMode === 'function') {
                window.exitEditMode();
            }
        });
};

// Callback: end editing
window.onMapEditModeEnd = function() {
    isMapEditMode = false;
    currentPgmPixels = [];
    originalPgmPixels = [];
    editUndoStack = [];
    editRedoStack = [];
    
    // 임시 그리기 쉐이프 제거
    if (editTempShape) {
        canvas.remove(editTempShape);
        editTempShape = null;
    }
    
    // 원래 지도로 리로드하여 변경점 리셋
    if (currentMapName) {
        _loadMap(currentMapName);
    }
    
    // 계획 마커 복원
    if (typeof window._planRerenderMarkers === 'function') {
        window._planRerenderMarkers();
    }

    // 커서 기본값 복원
    canvas.defaultCursor = 'default';
    canvas.hoverCursor = 'move';
    canvas.requestRenderAll();
};

function syncEditUIControls() {
    const slider = document.getElementById('slider-brush-size');
    const brushVal = document.getElementById('brush-size-val');
    if (slider && brushVal) {
        slider.value = editBrushSize;
        brushVal.textContent = `${editBrushSize} px`;
    }

    const checkFill = document.getElementById('check-fill-inner');
    if (checkFill) {
        checkFill.checked = editFillInner;
    }

    // 색상 라디오 상태 동기화
    if (editDrawColor === 0) {
        const blackRadio = document.getElementById('btn-color-black');
        if (blackRadio) blackRadio.checked = true;
    } else {
        const whiteRadio = document.getElementById('btn-color-white');
        if (whiteRadio) whiteRadio.checked = true;
    }

    // 모양 라디오 상태 동기화
    const shapeRadio = document.getElementById(`btn-shape-${editDrawMode}`);
    if (shapeRadio) shapeRadio.checked = true;

    syncUndoRedoButtons();
    updateSaveButtonState();
}

function syncUndoRedoButtons() {
    const btnUndo = document.getElementById('btn-edit-undo');
    const btnRedo = document.getElementById('btn-edit-redo');
    if (btnUndo) btnUndo.disabled = (editUndoStack.length === 0);
    if (btnRedo) btnRedo.disabled = (editRedoStack.length === 0);
}

function hasMapChanges() {
    if (currentPgmPixels.length !== originalPgmPixels.length) return false;
    for (let i = 0; i < currentPgmPixels.length; i++) {
        if (currentPgmPixels[i] !== originalPgmPixels[i]) return true;
    }
    return false;
}

function updateSaveButtonState() {
    const btnSave = document.getElementById('btn-edit-save');
    if (btnSave) {
        btnSave.disabled = !hasMapChanges();
    }
}

function initMapEditorEvents() {
    // 드로잉 마우스 다운
    canvas.on('mouse:down', (opt) => {
        if (!isMapEditMode) return;
        const evt = opt.e;
        if (evt.button !== 0) return; // 좌클릭만 그리기 허용

        const pointer = canvas.getPointer(evt);
        const cx = Math.max(0, Math.min(mapWidth - 1, Math.floor(pointer.x)));
        const cy = Math.max(0, Math.min(mapHeight - 1, Math.floor(pointer.y)));

        editIsDrawing = true;
        editStartPos = { x: cx, y: cy };
        editLastPos = { x: cx, y: cy };

        // Undo 스택에 현재 상태 복사해 저장
        editUndoStack.push(currentPgmPixels.slice());
        editRedoStack = []; // 새 작업 시 redo stack은 초기화
        syncUndoRedoButtons();
        updateSaveButtonState();

        if (editDrawMode === 'pencil') {
            paintBrush(currentPgmPixels, mapWidth, mapHeight, cx, cy, editBrushSize, editDrawColor);
            renderPgmPixelsToCanvas();
        } else if (editDrawMode === 'line') {
            const colorStr = (editDrawColor === 0) ? '#212529' : '#fafafa';
            editTempShape = new fabric.Line([pointer.x, pointer.y, pointer.x, pointer.y], {
                stroke: colorStr,
                strokeWidth: editBrushSize,
                selectable: false,
                evented: false,
                strokeLineCap: 'square'
            });
            canvas.add(editTempShape);
        } else if (editDrawMode === 'rect') {
            const colorStr = (editDrawColor === 0) ? '#212529' : '#fafafa';
            editTempShape = new fabric.Rect({
                left: pointer.x,
                top: pointer.y,
                width: 0,
                height: 0,
                fill: editFillInner ? colorStr : 'transparent',
                stroke: colorStr,
                strokeWidth: editBrushSize,
                selectable: false,
                evented: false,
                strokeLineJoin: 'miter'
            });
            canvas.add(editTempShape);
        }
    });

    // 드로잉 마우스 무브 (실시간 피드백)
    canvas.on('mouse:move', (opt) => {
        if (!isMapEditMode || !editIsDrawing) return;
        const pointer = canvas.getPointer(opt.e);
        const cx = Math.max(0, Math.min(mapWidth - 1, Math.floor(pointer.x)));
        const cy = Math.max(0, Math.min(mapHeight - 1, Math.floor(pointer.y)));

        if (editDrawMode === 'pencil') {
            // 끊어짐 방지를 위해 이전 점과 현재 점을 Bresenham 선으로 연결
            drawLinePixels(currentPgmPixels, mapWidth, mapHeight, editLastPos.x, editLastPos.y, cx, cy, editBrushSize, editDrawColor);
            editLastPos = { x: cx, y: cy };
            renderPgmPixelsToCanvas();
        } else if (editDrawMode === 'line' && editTempShape) {
            editTempShape.set({ x2: pointer.x, y2: pointer.y });
            canvas.requestRenderAll();
        } else if (editDrawMode === 'rect' && editTempShape) {
            const left = Math.min(editStartPos.x, pointer.x);
            const top = Math.min(editStartPos.y, pointer.y);
            const width = Math.abs(editStartPos.x - pointer.x);
            const height = Math.abs(editStartPos.y - pointer.y);
            editTempShape.set({ left, top, width, height });
            canvas.requestRenderAll();
        }
    });

    // 드로잉 마우스 업 (래스터화)
    canvas.on('mouse:up', (opt) => {
        if (!isMapEditMode || !editIsDrawing) return;
        editIsDrawing = false;

        const pointer = canvas.getPointer(opt.e);
        const cx = Math.max(0, Math.min(mapWidth - 1, Math.floor(pointer.x)));
        const cy = Math.max(0, Math.min(mapHeight - 1, Math.floor(pointer.y)));

        if (editTempShape) {
            canvas.remove(editTempShape);
            editTempShape = null;
        }

        if (editDrawMode === 'line') {
            drawLinePixels(currentPgmPixels, mapWidth, mapHeight, editStartPos.x, editStartPos.y, cx, cy, editBrushSize, editDrawColor);
            renderPgmPixelsToCanvas();
        } else if (editDrawMode === 'rect') {
            drawRectPixels(currentPgmPixels, mapWidth, mapHeight, editStartPos.x, editStartPos.y, cx, cy, editBrushSize, editDrawColor, editFillInner);
            renderPgmPixelsToCanvas();
        }

        syncUndoRedoButtons();
        updateSaveButtonState();
    });

    // 1. 실행 관리
    document.getElementById('btn-edit-undo')?.addEventListener('click', () => {
        if (editUndoStack.length === 0) return;
        editRedoStack.push(currentPgmPixels.slice());
        currentPgmPixels = editUndoStack.pop();
        renderPgmPixelsToCanvas();
        syncUndoRedoButtons();
        updateSaveButtonState();
    });

    document.getElementById('btn-edit-redo')?.addEventListener('click', () => {
        if (editRedoStack.length === 0) return;
        editUndoStack.push(currentPgmPixels.slice());
        currentPgmPixels = editRedoStack.pop();
        renderPgmPixelsToCanvas();
        syncUndoRedoButtons();
        updateSaveButtonState();
    });

    // 2. 색상 선택
    document.getElementById('btn-color-black')?.addEventListener('change', () => {
        editDrawColor = 0;
    });

    document.getElementById('btn-color-white')?.addEventListener('change', () => {
        editDrawColor = 254;
    });

    // 3. 굵기 조정
    document.getElementById('slider-brush-size')?.addEventListener('input', (e) => {
        editBrushSize = parseInt(e.target.value) || 1;
        const brushVal = document.getElementById('brush-size-val');
        if (brushVal) brushVal.textContent = `${editBrushSize} px`;
    });

    // 4. 모양 선택
    document.getElementById('btn-shape-pencil')?.addEventListener('change', () => {
        editDrawMode = 'pencil';
    });

    document.getElementById('btn-shape-line')?.addEventListener('change', () => {
        editDrawMode = 'line';
    });

    document.getElementById('btn-shape-rect')?.addEventListener('change', () => {
        editDrawMode = 'rect';
    });

    // 5. 그리기 옵션
    document.getElementById('check-fill-inner')?.addEventListener('change', (e) => {
        editFillInner = e.target.checked;
    });

    // 6. 저장 메뉴
    document.getElementById('btn-edit-cancel')?.addEventListener('click', () => {
        if (hasMapChanges()) {
            if (confirm("변경사항을 저장하지 않고 편집을 취소하시겠습니까?")) {
                if (typeof window.exitEditMode === 'function') window.exitEditMode();
            }
        } else {
            if (typeof window.exitEditMode === 'function') window.exitEditMode();
        }
    });

    document.getElementById('btn-edit-save')?.addEventListener('click', () => {
        if (!hasMapChanges() || !currentMapName) return;

        const btnSave = document.getElementById('btn-edit-save');
        if (btnSave) btnSave.disabled = true;

        fetch(`/api/map_data/${encodeURIComponent(currentMapName)}`, {
            method: 'PUT',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                pixels: currentPgmPixels,
                width: mapWidth,
                height: mapHeight
            })
        })
        .then(res => {
            if (!res.ok) throw new Error('지도 데이터를 저장하지 못했습니다.');
            return res.json();
        })
        .then(data => {
            alert('지도가 성공적으로 저장되었습니다.');
            // 파일 갱신 후 캔버스 상에 지도 데이터를 다시 로딩
            _loadMap(currentMapName, () => {
                if (typeof window.exitEditMode === 'function') window.exitEditMode();
            });
        })
        .catch(err => {
            console.error('[Map Save]', err);
            alert(err.message);
            if (btnSave) btnSave.disabled = false;
        });
    });
}

// ── 지도 복제 ──────────────────────────────────────────────────────────
window.cloneMap = function() {
    if (!selectedMap) {
        alert('복제할 지도를 선택해 주세요.');
        return;
    }
    if (!confirm(`'${selectedMap}' 지도를 복제하시겠습니까?`)) return;

    fetch(`/api/map_clone/${encodeURIComponent(selectedMap)}`, {
        method: 'POST'
    })
    .then(res => {
        if (!res.ok) return res.json().then(data => { throw new Error(data.error || '복제 실패'); });
        return res.json();
    })
    .then(data => {
        alert('지도가 복제되었습니다.');
        // 복제된 새 지도를 자동 선택하기 위해 sessionStorage에 기록
        sessionStorage.setItem('selectedMap', data.new_map);
        window.location.reload();
    })
    .catch(err => {
        console.error('[Map Clone]', err);
        alert(err.message);
    });
};

// ── 지도 이름 변경 ──────────────────────────────────────────────────────
window.renameMap = function() {
    if (!selectedMap) {
        alert('이름을 변경할 지도를 선택해 주세요.');
        return;
    }

    const modalEl = document.getElementById('rename-modal');
    const inputEl = document.getElementById('rename-input');
    const btnOk = document.getElementById('rename-modal-ok');
    
    inputEl.value = selectedMap;
    const renameModal = new bootstrap.Modal(modalEl);

    // ok 버튼에 단일 클릭 리스너 연결
    const newBtnOk = btnOk.cloneNode(true);
    btnOk.replaceWith(newBtnOk);

    newBtnOk.addEventListener('click', () => {
        const newName = inputEl.value.trim();
        if (!newName) {
            alert('이름을 입력해 주세요.');
            return;
        }
        if (newName === selectedMap) {
            renameModal.hide();
            return;
        }

        // 프론트엔드 중복 검사
        const mapSelect = document.getElementById('map-select');
        const existingNames = Array.from(mapSelect.options).map(opt => opt.value);
        if (existingNames.includes(newName)) {
            alert('동일한 지도명이 이미 존재합니다. 변경이 불가능합니다.');
            return;
        }

        fetch('/api/map_rename', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ old_name: selectedMap, new_name: newName })
        })
        .then(res => {
            if (!res.ok) return res.json().then(data => { throw new Error(data.error || '이름 변경 실패'); });
            return res.json();
        })
        .then(data => {
            alert('지도 이름이 변경되었습니다.');
            renameModal.hide();
            sessionStorage.setItem('selectedMap', data.new_map);
            window.location.reload();
        })
        .catch(err => {
            console.error('[Map Rename]', err);
            alert(err.message);
        });
    });

    renameModal.show();
};

// ── 지도 삭제 ──────────────────────────────────────────────────────────
window.deleteMap = function() {
    if (!selectedMap) {
        alert('삭제할 지도를 선택해 주세요.');
        return;
    }

    showConfirm(
        '지도 삭제',
        `'${selectedMap}' 지도를 정말 삭제하시겠습니까? 관련된 모든 파일(.pgm, .yaml, _plan.json) 및 로봇의 지도 설정이 초기화됩니다.`,
        () => {
            fetch(`/api/map_delete/${encodeURIComponent(selectedMap)}`, {
                method: 'POST'
            })
            .then(res => {
                if (!res.ok) return res.json().then(data => { throw new Error(data.error || '삭제 실패'); });
                return res.json();
            })
            .then(data => {
                alert('지도가 삭제되었습니다.');
                // 삭제 완료 후 첫 페이지로 돌아가기 위해 sessionStorage 클리어
                sessionStorage.removeItem('selectedMap');
                window.location.reload();
            })
            .catch(err => {
                console.error('[Map Delete]', err);
                alert(err.message);
            });
        }
    );
};
