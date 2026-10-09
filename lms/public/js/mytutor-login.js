// Preserve Frappe's login form, handlers, fields and hash states. Only provide
// accessible presentation text for the CSS login composition.
// Keep the SVG as the native handler target; add real keyboard/touch semantics.
const enhancePasswordToggle = () => {
	const glyph = document.querySelector(
		"#page-login .password-field svg.toggle-password"
	);
	if (!glyph || glyph.closest("button")) return;
	const input = document.querySelector("#login_password");
	const button = document.createElement("button");
	button.type = "button";
	button.className = "lms-password-toggle";
	button.setAttribute("aria-controls", "login_password");
	const sync = () => {
		const visible = input.type === "text";
		button.setAttribute(
			"aria-label",
			__(visible ? "Hide password" : "Show password")
		);
		button.setAttribute("aria-pressed", String(visible));
	};
	glyph.setAttribute("aria-hidden", "true");
	glyph.parentNode.insertBefore(button, glyph);
	button.append(glyph);
	button.addEventListener("click", (event) => {
		if (!glyph.contains(event.target))
			glyph.dispatchEvent(new MouseEvent("click", { bubbles: true }));
		sync();
	});
	new MutationObserver(sync).observe(input, {
		attributes: true,
		attributeFilter: ["type"],
	});
	sync();
};

const mountLoginPresentation = () => {
	if (document.body.dataset.path !== "login") return;
	enhancePasswordToggle();
	const heading = document.querySelector(
		"#page-login .for-login .page-card-head h4"
	);
	if (heading) heading.textContent = "С возвращением";

	const content = document.querySelector("#page-login .page_content");
	if (!content || content.querySelector(".lms-login-placeholder")) return;
	const aside = document.createElement("aside");
	aside.className = "lms-login-placeholder";
	aside.setAttribute("aria-label", "Информация о курсе");
	const text = document.createElement("p");
	text.textContent = "Здесь будет информация о курсе";
	aside.append(text);
	const decoration = document.createElement("div");
	decoration.className = "lms-login-placeholder-lines";
	decoration.setAttribute("aria-hidden", "true");
	for (const width of ["100%", "74%", "43%"]) {
		const line = document.createElement("span");
		line.style.width = width;
		decoration.append(line);
	}
	aside.append(decoration);
	content.prepend(aside);
	const edge = document.createElement("span");
	edge.className = "lms-ai-divider";
	edge.setAttribute("aria-hidden", "true");
	content.append(edge);
};

if (document.readyState === "loading") {
	document.addEventListener("DOMContentLoaded", mountLoginPresentation, {
		once: true,
	});
} else {
	mountLoginPresentation();
}
