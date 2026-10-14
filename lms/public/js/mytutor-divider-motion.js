// Native login and SPA share the same calm, random travel and colour mixing.
(function (root) {
	if (!root || root.lmsDividerMotion) return;
	root.lmsDividerMotion = {
		start(element, { random = Math.random } = {}) {
			const motion = root.matchMedia("(prefers-reduced-motion: reduce)");
			const frames = new Map();
			let timer;
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
				const from = animation.playbackRate;
				if (from === direction) return;
				const started = root.performance.now();
				const turn = (now) => {
					if (stopped || motion.matches || !element.isConnected)
						return;
					const progress = Math.min(1, (now - started) / 1800);
					const eased = progress * progress * (3 - 2 * progress);
					animation.updatePlaybackRate(
						from + (direction - from) * eased
					);
					if (progress < 1)
						frames.set(animation, root.requestAnimationFrame(turn));
					else frames.delete(animation);
				};
				frames.set(animation, root.requestAnimationFrame(turn));
			};
			const changeDirection = () => {
				if (stopped || !element.isConnected) return stop();
				if (motion.matches) return;
				const animations = element.getAnimations({ subtree: true });
				const moving = animations.find(
					(item) => item.animationName === "lms-ai-wave-wander"
				);
				if (moving) easeDirection(moving, random() < 0.5 ? -1 : 1);
				const third = element.querySelector(".lms-ai-stream-third");
				if (third) {
					const colours = [
						"#4dc5c7",
						"#67a5e0",
						"#a493d6",
						"#d58ea7",
						"#dfa783",
						"#8b91d0",
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
					third.style.setProperty(
						"--lms-third-gain",
						String(0.45 + random() * 0.45)
					);
					third.style.setProperty(
						"--lms-third-width",
						`${20 + random() * 5}px`
					);
					const travel = animations.find(
						(item) => item.animationName === "lms-ai-wave-third"
					);
					if (travel) easeDirection(travel, random() < 0.5 ? -1 : 1);
				}
				schedule();
			};
			const cancelWork = () => {
				root.clearTimeout(timer);
				for (const frame of frames.values())
					root.cancelAnimationFrame(frame);
				frames.clear();
			};
			const onMotionChange = () => {
				cancelWork();
				schedule();
			};
			const stop = () => {
				stopped = true;
				cancelWork();
				motion.removeEventListener("change", onMotionChange);
			};
			motion.addEventListener("change", onMotionChange);
			schedule();
			return stop;
		},
	};
})(typeof window === "undefined" ? null : window);
