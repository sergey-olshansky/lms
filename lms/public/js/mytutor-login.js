// Preserve Frappe's login form, handlers, fields and hash states. Only provide
// accessible presentation text for the CSS login composition.
const mountLoginPresentation = () => {
	if (document.body.dataset.path !== 'login') return
	const heading = document.querySelector('#page-login .for-login .page-card-head h4')
	if (heading) heading.textContent = 'С возвращением'

	const content = document.querySelector('#page-login .page_content')
	if (!content || content.querySelector('.lms-login-placeholder')) return
	const aside = document.createElement('aside')
	aside.className = 'lms-login-placeholder'
	aside.setAttribute('aria-label', 'Информация о курсе')
	const text = document.createElement('p')
	text.textContent = 'Здесь будет информация о курсе'
	aside.append(text)
	const decoration = document.createElement('div')
	decoration.className = 'lms-login-placeholder-lines'
	decoration.setAttribute('aria-hidden', 'true')
	for (const width of ['100%', '74%', '43%']) {
		const line = document.createElement('span')
		line.style.width = width
		decoration.append(line)
	}
	aside.append(decoration)
	content.prepend(aside)
}

if (document.readyState === 'loading') {
	document.addEventListener('DOMContentLoaded', mountLoginPresentation, { once: true })
} else {
	mountLoginPresentation()
}
