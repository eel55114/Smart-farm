/**
 * 로봇 맵 시각화 및 캔버스 제어를 위한 공통 유틸리티 모듈
 */

/**
 * ROS OccupancyGrid 1차원 데이터 배열을 HTML Canvas 픽셀 데이터로 변환하여 Data URL로 반환합니다.
 * ROS 좌표(좌하단 시작)와 HTML Canvas 좌표(좌상단 시작) 간의 Y축 반전을 보정합니다.
 * @param {number} width - 지도의 가로 픽셀 크기
 * @param {number} height - 지도의 세로 픽셀 크기
 * @param {Array<number>} array - -1~100 범위의 격자 확률 배열
 * @returns {string} Base64 이미지 Data URL
 */
function drawOccupancyGrid(width, height, array) {
    const offCanvas = document.createElement('canvas');
    offCanvas.width = width;
    offCanvas.height = height;
    const ctx = offCanvas.getContext('2d');
    const imgData = ctx.createImageData(width, height);
    
    for (let y = 0; y < height; y++) {
        const rosY = height - 1 - y;
        for (let x = 0; x < width; x++) {
            const rosIdx = rosY * width + x;
            const canvasIdx = (y * width + x) * 4;
            const val = array[rosIdx];
            
            let r = 0, g = 0, b = 0, a = 0;
            if (val === -1) {
                r = 0; g = 0; b = 0; a = 0; // 미탐색 영역 투명화
            } else if (val === 0) {
                r = 250; g = 250; b = 250; a = 255; // 빈 공간
            } else if (val === 100) {
                r = 33; g = 37; b = 41; a = 255; // 장애물
            } else {
                const gray = Math.round(240 - (val * 2.07));
                r = gray; g = gray; b = gray; a = 255;
            }
            imgData.data[canvasIdx] = r;
            imgData.data[canvasIdx + 1] = g;
            imgData.data[canvasIdx + 2] = b;
            imgData.data[canvasIdx + 3] = a;
        }
    }
    ctx.putImageData(imgData, 0, 0);
    return offCanvas.toDataURL();
}

/**
 * 줌인/줌아웃 및 패닝 조작 시 맵이 캔버스 영역 밖으로 이탈하여 여백이 생기는 현상을 제한하고
 * 최소 줌 상태에서는 화면 중앙에 오도록 뷰포트를 교정합니다.
 * @param {fabric.Canvas} canvas - Fabric.js 캔버스 인스턴스
 * @param {fabric.Image} mapImageObject - 캔버스 내의 지도 이미지 객체
 * @param {number} mapWidth - 지도 원본 가로 픽셀 크기
 * @param {number} mapHeight - 지도 원본 세로 픽셀 크기
 */
function constrainViewport(canvas, mapImageObject, mapWidth, mapHeight) {
    if (!canvas || !mapImageObject) return;
    
    const zoom = canvas.getZoom();
    const vpt = canvas.viewportTransform;
    
    const scaledWidth = mapWidth * zoom;
    if (scaledWidth <= canvas.width) {
        vpt[4] = (canvas.width - scaledWidth) / 2;
    } else {
        if (vpt[4] > 0) {
            vpt[4] = 0;
        } else if (vpt[4] + scaledWidth < canvas.width) {
            vpt[4] = canvas.width - scaledWidth;
        }
    }
    
    const scaledHeight = mapHeight * zoom;
    if (scaledHeight <= canvas.height) {
        vpt[5] = (canvas.height - scaledHeight) / 2;
    } else {
        if (vpt[5] > 0) {
            vpt[5] = 0;
        } else if (vpt[5] + scaledHeight < canvas.height) {
            vpt[5] = canvas.height - scaledHeight;
        }
    }
    
    canvas.setViewportTransform(vpt);
}

/**
 * 현재 줌 배율과 지도 해상도를 계산하여 화면 하단에 동적 스케일바 축척을 갱신합니다.
 * @param {fabric.Canvas} canvas - Fabric.js 캔버스 인스턴스
 * @param {fabric.Image} mapImageObject - 캔버스 내의 지도 이미지 객체
 * @param {number} mapResolution - 지도 해상도 (m/pixel)
 * @param {string} scaleBarId - 스케일바 전체 오버레이 엘리먼트 ID
 * @param {string} labelId - 거리 정보 텍스트 라벨 엘리먼트 ID
 * @param {string} lineId - 축척선 라인 엘리먼트 ID
 */
function updateScaleBar(canvas, mapImageObject, mapResolution, scaleBarId = 'map-scale-bar', labelId = 'scale-label', lineId = 'scale-line') {
    const scaleBar = document.getElementById(scaleBarId);
    if (!scaleBar || !canvas || !mapImageObject) return;

    const zoom = canvas.getZoom();
    
    // 표시 후보 축척 단위들 (10cm, 50cm, 1m, 5m)
    const candidates = [
        { value: 5.0, label: '5m' },
        { value: 1.0, label: '1m' },
        { value: 0.5, label: '50cm' },
        { value: 0.1, label: '10cm' }
    ];
    
    let selected = null;
    let pixelWidth = 0;
    const maxBarWidth = 120; // 스케일바의 최대 너비
    
    for (const cand of candidates) {
        const w = (cand.value * zoom) / mapResolution;
        if (w <= maxBarWidth) {
            selected = cand;
            pixelWidth = w;
            break;
        }
    }
    
    if (!selected) {
        scaleBar.classList.add('d-none');
    } else {
        scaleBar.classList.remove('d-none');
        const labelElem = document.getElementById(labelId);
        const lineElem = document.getElementById(lineId);
        if (labelElem) labelElem.innerText = selected.label;
        if (lineElem) lineElem.style.width = pixelWidth + 'px';
    }
}
