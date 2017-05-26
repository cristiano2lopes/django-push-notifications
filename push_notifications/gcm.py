"""
Google Cloud Messaging
Previously known as C2DM
Documentation is available on the Android Developer website:
https://developer.android.com/google/gcm/index.html
"""

import json
import logging
from .models import GCMDevice

try:
	from urllib.request import Request, urlopen
	from urllib.parse import urlencode
except ImportError:
	# Python 2 support
	from urllib2 import Request, urlopen, HTTPError
	from urllib import urlencode

from django.core.exceptions import ImproperlyConfigured
from . import NotificationError
from .settings import PUSH_NOTIFICATIONS_SETTINGS as SETTINGS

logger = logging.getLogger(__name__)


class GCMError(NotificationError):
	pass


def _chunks(l, n):
	"""
	Yield successive chunks from list \a l with a minimum size \a n
	"""
	for i in range(0, len(l), n):
		yield l[i:i + n]


def _gcm_send(data, content_type):
	key = SETTINGS.get("GCM_API_KEY")
	if not key:
		raise ImproperlyConfigured('You need to set PUSH_NOTIFICATIONS_SETTINGS["GCM_API_KEY"] to send messages through GCM.')

	headers = {
		"Content-Type": content_type,
		"Authorization": "key=%s" % (key),
		"Content-Length": str(len(data)),
	}

	request = Request(SETTINGS["GCM_POST_URL"], data, headers)
	try:
		return urlopen(request).read()
	except HTTPError as e:
		logger.error(
			u"Gcm -> Error {} with data {} headers {}".format(
				unicode(e), unicode(data), unicode(headers)
			)
		)
		raise e


def _gcm_send_json(registration_ids, data, collapse_key=None, delay_while_idle=False, time_to_live=0):
	"""
	Sends a GCM notification to one or more registration_ids. The registration_ids
	needs to be a list.
	This will send the notification as json data.
	"""

	if not registration_ids:
                return

	values = {"registration_ids": registration_ids}

	if data is not None:
		values["data"] = data

	if collapse_key:
		values["collapse_key"] = collapse_key

	if delay_while_idle:
		values["delay_while_idle"] = delay_while_idle

	if time_to_live:
		values["time_to_live"] = time_to_live

	data = json.dumps(values, separators=(",", ":"), sort_keys=True).encode("utf-8")  # keys sorted for tests

	result = json.loads(_gcm_send(data, "application/json"))
	return _cm_handle_response(registration_ids, result)


def gcm_send_message(registration_id, data, collapse_key=None, delay_while_idle=False, time_to_live=0):
	"""
	Sends a GCM notification to a single registration_id.

	This will send the notification as form data if possible, otherwise it will
	fall back to json data.

	If sending multiple notifications, it is more efficient to use
	gcm_send_bulk_message() with a list of registration_ids
	"""

	args = data, collapse_key, delay_while_idle, time_to_live
	_gcm_send_json([registration_id], *args)

def gcm_send_bulk_message(registration_ids, data, collapse_key=None, delay_while_idle=False, time_to_live=0):
	"""
	Sends a GCM notification to one or more registration_ids. The registration_ids
	needs to be a list.
	This will send the notification as json data.
	"""

	args = data, collapse_key, delay_while_idle, time_to_live

	# GCM only allows up to 1000 reg ids per bulk message
	# https://developer.android.com/google/gcm/gcm.html#request
	max_recipients = SETTINGS.get("GCM_MAX_RECIPIENTS")
	if len(registration_ids) > max_recipients:
		ret = []
		for chunk in _chunks(registration_ids, max_recipients):
			ret.append(_gcm_send_json(chunk, *args))
		return ret

	return _gcm_send_json(registration_ids, *args)

def _cm_handle_response(registration_ids, response_data):
	response = response_data
	if response.get("failure") or response.get("canonical_ids"):
		ids_to_remove, old_new_ids = [], []
		throw_error = False
		for index, result in enumerate(response["results"]):
			error = result.get("error")
			if error:
				# https://firebase.google.com/docs/cloud-messaging/http-server-ref#error-codes
				# If error is NotRegistered or InvalidRegistration, then we will deactivate devices
				# because this registration ID is no more valid and can't be used to send messages,
				# otherwise raise error
				if error in ("NotRegistered", "InvalidRegistration"):
					ids_to_remove.append(registration_ids[index])
				else:
					throw_error = True

			# If registration_id is set, replace the original ID with the new value (canonical ID)
			# in your server database. Note that the original ID is not part of the result, you need
			# to obtain it from the list of registration_ids in the request (using the same index).
			new_id = result.get("registration_id")
			if new_id:
				old_new_ids.append((registration_ids[index], new_id))

		if ids_to_remove:
			removed = GCMDevice.objects.filter(
				registration_id__in=ids_to_remove
			)
			removed.update(active=0)

		for old_id, new_id in old_new_ids:
			_cm_handle_canonical_id(new_id, old_id)

		if throw_error:
			raise GCMError(response)
	return response

def _cm_handle_canonical_id(canonical_id, current_id):
	"""
	Handle situation when FCM server response contains canonical ID
	"""
	devices = GCMDevice.objects
	if devices.filter(registration_id=canonical_id, active=True).exists():
		devices.filter(registration_id=current_id).update(active=False)
	else:
		devices.filter(registration_id=current_id).update(registration_id=canonical_id)

