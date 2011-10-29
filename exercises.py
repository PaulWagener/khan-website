import re
import os
import logging
import itertools
import hashlib
import urllib

from google.appengine.ext import db
from google.appengine.api import users
from google.appengine.ext import deferred

from app import App
import consts
import datetime
import models
import request_handler
import util
import user_util
import points
import layer_cache
import knowledgemap
import string
from badges import util_badges, last_action_cache, custom_badges
from phantom_users import util_notify
from phantom_users.phantom_util import create_phantom
from custom_exceptions import MissingExerciseException
from api.auth.xsrf import ensure_xsrf_cookie
from api import jsonify
from gae_bingo.gae_bingo import bingo, ab_test
from gae_bingo.models import ConversionTypes

class MoveMapNodes(request_handler.RequestHandler):
    def post(self):
        self.get()

    @user_util.developer_only
    def get(self):
        node_list = string.split(self.request_string('exercises'), ',')
        delta_h = self.request_int('delta_h')
        delta_v = self.request_int('delta_v')

        for node_id in node_list:
            exercise = models.Exercise.get_by_name(node_id)

            exercise.h_position += delta_h
            exercise.v_position += delta_v

            exercise.put()

class ViewExercise(request_handler.RequestHandler):

    _hints_ab_test_alternatives = {
        'old': 17,  # The original, where it was unclear if a hint was costly after an attempt
        'more_visible': 1,  # Jace's shaking and pulsating emphasis on free hints after an attempt
        'solution_button': 1,  # David's show solution button in lieu of hint button after an attempt
        'full_solution': 1,  # Jason's just show the complete solution after an incorrect answer
    }
    _hints_conversion_tests = [
        ('hints_free_hint', ConversionTypes.Counting),
        ('hints_free_hint_binary', ConversionTypes.Binary),
        ('hints_costly_hint', ConversionTypes.Counting),
        ('hints_costly_hint_binary', ConversionTypes.Binary),
        ('hints_problems_done', ConversionTypes.Counting),
        ('hints_gained_proficiency_all', ConversionTypes.Counting),
        ('hints_gained_proficiency_easy_binary', ConversionTypes.Binary),
        ('hints_gained_proficiency_hard_binary', ConversionTypes.Binary),
        ('hints_wrong_problems', ConversionTypes.Counting),
        ('hints_keep_going_after_wrong', ConversionTypes.Counting),
    ]
    _hints_conversion_names, _hints_conversion_types = [list(x) for x in zip(*_hints_conversion_tests)]

    @ensure_xsrf_cookie
    def get(self):
        user_data = models.UserData.current() or models.UserData.pre_phantom()

        exid = self.request_string("exid", default="addition_1")
        exercise = models.Exercise.get_by_name(exid)

        if not exercise:
            raise MissingExerciseException("Missing exercise w/ exid '%s'" % exid)

        user_exercise = user_data.get_or_insert_exercise(exercise)

        # Cache this so we don't have to worry about future lookups
        user_exercise.exercise_model = exercise
        user_exercise._user_data = user_data
        user_exercise.summative = exercise.summative

        # Temporarily work around in-app memory caching bug
        exercise.user_exercise = None

        problem_number = self.request_int('problem_number', default=(user_exercise.total_done + 1))

        user_data_student = self.request_user_data("student_email") or user_data
        if user_data_student.key_email != user_data.key_email and not user_data_student.is_visible_to(user_data):
            user_data_student = user_data

        viewing_other = user_data_student.key_email != user_data.key_email

        # Can't view your own problems ahead of schedule
        if not viewing_other and problem_number > user_exercise.total_done + 1:
            problem_number = user_exercise.total_done + 1

        # When viewing another student's problem or a problem out-of-order, show read-only view
        read_only = viewing_other or problem_number != (user_exercise.total_done + 1)

        exercise_template_html = exercise_template()

        exercise_body_html, exercise_inline_script, exercise_inline_style, data_require, sha1 = exercise_contents(exercise)
        user_exercise.exercise_model.sha1 = sha1

        user_exercise.exercise_model.related_videos = map(lambda exercise_video: exercise_video.video, user_exercise.exercise_model.related_videos_fetch())
        for video in user_exercise.exercise_model.related_videos:
            video.id = video.key().id()

        renderable = True

        if read_only:
            # Override current problem number and user being inspected
            # so proper exercise content will be generated
            user_exercise.total_done = problem_number - 1
            user_exercise.user = user_data_student.user
            user_exercise.read_only = True

            if not self.request_bool("renderable", True):
                # We cannot render old problems that were created in the v1 exercise framework.
                renderable = False

            query = models.ProblemLog.all()
            query.filter("user = ", user_data_student.user)
            query.filter("exercise = ", exid)

            # adding this ordering to ensure that query is served by an existing index.
            # could be ok if we remove this
            query.order('time_done')
            problem_logs = query.fetch(500)

            problem_log = None
            for p in problem_logs:
                if p.problem_number == problem_number:
                    problem_log = p
                    break

            user_activity = []
            previous_time = 0

            if not problem_log or not hasattr(problem_log, "hint_after_attempt_list"):
                renderable = False
            else:
                # Don't include incomplete information
                problem_log.hint_after_attempt_list = filter(lambda x: x != -1, problem_log.hint_after_attempt_list)

                while len(problem_log.hint_after_attempt_list) and problem_log.hint_after_attempt_list[0] == 0:
                    user_activity.append([
                        "hint-activity",
                        "0",
                        max(0, problem_log.hint_time_taken_list[0] - previous_time)
                        ])

                    previous_time = problem_log.hint_time_taken_list[0]
                    problem_log.hint_after_attempt_list.pop(0)
                    problem_log.hint_time_taken_list.pop(0)

                # For each attempt, add it to the list and then add any hints
                # that came after it
                for i in range(0, len(problem_log.attempts)):
                    user_activity.append([
                        "correct-activity" if problem_log.correct else "incorrect-activity",
                        unicode(problem_log.attempts[i] if problem_log.attempts[i] else 0),
                        max(0, problem_log.time_taken_attempts[i] - previous_time)
                        ])

                    previous_time = 0

                    # Here i is 0-indexed but problems are numbered starting at 1
                    while len(problem_log.hint_after_attempt_list) and problem_log.hint_after_attempt_list[0] == i+1:
                        user_activity.append([
                            "hint-activity",
                            "0",
                            max(0, problem_log.hint_time_taken_list[0] - previous_time)
                            ])

                        previous_time = problem_log.hint_time_taken_list[0]
                        # easiest to just pop these instead of maintaining
                        # another index into this list
                        problem_log.hint_after_attempt_list.pop(0)
                        problem_log.hint_time_taken_list.pop(0)

                user_exercise.user_activity = user_activity

                if problem_log.count_hints is not None:
                    user_exercise.count_hints = problem_log.count_hints

        is_webos = self.is_webos()
        browser_disabled = is_webos or self.is_older_ie()
        renderable = renderable and not browser_disabled

        url_pattern = "/exercises?exid=%s&student_email=%s&problem_number=%d"
        user_exercise.previous_problem_url = url_pattern % \
            (exid, user_data_student.key_email , problem_number-1)
        user_exercise.next_problem_url = url_pattern % \
            (exid, user_data_student.key_email , problem_number+1)

        user_exercise_json = jsonify.jsonify(user_exercise)

        template_values = {
            'exercise': exercise,
            'user_exercise_json': user_exercise_json,
            'exercise_body_html': exercise_body_html,
            'exercise_template_html': exercise_template_html,
            'exercise_inline_script': exercise_inline_script,
            'exercise_inline_style': exercise_inline_style,
            'data_require': data_require,
            'read_only': read_only,
            'selected_nav_link': 'practice',
            'browser_disabled': browser_disabled,
            'is_webos': is_webos,
            'renderable': renderable,
            'issue_labels': ('Component-Code,Exercise-%s,Problem-%s' % (exid, problem_number)), 
            'alternate_hints_treatment': ab_test('Hints or Show Solution',
                ViewExercise._hints_ab_test_alternatives,
                ViewExercise._hints_conversion_names,
                ViewExercise._hints_conversion_types)
            }

        self.render_jinja2_template("exercise_template.html", template_values)

class ViewAllExercises(request_handler.RequestHandler):
    def get(self):
        user_data = models.UserData.current() or models.UserData.pre_phantom()

        user_exercise_graph = models.UserExerciseGraph.get(user_data)
        if user_data.reassess_from_graph(user_exercise_graph):
            user_data.put()

        graph_dicts = user_exercise_graph.graph_dicts()
        suggested_graph_dicts = user_exercise_graph.suggested_graph_dicts()
        proficient_graph_dicts = user_exercise_graph.proficient_graph_dicts()
        recent_graph_dicts = user_exercise_graph.recent_graph_dicts()
        review_graph_dicts = user_exercise_graph.review_graph_dicts()

        for graph_dict in suggested_graph_dicts:
            graph_dict["status"] = "Suggested"

        for graph_dict in proficient_graph_dicts:
            graph_dict["status"] = "Proficient"

        for graph_dict in review_graph_dicts:
            graph_dict["status"] = "Review"

            try:
                suggested_graph_dicts.remove(graph_dict)
            except ValueError:
                pass

        template_values = {
            'graph_dicts': graph_dicts,
            'suggested_graph_dicts': suggested_graph_dicts,
            'recent_graph_dicts': recent_graph_dicts,
            'review_graph_dicts': review_graph_dicts,
            'user_data': user_data,
            'expanded_all_exercises': user_data.expanded_all_exercises,
            'map_coords': knowledgemap.deserializeMapCoords(user_data.map_coords),
            'selected_nav_link': 'practice',
            }

        self.render_jinja2_template('viewexercises.html', template_values)

class RawExercise(request_handler.RequestHandler):
    def get(self):
        path = self.request.path
        exercise_file = urllib.unquote(path.rpartition('/')[2])
        self.response.headers["Content-Type"] = "text/html";
        self.response.out.write(raw_exercise_contents(exercise_file))

@layer_cache.cache(layer=layer_cache.Layers.InAppMemory)
def exercise_template():
    path = os.path.join(os.path.dirname(__file__), "khan-exercises/exercises/khan-exercise.html")

    contents = ""
    f = open(path)

    if f:
        try:
            contents = f.read()
        finally:
            f.close()

    if not len(contents):
        raise MissingExerciseException("Missing exercise template")

    return contents

@layer_cache.cache_with_key_fxn(lambda exercise: "exercise_contents_%s" % exercise.name, layer=layer_cache.Layers.InAppMemory)
def exercise_contents(exercise):
    contents = raw_exercise_contents("%s.html" % exercise.name)

    re_data_require = re.compile("^<html.*(data-require=\".*\").*>", re.MULTILINE)
    match_data_require = re_data_require.search(contents)
    data_require = match_data_require.groups()[0] if match_data_require else ""

    re_body_contents = re.compile("<body>(.*)</body>", re.DOTALL)
    match_body_contents = re_body_contents.search(contents)
    body_contents = match_body_contents.groups()[0]

    re_script_contents = re.compile("<script[^>]*>(.*?)</script>", re.DOTALL)
    list_script_contents = re_script_contents.findall(contents)
    script_contents = ";".join(list_script_contents)

    re_style_contents = re.compile("<style[^>]*>(.*?)</style>", re.DOTALL)
    list_style_contents = re_style_contents.findall(contents)
    style_contents = "\n".join(list_style_contents)

    sha1 = hashlib.sha1(contents).hexdigest()

    if not len(body_contents):
        raise MissingExerciseException("Missing exercise body in content for exid '%s'" % exercise.name)

    return map(lambda s: s.decode('utf-8'), (body_contents, script_contents, style_contents, data_require, sha1))

@layer_cache.cache_with_key_fxn(lambda exercise_file: "exercise_raw_html_%s" % exercise_file, layer=layer_cache.Layers.InAppMemory)
def raw_exercise_contents(exercise_file):
    path = os.path.join(os.path.dirname(__file__), "khan-exercises/exercises/%s" % exercise_file)

    f = None
    contents = ""

    try:
        f = open(path)
        contents = f.read()
    except:
        raise MissingExerciseException("Missing exercise file for exid '%s'" % exercise_file)
    finally:
        if f:
            f.close()

    if not len(contents):
        raise MissingExerciseException("Missing exercise content for exid '%s'" % exercise.name)

    return contents

# TODO(david): Rename this function
def reset_streak(user_data, user_exercise):
    if user_exercise and user_exercise.belongs_to(user_data):
        user_exercise.update_proficiency_model(correct=False)
        user_exercise.put()

        return user_exercise

def attempt_problem(user_data, user_exercise, problem_number, attempt_number,
    attempt_content, sha1, seed, completed, count_hints, time_taken,
    exercise_non_summative, problem_type, ip_address):

    if user_exercise and user_exercise.belongs_to(user_data):
        dt_now = datetime.datetime.now()
        exercise = user_exercise.exercise_model

        prev_last_done = user_exercise.last_done
        user_exercise.last_done = dt_now
        user_exercise.seconds_per_fast_problem = exercise.seconds_per_fast_problem
        user_exercise.summative = exercise.summative

        user_data.last_activity = user_exercise.last_done

        # If a non-admin tries to answer a problem out-of-order, just ignore it
        if problem_number != user_exercise.total_done + 1 and not user_util.is_current_user_developer():
            # Only admins can answer problems out of order.
            raise Exception("Problem number out of order (%s vs %s) for user_id: %s submitting attempt content: %s with seed: %s" % (problem_number, user_exercise.total_done + 1, user_data.user_id, attempt_content, seed))

        if len(sha1) <= 0:
            raise Exception("Missing sha1 hash of problem content.")

        if len(seed) <= 0:
            raise Exception("Missing seed for problem content.")

        if len(attempt_content) > 500:
            raise Exception("Attempt content exceeded maximum length.")

        # Build up problem log for deferred put
        problem_log = models.ProblemLog(
                key_name = "problemlog_%s_%s_%s" % (user_data.key_email, user_exercise.exercise, problem_number),
                user = user_data.user,
                exercise = user_exercise.exercise,
                problem_number = problem_number,
                time_taken = time_taken,
                time_done = dt_now,
                count_hints = count_hints,
                hint_used = count_hints > 0,
                correct = completed and not count_hints and (attempt_number == 1),
                sha1 = sha1,
                seed = seed,
                problem_type = problem_type,
                count_attempts = attempt_number,
                attempts = [attempt_content],
                ip_address = ip_address,
        )

        if exercise.summative:
            problem_log.exercise_non_summative = exercise_non_summative

        first_response = (attempt_number == 1 and count_hints == 0) or (count_hints == 1 and attempt_number == 0)

        if user_exercise.total_done == 0 and first_response:
            user_exercise.bingo_proficiency_model('prof_new_exercises_attempted')

        if user_exercise.total_done > 0 and user_exercise.streak == 0 and first_response:
            user_exercise.bingo_proficiency_model('prof_keep_going_after_wrong')
            bingo('hints_keep_going_after_wrong')

        first_problem_after_proficiency = prev_last_done and user_exercise.proficient_date and (
            abs(prev_last_done - user_exercise.proficient_date) <= datetime.timedelta(seconds=1))

        if first_problem_after_proficiency:
            user_exercise.bingo_proficiency_model('prof_does_problem_just_after_proficiency')

        if completed:

            user_exercise.total_done += 1

            if problem_log.correct:

                proficient = user_data.is_proficient_at(user_exercise.exercise)
                explicitly_proficient = user_data.is_explicitly_proficient_at(user_exercise.exercise)
                suggested = user_data.is_suggested(user_exercise.exercise)
                problem_log.suggested = suggested

                problem_log.points_earned = points.ExercisePointCalculator(user_exercise, suggested, proficient)
                user_data.add_points(problem_log.points_earned)

                # Streak only increments if problem was solved correctly (on first attempt)
                user_exercise.total_correct += 1
                user_exercise.streak += 1
                user_exercise.longest_streak = max(user_exercise.longest_streak, user_exercise.streak)

                user_exercise.update_proficiency_model(correct=True)

                if user_exercise.summative and user_exercise.streak % consts.CHALLENGE_STREAK_BARRIER == 0:
                    user_exercise.streak_start = 0.0

                if user_exercise.progress >= 1.0 and not explicitly_proficient:
                    bingo("hints_gained_proficiency_all")
                    user_exercise.set_proficient(True, user_data)
                    user_data.reassess_if_necessary()

                    problem_log.earned_proficiency = True

                if first_problem_after_proficiency:
                    user_exercise.bingo_proficiency_model('prof_problem_correct_just_after_proficiency')

            util_badges.update_with_user_exercise(
                user_data,
                user_exercise,
                include_other_badges = True,
                action_cache=last_action_cache.LastActionCache.get_cache_and_push_problem_log(user_data, problem_log))

            # Update phantom user notifications
            util_notify.update(user_data, user_exercise)

            user_exercise.bingo_proficiency_model('prof_problems_done')
            bingo('hints_problems_done')

        else:

            if user_exercise.streak == 0:
                # 2+ in a row wrong -> not proficient
                user_exercise.set_proficient(False, user_data)

            # Only count wrong answer at most once per problem
            if first_response:
                user_exercise.update_proficiency_model(correct=False)
                user_exercise.bingo_proficiency_model('prof_wrong_problems')
                bingo('hints_wrong_problems')

        # If this is the first attempt, update review schedule appropriately
        if attempt_number == 1:
            user_exercise.schedule_review(completed)

        user_exercise_graph = models.UserExerciseGraph.get_and_update(user_data, user_exercise)

        # Bulk put
        db.put([user_data, user_exercise, user_exercise_graph.cache])

        # Defer the put of ProblemLog for now, as we think it might be causing hot tablets
        # and want to shift it off to an automatically-retrying task queue.
        # http://ikaisays.com/2011/01/25/app-engine-datastore-tip-monotonically-increasing-values-are-bad/
        deferred.defer(models.commit_problem_log, problem_log,
                       _queue="problem-log-queue",
                       _url="/_ah/queue/deferred_problemlog")

        # Making a separate queue for the log summaries so we can clearly see how much they are getting used
        # deferred.defer(models.commit_log_summary, problem_log, user_data,
        #               _queue = "log-summary-queue",
        #               _url = "/ah/queue/deferred_log_summary") 

        return user_exercise, user_exercise_graph

class ExerciseAdmin(request_handler.RequestHandler):

    @user_util.developer_only
    def get(self):
        user_data = models.UserData.current()
        user_exercise_graph = models.UserExerciseGraph.current()

        if user_data.reassess_from_graph(user_exercise_graph):
            user_data.put()

        graph_dicts = user_exercise_graph.graph_dicts()
        for graph_dict in graph_dicts:
            exercise = models.Exercise.get_by_name(graph_dict["name"])
            graph_dict["live"] = exercise and exercise.live

        template_values = {
            'graph_dicts': sorted(graph_dicts, key=lambda graph_dict: graph_dict["name"]),
            'admin': True,
            'map_coords': (0, 0, 0),
            }

        self.render_jinja2_template('exerciseadmin.html', template_values)

class EditExercise(request_handler.RequestHandler):

    @user_util.developer_only
    def get(self):
        exercise_name = self.request.get('name')
        if exercise_name:
            query = models.Exercise.all().order('name')
            exercises = query.fetch(1000)

            main_exercise = None
            for exercise in exercises:
                if exercise.name == exercise_name:
                    main_exercise = exercise

            query = models.ExerciseVideo.all()
            query.filter('exercise =', main_exercise.key())
            exercise_videos = query.fetch(50)

            template_values = {
                'exercises': exercises,
                'exercise_videos': exercise_videos,
                'main_exercise': main_exercise,
                'saved': self.request_bool('saved', default=False),
                }

            self.render_jinja2_template("editexercise.html", template_values)

class UpdateExercise(request_handler.RequestHandler):

    def post(self):
        self.get()

    @user_util.developer_only
    def get(self):
        user = models.UserData.current().user

        exercise_name = self.request.get('name')
        if not exercise_name:
            self.response.out.write("No exercise submitted, please resubmit if you just logged in.")
            return

        query = models.Exercise.all()
        query.filter('name =', exercise_name)
        exercise = query.get()
        if not exercise:
            exercise = models.Exercise(name=exercise_name)
            exercise.prerequisites = []
            exercise.covers = []
            exercise.author = user
            exercise.summative = self.request_bool("summative", default=False)
            path = os.path.join(os.path.dirname(__file__), exercise_name + '.html')

        v_position = self.request.get('v_position')
        h_position = self.request.get('h_position')
        short_display_name = self.request.get('short_display_name')

        add_video = self.request.get('add_video')
        delete_video = self.request.get('delete_video')
        add_playlist = self.request.get('add_playlist')
        delete_playlist = self.request.get('delete_playlist')

        exercise.prerequisites = []
        for c_check_prereq in range(0, 1000):
            prereq_append = self.request_string("prereq-%s" % c_check_prereq, default="")
            if prereq_append and not prereq_append in exercise.prerequisites:
                exercise.prerequisites.append(prereq_append)

        exercise.covers = []
        for c_check_cover in range(0, 1000):
            cover_append = self.request_string("cover-%s" % c_check_cover, default="")
            if cover_append and not cover_append in exercise.covers:
                exercise.covers.append(cover_append)

        if v_position:
            exercise.v_position = int(v_position)

        if h_position:
            exercise.h_position = int(h_position)

        if short_display_name:
            exercise.short_display_name = short_display_name

        exercise.live = self.request_bool("live", default=False)

        if not exercise.is_saved():
            # Exercise needs to be saved before checking related videos.
            exercise.put()

        video_keys = []
        for c_check_video in range(0, 1000):
            video_name_append = self.request_string("video-%s-readable" % c_check_video, default="")
            if video_name_append:
                video = models.Video.get_for_readable_id(video_name_append)
                if not video.key() in video_keys:
                    video_keys.append(str(video.key()))

            video_append = self.request_string("video-%s" % c_check_video, default="")
            if video_append and not video_append in video_keys:
                video_keys.append(video_append)

        query = models.ExerciseVideo.all()
        query.filter('exercise =', exercise.key())
        existing_exercise_videos = query.fetch(1000)

        existing_video_keys = []
        for exercise_video in existing_exercise_videos:
            existing_video_keys.append(exercise_video.video.key())
            if not exercise_video.video.key() in video_keys:
                exercise_video.delete()

        for video_key in video_keys:
            if not video_key in existing_video_keys:
                exercise_video = models.ExerciseVideo()
                exercise_video.exercise = exercise
                exercise_video.video = db.Key(video_key)
                exercise_video.exercise_order = models.VideoPlaylist.all().filter('video =',exercise_video.video).get().video_position
                exercise_video.put()

        exercise.put()

        #Start ordering
        ExerciseVideos = models.ExerciseVideo.all().filter('exercise =', exercise.key()).fetch(1000)
        playlists = []
        for exercise_video in ExerciseVideos:
            playlists.append(models.VideoPlaylist.get_cached_playlists_for_video(exercise_video.video))

        if playlists:

            playlists = list(itertools.chain(*playlists))
            titles = map(lambda pl: pl.title, playlists)
            playlist_sorted = []
            for p in playlists:
                playlist_sorted.append([p, titles.count(p.title)])
            playlist_sorted.sort(key = lambda p: p[1])
            playlist_sorted.reverse()

            playlists = []
            for p in playlist_sorted:
                playlists.append(p[0])
            playlist_dict = {}
            exercise_list = []
            playlists = list(set(playlists))
            for p in playlists:
                playlist_dict[p.title]=[]
                for exercise_video in ExerciseVideos:
                    if p.title  in map(lambda pl: pl.title, models.VideoPlaylist.get_cached_playlists_for_video(exercise_video.video)):
                        playlist_dict[p.title].append(exercise_video)
                        # ExerciseVideos.remove(exercise_video)

                if playlist_dict[p.title]:
                    playlist_dict[p.title].sort(key = lambda e: models.VideoPlaylist.all().filter('video =', e.video).filter('playlist =',p).get().video_position)
                    exercise_list.append(playlist_dict[p.title])

            if exercise_list:
                exercise_list = list(itertools.chain(*exercise_list))
                for e in exercise_list:
                    e.exercise_order = exercise_list.index(e)
                    e.put()


        self.redirect('/editexercise?saved=1&name=' + exercise_name)

