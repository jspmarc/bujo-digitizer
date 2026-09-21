const fileInput = document.getElementById("bujo-page");
// const urlInput = document.getElementById("image-url");
// const button = document.getElementById("submit-btn");

// File -> base64 data URL (OpenAI accepts data URLs as image_url)
/**
fileInput.addEventListener("change", () => {
	const file = fileInput.files[0];
	if (!file) { urlInput.value = ""; button.disabled = true; return; }
	const reader = new FileReader();
	reader.onload = () => { urlInput.value = reader.result; button.disabled = false; };
	reader.readAsDataURL(file);
});
**/

// HTMX already swapped the HTML fragment; just restore the button label
document.querySelector("form").addEventListener("htmx:beforeRequest", () => {
	button.textContent = "Digitizing...";
});
document.querySelector("form").addEventListener("htmx:afterRequest", () => {
	button.textContent = "Digitize";
});
