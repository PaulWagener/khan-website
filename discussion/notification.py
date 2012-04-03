import os
import logging

from google.appengine.api import users
from google.appengine.ext import db

from app import App
import app
import user_util
import util
import util_discussion
import request_handler
import models
import models_discussion
import voting


def get_questions_data(user_data):
    """ Get data associated with a user's questions and unread answers
    """
    dict_meta_questions = {}

    # Get questions asked by user
    questions = models_discussion.Feedback.get_all_questions_by_author(user_data.user_id)
    for question in questions:
        qa_expand_key = str(question.key())
        meta_question = MetaQuestion.from_question(question, user_data)

        dict_meta_questions[qa_expand_key] = meta_question

    # Get unread answers to the above questions
    unread_answers = feedback_answers_for_user_data(user_data)
    for answer in unread_answers:
        meta_question = dict_meta_questions[str(answer.question_key())]
        meta_question.update_notifications(answer)

    return {
            'questions': dict_meta_questions.values(),
        }


class MetaQuestion(object):
    """ Data associated with a user's questions and unread answers

    Note: qa_expand_key is necessary so that the question appears expanded
    when the user clicks through the notification to view the video page.

    TODO(marcia): I am awful at naming things, help!
    """
    @staticmethod
    def from_question(question, viewer_user_data):
        """ Construct a MetaQuestion (ugh, the name!) from a
        models_discussion.Feedback entity
        """
        meta = MetaQuestion()

        # TODO(marcia): Is this too much junk to send down,
        # when we only need the readable_id and title?
        video = question.video()
        meta.video = video

        # HACK(marcia): The reason we need to send the topic is to construct
        # the video url so that it doesn't redirect to the canonical url,
        # which strips url parameters
        # Consider actually fixing that so the url parameters are passed
        # along with the redirect.
        meta.topic_slug = video.first_topic().get_extended_slug()

        meta.qa_expand_key = str(question.key())
        meta.viewer_user_data = viewer_user_data

        meta.notifications_count = 0
        meta.notifications_date = question.date

        return meta

    def update_notifications(self, answer):
        """ Update count and last-updated date for unread answers
        """
        if not answer.appears_as_deleted_to(self.viewer_user_data):
            self.increment_notifications_count()
            self.update_notifications_date(answer.date)

    def increment_notifications_count(self):
        self.notifications_count = self.notifications_count + 1

    def update_notifications_date(self, other_date):
        if self.notifications_date < other_date:
            self.notifications_date = other_date


class VideoFeedbackNotificationList(request_handler.RequestHandler):

    @user_util.open_access
    def get(self):

        user_data = models.UserData.current()

        if not user_data:
            self.redirect(util.create_login_url(self.request.uri))
            return

        answers = feedback_answers_for_user_data(user_data)

        # Whenever looking at this page, make sure the feedback count is recalculated
        # in case the user was notified about deleted or flagged posts.
        user_data.count_feedback_notification = -1
        user_data.put()

        dict_videos = {}
        dict_answers = {}

        for answer in answers:

            video = answer.video()

            dict_votes = models_discussion.FeedbackVote.get_dict_for_user_data_and_video(user_data, video)
            voting.add_vote_expando_properties(answer, dict_votes)

            if video == None or type(video).__name__ != "Video":
                continue

            video_key = video.key()
            dict_videos[video_key] = video
            
            if dict_answers.has_key(video_key):
                dict_answers[video_key].append(answer)
            else:
                dict_answers[video_key] = [answer]
        
        videos = sorted(dict_videos.values(), key=lambda video: video.first_topic().title + video.title)

        context = {
                    "email": user_data.email,
                    "videos": videos,
                    "dict_answers": dict_answers
                  }

        self.render_jinja2_template('discussion/video_feedback_notification_list.html', context)

class VideoFeedbackNotificationFeed(request_handler.RequestHandler):

    @user_util.open_access
    def get(self):

        user_data = self.request_user_data("email")

        max_entries = 100
        answers = feedback_answers_for_user_data(user_data)
        answers = sorted(answers, key=lambda answer: answer.date)

        context = {
                    "answers": answers,
                    "count": len(answers)
                  }

        self.response.headers['Content-Type'] = 'text/xml'
        self.render_jinja2_template('discussion/video_feedback_notification_feed.xml', context)

def feedback_answers_for_user_data(user_data):
    feedbacks = []

    if not user_data:
        return feedbacks

    notifications = models_discussion.FeedbackNotification.gql("WHERE user = :1", user_data.user)

    for notification in notifications:

        feedback = None

        try:
            feedback = notification.feedback
        except db.ReferencePropertyResolveError:
            pass

        if not feedback or not feedback.video() or not feedback.is_visible_to_public() or not feedback.is_type(models_discussion.FeedbackType.Answer):
            # If we ever run into notification for a deleted or non-FeedbackType.Answer piece of feedback,
            # go ahead and clear the notification so we keep the DB clean.
            db.delete(notification)
            continue

        feedbacks.append(feedback)

    return feedbacks

# Send a notification to the author of this question, letting
# them know that a new answer is available.
def new_answer_for_video_question(video, question, answer):

    if not question or not question.author:
        return

    # Don't notify if user answering own question
    if question.author == answer.author:
        return

    notification = models_discussion.FeedbackNotification()
    notification.user = question.author
    notification.feedback = answer

    user_data = models.UserData.get_from_db_key_email(notification.user.email())
    if not user_data:
        return

    user_data.count_feedback_notification = -1

    db.put([notification, user_data])

def clear_question_answers_for_current_user(question_key):

    user_data = models.UserData.current()

    if not user_data:
        return

    if not question_key:
        return

    question = models_discussion.Feedback.get(question_key)
    if not question:
        return;

    feedback_keys = question.children_keys()
    for key in feedback_keys:
        notifications = models_discussion.FeedbackNotification.gql("WHERE user = :1 AND feedback = :2", user_data.user, key)
        if notifications.count():
            db.delete(notifications)

    user_data.count_feedback_notification = -1
    user_data.put()
