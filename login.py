from api import jsonify
from google.appengine.api import mail

from app import App
from auth import age_util
from counters import user_counter
from google.appengine.api import users
from models import UserData
from notifications import UserNotifier
from phantom_users.phantom_util import get_phantom_user_id_from_cookies

import auth.cookies
import auth.passwords
from auth.tokens import AuthToken, EmailVerificationToken
import cookie_util
import datetime
import logging
import models
import os
import re
import request_handler
import uid
import user_util
import util
from api.auth.auth_models import OAuthMap
from api.auth import auth_util

class Login(request_handler.RequestHandler):
    @user_util.open_access
    def get(self):
        self.render_login()

    def render_login(self, identifier=None, errors=None):
        """ Renders the login page.

        errors - a dictionary of possible errors from a previous login that
                 can be highlighted in the UI of the login page
        """
        cont = self.request_continue_url()
        direct = self.request_bool('direct', default=False)

        template_values = {
                           'continue': cont,
                           'direct': direct,
                           'identifier': identifier or "",
                           'errors': errors or {},
                           'google_url': users.create_login_url(cont),
                           }

        self.render_jinja2_template('login.html', template_values)

    @user_util.open_access
    def post(self):
        """ Handles a POST from the login page.

        This happens when the user attempts to login with an identifier (email
        or username) and password.

        """

        cont = self.request_continue_url()

        # Authenticate via username or email + password
        identifier = self.request_string('identifier')
        password = self.request_string('password')
        if not identifier or not password:
            errors = {}
            if not identifier: errors['noemail'] = True
            if not password: errors['nopassword'] = True
            self.render_json({'errors': errors})
            return

        user_data = UserData.get_from_username_or_email(identifier.strip())
        if not user_data or not user_data.validate_password(password):
            errors = {}
            errors['badlogin'] = True
            # TODO(benkomalo): IP-based throttling of failed logins?
            self.render_json({'errors': errors})
            return

        # Successful login
        Login.return_login_json(self, user_data, cont)

    @staticmethod
    def return_login_json(handler, user_data, cont="/"):
        """ Handles a successful login for a user by redirecting them
        to the PostLogin URL with the auth token, which will ultimately set
        the auth cookie for them.

        This level of indirection is needed since the Login/Register handlers
        must accept requests with password strings over https, but the rest
        of the site is not (yet) using https, and therefore must use a
        non-https cookie.

        """

        auth_token = AuthToken.for_user(user_data)
        handler.response.write(jsonify.jsonify({
                    'auth': auth_token.value,
                    'continue': cont
                }, camel_cased=True))

class MobileOAuthLogin(request_handler.RequestHandler):
    @user_util.open_access
    def get(self):
        self.render_login_page()

    def render_login_page(self, error=None):
        self.render_jinja2_template('login_mobile_oauth.html', {
            "oauth_map_id": self.request_string("oauth_map_id", default=""),
            "anointed": self.request_bool("an", default=False),
            "view": self.request_string("view", default=""),
            "error": error,
        })

    @user_util.manual_access_checking
    def post(self):
        """ POST submissions are for username/password based logins to
        acquire an OAuth access token.
        
        """

        identifier = self.request_string('identifier')
        password = self.request_string('password')
        if not identifier or not password:
            self.render_login_page("Please enter your username and password")
            return

        user_data = UserData.get_from_username_or_email(identifier.strip())
        if not user_data or not user_data.validate_password(password):
            # TODO(benkomalo): IP-based throttling of failed logins?
            self.render_login_page("Username and password doesn't match")
            return
        
        # Successful login - convert to an OAuth access_token
        oauth_map_id = self.request_string("oauth_map_id", default="")
        oauth_map = OAuthMap.get_by_id_safe(oauth_map_id)
        if not oauth_map:
            self.render_login_page("Unable to find OAuthMap by id.")
            return

        # Mint the token and persist to the oauth_map
        oauth_map.khan_auth_token = AuthToken.for_user(user_data).value
        oauth_map.put()

        # Need to redirect back to the http authorize endpoint
        return auth_util.authorize_token_redirect(oauth_map, force_http=True)

def _upgrade_phantom_into(phantom_data, target_data):
    """ Attempts to merge a phantom user into a target user.
    Will bail if any signs that the target user has previous activity.
    """


    # First make sure user has 0 points and phantom user has some activity
    if (phantom_data and phantom_data.points > 0):
        if phantom_data.consume_identity(target_data):
            # Phantom user just converted into a real user.
            user_counter.add(1)

            # Clear all "login" notifications
            UserNotifier.clear_all(phantom_data)
            return True
    return False

class PostLogin(request_handler.RequestHandler):
    @user_util.manual_access_checking
    def get(self):
        cont = self.request_continue_url()

        self.consume_auth_token()

        user_data = UserData.current()
        if user_data:

            first_time = not user_data.last_login

            # Update email address if it has changed
            current_google_user = users.get_current_user()
            if current_google_user:
                if current_google_user.email() != user_data.email:
                    user_data.user_email = current_google_user.email()

            # If the user has a public profile, we stop "syncing" their username
            # from Facebook, as they now have an opportunity to set it themself
            if not user_data.username:
                user_data.update_nickname()

            # Set developer and moderator to True if user is admin
            if ((not user_data.developer or not user_data.moderator) and
                    users.is_current_user_admin()):
                user_data.developer = True
                user_data.moderator = True

            user_data.last_login = datetime.datetime.utcnow()
            user_data.put()
            
            complete_signup = self.request_bool("completesignup", default=False)
            if first_time:
                if current_google_user:
                    # Look for a matching UnverifiedUser with the same e-mail
                    # to see if the user used Google login to verify.
                    unverified_user = models.UnverifiedUser.get_for_value(
                            current_google_user.email())
                    if unverified_user:
                        unverified_user.delete()

                # Note that we can only migrate phantom users right now if this
                # login is not going to lead to a "/completesignup" page, which
                # indicates the user has to finish more information in the
                # signup phase.
                if not complete_signup:
                    # If user is brand new and has 0 points, migrate data.
                    phantom_id = get_phantom_user_id_from_cookies()
                    if phantom_id:
                        phantom_data = UserData.get_from_db_key_email(phantom_id)
                        if _upgrade_phantom_into(phantom_data, user_data):
                            cont = "/newaccount?continue=%s" % cont
            if complete_signup:
                cont = "/completesignup"

        else:

            # If nobody is logged in, clear any expired Facebook cookie that may be hanging around.
            if App.facebook_app_id:
                self.delete_cookie("fbsr_" + App.facebook_app_id)
                self.delete_cookie("fbm_" + App.facebook_app_id)

            logging.critical("Missing UserData during PostLogin, with id: %s, cookies: (%s), google user: %s" % (
                    util.get_current_user_id(), os.environ.get('HTTP_COOKIE', ''), users.get_current_user()
                )
            )

        # Always delete phantom user cookies on login
        self.delete_cookie('ureg_id')
        self.redirect(cont)

class Logout(request_handler.RequestHandler):
    @staticmethod
    def delete_all_identifying_cookies(handler):
        handler.delete_cookie('ureg_id')
        handler.delete_cookie(auth.cookies.AUTH_COOKIE_NAME)

        # Delete session cookie set by flask (used in /api/auth/token_to_session)
        handler.delete_cookie('session')

        # Delete Facebook cookie, which sets ithandler both on "www.ka.org" and ".www.ka.org"
        if App.facebook_app_id:
            handler.delete_cookie_including_dot_domain('fbsr_' + App.facebook_app_id)
            handler.delete_cookie_including_dot_domain('fbm_' + App.facebook_app_id)

    @user_util.open_access
    def get(self):
        google_user = users.get_current_user()
        Logout.delete_all_identifying_cookies(self)

        next_url = "/"
        if google_user is not None:
            next_url = users.create_logout_url(self.request_continue_url())
        self.redirect(next_url)

# TODO(benkomalo): move this to a more appropriate, generic spot
# Loose regex for Email validation, copied from django.core.validators
# Most regex or validation libraries are overly strict - this is intentionally
# loose since the RFC is crazy and the only good way to know if an e-mail is
# really valid is to send and see if it fails.
_email_re = re.compile(
    r"(^[-!#$%&'*+/=?^_`{}|~0-9A-Z]+(\.[-!#$%&'*+/=?^_`{}|~0-9A-Z]+)*"  # dot-atom
    r'|^"([\001-\010\013\014\016-\037!#-\[\]-\177]|\\[\001-011\013\014\016-\177])*"' # quoted-string
    r')@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,6}\.?$', re.IGNORECASE)  # domain

class Signup(request_handler.RequestHandler):
    @user_util.open_access
    def get(self):
        """ Renders the register for new user page.  """

        if (self.request_bool('under13', default=False)
                or cookie_util.get_cookie_value(auth.cookies.U13_COOKIE_NAME)):
            # User detected to be under13. Show them a sorry page.
            name = self.request_string('name', default=None)
            self.render_jinja2_template('under13.html', {'name': name})
            return

        template_values = {
            'errors': {},
            'values': {},
            'google_url': users.create_login_url("/postlogin?completesignup=1"),
        }
        self.render_jinja2_template('signup.html', template_values)

    @user_util.manual_access_checking
    def post(self):
        """ Handles registration request on our site.

        Note that new users can still be created via PostLogin if the user
        signs in via Google/FB for the first time - this is for the
        explicit registration via our own services.

        """

        values = {
            'birthdate': self.request_string('birthdate', default=None),
            'email': self.request_string('email', default=None),
        }

        errors = {}

        # Under-13 check.
        birthdate = None
        if values['birthdate']:
            try:
                birthdate = datetime.datetime.strptime(values['birthdate'],
                                                       '%Y-%m-%d')
                birthdate = birthdate.date()
            except ValueError:
                errors['birthdate'] = "Invalid birthdate"
        else:
            errors['birthdate'] = "Birthdate required"

        if birthdate and age_util.get_age(birthdate) < 13:
            # We don't yet allow under13 users. We need to lock them out now,
            # unfortunately. Set an under-13 cookie so they can't try again.
            Logout.delete_all_identifying_cookies(self)
            auth.cookies.set_under13_cookie(self)
            
            # TODO(benkomalo): investigate how reliable setting cookies from
            # a jQuery POST is going to be
            self.render_json({"under13": True})
            return

        existing_google_user_detected = False
        if values['email']:
            email = values['email']

            # Perform loose validation - we can't actually know if this is
            # valid until we send an e-mail.
            if not _email_re.search(email):
                errors['email'] = "Email appears to be invalid"
            else:
                existing = UserData.get_from_user_input_email(email)
                if existing is not None:
                    if existing.has_password():
                        # TODO(benkomalo): do something nicer and maybe ask the
                        # user to try and login with that e-mail?
                        errors['email'] = "There is already an account with that e-mail"
                    else:
                        existing_google_user_detected = True
                        logging.warn("User tried to register with password, "
                                     "but has an account w/ Google login")
                else:
                    # No full user account detected, but have they tried to
                    # signup before and still haven't verified their e-mail?
                    existing = models.UnverifiedUser.get_for_value(email)
                    if existing is not None:
                        # TODO(benkomalo): do something nicer here and present
                        # call to action for re-sending verification e-mail
                        errors['email'] = "Looks like you've already tried signing up"
        else:
            errors['email'] = "Email required"
            
        if existing_google_user_detected:
            # TODO(benkomalo): just deny signing up with username/password for
            # existing users with a Google login. In the future, we can show
            # a message to ask them to sign in with their Google login
            errors['email'] = "There is already an account with that e-mail"

        if len(errors) > 0:
            self.render_json({'errors': errors})
            return

        # Success!
        unverified_user = models.UnverifiedUser.get_or_insert_for_value(email)
        verification_token = EmailVerificationToken.for_user(unverified_user)
        verification_link = CompleteSignup.build_link(unverified_user)

        self.send_verification_email(email, verification_link)
        
        response_json = {
                'success': True,
                'email': email,
                'existing_google_user_detected': existing_google_user_detected,
                }
        
        if App.is_dev_server:
            response_json['token'] = verification_token.value

        # TODO(benkomalo): since users are now blocked from further access
        #    due to requiring verification of e-mail, we need to do something
        #    about migrating phantom data (we can store the phantom id in
        #    the UnverifiedUser object and migrate after they finish
        #    registering, for example)
        self.render_json(response_json, camel_cased=True)

    def send_verification_email(self, recipient, verification_link):
        template_values = {
                'verification_link': verification_link,
            }

        body = self.render_jinja2_template_to_string(
                'verification-email-text-only.html',
                template_values)

        if not App.is_dev_server:
            mail.send_mail(
                    sender='no-reply@khanacademy.org',
                    to=recipient,
                    subject="Verify your email with Khan Academy",
                    body=body)

class CompleteSignup(request_handler.RequestHandler):
    """ A handler for a page that allows users to create a password to login
    with a Khan Academy account. This is also being doubly used for existing
    Google/FB users to add a password to their account.

    """

    @staticmethod
    def build_link(unverified_user):
        """ Builds a link for an unverified user by minting a unique token
        via auth.tokens.EmailVerificationToken and embedding it in the URL

        """

        return util.absolute_url(
                "/completesignup?token=%s" %
                EmailVerificationToken.for_user(unverified_user).value)

    def validated_token(self):
        """ Validates the token specified in the request parameters and returns
        it. Returns None if no valid token was detected.

        """

        token_value = self.request_string("token", default=None)
        if not token_value:
            return None

        token = EmailVerificationToken.for_value(token_value)

        if not token:
            return None

        unverified_user = models.UnverifiedUser.get_for_value(token.email)
        if not unverified_user or not token.is_valid(unverified_user):
            return None

        # Success - token does indeed point to an unverified user.
        return token

    @user_util.manual_access_checking
    def get(self):
        """ Renders the second part of the user signup step, after the user
        has verified ownership of their e-mail account.

        The request URI must include a valid EmailVerificationToken, and
        can be made via build_link(), or be made by a user without an existing
        password set.

        """
        
        valid_token = self.validated_token()
        user_data = UserData.current()
        if not valid_token and not user_data:
            # Just take them to the homepage for now.
            self.redirect("/")
            return

        if user_data and user_data.has_password():
            # The user already has a KA login - redirect them to their profile
            self.redirect(user_data.profile_root)
            return

        values = {}
        if valid_token:
            # Give priority to the token in the URL.
            values['email'] = valid_token.email
            user_data = None
        else:
            # Must be that the user is signing in with Google/FB and wanting
            # to create a KA password to associate with it

            # TODO(benkomalo): handle storage for FB users. Right now their
            # "email" value is a URI like http://facebookid.ka.org/1234
            if not user_data.is_facebook_user:
                values['email'] = user_data.email
            values['nickname'] = user_data.nickname
            values['gender'] = user_data.gender
            values['username'] = user_data.username

        template_values = {
            'user': user_data,
            'values': values,
            'token': valid_token,
        }
        self.render_jinja2_template('completesignup.html', template_values)

    @user_util.manual_access_checking
    def post(self):
        valid_token = self.validated_token()
        user_data = UserData.current()
        if not valid_token and not user_data:
            logging.warn("No valid token or user for /completesignup")
            self.redirect("/")
            return

        if valid_token:
            if user_data:
                logging.warn("Existing user is signed in, but also specified "
                             "a valid EmailVerificationToken. Ignoring "
                             " existing sign-in and using token")
            user_data = None

        # Store values in a dict so we can iterate for monotonous checks.
        values = {
            'nickname': self.request_string('nickname', default=None),
            'gender': self.request_string('gender', default="unspecified"),
            'username': self.request_string('username', default=None),
            'password': self.request_string('password', default=None),
        }

        # Simple existence validations
        errors = {}
        for field, error in [('nickname', "Name required"),
                             ('username', "Username required"),
                             ('password', "Password required")]:
            if not values[field]:
                errors[field] = error

        gender = None
        if values['gender']:
            gender = values['gender'].lower()
            if gender not in ['male', 'female']:
                gender = None

        if values['username']:
            username = values['username']
            # TODO(benkomalo): ask for advice on text
            if not models.UniqueUsername.is_valid_username(username):
                errors['username'] = "Must start with a letter, be alphanumeric, and at least 3 characters"

            # Only check to see if it's available if we're changing values
            # or if this is a brand new UserData
            elif ((not user_data or user_data.username != username) and
                    not models.UniqueUsername.is_available_username(username)):
                errors['username'] = "Username is not available"

        if values['password']:
            password = values['password']
            if not auth.passwords.is_sufficient_password(password,
                                                         values['nickname'],
                                                         values['username']):
                errors['password'] = "Password is too weak"


        if len(errors) > 0:
            self.render_json({'errors': errors}, camel_cased=True)
            return

        if user_data:
            # Existing user - update their info
            def txn():
                if (username != user_data.username
                        and not user_data.claim_username(username)):
                    errors['username'] = "Username is not available"
                    return False

                user_data.set_password(password)
                user_data.update_nickname(values['nickname'])

            util.ensure_in_transaction(txn, xg_on=True)
            if len(errors) > 0:
                self.render_json({'errors': errors}, camel_cased=True)
                return

        else:
            unverified_user = models.UnverifiedUser.get_for_value(
                    valid_token.email)

            num_tries = 0
            user_data = None
            while not user_data and num_tries < 2:
                user_id = uid.new_user_id()
                user_data = models.UserData.insert_for(
                        user_id,
                        unverified_user.email,
                        username,
                        password,
                        birthdate=unverified_user.birthdate,
                        gender=gender)

                if not user_data:
                    self.render_json({'errors': {'username': "Username taken."}},
                                     camel_cased=True)
                    return
                elif user_data.username != username:
                    # Something went awry - insert_for may have returned
                    # an existing user due to an ID collision. Try again.
                    user_data = None
                num_tries += 1
                
            if not user_data:
                self.render_json({
                        'errors': {'username': "Oops! Something went wrong. " +
                                               "Please try again later."}
                }, camel_cased=True)
                return

            # Nickname is special since it requires updating external indices.
            user_data.update_nickname(values['nickname'])

            # TODO(benkomalo): move this into a transaction with the above creation
            unverified_user.delete()

        # TODO(benkomalo): give some kind of "congrats"/"welcome" notification
        Login.return_login_json(self, user_data, cont=user_data.profile_root)

class PasswordChange(request_handler.RequestHandler):
    @user_util.manual_access_checking
    def get(self):
        if self.consume_auth_token():
            # Just updated the auth cookie, which means we just succesfully
            # completed a password change.
            self.render_form(message="Password changed", success=True)
        else:
            self.render_form()

    def render_form(self, message=None, success=False):
        self.render_jinja2_template('password-change.html',
                                    {'message': message or "",
                                     'success': success})
        
    @user_util.manual_access_checking
    def post(self):
        user_data = models.UserData.current()
        if not user_data:
            self.response.unauthorized()
            return

        existing = self.request_string("existing")
        if not user_data.validate_password(existing):
            # TODO(benkomalo): throttle incorrect password attempts
            self.render_form(message="Incorrect password")
            return

        password1 = self.request_string("password1")
        password2 = self.request_string("password2")
        if (not password1 or
                not password2 or
                password1 != password2):
            self.render_form(message="Passwords don't match")
        elif not auth.passwords.is_sufficient_password(password1,
                                                       user_data.nickname,
                                                       user_data.username):
            self.render_form(message="Password too weak")
        else:
            # We're good!
            user_data.set_password(password1)

            # Need to create a new auth token as the existing cookie will expire
            auth_token = AuthToken.for_user(user_data)
            self.redirect(util.insecure_url(
                    "/pwchange?auth=%s" % auth_token.value))
