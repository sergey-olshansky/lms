// Native login and SPA share the same calm, random travel and colour mixing.
(function (root) {
	if (!root || root.lmsDividerMotion) return;
	root.lmsDividerMotion = {
		start(element, { random = Math.random, initialize = true } = {}) {
			if (!element) return () => {};
			let previewSpeed = 1;
			let speedFrame,
				brightnessTimer,
				fadeTimer,
				restoreTimer,
				haloResumeTimer;
			let effectActive = false;
			const motion = root.matchMedia("(prefers-reduced-motion: reduce)");
			const frames = new Map();
			let timer;
			let haloTimer;
			let stopped = false;
			const schedule = () => {
				if (!stopped && !motion.matches)
					timer = root.setTimeout(
						changeDirection,
						10000 + random() * 20000
					);
			};
			const easeDirection = (animation, direction) => {
				root.cancelAnimationFrame(frames.get(animation));
				const duration = Number(animation.effect.getTiming().duration);
				// Whole loops preserve phase and keep reverse travel away from
				// time zero, where an otherwise infinite animation would stop.
				if (direction < 0 && animation.currentTime < duration)
					animation.currentTime += duration * 1024;
				const from = animation.playbackRate / previewSpeed;
				if (from === direction) return;
				const started = root.performance.now();
				const turn = (now) => {
					if (stopped || motion.matches || !element.isConnected)
						return;
					const progress = Math.min(1, (now - started) / 1800);
					const eased = progress * progress * (3 - 2 * progress);
					animation.updatePlaybackRate(
						(from + (direction - from) * eased) * previewSpeed
					);
					if (progress < 1)
						frames.set(animation, root.requestAnimationFrame(turn));
					else frames.delete(animation);
				};
				frames.set(animation, root.requestAnimationFrame(turn));
			};
			const randomizeThird = () => {
				const third = element.querySelector(".lms-ai-stream-third");
				if (!third) return;
				const colours = [
					"#4dc5c7",
					"#67a5e0",
					"#a493d6",
					"#d58ea7",
					"#dfa783",
					"#8b91d0",
					"#88c6b4",
					"#b8a1ce",
				];
				third.style.setProperty(
					"--lms-third-colour",
					colours[Math.floor(random() * colours.length)]
				);
				third.style.setProperty(
					"--lms-third-center",
					`${20 + random() * 60}%`
				);
				third.style.setProperty(
					"--lms-third-span",
					`${22 + random() * 20}%`
				);
				const spread = random();
				third.style.setProperty(
					"--lms-third-gain",
					String(0.65 + spread * 0.25)
				);
				third.style.setProperty(
					"--lms-third-width",
					`${20 + spread * 20}px`
				);
				return third;
			};
			const seedPhases = () => {
				if (motion.matches) return;
				// Both presence cycles get the same phase; their half-period CSS
				// offset remains intact, so random starts never cause a blackout.
				const presence = random() * 41000;
				for (const animation of element.getAnimations({
					subtree: true,
				})) {
					if (!animation.animationName) continue;
					const duration = Number(
						animation.effect.getTiming().duration
					);
					if (!Number.isFinite(duration) || duration <= 0) continue;
					animation.currentTime =
						animation.animationName === "lms-ai-presence"
							? presence
							: random() * duration;
					if (
						["lms-ai-wave-wander", "lms-ai-wave-third"].includes(
							animation.animationName
						)
					) {
						const direction = random() < 0.5 ? -1 : 1;
						if (direction < 0)
							animation.currentTime += duration * 1024;
						animation.updatePlaybackRate(direction);
					}
				}
				const third = element.querySelector(".lms-ai-stream-third");
				if (third) {
					third.style.transition = "none";
					randomizeThird();
					void third.offsetWidth;
					third.style.removeProperty("transition");
				}
			};
			const changeDirection = () => {
				if (stopped || !element.isConnected) return stop();
				if (motion.matches) return;
				if (effectActive) {
					schedule();
					return;
				}
				const animations = element.getAnimations({ subtree: true });
				const moving = animations.find(
					(item) => item.animationName === "lms-ai-wave-wander"
				);
				if (moving) easeDirection(moving, random() < 0.5 ? -1 : 1);
				const third = randomizeThird();
				if (third) {
					const travel = animations.find(
						(item) => item.animationName === "lms-ai-wave-third"
					);
					if (travel) easeDirection(travel, random() < 0.5 ? -1 : 1);
				}
				schedule();
			};
			const sampleHalo = () => {
				if (
					stopped ||
					motion.matches ||
					root.document.hidden ||
					!element.isConnected
				)
					return;
				const halo = element.querySelector(".lms-ai-halo");
				const third = element.querySelector(".lms-ai-stream-third");
				const height = element.clientHeight;
				if (!halo || !third || !height) return;
				const styles = [
					root.getComputedStyle(element, "::before"),
					root.getComputedStyle(element, "::after"),
					root.getComputedStyle(third),
				];
				const streams = styles.map((style, index) => {
					const transform = new root.DOMMatrixReadOnly(
						style.transform === "none" ? undefined : style.transform
					);
					const y = (((0.5 + transform.m42 / height) % 1) + 1) % 1;
					return {
						y,
						opacity: Number(style.opacity),
						colour: style
							.getPropertyValue(
								index === 2
									? "--lms-third-colour"
									: "--lms-blue-colour"
							)
							.trim(),
					};
				});
				let strongest = 0;
				for (let a = 0; a < streams.length; a++) {
					for (let b = a + 1; b < streams.length; b++) {
						const first = streams[a],
							second = streams[b];
						const proximity = Math.max(
							0,
							1 - Math.abs(first.y - second.y) / 0.18
						);
						const strength = Math.min(
							1,
							proximity *
								Math.min(first.opacity, second.opacity) *
								2.7
						);
						if (strength > strongest) {
							strongest = strength;
							halo.style.setProperty(
								"--lms-halo-y",
								`${(first.y + second.y) * 50}%`
							);
							halo.style.setProperty(
								"--lms-halo-colour",
								`color-mix(in srgb, ${first.colour}, ${second.colour})`
							);
							halo.style.setProperty(
								"--lms-halo-colour-two",
								first.colour
							);
							halo.style.setProperty(
								"--lms-halo-colour-three",
								second.colour
							);
						}
					}
				}
				halo.style.setProperty(
					"--lms-halo-strength",
					String(strongest)
				);
			};
			const startHalo = () => {
				if (
					!motion.matches &&
					typeof root.DOMMatrixReadOnly === "function"
				) {
					sampleHalo();
					haloTimer = root.setInterval(sampleHalo, 240);
				}
			};
			const edge = element;
			const rampSpeed = (target, duration) => {
				cancelAnimationFrame(speedFrame);
				const from = previewSpeed;
				const start = performance.now();
				const tick = (now) => {
					const progress = Math.min(1, (now - start) / duration);
					const eased = progress * progress * (3 - 2 * progress);
					const next = from + (target - from) * eased;
					for (const animation of edge.getAnimations({
						subtree: true,
					})) {
						if (
							[
								"lms-ai-wave",
								"lms-ai-wave-wander",
								"lms-ai-wave-third",
							].includes(animation.animationName)
						) {
							animation.updatePlaybackRate(
								(animation.playbackRate * next) / previewSpeed
							);
						}
					}
					previewSpeed = next;
					if (progress < 1) speedFrame = requestAnimationFrame(tick);
				};
				speedFrame = requestAnimationFrame(tick);
			};
			const showResult = (passed) => {
				if (
					stopped ||
					motion.matches ||
					!element.isConnected ||
					!element.clientHeight ||
					typeof root.DOMMatrixReadOnly !== "function"
				)
					return;
				effectActive = true;
				// Finish any ambient reversal before temporarily accelerating the streams.
				for (const frame of frames.values())
					root.cancelAnimationFrame(frame);
				frames.clear();
				const colours = passed
					? ["#36eaa2", "#17ce83", "#43ddaf", "#21dc94"]
					: ["#ff6558", "#f33258", "#e33b70", "#fa4656"];
				["teal", "blue", "lavender", "third"].forEach((name, i) => {
					edge.style.setProperty("--lms-result-" + name, colours[i]);
				});
				clearTimeout(brightnessTimer);
				clearTimeout(fadeTimer);
				clearTimeout(restoreTimer);
				clearTimeout(haloResumeTimer);
				edge.style.removeProperty("--lms-sunset");
				// Move the visible copy of each wave directly to the centre.
				const third = edge.querySelector(".lms-ai-stream-third");
				const styles = [
					getComputedStyle(edge, "::before"),
					getComputedStyle(edge, "::after"),
					getComputedStyle(third),
				];
				const height = edge.clientHeight;
				const offsets = styles.map((style) => {
					const y = new DOMMatrixReadOnly(
						style.transform === "none" ? undefined : style.transform
					).m42;
					return (
						((((y + height / 2) % height) + height) % height) -
						height / 2
					);
				});
				edge.style.transition = "none";
				["first", "second", "third"].forEach((name, i) =>
					edge.style.setProperty(
						"--lms-meet-" + name,
						offsets[i] + "px"
					)
				);
				edge.classList.add("success-gather", "success-active");
				void edge.offsetWidth;
				edge.style.transition =
					"--lms-flash-intensity 1s ease-in-out, --lms-success-warmth 1s ease-in-out, --lms-success-converge 1s ease-in-out, --lms-meet-first 1s ease-in-out, --lms-meet-second 1s ease-in-out, --lms-meet-third 1s ease-in-out, opacity .25s ease-in-out";
				edge.style.opacity = "1";
				edge.style.setProperty("--lms-flash-intensity", "5");
				edge.style.setProperty("--lms-success-warmth", "1");
				edge.style.setProperty("--lms-success-converge", "1");
				["first", "second", "third"].forEach((name) =>
					edge.style.setProperty("--lms-meet-" + name, "0px")
				);
				rampSpeed(5, 1000);
				brightnessTimer = setTimeout(() => {
					// Hide the meeting before restoring the underlying, freely moving streams.
					edge.style.transition =
						"opacity 2.4s cubic-bezier(.4, 0, .65, 1), --lms-sunset 2.4s ease-in-out";
					edge.style.setProperty("--lms-sunset", "1");
					edge.style.opacity = "0";
					restoreTimer = setTimeout(() => {
						cancelAnimationFrame(speedFrame);
						for (const animation of edge.getAnimations({
							subtree: true,
						})) {
							if (
								[
									"lms-ai-wave",
									"lms-ai-wave-wander",
									"lms-ai-wave-third",
								].includes(animation.animationName)
							) {
								animation.updatePlaybackRate(
									animation.playbackRate / previewSpeed
								);
							}
						}
						previewSpeed = 1;
						edge.style.transition = "none";
						edge.style.removeProperty("--lms-sunset");
						edge.classList.remove("success-gather");
						["first", "second", "third"].forEach((name) =>
							edge.style.removeProperty("--lms-meet-" + name)
						);
						edge.style.removeProperty("--lms-flash-intensity");
						edge.style.removeProperty("--lms-success-warmth");
						edge.style.removeProperty("--lms-success-converge");
						void edge.offsetWidth;
						edge.style.transition = "opacity 1.8s ease-in-out";
						edge.style.opacity = "1";
						fadeTimer = setTimeout(() => {
							edge.style.removeProperty("opacity");
							edge.style.removeProperty("transition");
							effectActive = false;
							haloResumeTimer = setTimeout(
								() => edge.classList.remove("success-active"),
								10000
							);
						}, 1800);
					}, 2400);
				}, 2000);
			};

			const cancelResult = () => {
				[
					brightnessTimer,
					fadeTimer,
					restoreTimer,
					haloResumeTimer,
				].forEach((id) => root.clearTimeout(id));
				root.cancelAnimationFrame(speedFrame);
				for (const animation of element.getAnimations({
					subtree: true,
				})) {
					if (
						[
							"lms-ai-wave",
							"lms-ai-wave-wander",
							"lms-ai-wave-third",
						].includes(animation.animationName)
					) {
						animation.updatePlaybackRate(
							animation.playbackRate / previewSpeed
						);
					}
				}
				previewSpeed = 1;
				effectActive = false;
				element.classList.remove("success-gather", "success-active");
				[
					"opacity",
					"transition",
					"--lms-sunset",
					"--lms-flash-intensity",
					"--lms-success-warmth",
					"--lms-success-converge",
					"--lms-meet-first",
					"--lms-meet-second",
					"--lms-meet-third",
					"--lms-result-teal",
					"--lms-result-blue",
					"--lms-result-lavender",
					"--lms-result-third",
				].forEach((name) => element.style.removeProperty(name));
			};
			const onQuizResult = (event) => {
				if (typeof event.detail?.passed === "boolean")
					showResult(event.detail.passed);
			};

			const cancelWork = () => {
				root.clearTimeout(timer);
				root.clearInterval(haloTimer);
				for (const frame of frames.values())
					root.cancelAnimationFrame(frame);
				frames.clear();
			};
			const onMotionChange = () => {
				cancelResult();
				cancelWork();
				schedule();
				startHalo();
			};
			const stop = () => {
				stopped = true;
				cancelResult();
				root.removeEventListener("lms:quiz-result", onQuizResult);
				cancelWork();
				motion.removeEventListener("change", onMotionChange);
			};
			root.addEventListener("lms:quiz-result", onQuizResult);
			motion.addEventListener("change", onMotionChange);
			if (initialize) seedPhases();
			schedule();
			startHalo();
			return stop;
		},
	};
})(typeof window === "undefined" ? null : window);
