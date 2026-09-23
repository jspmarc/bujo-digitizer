// Position OCR bounding boxes inside `container` relative to `image`.
// Source boxes are read from `boxesRoot` (defaults to `container`) and replaced
// by absolutely positioned elements. Bounding boxes are expected to use the
// 0-1000 normalized space, falling back to image pixel coordinates.
function renderBoundingBoxes(container, image, boxesRoot = container) {
	const boxes = [...boxesRoot.querySelectorAll("[data-bbox]")];
	container.innerHTML = "";
	if (boxes.length === 0) return;

	const raw = boxes.flatMap((b) => b.dataset.bbox.trim().split(/\s+/).map(Number));
	const normalized = raw.every((v) => v <= 1000);
	const dx = normalized ? 1000 : image.naturalWidth;
	const dy = normalized ? 1000 : image.naturalHeight;
	if (dx === 0 || dy === 0) return;

	for (const b of boxes) {
		const [x1, y1, x2, y2] = b.dataset.bbox.trim().split(/\s+/).map(Number);
		const div = document.createElement("div");
		div.className = "bbox";
		div.style.left = `${(x1 / dx) * 100}%`;
		div.style.top = `${(y1 / dy) * 100}%`;
		div.style.width = `${((x2 - x1) / dx) * 100}%`;
		div.style.height = `${((y2 - y1) / dy) * 100}%`;

		const label = document.createElement("span");
		label.className = "bbox-label";
		label.textContent = b.textContent;

		div.appendChild(label);
		container.appendChild(div);
	}
}

window.renderBoundingBoxes = renderBoundingBoxes;
