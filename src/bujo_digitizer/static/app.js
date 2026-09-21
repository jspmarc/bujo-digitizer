const fileInput = document.getElementById("bujo-page");
const button = document.getElementById("submit-btn");
const preview = document.getElementById("preview");
const page = document.getElementById("page");
const overlay = document.getElementById("overlay");
const result = document.getElementById("result");

fileInput.addEventListener("change", () => {
	const file = fileInput.files[0];
	if (!file) return;
	page.src = URL.createObjectURL(file);
	overlay.innerHTML = "";
	preview.classList.add("visible");
});

// HTMX already swapped the HTML fragment; just restore the button label
document.querySelector("form").addEventListener("htmx:beforeRequest", () => {
	button.textContent = "Digitizing...";
});
document.querySelector("form").addEventListener("htmx:afterRequest", () => {
	button.textContent = "Digitize";
});

// Draw OCR bounding boxes from the payload embedded in the swapped fragment
result.addEventListener("htmx:afterSwap", (event) => {
	const script = event.detail.elt.querySelector("script#ocr-html");
	if (!script) return;
	const doc = new DOMParser().parseFromString(script.textContent, "text/html");
	const boxes = [...doc.querySelectorAll("[data-bbox]")];
	overlay.innerHTML = "";
	const raw = boxes.flatMap((b) => b.dataset.bbox.trim().split(/\s+/).map(Number));
	const normalized = raw.every((v) => v <= 1000);
	for (const b of boxes) {
		const [x1, y1, x2, y2] = b.dataset.bbox.trim().split(/\s+/).map(Number);
		const dx = normalized ? 1000 : page.naturalWidth;
		const dy = normalized ? 1000 : page.naturalHeight;
		const div = document.createElement("div");
		div.className = "bbox";
		div.style.left = `${(x1 / dx) * 100}%`;
		div.style.top = `${(y1 / dy) * 100}%`;
		div.style.width = `${((x2 - x1) / dx) * 100}%`;
		div.style.height = `${((y2 - y1) / dy) * 100}%`;
		overlay.appendChild(div);
	}
});
