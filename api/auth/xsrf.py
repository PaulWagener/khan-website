import cookie_util
import base64
import os
import logging
from functools import wraps

XSRF_COOKIE_KEY = "fkey"
XSRF_HEADER_KEY = "HTTP_X_KA_FKEY"

def ensure_xsrf_cookie(func):
    """ This is a decorator for a method that ensures when the response to
    this request is sent, the user's browser has the appropriate XSRF cookie
    set.
    
    The XSRF cookie is required for making successful API calls from our site
    for calls that require oauth.
    """
    @wraps(func)
    def wrapper(self, *args, **kwargs):

        if not get_xsrf_cookie_value():

            xsrf_value = base64.urlsafe_b64encode(os.urandom(30))

            # Set an http-only cookie containing the XSRF value.
            # A matching header value will be required by validate_xsrf_cookie.
            self.set_cookie(XSRF_COOKIE_KEY, xsrf_value, httponly=True)
            cookie_util.set_request_cookie(XSRF_COOKIE_KEY, xsrf_value)

        return func(self, *args, **kwargs)

    return wrapper

def get_xsrf_cookie_value():
    return cookie_util.get_cookie_value(XSRF_COOKIE_KEY)

def validate_xsrf_value():
    header_value = os.environ.get(XSRF_HEADER_KEY)
    cookie_value = get_xsrf_cookie_value()
    if not header_value:
        logging.critical("Missing XSRF header")
        return False
    elif not cookie_value:
        logging.critical("Missing XSRF cookie")
        return False
    elif header_value != cookie_value:
        logging.critical("Mismatch between XSRF header and cookie")
        return False
    return True

def render_xsrf_js():
    return "<script>var fkey = '%s';</script>" % get_xsrf_cookie_value();

