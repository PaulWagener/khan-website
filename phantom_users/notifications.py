from google.appengine.api import memcache

import util
import logging


class UserLoginNotifier:

    # Only show up to 1 notifications at a time
    NOTIFICATION_LIMIT = 1

    @staticmethod
    def key_for_user(user):
        return "login_notifications_for_%s" % user.email()

    @staticmethod
    def push_for_user(user, user_alert):
        if user is None or user_alert is None:
            return

        user_login = memcache.get(UserLoginNotifier.key_for_user(user))

        if user_login is None:
            user_login = []

        if len(user_login) < UserLoginNotifier.NOTIFICATION_LIMIT:
            user_login.append(user_alert)
            memcache.set(UserLoginNotifier.key_for_user(user), user_login)

    @staticmethod
    def pop_for_current_user():
        return UserLoginNotifier.pop_for_user(util.get_current_user())

    @staticmethod
    def pop_for_user(user):
        if not user:
            return []

        user_login = memcache.get(UserLoginNotifier.key_for_user(user)) or []

        if len(user_login) > 0:
            memcache.delete(UserLoginNotifier.key_for_user(user))
              
        return user_login
