import { defineStore } from 'pinia'
import { createResource } from 'frappe-ui'
import { redirectToLogin } from '@/utils/loginReturn'

export const usersStore = defineStore('lms-users', () => {
	let userResource = createResource({
		url: 'lms.lms.api.get_user_info',
		onError(error) {
			if (error && error.exc_type === 'AuthenticationError') {
				redirectToLogin()
			}
		},
	})

	const allUsers = createResource({
		url: 'lms.lms.api.get_all_users',
		cache: ['allUsers'],
	})

	return {
		userResource,
		allUsers,
	}
})
