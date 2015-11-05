from django.core.management.base import BaseCommand


class Command(BaseCommand):
	can_import_settings = True
	args = '<app_name app_name ...>'
	help = 'Deactivate APNS devices that are not receiving notifications'

	def handle(self, *args, **options):
		from push_notifications.models import APNSDevice, get_expired_tokens
		for app in args:
			expired = get_expired_tokens(app_name=app)
			devices = APNSDevice.objects.filter(registration_id__in=expired)
			for d in devices:
				self.stdout.write('deactivating [%s]' % d.registration_id)
				d.active = False
				d.save()
			self.stdout.write(u'deactivated {} devices for app {}'.format(len(devices), app))
