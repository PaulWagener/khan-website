from google.appengine.ext import db
from google.appengine.api import users

import api.auth.xsrf
import request_handler
import user_models
import models_discussion
from badges.discussion_badges import ModeratorBadge
import user_util

class ModPanel(request_handler.RequestHandler):

    @user_util.moderator_required
    def get(self):
        self.render_jinja2_template('discussion/mod/mod.html', { "selected_id": "panel" })

class ModeratorList(request_handler.RequestHandler):

    # Must be an admin to change moderators
    @user_util.admin_required
    @api.auth.xsrf.ensure_xsrf_cookie
    def get(self):
        mods = user_models.UserData.gql("WHERE moderator = :1", True)
        self.render_jinja2_template('discussion/mod/moderatorlist.html', {
            "mods" : mods,
            "selected_id": "moderatorlist",
        })

    @user_util.admin_required
    @api.auth.xsrf.ensure_xsrf_cookie
    def post(self):
        user_data = self.request_user_data("user")

        if user_data:
            user_data.moderator = self.request_bool("mod")

            if user_data.moderator:
                if not ModeratorBadge().is_already_owned_by(user_data):
                    ModeratorBadge().award_to(user_data)

            db.put(user_data)

        self.redirect("/discussion/mod/moderatorlist")

class FlaggedFeedback(request_handler.RequestHandler):

    @user_util.moderator_required
    def get(self):

        # Show all non-deleted feedback flagged for moderator attention
        feedback_query = models_discussion.Feedback.all().filter("is_flagged = ", True).filter("deleted = ", False)

        feedback_count = feedback_query.count()

        # Grab a bunch of flagged pieces of feedback and point moderators at the 50 w/ lowest votes first.
        # ...can easily do this w/ an order on the above query and a new index, but avoiding the index for now
        # since it's only marginally helpful.
        feedbacks = feedback_query.fetch(250)
        feedbacks = sorted(feedbacks, key=lambda feedback: feedback.sum_votes)[:50]

        template_content = {
                "feedbacks": feedbacks, 
                "feedback_count": feedback_count,
                "has_more": len(feedbacks) < feedback_count,
                "feedback_type_question": models_discussion.FeedbackType.Question,
                "feedback_type_comment": models_discussion.FeedbackType.Comment,
                "selected_id": "flaggedfeedback",
                }

        self.render_jinja2_template("discussion/mod/flaggedfeedback.html", template_content)

class BannedList(request_handler.RequestHandler):

    @user_util.moderator_required
    def get(self):
        banned_user_data_list = user_models.UserData.gql("WHERE discussion_banned = :1", True)
        self.render_jinja2_template('discussion/mod/bannedlist.html', {
            "banned_user_data_list" : banned_user_data_list,
            "selected_id": "bannedlist",
        })

    @user_util.moderator_required
    def post(self):
        user_data = self.request_user_data("user")

        if user_data:
            user_data.discussion_banned = self.request_bool("banned")
            db.put(user_data)

            if user_data.discussion_banned:
                # Delete all old posts by hellbanned user
                query = models_discussion.Feedback.all()
                query.ancestor(user_data)
                for feedback in query:
                    if not feedback.deleted:
                        feedback.deleted = True
                        feedback.put()

        self.redirect("/discussion/mod/bannedlist")
